# 🚀 AWS ECS — Part 4: Resource Exhaustion (OOM & CPU) on Fargate

> **Learn DevOps Playbook** · ECS Series (Part 4 of 5)
>
> What *actually* happens when a Fargate task runs out of memory or pins the CPU — at the container, kernel, and ECS-service layers. Concept first, then a hands-on repro you can run to watch an OOM kill unfold.
>
> 👈 **Part 3 — Deep Dives:** ALB → target groups, networking, IAM.
> 👉 **Part 5 — Recovery & Self-Healing:** how ECS brings the service back after these failures.

> Assumes `$CLUSTER`, `$SERVICE`, `$AWS_DEFAULT_REGION` from earlier parts, and the `hello-ecs` app from Part 1.

---

## 📚 Table of Contents

1. [The Mental Model: Where Limits Live](#-the-mental-model-where-limits-live)
2. [Memory Exhaustion — What Actually Happens](#-memory-exhaustion--what-actually-happens)
3. [CPU Exhaustion — What Actually Happens](#-cpu-exhaustion--what-actually-happens)
4. [Memory vs CPU: The Critical Asymmetry](#-memory-vs-cpu-the-critical-asymmetry)
5. [Hands-On: Reproduce an OOM Kill](#-hands-on-reproduce-an-oom-kill)
6. [Hands-On: Reproduce CPU Saturation](#-hands-on-reproduce-cpu-saturation)
7. [Detecting Exhaustion Before It Kills You](#-detecting-exhaustion-before-it-kills-you)
8. [What's Next](#-whats-next)

---

## 🧠 The Mental Model: Where Limits Live

On Fargate there are **two layers of resource limits**, and they behave completely differently. Getting these straight is the whole game.

```
┌─────────────────────────────────────────────┐
│  TASK-LEVEL limits (cpu / memory in task def)│  ← Fargate provisions this much
│  e.g. cpu=256, memory=512                    │     capacity for the microVM
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │ CONTAINER-LEVEL limits                 │ │  ← cgroup limits per container
│  │  memory        (hard cap → OOM kill)   │ │
│  │  memoryReservation (soft cap)          │ │
│  │  cpu           (relative weight)       │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

| Setting | Level | Type | Effect when exceeded |
|---|---|---|---|
| `memory` (task) | Task | Hard | Total microVM RAM; container `memory` can't exceed it |
| `cpu` (task) | Task | Hard | Total vCPU allotment for the whole task |
| `memory` (container) | Container | **Hard cap** | Container is **OOM-killed** the instant it exceeds this |
| `memoryReservation` (container) | Container | **Soft cap** | Guaranteed floor; container can burst above until task memory is contended |
| `cpu` (container) | Container | **Relative weight** | Throttled, never killed — shares are divided by weight under contention |

> 💡 **The one sentence to remember:** memory limits are *hard walls* (breach them → your process dies); CPU limits are *speed limits* (breach them → your process slows down). This asymmetry drives everything below.

---

## 💥 Memory Exhaustion — What Actually Happens

### The sequence, layer by layer

When a container's memory usage climbs toward its hard `memory` limit:

1. **cgroup accounting** — the Linux kernel tracks the container's memory via its cgroup. Every allocation counts against the limit.
2. **The wall is hit** — the moment the container tries to allocate past its hard `memory` value, the kernel's **OOM killer** fires *inside that cgroup*.
3. **Process killed with SIGKILL** — the offending process (usually PID 1, your app) receives signal 9. It cannot catch or handle SIGKILL — there's no graceful shutdown, no cleanup.
4. **Container exits 137** — `137 = 128 + 9`. This exit code is the fingerprint of an OOM kill.
5. **Task stops** — if the OOM-killed container is `essential` (the default), the whole **task** transitions to `STOPPED`.
6. **ECS records the reason** — `stoppedReason` on the task reads `OutOfMemoryError: Container killed due to memory usage`.

```
app allocates memory ──▶ cgroup limit reached ──▶ kernel OOM killer
        │                                              │
        ▼                                              ▼
   SIGKILL (9) ──▶ container exit 137 ──▶ essential? ──▶ task STOPPED
                                              │
                                              ▼
                              stoppedReason: OutOfMemoryError
```

### Where to see the evidence

```bash
# Find recently OOM-killed tasks and confirm the fingerprint
STOPPED=$(aws ecs list-tasks --cluster $CLUSTER --service-name $SERVICE \
  --desired-status STOPPED --query 'taskArns[:5]' --output text)

aws ecs describe-tasks --cluster $CLUSTER --tasks $STOPPED \
  --query 'tasks[*].{
    StopCode:stopCode,
    StoppedReason:stoppedReason,
    Container:containers[0].name,
    ExitCode:containers[0].exitCode,
    ContainerReason:containers[0].reason
  }' --output table
```

An OOM kill shows: `ExitCode: 137` and `ContainerReason` / `StoppedReason` mentioning `OutOfMemoryError`.

### `memory` vs `memoryReservation` — the nuance that bites people

```json
{
  "name": "web",
  "memory": 512,             // hard cap: exceed → OOM kill
  "memoryReservation": 256   // soft cap: guaranteed floor, can burst above
}
```

- Set **only `memory`** → hard cap, simple, predictable kills.
- Set **only `memoryReservation`** → soft floor; the container can use up to the *task's* total memory. Flexible, but one greedy container can starve siblings.
- Set **both** → soft floor of 256 with a hard ceiling of 512. Common best practice: reservation = normal usage, memory = absolute max you'll tolerate.

> ⚠️ On Fargate, if a container has no hard `memory` but the whole **task** hits its memory allotment, the kernel still OOM-kills a process in the task — you just have less control over *which* one.

---

## 🔥 CPU Exhaustion — What Actually Happens

CPU is the opposite story: **nothing gets killed**. When a container demands more CPU than it's entitled to, the kernel's CFS (Completely Fair Scheduler) simply **throttles** it.

### The sequence

1. **CPU shares / quota** — the container's `cpu` value becomes a cgroup CPU weight. Under contention, the scheduler divides available CPU time by weight.
2. **Throttling, not killing** — when the container wants more CPU than its slice, the kernel makes it **wait**. Requests queue, latency rises, throughput falls.
3. **The app degrades, stays alive** — health checks may start timing out (see the cascade below), but the process itself keeps running.

```
app wants more CPU ──▶ cgroup CPU quota exceeded ──▶ CFS throttles
        │                                                 │
        ▼                                                 ▼
   requests queue ──▶ latency ↑, throughput ↓ ──▶ (process stays ALIVE)
        │
        ▼
   health check may time out ──▶ [see Part 5 for what happens next]
```

### The dangerous second-order effect

CPU exhaustion rarely kills a task *directly*. It kills it *indirectly*:

1. CPU pinned at 100% → the app can't respond to the ALB health check within `HealthCheckTimeoutSeconds`.
2. Enough consecutive timeouts → target group marks the target **unhealthy**.
3. ALB stops routing to it; if it's a container health check failing, ECS may **restart the task**.

So a CPU problem masquerades as a *health-check* problem. This is why "task keeps getting replaced but exits cleanly" so often traces back to CPU starvation, not a crash.

### Seeing throttling

CloudWatch's standard `CPUUtilization` shows the *service average* but hides per-task throttling. **Container Insights** exposes the real signal:

```bash
# Service-level CPU (the blunt instrument)
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ClusterName,Value=$CLUSTER Name=ServiceName,Value=$SERVICE \
  --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Average Maximum \
  --query 'Datapoints[*].{Time:Timestamp, Avg:Average, Max:Maximum}' \
  --output table
```

> 📎 To see genuine per-task CPU/memory and throttle counts, enable **Container Insights** on the cluster — covered in the detection section below.

---

## ⚖️ Memory vs CPU: The Critical Asymmetry

This table is the article in miniature — worth committing to memory:

| Dimension | Memory exhaustion | CPU exhaustion |
|---|---|---|
| Kernel behavior | OOM killer fires | CFS throttles |
| Signal to process | SIGKILL (9) — uncatchable | none — just waits |
| Process outcome | **Killed immediately** | **Stays alive, runs slow** |
| Exit code | `137` | n/a (no exit) |
| Task outcome | `STOPPED` (if essential) | usually keeps `RUNNING` |
| `stoppedReason` | `OutOfMemoryError` | (task doesn't stop from CPU alone) |
| How it usually kills a task | Directly | Indirectly, via health-check timeouts |
| Graceful shutdown? | No | Yes (app never stops) |

> 🤔 **Worth thinking through:** given SIGKILL can't be caught, is there *anything* your app can do to shut down cleanly on OOM? (Hint: the leverage isn't at kill time — it's earlier, at the `memoryReservation`/`memory` gap and at what you do when memory *approaches* the limit. We revisit graceful drain in Part 5.)

---

## 🧪 Hands-On: Reproduce an OOM Kill

Let's make a task OOM itself on purpose and watch the fingerprint appear. We'll add a memory-hog endpoint to the Part 1 FastAPI app.

### Step 1 — An app that can eat memory on demand

```python
# app.py
from fastapi import FastAPI

app = FastAPI()

# Module-level list so allocations aren't garbage-collected
_hog: list[bytearray] = []

@app.get("/")
def root():
    return {"message": "Hello from ECS Fargate 👋"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/eat/{mb}")
def eat(mb: int):
    """Allocate `mb` megabytes and hold onto it. Repeated calls accumulate."""
    _hog.append(bytearray(mb * 1024 * 1024))
    held = sum(len(b) for b in _hog) // (1024 * 1024)
    return {"allocated_mb_this_call": mb, "total_held_mb": held}
```

### Step 2 — A deliberately tight task definition

Give the container a hard 512 MB cap so it's easy to breach:

```bash
cat > taskdef-oom.json <<EOF
{
  "family": "hello-ecs-oom",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "web",
      "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com/hello-ecs:oom",
      "essential": true,
      "memory": 512,
      "portMappings": [{ "containerPort": 8080, "protocol": "tcp" }],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/hello-ecs-oom",
          "awslogs-region": "${AWS_DEFAULT_REGION}",
          "awslogs-stream-prefix": "ecs",
          "awslogs-create-group": "true"
        }
      }
    }
  ]
}
EOF

# Build & push the :oom image (see Part 1 for the ECR login)
docker build -t hello-ecs:oom .
docker tag hello-ecs:oom $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/hello-ecs:oom
docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/hello-ecs:oom

aws ecs register-task-definition --cli-input-json file://taskdef-oom.json
```

### Step 3 — Run it and get the public IP

Use the Part 1 `run-task` flow (`assignPublicIp=ENABLED`, an SG allowing 8080), then resolve the task's public IP exactly as in Part 1, Step 7. Save it:

```bash
echo "Target: http://$PUBLIC_IP:8080"
curl http://$PUBLIC_IP:8080/health   # {"status":"ok"}
```

### Step 4 — Push it over the wall

The task has ~512 MB. The Python runtime and FastAPI already use some, so a few hundred MB of deliberate allocation will trip it:

```bash
# Allocate in 100 MB chunks until the container dies
for i in $(seq 1 6); do
  echo "Call $i:"
  curl -s http://$PUBLIC_IP:8080/eat/100 || echo "  (connection dropped — likely OOM)"
  sleep 1
done
```

Somewhere around the 4th–5th call the container crosses 512 MB, the OOM killer fires, and the curl connection drops.

### Step 5 — Confirm the fingerprint

```bash
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER \
  --desired-status STOPPED --query 'taskArns[0]' --output text)

aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN \
  --query 'tasks[0].{
    StopCode:stopCode,
    StoppedReason:stoppedReason,
    ExitCode:containers[0].exitCode,
    Reason:containers[0].reason
  }'
```

Expected:

```json
{
  "StopCode": "EssentialContainerExited",
  "StoppedReason": "Essential container in task exited",
  "ExitCode": 137,
  "Reason": "OutOfMemoryError: Container killed due to memory usage"
}
```

There it is: **exit 137 + OutOfMemoryError**. You've reproduced an OOM kill end to end.

### A boto3 verifier

```python
import boto3

ecs = boto3.client("ecs")

def find_oom_kills(cluster: str, service: str | None = None) -> list[dict]:
    """Return stopped tasks whose fingerprint matches an OOM kill (exit 137)."""
    kwargs = {"cluster": cluster, "desiredStatus": "STOPPED"}
    if service:
        kwargs["serviceName"] = service
    arns = ecs.list_tasks(**kwargs)["taskArns"]
    if not arns:
        return []

    oom = []
    for t in ecs.describe_tasks(cluster=cluster, tasks=arns)["tasks"]:
        for c in t["containers"]:
            reason = (c.get("reason") or "") + (t.get("stoppedReason") or "")
            if c.get("exitCode") == 137 or "OutOfMemory" in reason:
                oom.append({
                    "task": t["taskArn"].split("/")[-1],
                    "exit_code": c.get("exitCode"),
                    "reason": c.get("reason") or t.get("stoppedReason"),
                })
    return oom

for row in find_oom_kills("your-cluster", "your-service"):
    print(row)
```

---

## 🧪 Hands-On: Reproduce CPU Saturation

CPU exhaustion won't kill the task, so here the goal is to *watch throttling and health-check impact*, not a crash.

### Step 1 — A CPU-burning endpoint

```python
@app.get("/burn/{seconds}")
def burn(seconds: int):
    """Busy-loop to peg a core for `seconds`."""
    import time
    end = time.time() + seconds
    x = 0
    while time.time() < end:
        x += 1  # pure CPU spin
    return {"burned_seconds": seconds, "iterations": x}
```

Rebuild/push as `:cpu` and register a task def with `cpu=256` (0.25 vCPU — easy to saturate).

### Step 2 — Saturate and observe

```bash
# Fire several concurrent burns to exceed the 0.25 vCPU slice
for i in $(seq 1 4); do
  curl -s "http://$PUBLIC_IP:8080/burn/60" &
done

# In another terminal, watch service CPU climb toward its ceiling
watch -n 10 "aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS --metric-name CPUUtilization \
  --dimensions Name=ClusterName,Value=$CLUSTER Name=ServiceName,Value=$SERVICE \
  --start-time \$(date -u -d '10 minutes ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time \$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 60 --statistics Average Maximum \
  --query 'Datapoints[-3:].{Time:Timestamp, Avg:Average, Max:Maximum}' --output table"
```

### Step 3 — Watch the health check suffer

While the burn runs, probe `/health` and time it:

```bash
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "attempt $i: %{time_total}s (HTTP %{http_code})\n" \
    http://$PUBLIC_IP:8080/health
  sleep 2
done
```

You'll see response times climb as the CPU stays pinned — the mechanism by which CPU starvation *becomes* a health-check failure. Crucially, `describe-tasks` still shows `lastStatus: RUNNING` — the task never died, it just got slow. Contrast this directly with the OOM repro, where the task went `STOPPED` with exit 137.

---

## 📡 Detecting Exhaustion Before It Kills You

### Enable Container Insights (real per-task metrics)

```bash
aws ecs update-cluster-settings \
  --cluster $CLUSTER \
  --settings name=containerInsights,value=enabled
```

This unlocks the `ECS/ContainerInsights` namespace with per-task `MemoryUtilized`, `CpuUtilized`, and (with enhanced observability) throttling signals — far more actionable than the service-average `AWS/ECS` metrics.

### Alarm on memory *before* the OOM wall

The point is to fire while there's still time to react (scale, restart, page someone):

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name "$SERVICE-memory-high" \
  --namespace ECS/ContainerInsights \
  --metric-name MemoryUtilized \
  --dimensions Name=ClusterName,Value=$CLUSTER Name=ServiceName,Value=$SERVICE \
  --statistic Maximum \
  --period 60 \
  --evaluation-periods 3 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:$AWS_DEFAULT_REGION:$AWS_ACCOUNT_ID:ops-alerts
```

### Right-sizing checklist

| Symptom in the repros | Likely misconfiguration | Fix |
|---|---|---|
| Frequent exit 137 | `memory` too low for real workload | Raise container/task `memory`; add `memoryReservation` floor |
| Health checks flapping under load | `cpu` too low; app CPU-bound | Raise task `cpu`; scale out (Part 2 auto-scaling) |
| One container starves siblings | Only `memoryReservation` set, no hard cap | Add hard `memory` per container |
| OOM under traffic spikes only | Sized for average, not peak | Size for peak + memory-based auto-scaling |

---

## 🎯 What's Next

You now know exactly what exhaustion *does* — the kill vs throttle asymmetry, the 137 fingerprint, and how CPU starvation hides behind health checks.

**Part 5 — Recovery & Self-Healing** picks up the instant a task dies: how the ECS service scheduler detects the missing task, spins up a replacement, drains the dead target from the ALB, registers the new one, and how the deployment circuit breaker and auto-scaling turn a single failure into (ideally) a non-event.

---

> 💬 **Contributions welcome!** Open a PR on `learn-devops-playbook`.
>
> ⬅️ **[Part 3 — Deep Dives](ecs-part-3-deep-dives.md)** · **[Part 5 — Recovery & Self-Healing](ecs-part-5-recovery.md)** ➡️
