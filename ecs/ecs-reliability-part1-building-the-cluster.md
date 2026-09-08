# ECS Cluster Reliability — Part 1: Building a Cluster That Just Works

*The architecture and configuration decisions that determine whether your cluster is resilient by design — or fragile by accident.*

> **This is Part 1 of a two-part series.**
> - **Part 1 (this article):** Design decisions, resilient cluster construction, and service configuration — everything you set up *before* the first request hits.
> - **Part 2:** Monitoring, alerting, failure modes, and Day-2 operations — everything that keeps it alive *after* launch.

---

## Why This Series Exists

You know that sinking feeling when you get paged at 2 AM because your ECS tasks are stuck in a restart loop? Or when you discover your cluster has been quietly failing to launch tasks for the past hour because you hit an AWS service quota?

After years of running ECS in production — and learning plenty of lessons the hard way — I've boiled it down to the practices that actually matter. None of this is theoretical box-ticking. It's the stuff that keeps services running and lets you sleep.

Here's the core idea that frames everything: **reliability is mostly decided before launch.** The choices you make about launch type, networking, and availability zones are load-bearing. Get them right and the cluster is forgiving. Get them wrong and you spend Part 2 firefighting problems you designed in.

Let's build a cluster that just works.

---

## Table of Contents

1. [Pre-Flight: Design Decisions That Matter](#1-pre-flight-design-decisions-that-matter)
2. [Building a Resilient Cluster](#2-building-a-resilient-cluster)
3. [Service Configuration Best Practices](#3-service-configuration-best-practices)
4. [Part 1 Checklist](#4-part-1-checklist)
5. [Quick Reference Cheatsheet](#5-quick-reference-cheatsheet)

---

## 1. Pre-Flight: Design Decisions That Matter

Before you create your first cluster, a handful of architectural decisions will quietly determine how well your system survives failures. Think of these as the foundation poured before the house goes up — expensive to change later, cheap to get right now.

### 1.1 Choosing Launch Type: EC2 vs Fargate

This is the first fork in the road. Fargate means AWS runs the servers; you just hand over containers. EC2 means you run the servers yourself and get more control in exchange for more responsibility.

| Choose **Fargate** when… | Choose **EC2** when… |
|---|---|
| You want to focus on apps, not infrastructure | You have steady-state, predictable workloads |
| Your workload is unpredictable or spiky | You need GPU or specific instance types |
| You value operational simplicity over raw cost | You're optimizing cost with Reserved Instances |
| You need fast, predictable scaling | You need kernel tuning or custom AMIs |
| Your team is small or new to AWS | You have the capacity to manage infrastructure |

**My recommendation:** Start with Fargate unless you have a *specific* reason not to. You can always migrate to EC2 later, once you actually understand your workload patterns. Premature infrastructure ownership is a classic way to drown a small team.

### 1.2 Network Mode Selection

This matters more than most people realize, because it shapes your security model and your IP-address math for the life of the cluster.

**`awsvpc` mode** (required for Fargate, recommended for EC2):

Every task gets its own elastic network interface (ENI) and private IP. That gives you per-task security groups — the finest-grained security you can get — and eliminates port conflicts entirely. The cost is that you consume more IP addresses and run into per-instance ENI limits on EC2. The latency overhead is negligible.

**Bridge mode** (EC2 only):

One ENI per instance, which saves IPs and gives faster container startup since there's no ENI to attach. But you inherit port-mapping complexity, possible port conflicts, and security groups only at the instance level. It's also incompatible with many AWS integrations.

**Best practice:** Use `awsvpc`. The operational simplicity and security granularity are worth the ENI overhead for almost everyone. Just keep the ENI limits in the back of your mind — they'll come up again in Part 2 as a failure mode.

### 1.3 Subnet and Availability Zone Strategy

**The golden rule: always use at least 3 Availability Zones.** This isn't superstition — it's arithmetic.

```
With 2 AZs:
- One AZ fails → 50% capacity loss
- You must run 2x capacity to survive a single failure
- Expensive and inefficient

With 3 AZs:
- One AZ fails → 33% capacity loss
- You run ~1.5x capacity to survive a single failure
- Much more efficient, survives any single-AZ outage gracefully
```

A spread across three zones turns an AZ outage from an incident into a non-event.

```hcl
# Terraform: spread your service across three private subnets
resource "aws_ecs_service" "api" {
  # ... other config ...

  network_configuration {
    subnets = [
      aws_subnet.private_us_east_1a.id,
      aws_subnet.private_us_east_1b.id,
      aws_subnet.private_us_east_1c.id,
    ]
    security_groups = [aws_security_group.api_tasks.id]
  }
}
```

**Private vs public subnets:** Put tasks in **private subnets** behind a NAT Gateway. Public subnets (tasks with public IPs) are rarely needed and widen your attack surface for no good reason.

> 💡 **Sizing foreshadow:** subnet size determines how many tasks you can run. A `/24` gives you 256 IPs; a `/23` gives 512. In `awsvpc` mode every task eats an IP — undersized subnets are a top cause of "tasks stuck in PENDING," which we'll dissect in Part 2.

---

## 2. Building a Resilient Cluster

Design decided, now we build. Resilience here comes from three things working together: enough capacity, automatic scaling at *both* levels, and smart placement.

### 2.1 Cluster Capacity Planning (EC2 Launch Type)

If you're on EC2, capacity planning is non-negotiable. Here's the formula:

```
Required Instances = (Total Task Resources × Safety Buffer) / Instance Resources

Example:
- 20 tasks × 1024 CPU × 2048 MB each
- Safety buffer: 30% (1.3x)
- Instance type: c5.xlarge (4096 CPU, 8192 MB)

CPU needed:    20 × 1024 × 1.3 = 26,624 CPU units
Memory needed: 20 × 2048 × 1.3 = 53,248 MB

Instances by CPU:    26,624 / 4096 = 6.5
Instances by memory: 53,248 / 8192 = 6.5
→ Round up: 7 instances minimum
```

**Best practice:** Always round up, then add 1–2 extra instances. Spare capacity is cheap insurance; tasks stuck in PENDING because there's nowhere to place them is an outage.

### 2.2 Auto Scaling Setup (EC2)

Manual scaling does not survive contact with real traffic. On EC2 you need *two* levels of auto-scaling, and they're easy to confuse:

**Level 1 — ECS Service Auto Scaling** scales the number of *tasks*:

```json
{
  "targetTrackingScalingPolicies": [
    {
      "policyName": "cpu-scaling",
      "targetValue": 70.0,
      "predefinedMetricSpecification": {
        "predefinedMetricType": "ECSServiceAverageCPUUtilization"
      },
      "scaleInCooldown": 300,
      "scaleOutCooldown": 60
    }
  ]
}
```

**Level 2 — Capacity Provider Auto Scaling** scales the number of *EC2 instances*:

```json
{
  "capacityProviders": [
    {
      "name": "my-capacity-provider",
      "autoScalingGroupProvider": {
        "autoScalingGroupArn": "arn:aws:autoscaling:...",
        "managedScaling": {
          "status": "ENABLED",
          "targetCapacity": 80,
          "minimumScalingStepSize": 1,
          "maximumScalingStepSize": 10
        }
      }
    }
  ]
}
```

Think of it as a stack: Level 1 adds tasks, Level 2 makes sure there are instances to put them on. Miss either and scaling silently stalls.

**Critical:** tune your cooldowns. Too short and you get thrashing (scale up, scale down, repeat). Too long and you respond to load far too slowly. Notice the asymmetry above — scale *out* fast (60s) to absorb load, scale *in* slow (300s) to avoid yanking capacity during a brief dip.

### 2.3 Task Placement Strategies (EC2)

Tell ECS how to distribute tasks so a single failure can't take out a disproportionate chunk:

```json
{
  "placementStrategy": [
    { "type": "spread", "field": "attribute:ecs.availability-zone" },
    { "type": "spread", "field": "instanceId" }
  ]
}
```

This double-spread does two things in order: first spread across AZs (survive an AZ failure), then spread across instances (survive an instance failure).

The alternatives have their place: `binpack` packs tasks tightly to save money but concentrates risk, and `random` is for when placement genuinely doesn't matter. **For production services, use the double-spread above.** The small efficiency loss buys real resilience.

### 2.4 Fargate Ephemeral Storage

If you're on Fargate and your app writes logs or temp files, size your ephemeral storage deliberately:

```json
{
  "family": "my-task",
  "ephemeralStorage": { "sizeInGiB": 30 }
}
```

The default is 20 GB. Tasks get killed when the disk fills, so monitor usage — a slow-leaking temp directory is an annoying way to discover this default.

---

## 3. Service Configuration Best Practices

The cluster exists. Now we configure the services that run on it. This is where small details — a memory reservation here, a grace period there — separate "rock solid" from "mysteriously flaky."

### 3.1 Task Definition Essentials

```json
{
  "family": "api-server",
  "cpu": "1024",
  "memory": "2048",
  "containerDefinitions": [
    {
      "name": "nginx",
      "image": "nginx:1.21",
      "cpu": 256,
      "memory": 512,
      "memoryReservation": 256,
      "essential": true,
      "portMappings": [{ "containerPort": 80 }]
    },
    {
      "name": "app",
      "image": "my-app:v1.2.3",
      "cpu": 768,
      "memory": 1536,
      "memoryReservation": 1024,
      "essential": true,
      "portMappings": [{ "containerPort": 8080 }]
    }
  ]
}
```

The four fields people get wrong:

- **`cpu`** — task-level CPU is the sum of all container CPU values.
- **`memory`** — a *hard* limit. Exceed it and the task gets OOM-killed.
- **`memoryReservation`** — a *soft* limit, the guaranteed minimum.
- **`essential`** — if `true` and this container dies, the entire task stops.

**Best practice:** set `memoryReservation` to roughly 70–80% of `memory`. That gap is the headroom your app uses for legitimate spikes without getting killed.

### 3.2 Logging Configuration (Don't Skip This)

When something breaks, logs are your lifeline. Configure them *before* you need them.

```json
{
  "logConfiguration": {
    "logDriver": "awslogs",
    "options": {
      "awslogs-group": "/ecs/my-api",
      "awslogs-region": "us-east-1",
      "awslogs-stream-prefix": "api",
      "awslogs-create-group": "true"
    }
  }
}
```

Then add a retention policy, or logs accumulate forever and the bill creeps:

```python
import boto3

logs = boto3.client('logs')
logs.put_retention_policy(
    logGroupName='/ecs/my-api',
    retentionInDays=30  # 7, 14, 60, 90… pick per compliance needs
)
```

I've watched a forgotten log group quietly grow into a four-figure monthly line item. Set retention on day one.

### 3.3 Health Checks — The Most Important Config

If you take one thing from this article, take this: **a good health check is the single most effective reliability control you have.** It's how ECS knows whether to send traffic to a task or kill it.

**ALB health check:**

```json
{
  "healthCheckPath": "/health",
  "healthCheckIntervalSeconds": 30,
  "healthCheckTimeoutSeconds": 5,
  "healthyThresholdCount": 2,
  "unhealthyThresholdCount": 3,
  "matcher": "200-299"
}
```

**ECS grace period** — gives slow-starting apps time to boot before health checks count against them:

```json
{ "healthCheckGracePeriodSeconds": 60 }
```

**A health check should verify dependencies, not just "the process is alive."** A real `/health` endpoint:

```python
from flask import Flask, jsonify
import psycopg2, shutil, psutil

app = Flask(__name__)

@app.route('/health')
def health():
    checks = {}
    overall = "healthy"

    # Database reachability
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.close()
        checks['database'] = 'healthy'
    except Exception:
        checks['database'] = 'unhealthy'
        overall = "unhealthy"

    # Disk headroom (need >10% free)
    disk = shutil.disk_usage('/')
    checks['disk'] = 'healthy' if disk.free / disk.total >= 0.1 else 'unhealthy'
    if checks['disk'] == 'unhealthy':
        overall = "unhealthy"

    # Memory pressure
    checks['memory'] = 'healthy' if psutil.virtual_memory().percent <= 90 else 'unhealthy'
    if checks['memory'] == 'unhealthy':
        overall = "unhealthy"

    return jsonify({'status': overall, 'checks': checks}), (200 if overall == "healthy" else 503)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

**Tuning the sensitivity** is a balance between catching real failures fast and not over-reacting to brief blips:

```
Detection Time = unhealthyThresholdCount × intervalSeconds

Too sensitive:  interval 5s,  threshold 1  → 5s detection  → false positives from momentary slowdowns
Too lenient:    interval 60s, threshold 5  → 300s          → unhealthy tasks serve traffic for 5 minutes
Just right:     interval 30s, threshold 2–3 → 60–90s       → quick detection, few false alarms
```

> 🔗 **This connects forward:** in Part 2, "tasks constantly restarting" and "deployment stuck" both trace back to health-check tuning. A grace period that's shorter than your real startup time will fail healthy tasks forever. Get this right here and you prevent a whole class of incidents later.

### 3.4 Deployment Configuration

Rolling deploys with a safety net:

```json
{
  "deploymentConfiguration": {
    "maximumPercent": 200,
    "minimumHealthyPercent": 100,
    "deploymentCircuitBreaker": { "enable": true, "rollback": true }
  }
}
```

What the numbers mean, for a service with 10 desired tasks:

- **`maximumPercent: 200`** — can run up to 20 tasks during a deploy, so ECS spins up 10 new before stopping any old ones → zero downtime.
- **`minimumHealthyPercent: 100`** — never drop below 10 healthy tasks → safest option.
- **`deploymentCircuitBreaker`** — auto-rolls-back a failing deployment. This is what saves you from a bad push at 3 AM.

Two common alternatives:

```
minHealthy 50 / max 100  → cost-optimized, briefly runs at half capacity (non-critical services)
minHealthy 100 / max 150 → balanced, minimal extra capacity (good default for most services)
```

### 3.5 Service Discovery

When services need to find each other, skip the hardcoded IPs:

```json
{
  "serviceRegistries": [
    {
      "registryArn": "arn:aws:servicediscovery:us-east-1:...:service/srv-abc123",
      "containerName": "app",
      "containerPort": 8080
    }
  ]
}
```

Now other services reach yours by DNS — `api-server.production.local` — with automatic updates as tasks scale, and it works across VPCs with proper DNS setup. No IPs to chase when things move.

---

## 4. Part 1 Checklist

Before you consider the cluster "built," verify:

**Architecture**
- ☐ Using 3+ Availability Zones
- ☐ Subnets sized for enough IPs (`awsvpc` eats one per task)
- ☐ `awsvpc` networking mode configured
- ☐ Task placement strategy spreads across AZs, then instances
- ☐ Load balancer with health checks configured

**Capacity**
- ☐ 30% capacity buffer (EC2) or sufficient service quotas (Fargate)
- ☐ Auto-scaling configured at *both* levels (service + cluster, on EC2)
- ☐ Capacity provider auto-scaling enabled (EC2)

**Task Configuration**
- ☐ Resource requests tested under real load
- ☐ Health check endpoint implemented *and* dependency-aware
- ☐ Grace period covers true startup time
- ☐ Logging configured with a retention policy
- ☐ Secrets in Secrets Manager / SSM, not env vars

**Deployment**
- ☐ Circuit breaker enabled with rollback
- ☐ Config allows zero-downtime rollout
- ☐ Rollback procedure documented

---

## 5. Quick Reference Cheatsheet

```
┌──────────────────────────────────────────────────────────────────┐
│              ECS RELIABILITY — PART 1: BUILD CHEATSHEET            │
└──────────────────────────────────────────────────────────────────┘

LAUNCH TYPE
  Fargate → default; spiky load, small team, simplicity
  EC2     → steady load, GPUs, RI cost savings, customization

NETWORK MODE
  awsvpc  → per-task ENI + SG (recommended; watch ENI limits)
  bridge  → one ENI/instance, port-mapping pain (EC2 only)

AVAILABILITY ZONES
  ALWAYS ≥ 3 AZs.  3 AZs = 33% loss on failure vs 50% with 2.

CAPACITY (EC2)
  Instances = (tasks × resources × 1.3) / instance_resources → round up, +1–2

AUTO SCALING (EC2 — need BOTH)
  L1 Service Auto Scaling      → scales TASKS   (target ~70% CPU)
  L2 Capacity Provider Scaling → scales EC2     (targetCapacity ~80)
  Scale out fast (60s), scale in slow (300s)

PLACEMENT (EC2)
  spread by AZ, then spread by instanceId   ◄ production default
  binpack = cheap but fragile | random = don't-care

TASK DEF MEMORY
  memory            = HARD limit (OOM-kill above)
  memoryReservation = SOFT limit (~70–80% of memory)
  essential: true   = container dies → whole task stops

HEALTH CHECK
  Detection = unhealthyThreshold × interval
  Sweet spot: interval 30s, threshold 2–3 → 60–90s
  Check DEPENDENCIES (db/disk/mem), not just "process alive"
  grace period ≥ real startup time   ◄ prevents restart loops

DEPLOYMENT
  max 200 / minHealthy 100 → zero-downtime default
  circuit breaker + rollback = ENABLE IT (saves 3 AM pushes)

GOLDEN RULE
  ► Reliability is decided BEFORE launch. Foundation first. ◄
```

---

*Next up — **Part 2: Keeping It Alive.** The monitoring stack you actually need, alerting that doesn't cause burnout, the four failure modes that cause most ECS incidents, and the Day-2 operational rhythm that keeps a cluster boring (in the best way).*
