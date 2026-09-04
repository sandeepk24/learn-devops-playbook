# Why Your ECS Deployments Return 503s (And How to Stop It)

*Written for teams who've used Kubernetes, expect the same deployment safety from ECS, and aren't getting it.*

---

## The complaint

Your team ships a new task definition. For thirty to sixty seconds, some fraction of requests come back as `503 Service Unavailable`. Then it clears up and everyone moves on until the next deploy.

Meanwhile the same team remembers EKS, where a rolling update meant the old pod stayed alive until the new pod passed its readiness probe. Nothing dropped. So the natural conclusion is that ECS is just worse at this.

It isn't. ECS has every primitive you need for a genuinely zero-downtime rollout, and in one respect its default draining behavior is actually safer than vanilla Kubernetes. The problem is that the defaults are tuned for deployment speed rather than deployment safety, and a handful of settings that look unrelated turn out to be load-bearing. Almost every ECS 503-on-deploy I've been called into traces back to two or three of the same misconfigurations.

Let's find yours.

---

## First, read the error correctly

This is the single most important diagnostic step, and most teams skip it.

A `503` from an Application Load Balancer has a specific meaning that is different from a `502` or a `504`:

| Code | What the ALB is telling you |
|---|---|
| **503** | I had **no healthy target** to send this request to. I never even tried. |
| **502** | I sent the request to a target and the connection was reset or the response was malformed. |
| **504** | I sent the request to a target and it never answered in time. |

That distinction narrows your search enormously. A 503 means the target group was genuinely empty (or empty in the Availability Zone that received the request) at the moment the request arrived. It is not a draining problem, not a slow-shutdown problem, not a keep-alive problem. Those produce 502s and 504s.

So if your team is reporting 503s specifically, stop tuning deregistration delay. You have a capacity problem during rollout: old tasks left the target group before new tasks arrived in it.

You can confirm this in about two minutes. Pull the ALB access logs and look at any 503 line:

```
elb_status_code = 503
target_status_code = -
target:port = -
```

When `target_status_code` is a dash, the load balancer never got a backend. That's your smoking gun. If instead you see `elb_status_code 502` with a real target IP, you're chasing a different bug and I cover that further down.

The CloudWatch equivalent is comparing two metrics side by side. `HTTPCode_ELB_5XX_Count` counts errors the load balancer generated itself. `HTTPCode_Target_5XX_Count` counts errors your application generated. If the ELB number spikes during deploys while the target number stays flat, the load balancer ran out of backends.

---

## What ECS actually does during a rolling deployment

Before fixing anything, it's worth understanding the sequence, because it's more careful than most people assume.

When you call `UpdateService` with a new task definition, ECS creates an immutable service revision and begins replacing tasks in waves. Within each wave:

1. The scheduler launches new tasks, subject to your `maximumPercent` ceiling.
2. Each new task registers with the target group and enters `initial` state.
3. The ALB begins health checking it. Once it passes `healthyThresholdCount` consecutive checks, the target flips to `healthy`.
4. ECS now considers that task healthy and counts it toward the running total.
5. Only then does the scheduler pick old tasks to stop, subject to your `minimumHealthyPercent` floor.
6. Old tasks are **deregistered from the target group first**. They go into `draining`.
7. ECS waits for the load balancer to report the target as `unused`, meaning in-flight requests finished or the deregistration delay expired.
8. Only after draining completes does ECS send `SIGTERM` to the container.
9. After `stopTimeout` seconds, `SIGKILL`.

Step 6 through 8 is genuinely nice. In stock Kubernetes, pod deletion and endpoint removal race each other, which is exactly why everyone ends up writing a `preStop: sleep 15` hack. ECS orders it for you. You do not need a preStop equivalent.

Step 3 is the readiness gate. When your service is attached to a load balancer, ECS uses target group health as its definition of task health. That's the same guarantee EKS gives you with ALB readiness gates, and it's on by default.

So where do the 503s come from?

From step 5. The floor is a percentage, and percentages round badly at small task counts.

---

## The four causes, in order of how often I find them

### Cause 1: `minimumHealthyPercent` at 50% with a small desired count

This is the big one. It shows up in roughly half the cases I look at.

Plenty of blog posts, Terraform modules, and internal templates recommend `minimumHealthyPercent = 50` because it makes deployments faster and cheaper. The ECS documentation itself suggests 50% for tasks that are idle much of the time. That advice is fine for a batch worker. It is dangerous for a customer-facing API.

Watch what happens at small scale. The floor is `desiredCount × minimumHealthyPercent / 100`, rounded up:

| desiredCount | min % 50 → floor | What ECS is allowed to do |
|---|---|---|
| 1 | 1 | Actually safe, rounding saves you |
| 2 | 1 | Kill one of two. Half capacity during rollout. |
| 3 | 2 | Kill one. Tolerable. |
| 4 | 2 | Kill two before starting any. |
| 6 | 3 | Kill three before starting any. |

Notice step 5 in the sequence above. With a 50% floor, the scheduler is permitted to stop old tasks *first* and start new ones afterward. The AWS documentation walks through exactly this: with six tasks and a 50% floor, the scheduler stops three existing tasks, then starts five new ones. For the window between those two events you are running at half capacity with new tasks still booting.

Half capacity is not zero capacity, so why 503s? Because remaining capacity now absorbs double the traffic, response times climb, the ALB health check starts timing out on the survivors, and they get marked unhealthy too. The target group empties. That's your 503. It's a small cascade, and it only shows up under real production load, which is why it never reproduces in staging.

**Fix:** set `minimumHealthyPercent = 100` and `maximumPercent = 200` for anything serving user traffic. This is the actual API default for replica services, so if you're seeing 50%, someone set it deliberately. With a 100% floor ECS must add before it removes, which is precisely the EKS `maxUnavailable: 0` behavior your team is used to.

The cost is that you need headroom for double the tasks during rollout. On Fargate that's a few minutes of extra billing. On EC2 it means your cluster needs real free capacity or the deployment will stall waiting for placement.

### Cause 2: `desiredCount` of 1 or 2

Related but distinct. With a single task, there is no configuration on earth that gives you a zero-downtime rolling deploy, because there's a moment where the only task is being replaced. With two tasks, one AZ failure during a deploy leaves you at 50%.

Three is the practical minimum for a production service, spread across three AZs. This also interacts with the ALB in a way people miss: an ALB node in each AZ routes to targets in its own AZ when cross-zone load balancing is disabled. If cross-zone is off (the default for Network Load Balancers, and configurable per target group on ALBs) and all your tasks land in two of three AZs, the third AZ's ALB node has nothing to route to and returns 503 for every request it receives. That failure mode is invisible in aggregate metrics and obvious in per-AZ ones.

**Fix:** minimum three tasks, three subnets, and verify cross-zone load balancing is enabled on the target group unless you have a specific reason to disable it.

### Cause 3: `healthCheckGracePeriodSeconds` shorter than real startup time

This one produces a nastier failure than a brief dip.

The grace period tells ECS to ignore load balancer health check results for the first N seconds after a task starts. If your Spring Boot app takes 45 seconds to warm up and your grace period is 30 seconds, here's the loop: task starts, ALB health checks fail because the app isn't listening yet, ECS sees an unhealthy task past the grace period, ECS kills it, ECS launches a replacement, replacement does the same thing.

Now the deployment is churning, no new tasks ever become healthy, and if your `minimumHealthyPercent` also let old tasks go, the target group is empty for minutes rather than seconds. That's a real outage, not a blip.

**Fix:** measure your actual p99 startup time from container start to first successful health check, then set the grace period to roughly double it. For a Java service that's often 120 to 180 seconds. For a Go binary, 30 is plenty. Err high; the grace period costs you nothing when tasks start fast, since ECS stops waiting as soon as the target reports healthy.

Pair this with a container-level `healthCheck` in the task definition using `startPeriod`, which serves the same purpose at the container layer.

### Cause 4: no load balancer health check at all

If your ECS service isn't attached to a target group, or the target group health check is misconfigured to always pass, ECS falls back to a much weaker definition of healthy: the container is `RUNNING`. That means the process started. Not that it can serve traffic.

ECS will happily drain your old tasks the instant the new container's PID 1 exists. Your app is still connecting to the database. Requests arrive. 503.

**Fix:** always attach a target group with a real health check that exercises the app, and make sure the health check path returns non-200 while the app is still initializing. A `/health` endpoint that returns 200 from a static route handler before dependencies are wired up is worse than useless, because it lies to the load balancer at exactly the wrong moment.

---

## If you're actually seeing 502s and 504s

Different problem, different fix. These come from the shutdown side rather than the startup side.

**Deregistration delay left at the 300-second default.** Not a correctness issue, but it makes every deployment slow and it makes tasks appear stuck in draining. AWS's guidance is to set it to roughly double your application's response time. For a typical API answering in under a second, 30 seconds is comfortable, and the docs note you can go as low as 5 for sub-second services. Do not do this if you have long-lived requests: file uploads, streaming responses, WebSockets, or server-sent events all need the full window.

**The app ignores `SIGTERM`.** ECS sends the stop signal (`SIGTERM` by default, overridable with `STOPSIGNAL` in your image), waits `stopTimeout`, then sends `SIGKILL`. The agent default is 30 seconds via `ECS_CONTAINER_STOP_TIMEOUT`, and you can set `stopTimeout` per container in the task definition. If your framework doesn't trap `SIGTERM` and close the listener gracefully, every in-flight request at the moment of `SIGKILL` becomes a 502.

Most modern frameworks handle this. Some don't out of the box. Here's the Python shape, since that's likely your stack:

```python
import signal
import sys
import time

shutting_down = False

def handle_sigterm(signum, frame):
    global shutting_down
    shutting_down = True
    # Flip the health endpoint to unhealthy first so the LB stops
    # sending new work, then let in-flight requests finish.
    app.stop_accepting_new_connections()
    time.sleep(2)          # let the LB notice
    app.wait_for_inflight(timeout=25)
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)
```

For Gunicorn, `--graceful-timeout` needs to be shorter than your `stopTimeout` or the worker gets killed mid-request anyway. For uvicorn, the default `SIGTERM` handling drains correctly but you still want `timeout_graceful_shutdown` set explicitly.

**ALB idle timeout shorter than your app's keep-alive timeout.** Classic and maddening. The ALB holds a keep-alive connection to your task. Your app decides the connection is idle and closes it. A request arrives on that connection in the microsecond before the ALB notices. Reset. 502. The rule is that your application's keep-alive timeout must be *longer* than the ALB idle timeout, which defaults to 60 seconds. Set your app to 65 or 75.

---

## The configuration that actually fixes it

Here's what a production service should look like. I'll give it in Terraform since that's what most teams are running.

```hcl
resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 6                # never fewer than 3
  launch_type     = "FARGATE"

  # The two numbers that stop the 503s.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Ignore LB health checks while the app boots.
  # Measure your real p99 startup and roughly double it.
  health_check_grace_period_seconds = 120

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Roll back automatically if error rates spike after the deploy.
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

  # Spread first by AZ, then by instance. Order matters.
  ordered_placement_strategy {
    type  = "spread"
    field = "attribute:ecs.availability-zone"
  }
}

resource "aws_lb_target_group" "api" {
  name        = "api-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"                 # required for awsvpc / Fargate

  # 300s default makes every deploy crawl. Roughly 2x your p99 response time.
  deregistration_delay = 30

  # Keep this on unless you have a specific reason not to.
  load_balancing_cross_zone_enabled = true

  health_check {
    enabled             = true
    path                = "/health"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 15         # check often so new tasks join fast
    timeout             = 5
    healthy_threshold   = 2          # 2 x 15s = healthy in ~30s
    unhealthy_threshold = 3          # tolerate a blip before ejecting
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"

  container_definitions = jsonencode([{
    name  = "api"
    image = var.image_uri

    # Time between SIGTERM and SIGKILL. Must exceed your drain window.
    stopTimeout = 60

    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"]
      interval    = 15
      timeout     = 5
      retries     = 3
      startPeriod = 120   # mirrors the service grace period
    }

    portMappings = [{ containerPort = 8080 }]
  }])
}
```

A note on the numbers, because they're related and people tune them in isolation.

Your health check interval times the healthy threshold determines how fast a new task can join the target group. At 15 and 2 that's about 30 seconds. Lower it and deployments speed up, but you also add health check load to every task.

Your deregistration delay must exceed your p99 request duration or you'll cut off legitimate in-flight work. Your `stopTimeout` must exceed your deregistration delay, because ECS drains first and *then* signals the container. If `stopTimeout` is 30 and deregistration delay is 60, the container gets killed while requests are still landing on it.

The ordering to remember is: **health check window < deregistration delay < stopTimeout < grace period budget**.

---

## Beyond rolling: native blue/green

Everything above makes rolling deployments safe. But if your team wants the stronger guarantee, ECS gained something significant in 2025 that a lot of people still haven't picked up.

In July 2025 AWS shipped built-in blue/green deployments directly in ECS, with no CodeDeploy required. ECS provisions the new version alongside the old, lets you validate it before shifting production traffic, and rolls back without downtime if you detect a regression. In October 2025 they added canary and linear traffic shifting, reaching parity with CodeDeploy. The AWS CDK guidance was updated in March 2026 to recommend the ECS-native path as the default for new deployments.

Three things make this worth the migration:

**Lifecycle hooks.** These are synchronous Lambda functions ECS invokes at defined stages of the deployment. Your function returns a status, and a failure blocks the deployment from proceeding. That means you can run an integration suite against the green environment before a single user request touches it, or require a manual approval, or check that the image came from a trusted registry.

**Test listeners, sometimes called dark canary.** You point a separate ALB listener at the green target group and hit it with synthetic traffic in the real production environment, with real dependencies, and zero user impact. Then you shift.

**Bake time.** After traffic shifts, ECS holds both versions and watches. Wire CloudWatch alarms into it and a latency regression triggers an automatic rollback to a version that's still warm and running. Rolling deployments can't do this, because the old version is already gone.

The other quiet improvement in that release: you can now change the deployment controller after service creation. Previously, picking rolling update at creation time locked you in. So migrating an existing service is now an update rather than a rebuild.

If I were advising your team, I'd say: fix the rolling configuration first because it's a one-day change that eliminates the 503s, then evaluate blue/green for your highest-traffic services over the following quarter.

---

## Mapping your team's EKS instincts to ECS

Since the team is comparing against Kubernetes, here's the translation table. Print it and hand it out.

| What you did in EKS | The ECS equivalent | Notes |
|---|---|---|
| `readinessProbe` | Target group health check | ECS treats target health as task health when a LB is attached |
| ALB readiness gates | Nothing to install | Built in, not an add-on controller |
| `maxUnavailable: 0` | `minimumHealthyPercent: 100` | The setting that most often causes 503s when wrong |
| `maxSurge: 100%` | `maximumPercent: 200` | Same idea, same math |
| `preStop: sleep 15` | Not needed | ECS deregisters and drains *before* it sends SIGTERM |
| `terminationGracePeriodSeconds` | `stopTimeout` on the container | Fargate allows up to 120s |
| `livenessProbe` | Container `healthCheck` in the task definition | Separate from the LB check |
| `startupProbe` | `startPeriod` + `healthCheckGracePeriodSeconds` | Two layers, set both |
| PodDisruptionBudget | `minimumHealthyPercent` | Covers deploys and instance draining |
| Argo Rollouts / Flagger | ECS native blue/green + lifecycle hooks | As of July 2025, no third tool required |
| `kubectl rollout undo` | Deployment circuit breaker with rollback | Automatic rather than manual |

The point worth landing with your team: the preStop hack they're used to writing is unnecessary here, and the readiness gate they had to install a controller for is already running.

---

## A diagnostic script for next deploy

Run this against the service during a deployment. It'll tell you which of the four causes you have.

```python
import boto3
from datetime import datetime, timedelta, timezone

ecs = boto3.client("ecs")
elbv2 = boto3.client("elbv2")

CLUSTER = "production"
SERVICE = "api"

def diagnose():
    svc = ecs.describe_services(cluster=CLUSTER, services=[SERVICE])["services"][0]
    dc = svc["deploymentConfiguration"]
    desired = svc["desiredCount"]

    min_pct = dc.get("minimumHealthyPercent", 100)
    floor = -(-desired * min_pct // 100)   # ceiling division

    print(f"desiredCount={desired}  minimumHealthyPercent={min_pct}%")
    print(f"  -> ECS may drop to {floor} running tasks mid-deploy")

    if min_pct < 100:
        print("  RISK: ECS can stop old tasks before starting new ones.")
    if desired < 3:
        print("  RISK: too few tasks for a safe rolling replace.")

    grace = svc.get("healthCheckGracePeriodSeconds", 0)
    print(f"healthCheckGracePeriodSeconds={grace}")
    if grace < 60:
        print("  RISK: verify this exceeds real container startup time.")

    if not svc.get("loadBalancers"):
        print("  RISK: no target group attached. ECS will treat RUNNING as healthy.")
        return

    tg_arn = svc["loadBalancers"][0]["targetGroupArn"]

    attrs = {a["Key"]: a["Value"] for a in
             elbv2.describe_target_group_attributes(TargetGroupArn=tg_arn)["Attributes"]}
    dereg = int(attrs.get("deregistration_delay.timeout_seconds", 300))
    print(f"deregistration_delay={dereg}s")
    if dereg >= 300:
        print("  SLOW: default 300s. Consider ~2x your p99 response time.")

    health = elbv2.describe_target_health(TargetGroupArn=tg_arn)["TargetHealthDescriptions"]
    states = {}
    for t in health:
        s = t["TargetHealth"]["State"]
        states[s] = states.get(s, 0) + 1
    print(f"target states: {states}")

    if states.get("healthy", 0) == 0:
        print("  ACTIVE OUTAGE: zero healthy targets. This is your 503.")

diagnose()
```

Run it in a loop every five seconds through an entire deployment and you'll watch the healthy count dip. Where it dips to tells you the cause.

---

## The short version for your standup

1. Set `minimumHealthyPercent` to 100 and `maximumPercent` to 200. This alone fixes most cases.
2. Run at least three tasks across three AZs.
3. Set `healthCheckGracePeriodSeconds` to about twice your measured startup time.
4. Drop `deregistration_delay` from 300 to around 30, unless you have long-lived connections.
5. Make sure the app traps `SIGTERM` and that `stopTimeout` is longer than the drain window.
6. Confirm the health endpoint returns non-200 until dependencies are actually ready.
7. Turn on the deployment circuit breaker with rollback, and wire CloudWatch alarms into it.
8. For your top services, plan a move to ECS native blue/green with lifecycle hooks.

---

## References

Official AWS documentation and blogs, in the order you'll want them:

- [Best practices for Amazon ECS service parameters](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-options.html) — walks through the exact rolling replacement sequence at different `minimumHealthyPercent` values
- [Optimize load balancer connection draining parameters](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/load-balancer-connection-draining.html) — deregistration delay, `ECS_CONTAINER_STOP_TIMEOUT`, SIGTERM responsiveness
- [Optimize load balancer health check parameters](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/load-balancer-healthcheck.html)
- [DeploymentConfiguration API reference](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_DeploymentConfiguration.html) — the authoritative defaults
- [Deploy new tasks in Amazon ECS without downtime](https://repost.aws/knowledge-center/ecs-deploy-tasks-no-downtime) — AWS re:Post knowledge center article
- [Amazon ECS enables built-in blue/green deployments](https://aws.amazon.com/about-aws/whats-new/2025/07/amazon-ecs-built-in-blue-green-deployments/) — the July 2025 launch announcement
- [Extending deployment pipelines with Amazon ECS blue/green deployments and lifecycle hooks](https://aws.amazon.com/blogs/containers/extending-deployment-pipelines-with-amazon-ecs-blue-green-deployments-and-lifecycle-hooks) — Containers blog, the deep dive on hooks
- [Choosing between Amazon ECS Blue/Green Native or AWS CodeDeploy in AWS CDK](https://aws.amazon.com/blogs/devops/choosing-between-amazon-ecs-blue-green-native-or-aws-codedeploy-in-aws-cdk) — updated March 2026, recommends ECS-native as the default
- [Using load balancer target group health thresholds to improve availability](https://aws.amazon.com/blogs/networking-and-content-delivery/using-load-balancer-target-group-health-thresholds-to-improve-availability/) — relevant to the per-AZ 503 case
- [aws-samples: ECS blue/green deployment patterns](https://github.com/aws-samples/sample-amazon-ecs-blue-green-deployment-patterns) — working lifecycle hook examples

---

Two questions I'd want answered before signing off on the fix:

What's your actual p99 container startup time, measured from task start to first healthy target? Most teams guess and guess low, and it's the number that everything else keys off.

And are any of your services running with `desiredCount` of 1 or 2 in production? Because if so, no amount of deployment tuning will get you to zero downtime there, and that's a capacity conversation rather than a configuration one.
