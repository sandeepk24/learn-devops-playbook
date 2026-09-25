# ECS rolling deployments without dropped requests

A deploy returns 503s when the target group has no healthy target at the moment the request arrives. The scheduler, the target group, and the process have separate clocks. They have to be set so the old tasks stay registered until the new ones are healthy, and so a stopped task finishes the requests it already accepted.

The API defaults for a replica service are already the safe ones: `minimumHealthyPercent` 100, `maximumPercent` 200. Most 503s come from someone lowering the floor, from a service too small to survive one AZ, or from a health check that reports healthy before the process can serve.

---

## Which status code, which knob

| Code | What the ALB did | Where to look |
|---|---|---|
| **503** | It had no healthy target. It did not open a connection to a task. | Capacity during the rollout. `minimumHealthyPercent`, desired count, AZ spread, tasks that never became healthy. |
| **502** | It sent the request. The target reset the connection or returned a malformed response. | Shutdown. `SIGTERM` handling, `stopTimeout`, keep-alive vs ALB idle timeout. |
| **504** | It sent the request. The target did not answer before the ALB idle timeout. | Slow requests, a process wedged on shutdown, idle timeout too low for the route. |

Confirm a 503 from the access log. A line with no backend looks like this:

```
elb_status_code = 503
target_status_code = -
target:port = -
```

`HTTPCode_ELB_5XX_Count` is errors the load balancer generated. `HTTPCode_Target_5XX_Count` is errors the application generated. During a deploy, an ELB spike with a flat target count means the target group ran out of backends.

Deregistration delay applies to requests already on a target that is leaving. It does not put a healthy target back into an empty group.

---

## One deploy, counted

Service: desired count 6, `minimumHealthyPercent` 100, `maximumPercent` 200, load balancer attached. The floor is `ceil(6 × 100 / 100) = 6`. The ceiling is `floor(6 × 200 / 100) = 12`. A task counts as healthy only after the target group says so.

AWS documents this replacement as waves of two, not as "launch all six, then kill all six":

| Step | Old tasks | New tasks | Healthy tasks serving |
|---|---|---|---|
| Start | 6 | 0 | 6 |
| Start 2 new | 6 | 2, still booting | 6 |
| 2 new pass health checks | 6 | 2 | 8 |
| Stop 2 old | 4 | 2 | 6 |
| Repeat the wave twice more | 0 | 6 | 6 |

The healthy count does not go below 6. Old tasks leave the target group only after their replacements are healthy.

The faster configuration people copy is `minimumHealthyPercent` 50 with a cluster that only has room for 8 tasks. Floor is `ceil(6 × 0.5) = 3`. AWS documents this sequence:

| Step | What the scheduler does | Tasks that can serve |
|---|---|---|
| 1 | Stops 3 old tasks | 3 |
| 2 | Starts 5 new tasks (3 old + 5 new = 8, the cluster is full) | 3, until the new ones pass health checks |
| 3 | Stops the remaining 3 old tasks | however many of the 5 have become healthy |
| 4 | Starts the last new task | 6, once that task is healthy |

Between step 1 and the new tasks passing checks, the service is at half capacity and the new tasks are booting. The three survivors take the traffic of six. Their response time climbs, the target-group check times out, and they go unhealthy too. The group can reach zero healthy targets. That is the 503. It shows up under production load and stays invisible in an idle staging environment.

50% is a reasonable setting for a queue worker that is idle most of the time. For a service on a load balancer, use 100 and 200.

### The floor at small counts

`minimumHealthyPercent` 50, rounded up:

| desiredCount | Floor | What a rollout may do |
|---|---|---|
| 1 | 1 | Rounding keeps the only task up. The risk is elsewhere: no second AZ, and no room if that task fails. |
| 2 | 1 | May stop one task first. Half capacity for the whole boot window. |
| 3 | 2 | May stop one. |
| 4 | 2 | May stop two before any replacement is healthy. |
| 6 | 3 | The sequence in the table above. |

Same counts at 100%: the floor equals the desired count, so a replacement has to be healthy before an old task is stopped. The ceiling at 200% is what makes the extra tasks fit.

`desiredCount` 1 with 100/200 can roll without a gap, if the cluster can place the second task and the new task becomes healthy. It still loses the service if that one AZ fails, or if the only task dies during boot. Three tasks, one subnet in each of three AZs, is the smallest production shape that still has a task left when one AZ is gone.

### An AZ with no targets

An ALB node in each AZ routes inside its own AZ when cross-zone load balancing is off. Cross-zone is on by default for an ALB target group and off by default for an NLB.

Three AZs, cross-zone off, both tasks landed in `us-east-1a` and `us-east-1b`:

- Requests that resolve to the `1a` or `1b` load balancer node succeed.
- Every request that lands on the `1c` node is a 503, because that node has no target.
- Aggregate `HealthyHostCount` still looks fine.

Turn cross-zone on unless you have a reason to keep traffic in-AZ, and spread tasks across the subnets you gave the service. On Fargate that spread is the subnet list. Placement strategies are an EC2 mechanism; Fargate ignores them.

On EC2, 200% means the cluster has to place the extra tasks. If it cannot, they sit `PENDING`, the deployment does not fail, and it does not finish. A capacity provider with managed scaling, or a standing free-capacity buffer, is part of the deploy config.

---

## When "healthy" is early

With a load balancer attached, ECS treats target-group health as task health. `RUNNING` only means the process started. Without a target group, that is the whole check, and ECS will drain the old tasks as soon as the new container is up.

### Two checks

| | Container `healthCheck` | Target group health check |
|---|---|---|
| Runs where | Inside the task, against localhost | From the ALB, against the task IP |
| ECS uses it to | Restart a dead container | Decide the task is healthy enough to replace an old one, and to receive traffic |
| A security group can block it | No | Yes. The task security group has to allow the ALB security group on the container port. |

Point the target-group check at an endpoint that fails until the dependencies the route needs are ready. A handler that returns 200 as soon as the socket is open will go healthy while the connection pool is still empty. The old tasks drain. The new tasks take traffic and time out.

```python
@app.get("/health")
def health():
    if not db.ping():
        return JSONResponse({"status": "starting"}, status_code=503)
    return {"status": "ok"}
```

Keep this cheap. It runs at the target-group interval on every task. A check that queries five downstreams will flap under load and eject healthy tasks.

### The boot clock

`healthCheckGracePeriodSeconds` is how long ECS ignores target-group failures after a task starts. The ALB is still checking, and it still withholds traffic until the target is healthy. The grace period only stops ECS from killing the task for those failures.

App listens at 45 seconds. Grace period is 30 seconds. Interval 30, unhealthy threshold 2.

| t | What happens |
|---|---|
| 0s | Task starts. Target is `initial`, then `unhealthy`, because nothing is listening. |
| 30s | Grace period ends. The task is already unhealthy. |
| 45s | The process listens. |
| ~60s | ECS has already replaced the task for failing the check. The replacement starts the same loop. |

No new task ever stays up. If the deployment configuration also allowed old tasks to stop, the target group is empty for minutes.

Measure p99 from container start to the first successful target-group check, and set the grace period above that. A Java service is often 120–180 seconds. A small Go binary is often fine at 30. Once the target is healthy, ECS stops waiting; a long grace period does not slow a fast start.

The container check has its own grace window, `startPeriod`. Set it to the same boot budget. A container check that fails during `startPeriod` does not count toward `retries`.

Time to join the target group, after the process is listening, is about `healthyThresholdCount × interval`. At interval 15 and threshold 2, budget 30 seconds. Threshold 2 with interval 10 is faster and sends more checks to every task.

---

## When the request dies on the way out

Shutdown for a load-balanced task:

| t, with delay 30s and stopTimeout 60s | What happens |
|---|---|
| 0s | ECS deregisters the target. The ALB stops sending new requests. The process is still running. |
| 0–30s | In-flight requests finish, or the delay expires and the ALB closes what is left. |
| 30s | The target is `unused`. ECS sends `SIGTERM`. |
| 30–90s | The process exits. At 90s ECS sends `SIGKILL` if it is still there. |

`deregistration_delay.timeout_seconds` covers in-flight work. The default is 300. For an API whose slow requests finish in under a second, 30 is enough; AWS allows 5 for sub-second routes. Leave the long window for uploads, streams, WebSockets, and server-sent events.

`stopTimeout` starts at `SIGTERM`, after the target is unused. It has to cover process exit, not the drain. Default is 30 seconds. Fargate allows up to 120. If the process is still alive at the end of `stopTimeout`, the remaining requests die as 502s.

```python
def _on_sigterm(signum, frame):
    server.shutdown()  # stop accept, finish accepted requests, then return

signal.signal(signal.SIGTERM, _on_sigterm)
```

Gunicorn: `--graceful-timeout` shorter than `stopTimeout`. Uvicorn: set `timeout_graceful_shutdown` the same way. The framework default is not always shorter than 30 seconds.

### Keep-alive

The ALB idle timeout defaults to 60 seconds. If the application closes an idle connection first, the ALB can send the next request on a socket the process already reset. That is a 502, and it is unrelated to deploys.

Set the application keep-alive above the ALB idle timeout. ALB at 60, application at 75.

---

## A configuration that lines up

Numbers for an API that listens in about 40 seconds and finishes requests in under a second:

| Knob | Value | Why this value |
|---|---|---|
| desired count | 6 | Two per AZ. One AZ can fail and four remain. |
| `minimumHealthyPercent` / `maximumPercent` | 100 / 200 | Floor stays at 6. Ceiling allows the next wave. |
| grace period and `startPeriod` | 120s | Above a 40s start, with room for a slow boot. |
| target check | 15s interval, threshold 2 / 3 | Joins in about 30s. Three failures before ejection. |
| deregistration delay | 30s | Several times the slow request. |
| `stopTimeout` | 60s | Shutdown after `SIGTERM`, still under the Fargate 120s cap. |
| circuit breaker | enabled, rollback | A revision that never becomes healthy is failed and reverted. |
| deployment alarms | target 5xx, latency, rollback | A revision that is healthy and wrong is reverted. |

```hcl
resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 6
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 120

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  alarms {
    alarm_names = [
      aws_cloudwatch_metric_alarm.api_5xx.alarm_name,
      aws_cloudwatch_metric_alarm.api_latency.alarm_name,
    ]
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets = [
      aws_subnet.private_a.id,
      aws_subnet.private_b.id,
      aws_subnet.private_c.id,
    ]
    security_groups = [aws_security_group.api_tasks.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8080
  }
}

resource "aws_lb_target_group" "api" {
  name        = "api-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  deregistration_delay              = 30
  load_balancing_cross_zone_enabled = true

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"

  container_definitions = jsonencode([{
    name        = "api"
    image       = var.image_uri
    stopTimeout = 60

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = 120
    }

    portMappings = [{ containerPort = 8080 }]
  }])
}
```

The container check needs `curl` in the image, or a binary the image already has. On EC2, add a spread placement strategy, availability zone first, then instance. On Fargate, the three subnets are the spread.

The circuit breaker watches tasks that fail to reach a healthy `RUNNING` state. The failure count is derived from the desired count; there is no "roll back after N" field. A bad image that exits on startup trips it, the deployment goes `FAILED`, and `rollback = true` puts `PRIMARY` back on the previous task definition. The old tasks were serving the whole time because the floor was 100%.

An application that passes `/health` and returns 500 on the real routes does not trip that breaker. The deployment alarms cover that window. The alarms have to be `OK` when the deployment starts.

After `services_stable`, compare the `PRIMARY` task definition with the revision you deployed. A rolled-back service is stable on the old revision. The pipeline should fail.

```python
ecs.get_waiter("services_stable").wait(cluster="prod", services=["api"])
svc = ecs.describe_services(cluster="prod", services=["api"])["services"][0]
primary = next(d for d in svc["deployments"] if d["status"] == "PRIMARY")
if not primary["taskDefinition"].endswith(":42"):
    raise SystemExit(f"rolled back to {primary['taskDefinition']}")
```

---

## When the old tasks have to stay after traffic moves

Rolling update with the settings above keeps the previous task until the new one is a healthy target. Once the wave finishes, the previous task is gone. A regression that shows up after that has nothing to shift back to.

ECS blue/green (`deploymentStrategy` `BLUE_GREEN`) runs the new set beside the old one and moves traffic at the listener. Bake time is how long both stay up after the shift. An alarm during the bake shifts traffic back to the set that is still running.

Use it when the acceptance signal is not a health check: error rate, latency, or a lifecycle-hook Lambda that runs checks against the green target group before production traffic moves. The hook failure stops the deployment. Rolling update plus alarms is the right default for everything else. Blue/green costs a second target group and, while it bakes, a second full set of tasks.

---

## EKS settings, ECS fields

| EKS | ECS |
|---|---|
| `readinessProbe` | Target group health check. With a load balancer, this is what ECS waits for. |
| ALB readiness gate | Built in once the service has a target group. |
| `maxUnavailable: 0` | `minimumHealthyPercent: 100` |
| `maxSurge: 100%` | `maximumPercent: 200` |
| `preStop: sleep` | Omit it. Deregistration finishes before `SIGTERM`. |
| `terminationGracePeriodSeconds` | Container `stopTimeout`. 120s max on Fargate. |
| `livenessProbe` | Container `healthCheck` |
| `startupProbe` | `startPeriod` and `healthCheckGracePeriodSeconds` |
| PodDisruptionBudget | `minimumHealthyPercent`, including EC2 instance drain |
| Argo Rollouts / Flagger | ECS blue/green, lifecycle hooks, bake time |
| `kubectl rollout undo` | Circuit breaker `rollback`, or `UpdateService` back to the old revision |

---

## Check a service before the next deploy

```python
import boto3

ecs = boto3.client("ecs")
elbv2 = boto3.client("elbv2")

CLUSTER = "production"
SERVICE = "api"

def diagnose():
    svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
    dc = svc["deploymentConfiguration"]
    desired = svc["desiredCount"]
    min_pct = dc.get("minimumHealthyPercent", 100)
    max_pct = dc.get("maximumPercent", 200)
    floor = -(-desired * min_pct // 100)
    ceiling = desired * max_pct // 100

    print(f"desired={desired}  min={min_pct}% -> floor {floor}  max={max_pct}% -> ceiling {ceiling}")
    if min_pct < 100:
        print("  floor is below desired; old tasks may stop before replacements are healthy")
    if desired < 3:
        print("  fewer than 3 tasks; one AZ failure drops at least half the service")

    grace = svc.get("healthCheckGracePeriodSeconds", 0)
    print(f"healthCheckGracePeriodSeconds={grace}")

    if not svc.get("loadBalancers"):
        print("  no target group; ECS treats RUNNING as healthy")
        return

    tg_arn = svc["loadBalancers"][0]["targetGroupArn"]
    tg = elbv2.describe_target_groups(TargetGroupArns=[tg_arn])["TargetGroups"][0]
    attrs = {a["Key"]: a["Value"] for a in
             elbv2.describe_target_group_attributes(TargetGroupArn=tg_arn)["Attributes"]}
    dereg = int(attrs.get("deregistration_delay.timeout_seconds", 300))
    print(
        f"health interval={tg['HealthCheckIntervalSeconds']}s "
        f"healthy_threshold={tg['HealthyThresholdCount']} "
        f"deregistration_delay={dereg}s"
    )

    states = {}
    for t in elbv2.describe_target_health(TargetGroupArn=tg_arn)["TargetHealthDescriptions"]:
        state = t["TargetHealth"]["State"]
        states[state] = states.get(state, 0) + 1
    print(f"targets={states}")

diagnose()
```

A 6-task service that is safe to roll prints this:

```
desired=6  min=100% -> floor 6  max=200% -> ceiling 12
healthCheckGracePeriodSeconds=120
health interval=15s healthy_threshold=2 deregistration_delay=30s
targets={'healthy': 6}
```

Run it every few seconds through a deploy. The `healthy` count should stay at the desired count. A dip to the floor from the 50% table is the 503 window. `healthy: 0` is the outage in progress.

---

## Before you call the deploy done

1. `minimumHealthyPercent` 100, `maximumPercent` 200, and spare capacity for the ceiling.
2. At least three tasks, across three subnets. Cross-zone on unless traffic must stay in-AZ.
3. Grace period and `startPeriod` above measured startup. `/health` returns non-200 until dependencies answer.
4. Deregistration delay covers the longest request you intend to finish. `stopTimeout` covers exit after `SIGTERM`. Application keep-alive is above the ALB idle timeout.
5. Circuit breaker with rollback. Alarms on target 5xx and latency for the failures the breaker does not see.
6. The pipeline compares `PRIMARY` with the revision it just shipped.

Blue/green is the next step for a service where you need the previous tasks still running after traffic has moved.

---

## References

- [Service parameters, including the six-task replacement sequences](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-options.html)
- [Rolling update behavior](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html)
- [Connection draining and SIGTERM](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/load-balancer-connection-draining.html)
- [Load balancer health checks](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/load-balancer-healthcheck.html)
- [DeploymentConfiguration](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_DeploymentConfiguration.html)
- [Deploy without downtime](https://repost.aws/knowledge-center/ecs-deploy-tasks-no-downtime)
- [ECS blue/green](https://aws.amazon.com/about-aws/whats-new/2025/07/amazon-ecs-built-in-blue-green-deployments/)
- [Lifecycle hooks](https://aws.amazon.com/blogs/containers/extending-deployment-pipelines-with-amazon-ecs-blue-green-deployments-and-lifecycle-hooks)
- [Target group health and per-AZ 503s](https://aws.amazon.com/blogs/networking-and-content-delivery/using-load-balancer-target-group-health-thresholds-to-improve-availability/)
