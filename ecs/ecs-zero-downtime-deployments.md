# Zero-downtime deployments on ECS

A zero-downtime deploy comes down to two rules:

1. Old tasks keep running until the new ones are ready.
2. An old task finishes the requests it already has before it is shut down.

ECS can do both. Most deploys that drop requests have one setting that breaks one of these rules. This note covers the five settings that matter, a config you can copy, and a way to test it.

---

## What a safe deploy looks like

Say the service runs 6 tasks and you deploy a new version.

```
Before     [old] [old] [old] [old] [old] [old]          6 serving

Start 2    [old] [old] [old] [old] [old] [old] [new] [new]
           the new ones are booting, nobody sends them traffic yet

Ready      [old] [old] [old] [old] [old] [old] [new] [new]
           the new ones pass health checks, 8 serving

Retire 2   [old] [old] [old] [old] [new] [new]          6 serving
           the old ones drain, finish their requests, stop

...repeat until all six are new
```

The number serving never drops below 6. That is the whole idea.

The unsafe version starts by stopping old tasks to make room. With 6 tasks and a 50% floor, ECS can stop 3 old tasks first. Three tasks then carry the traffic of six while the new ones boot. They slow down, fail their health checks, and the load balancer ends up with no healthy targets. Every request in that gap is a 503.

---

## The five settings

| # | Setting | Use | In plain words |
|---|---|---|---|
| 1 | `minimumHealthyPercent` | `100` | Never go below the current number of healthy tasks. |
| 2 | `maximumPercent` | `200` | Allow double the tasks during a deploy, so new ones start before old ones stop. |
| 3 | Health check on `/health` | returns 200 only when the app is ready | ECS will not stop an old task until the new one passes this. |
| 4 | `healthCheckGracePeriodSeconds` | longer than your app takes to start | Do not kill a new task for failing checks while it is still booting. |
| 5 | Shutdown: `deregistration_delay` and `stopTimeout` | about 30s and 60s | Let the old task finish what it started before it stops. |

If you only do one thing, do 1 and 2. They are the API defaults for a normal service, so check that nobody lowered them. Templates and blog posts often set `minimumHealthyPercent` to 50 to make deploys faster. That is fine for a background worker. It is not fine for something behind a load balancer.

Also run at least 3 tasks, spread across 3 availability zones. With one or two tasks there is no setting that makes a rolling deploy safe, because one failure leaves you with nothing.

---

## A config you can copy

Terraform. This is for a Fargate service behind an ALB, with an app that starts in about 40 seconds.

```hcl
resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 3
  launch_type     = "FARGATE"

  # 1 and 2: add new tasks first, never drop below full capacity
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # 4: do not kill a new task while it is still starting
  health_check_grace_period_seconds = 120

  # If the new version never becomes healthy, stop and roll back
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8080
  }

  network_configuration {
    subnets         = [aws_subnet.private_a.id, aws_subnet.private_b.id, aws_subnet.private_c.id]
    security_groups = [aws_security_group.api_tasks.id]
  }
}

resource "aws_lb_target_group" "api" {
  name        = "api-tg"
  port        = 8080
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  # 5: wait up to 30s for in-flight requests (default is 300s)
  deregistration_delay = 30

  # 3: the health check ECS waits for
  health_check {
    path                = "/health"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
```

In the task definition, give the container time to shut down:

```json
{
  "name": "api",
  "stopTimeout": 60
}
```

The circuit breaker is the safety net. If the new tasks keep failing to start, ECS marks the deployment failed and goes back to the previous version. The old tasks were serving the whole time, so users do not notice.

---

## Two things your app has to do

### 1. Say "not ready" until it is ready

A health check that always returns 200 makes ECS think a new task is ready as soon as the web server opens its port. The old tasks go away while the new one is still connecting to the database.

```python
@app.get("/health")
def health():
    if not db.ping():
        return JSONResponse({"status": "starting"}, status_code=503)
    return {"status": "ok"}
```

Keep it light. It runs every 15 seconds on every task. Check the one or two things the app cannot work without, and nothing else.

### 2. Stop cleanly on SIGTERM

When ECS stops a task, it first removes it from the load balancer, waits for requests to finish, and then sends `SIGTERM`. Your app should stop accepting new work, finish the current requests, and exit. Most frameworks do this by default. If yours does not, any request still running when `stopTimeout` ends is cut off, and the client sees a 502.

```python
import signal

def on_sigterm(signum, frame):
    server.shutdown()   # stop accepting, finish what is running, then exit

signal.signal(signal.SIGTERM, on_sigterm)
```

Gunicorn: `--graceful-timeout` should be shorter than `stopTimeout`.

---

## Test it before you trust it

Run a request loop in one terminal while you deploy from another.

```bash
for i in $(seq 1 600); do
  curl -s -o /dev/null -w "%{http_code}\n" https://api.example.com/health
  sleep 0.2
done | sort | uniq -c
```

A good run prints one line:

```
600 200
```

Anything else tells you which setting to look at:

| You see | Likely cause |
|---|---|
| `503` | The load balancer had no healthy task. Check `minimumHealthyPercent`, the number of tasks, and whether `/health` returns 200 too early. |
| `502` | A task closed a connection mid-request. Check `SIGTERM` handling and `stopTimeout`. |
| `504` | A request took longer than the load balancer's idle timeout (60s by default). |

Run the test in staging first, with real traffic volume if you can. The 50% setting looks fine with no load and fails under load.

---

## Common mistakes

- **`minimumHealthyPercent` at 50.** Copied from a template. Set it back to 100.
- **Grace period shorter than startup time.** ECS kills each new task before it finishes booting, and the deploy never completes. Measure how long your app takes to pass its first health check and set the grace period above that. Java apps often need 2 to 3 minutes.
- **`/health` returns 200 immediately.** The deploy looks green, and the first real requests fail.
- **Not enough room on EC2.** With 200% the cluster needs space for double the tasks. If there is none, the new tasks stay in `PENDING` and the deploy hangs. Fargate does not have this problem.
- **Deregistration delay left at 300 seconds.** Not a failure, but every deploy is slow. 30 seconds is enough for most APIs.

---

## Where to go next

- A service that passes `/health` but returns errors on real routes is not caught by the circuit breaker. Add CloudWatch alarms on 5xx and latency, and attach them to the deployment so ECS rolls back on them.
- If you need the old version to keep running after traffic has moved, use ECS blue/green. It keeps both versions up for a set time and shifts traffic back if an alarm fires. See [deployment circuit breakers](./ecs-deployment-circuit-breakers.md) for how the breaker and alarms fit together.
- For why `RUNNING` does not mean healthy, see [task health is not application health](./ecs-task-health-is-not-the-same-as-app-health.md).

## References

- [Service parameters and the rolling replacement sequences](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-options.html)
- [Connection draining and SIGTERM](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/load-balancer-connection-draining.html)
- [Load balancer health checks](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/load-balancer-healthcheck.html)
- [Deploy without downtime (re:Post)](https://repost.aws/knowledge-center/ecs-deploy-tasks-no-downtime)
