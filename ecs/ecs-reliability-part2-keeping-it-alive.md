# ECS Cluster Reliability — Part 2: Keeping It Alive

*Monitoring, alerting, failure modes, and the Day-2 operational rhythm that turns a cluster from "constant firefight" into "boring and bulletproof."*

> **This is Part 2 of a two-part series.**
> - **Part 1:** Design decisions, resilient cluster construction, and service configuration — everything you set up *before* launch.
> - **Part 2 (this article):** Monitoring, alerting, failure modes, and Day-2 operations — everything that keeps it alive *after* launch.

If you haven't read Part 1, the short version: reliability is mostly decided before launch through AZ spread, networking, capacity, and health checks. This article assumes that foundation exists and focuses on the harder question — **how do you catch problems before your users do?**

---

## The Goal: Boring Clusters

The best clusters are boring. They just work. You don't think about them. Everything below exists to get you there: observability that catches issues early, alerts that fire only when they should, a clear-eyed catalogue of how ECS actually fails, and the operational habits that compound into reliability.

---

## Table of Contents

1. [The Monitoring Stack You Actually Need](#1-the-monitoring-stack-you-actually-need)
2. [Proactive Health Checks](#2-proactive-health-checks)
3. [Alerting That Works](#3-alerting-that-works)
4. [Common Failure Modes and How to Prevent Them](#4-common-failure-modes-and-how-to-prevent-them)
5. [Day-2 Operations](#5-day-2-operations)
6. [The War Room Dashboard](#6-the-war-room-dashboard)
7. [Troubleshooting Playbook](#7-troubleshooting-playbook)
8. [Part 2 Checklist](#8-part-2-checklist)
9. [Quick Reference Cheatsheet](#9-quick-reference-cheatsheet)

---

## 1. The Monitoring Stack You Actually Need

Let's build a monitoring system that catches problems before users feel them. The trick is knowing *which* metrics matter — drowning in dashboards is its own kind of blindness.

### 1.1 Essential CloudWatch Metrics

**Service-level metrics — check these daily:**

| Metric | Tells you | Normal | Warning | Critical | Action |
|---|---|---|---|---|---|
| `CPUUtilization` | How hard tasks work | 30–70% | >80% sustained | >90% sustained | Scale up or optimize code |
| `MemoryUtilization` | Memory pressure | 40–70% | >80% | >90% | Scale up or raise task memory |
| `RunningTaskCount` | Tasks actually running | = Desired | < Desired >5 min | < 50% of Desired | Investigate why tasks won't start |
| `DesiredTaskCount` | Tasks that *should* run | tracks scaling | — | — | Verify auto-scaling behaves |

**Target group metrics (ALB):**

| Metric | Tells you | Normal | Warning | Critical |
|---|---|---|---|---|
| `HealthyHostCount` | Targets passing checks | = RunningTaskCount | <90% of running | <50% of running |
| `UnHealthyHostCount` | Targets failing checks | 0 | >0 for >5 min | >20% of targets |
| `TargetResponseTime` | API latency | <500ms* | >1s | >3s or rising |
| `RequestCountPerTarget` | Load distribution | roughly even | one target >2x others | — |

*\*Latency "normal" varies wildly by app — set your own baseline.*

**Cluster-level metrics (EC2 only):** watch `CPUReservation` and `MemoryReservation` (normal 60–80%, critical >95% → add instances) and `RegisteredContainerInstancesCount` (should match your ASG desired count; a mismatch >10 min means a sick ECS agent or ASG).

### 1.2 Custom Metrics You Should Build

CloudWatch's defaults miss things that predict outages. Three worth instrumenting yourself:

**Task placement failures** — the canary for capacity problems:

```python
import boto3, time

cloudwatch = boto3.client('cloudwatch')
ecs = boto3.client('ecs')

def monitor_task_placement():
    svc = ecs.describe_services(cluster='production', services=['api-service'])
    for event in svc['services'][0]['events']:
        if 'unable to place task' in event['message'].lower():
            cloudwatch.put_metric_data(
                Namespace='CustomECS',
                MetricData=[{'MetricName': 'TaskPlacementFailures',
                             'Value': 1, 'Unit': 'Count', 'Timestamp': time.time()}]
            )
            print(f"ALERT: placement failure: {event['message']}")

while True:
    monitor_task_placement()
    time.sleep(60)
```

**Task churn rate** — how often tasks restart in the last hour. A rising churn rate is often the *first* visible symptom of OOM kills or failing health checks, before users notice anything:

```python
def calculate_task_churn():
    tasks = ecs.list_tasks(cluster='production', serviceName='api-service')
    detail = ecs.describe_tasks(cluster='production', tasks=tasks['taskArns'])
    one_hour_ago = time.time() - 3600
    restarts = sum(1 for t in detail['tasks'] if t['createdAt'].timestamp() > one_hour_ago)
    cloudwatch.put_metric_data(
        Namespace='CustomECS',
        MetricData=[{'MetricName': 'TaskChurnRate', 'Value': restarts, 'Unit': 'Count'}]
    )
    if restarts > 10:
        print(f"HIGH CHURN: {restarts} tasks restarted in the past hour")
```

**Deployment success** — emit a 1/0 when a deployment reaches (or misses) its desired count, so you can alarm on failed rollouts instead of discovering them by accident.

### 1.3 Log-Based Metrics

Turn application logs into numbers you can alarm on:

```json
{
  "filterName": "ErrorCount",
  "filterPattern": "[time, request_id, level = ERROR, ...]",
  "metricTransformations": [
    {
      "metricName": "ApplicationErrors",
      "metricNamespace": "MyApp",
      "metricValue": "1",
      "defaultValue": 0
    }
  ]
}
```

Patterns worth tracking: `ERROR` lines (app error rate), `OutOfMemoryError` (memory pressure), `Connection timeout` (dependency trouble), and `429` status codes (rate limiting). Each maps to a specific failure mode in section 4.

---

## 2. Proactive Health Checks

Don't wait for things to break. The checks below catch issues that internal AWS metrics structurally *cannot* see.

### 2.1 Synthetic Monitoring

Run this from *outside* AWS — a different region or on-prem. AWS's internal view can look perfectly green while DNS, CloudFront, or a regional connectivity issue quietly breaks things for real users:

```python
import requests, time

def synthetic_health_check():
    endpoints = [
        'https://api.example.com/health',
        'https://api.example.com/v1/users',
        'https://api.example.com/v1/orders',
    ]
    for endpoint in endpoints:
        start = time.time()
        try:
            r = requests.get(endpoint, timeout=5)
            latency = (time.time() - start) * 1000
            cloudwatch.put_metric_data(
                Namespace='SyntheticMonitoring',
                MetricData=[
                    {'MetricName': 'EndpointAvailability',
                     'Dimensions': [{'Name': 'Endpoint', 'Value': endpoint}],
                     'Value': 1 if r.status_code == 200 else 0, 'Unit': 'None'},
                    {'MetricName': 'EndpointLatency',
                     'Dimensions': [{'Name': 'Endpoint', 'Value': endpoint}],
                     'Value': latency, 'Unit': 'Milliseconds'},
                ]
            )
            if r.status_code != 200:
                print(f"ALERT: {endpoint} returned {r.status_code}")
            if latency > 1000:
                print(f"ALERT: {endpoint} slow: {latency:.0f}ms")
        except requests.exceptions.Timeout:
            print(f"ALERT: {endpoint} timed out")
        except Exception as e:
            print(f"ALERT: {endpoint} error: {e}")

while True:
    synthetic_health_check()
    time.sleep(60)
```

### 2.2 Capacity Headroom Checks

Alert at 85% reservation — *before* you hit the wall, not after:

```python
def check_capacity_headroom():
    cluster = ecs.describe_clusters(
        clusters=['production'], include=['STATISTICS']
    )['clusters'][0]
    cpu = next(s['value'] for s in cluster['statistics'] if s['name'] == 'CPUReservation')
    mem = next(s['value'] for s in cluster['statistics'] if s['name'] == 'MemoryReservation')
    if cpu > 85:
        print(f"WARNING: CPU reservation at {cpu}% — scale up before you hit the limit")
    if mem > 85:
        print(f"WARNING: Memory reservation at {mem}% — scale up before you hit the limit")
```

### 2.3 Service Limit Checks

AWS limits bite quietly. The one that matters most in `awsvpc` mode is **ENIs** — recall from Part 1 that every task consumes one. Track them and alarm at 80% of your account limit, alongside cluster/service counts. Hitting an ENI ceiling looks exactly like a capacity outage but won't show up in CPU/memory metrics.

---

## 3. Alerting That Works

Not all alerts are equal. An alerting strategy that pages on everything trains people to ignore the pager — which is worse than no alerting at all. Tier by severity and route accordingly.

| Level | Examples | Response |
|---|---|---|
| **P1 — Critical** | Service down (0 healthy), >50% error rate, DB unreachable, full AZ failure | Page immediately, 24/7 |
| **P2 — High** | >30% unhealthy tasks, 10–50% errors, single-AZ failure, deploy failing | Page during business hours |
| **P3 — Medium** | 5–10% errors, latency climbing, CPU/mem >80%, elevated churn | Slack notification |
| **P4 — Low** | Cost anomalies, approaching limits, config warnings | Email / daily digest |

**Critical alarm — service down:**

```json
{
  "AlarmName": "api-service-down",
  "MetricName": "HealthyHostCount",
  "Namespace": "AWS/ApplicationELB",
  "Statistic": "Average",
  "Period": 60,
  "EvaluationPeriods": 2,
  "Threshold": 1,
  "ComparisonOperator": "LessThanThreshold",
  "AlarmActions": ["arn:aws:sns:us-east-1:123456789:critical-alerts"],
  "TreatMissingData": "breaching"
}
```

**Composite alarm — kill the noise.** This fires only when resource pressure *and* errors coincide, not on a harmless CPU blip:

```json
{
  "AlarmName": "api-service-degraded",
  "AlarmRule": "(ALARM(high-cpu-alarm) OR ALARM(high-memory-alarm)) AND ALARM(elevated-errors-alarm)",
  "AlarmActions": ["arn:aws:sns:us-east-1:123456789:critical-alerts"]
}
```

> High CPU *alone* is often fine — that's a task working hard, exactly what you paid for. High CPU *with* rising errors is a real problem. Composite alarms encode that judgment so humans don't get paged to make it at 3 AM.

---

## 4. Common Failure Modes and How to Prevent Them

Here are the failures I've seen (and caused) in production, and how to head them off. If you read only one section of this article, read this one — these four modes account for the overwhelming majority of ECS incidents.

### Failure Mode 1: Tasks Stuck in PENDING

**Symptom:** `RunningTaskCount` sits below `DesiredTaskCount` with tasks stuck pending for minutes.

The cause is almost always one of four, and the service events tell you which:

- **Insufficient cluster capacity (EC2)** — *"unable to place a task because no container instance met all of its requirements."* Check reservation metrics; add instances or enable capacity-provider scaling.
- **ENI limit exceeded (`awsvpc`)** — *"network interface limit exceeded."* Each instance type caps ENIs (t3.small: 3, m5.large: 10). Use larger instances or request a limit increase. *(This is the Part 1 ENI warning coming home to roost.)*
- **No IP addresses left** — *"no IP addresses available in subnet."* Your subnets are too small; every `awsvpc` task needs an IP. Use `/23` or larger, or add subnets.
- **Image pull failure** — `CannotPullContainerError`. Check the task execution role's ECR permissions, the image tag, NAT connectivity, and consider an ECR VPC endpoint.

**Prevention** — sweep for pending tasks and surface the reason automatically:

```python
def check_pending_tasks():
    services = ecs.describe_services(
        cluster='production',
        services=ecs.list_services(cluster='production')['serviceArns']
    )
    for service in services['services']:
        pending = service['desiredCount'] - service['runningCount']
        if pending > 0:
            print(f"WARNING: {service['serviceName']} has {pending} pending tasks")
            for event in service['events'][:5]:
                if 'unable to place' in event['message'].lower():
                    print(f"  Reason: {event['message']}")
```

### Failure Mode 2: Tasks Constantly Restarting

**Symptom:** tasks start and stop every 30–60 seconds, `HealthyHostCount` flickers, churn rate spikes.

Three usual culprits: **application crashes** (check logs for OOM, segfaults, uncaught exceptions → raise memory or fix the bug), **failing health checks** (task starts → check fails → killed → repeat → fix the endpoint or, very often, raise `healthCheckGracePeriodSeconds` to cover real startup time — straight from Part 1), and **OOM kills** (stopped reason: *"OutOfMemoryError: Container killed due to memory usage"* → raise memory or fix the leak).

**Prevention** — read the stop reasons; patterns jump out fast:

```python
def analyze_task_stops():
    tasks = ecs.list_tasks(cluster='production', serviceName='api-service',
                           desiredStatus='STOPPED', maxResults=10)
    detail = ecs.describe_tasks(cluster='production', tasks=tasks['taskArns'])
    reasons = {}
    for t in detail['tasks']:
        r = t.get('stoppedReason', 'Unknown')
        reasons[r] = reasons.get(r, 0) + 1
    for reason, count in reasons.items():
        if count >= 5:
            print(f"PATTERN: {count} tasks stopped due to: {reason}")
```

### Failure Mode 3: Deployment Failures

**Symptom:** deployment stuck, circuit breaker triggered, old tasks still running.

Usually either **new tasks fail health checks** (test the endpoint and check for breaking changes before deploying; extend the grace period for slower starts) or **resource requirements grew** beyond available capacity. The Part 1 circuit breaker is your safety net — but prevention beats rollback:

```python
def validate_deployment(new_task_def):
    cluster = ecs.describe_clusters(clusters=['production'], include=['STATISTICS'])
    stats = {s['name']: s['value'] for s in cluster['clusters'][0]['statistics']}
    cpu_free = 100 - stats['CPUReservation']
    mem_free = 100 - stats['MemoryReservation']
    if cpu_free < 20 or mem_free < 20:
        print("ERROR: insufficient capacity for a safe deployment")
        return False
    print("✓ pre-deployment checks passed")
    return True
```

### Failure Mode 4: Silent Degradation

**Symptom:** every metric is green, yet users report slowness or errors. This is the scariest mode precisely because standard monitoring misses it.

Common causes: a **slow external dependency** (your service is healthy, but it's blocking on a 3-second upstream call → monitor dependency latency, add timeouts and circuit breakers), an **exhausted DB connection pool** (tasks healthy, database fine, but the pool is maxed → monitor pool metrics, size it up), or **cascading failures** (one slow service makes others time out → bulkheads and circuit breakers to isolate).

**Prevention** — watch the *gaps* between signals, and watch tail latency, not averages:

```python
def check_hidden_issues():
    # External view worse than internal? Suspect DNS / CDN / geo-specific failure.
    synthetic = get_metric('SyntheticMonitoring', 'SuccessRate')
    internal = 100 - get_metric('AWS/ApplicationELB', '5XXError')
    if synthetic < internal - 5:
        print("ALERT: external monitoring shows worse than internal")

    # p99 ≫ p50 means some users are getting hammered even if the average looks fine.
    rt = get_detailed_latency_metrics()
    if rt['p99'] > rt['p50'] * 10:
        print(f"ALERT: latency variance — p50 {rt['p50']}ms, p99 {rt['p99']}ms")
```

> **The averages lie.** A healthy-looking 200ms average can hide a p99 of 4 seconds — meaning 1 in 100 requests is miserable. Always alarm on tail latency.

---

## 5. Day-2 Operations

Building the cluster is one thing; keeping it healthy for months is another. Reliability is a *habit*, not a launch milestone.

**Daily — a 5-minute dashboard review:** every service at desired count? CPU/memory in the 30–70% band? error rates under 1%? any overnight deployment failures or cost anomalies? Automate a morning report that summarizes each service's desired/running/pending counts and recent events and drops it in Slack.

**Weekly — capacity and cost review.** Pull seven days of utilization: average CPU under 30% suggests scaling down; peaks over 85% mean add capacity. On cost, flag any day more than 1.5× the weekly average — that spike is usually a runaway auto-scaler or a forgotten test environment.

```python
def weekly_capacity_review():
    cw = boto3.client('cloudwatch')
    end, start = datetime.now(), datetime.now() - timedelta(days=7)
    stats = cw.get_metric_statistics(
        Namespace='AWS/ECS', MetricName='CPUUtilization',
        Dimensions=[{'Name': 'ServiceName', 'Value': 'api-service'},
                    {'Name': 'ClusterName', 'Value': 'production'}],
        StartTime=start, EndTime=end, Period=3600,
        Statistics=['Average', 'Maximum'])
    pts = stats['Datapoints']
    avg = sum(p['Average'] for p in pts) / len(pts)
    peak = max(p['Maximum'] for p in pts)
    print(f"Weekly CPU — avg {avg:.1f}%, peak {peak:.1f}%")
    if avg < 30:   print("→ consider scaling down")
    elif peak > 85: print("→ add capacity")
    else:          print("✓ capacity looks good")
```

**Monthly:** review Reserved Instances, audit security-group rules, refresh base images in task definitions, archive old logs, **test your disaster-recovery procedure**, and update runbooks from the month's incidents. A DR plan you've never run is a hope, not a plan.

---

## 6. The War Room Dashboard

When things go wrong you need answers fast — everything critical on one screen, no clicking around. Build a CloudWatch dashboard with these widgets:

```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "title": "Service Health Overview",
        "metrics": [
          ["AWS/ECS", "RunningTaskCount", {"stat": "Average", "label": "Running"}],
          [".", "DesiredTaskCount", {"stat": "Average", "label": "Desired"}],
          ["AWS/ApplicationELB", "HealthyHostCount", {"stat": "Average"}],
          [".", "UnHealthyHostCount", {"stat": "Average"}]
        ],
        "period": 60, "region": "us-east-1", "yAxis": {"left": {"min": 0}}
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "API Performance",
        "metrics": [
          ["AWS/ApplicationELB", "TargetResponseTime", {"stat": "Average"}],
          ["...", {"stat": "p99"}],
          [".", "RequestCount", {"stat": "Sum", "yAxis": "right"}]
        ],
        "period": 60
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Error Rates",
        "metrics": [
          ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", {"stat": "Sum"}],
          [".", "HTTPCode_Target_4XX_Count", {"stat": "Sum"}],
          ["CustomECS", "ApplicationErrors", {"stat": "Sum"}]
        ],
        "period": 60
      }
    },
    {
      "type": "log",
      "properties": {
        "title": "Recent Errors",
        "query": "SOURCE '/ecs/api-service' | fields @timestamp, @message | filter @message like /ERROR/ | sort @timestamp desc | limit 20",
        "region": "us-east-1"
      }
    }
  ]
}
```

The principle: **running vs desired** (placement issues), **healthy vs unhealthy** (health-check failures), **latency and request count** (load), **error rates** (app issues), and **live error logs** (investigation) — all visible at a glance.

---

## 7. Troubleshooting Playbook

### Tasks Won't Start

```bash
# 1. Read the service events — they almost always name the cause
aws ecs describe-services --cluster production --services api-service \
  --query 'services[0].events[0:5]'
#   "unable to place task"     → capacity
#   "CannotPullContainer"      → image / ECR / network
#   "ResourceInitialization"   → networking / IAM

# 2. Check cluster capacity (EC2)
aws ecs describe-clusters --cluster production --include STATISTICS
#   CPU/MemoryReservation > 95% → add capacity

# 3. Verify the task definition
aws ecs describe-task-definition --task-definition api-service:42

# 4. Tail the logs
aws logs tail /ecs/api-service --follow
```

### High CPU / Memory

```bash
# Find the running tasks, then inspect one
aws ecs list-tasks --cluster production --service-name api-service --desired-status RUNNING
aws ecs describe-tasks --cluster production --tasks <task-arn>

# Exec in for deep debugging (ECS Exec must be enabled on the task def)
aws ecs execute-command --cluster production --task <task-id> \
  --container app --interactive --command "/bin/bash"
# inside: top -b -n 1   |   df -h   |   free -m
```

### Deployment Stuck

```bash
# Inspect the deployment, then the health of new-revision tasks
aws ecs describe-services --cluster production --services api-service \
  --query 'services[0].deployments'

# Roll back to the last known-good task definition if needed
aws ecs update-service --cluster production --service api-service \
  --task-definition api-service:41
```

---

## 8. Part 2 Checklist

**Monitoring**
- CloudWatch alarms on critical service + ALB metrics
- Synthetic monitoring from *outside* AWS
- Custom metric for task placement failures
- Task churn and deployment-success metrics emitted
- Log-based metrics for application errors

**Alerting**
- Severity tiers (P1–P4) with distinct routes
- Composite alarms to suppress single-signal noise
- `TreatMissingData: breaching` on "service down"

**Operations**
- Daily 5-minute health review (automated report)
- Weekly capacity + cost review
- Runbooks for the four failure modes
- On-call rotation and escalation path
- DR procedure tested, not just written
- Post-mortem process that updates monitoring

---

## 9. Quick Reference Cheatsheet

```
┌──────────────────────────────────────────────────────────────────┐
│           ECS RELIABILITY — PART 2: KEEP-ALIVE CHEATSHEET         │
└──────────────────────────────────────────────────────────────────┘

DAILY-WATCH METRICS
  CPU/MemUtilization     30–70% ok | >90% critical
  Running vs Desired     gap = placement problem
  Healthy vs Unhealthy   unhealthy >0 for 5 min = investigate
  TargetResponseTime     alarm on p99, NOT average

BUILD THESE CUSTOM METRICS
  TaskPlacementFailures  ← capacity canary
  TaskChurnRate          ← early warning for OOM / health fails
  DeploymentSuccess      ← catch failed rollouts

SYNTHETIC MONITORING
  Run from OUTSIDE AWS → catches DNS/CDN/geo failures
  internal green + external red = hidden outage

ALERT TIERS
  P1 page 24/7 | P2 page biz-hrs | P3 Slack | P4 email
  Composite alarms: (CPU OR Mem) AND errors → less noise

THE 4 FAILURE MODES
  1. PENDING tasks   → capacity | ENI limit | no IPs | image pull
  2. Restart loops   → crash | failed health check | OOM
  3. Deploy stuck    → new tasks fail checks | not enough capacity
  4. Silent degrade  → slow dep | pool exhausted | cascade
                       (all green but users hurt → watch the gaps)

TRIAGE ORDER (tasks won't start)
  events → cluster capacity → task def → logs

DAY-2 RHYTHM
  Daily   5-min dashboard check
  Weekly  capacity + cost review (flag >1.5× avg cost)
  Monthly RI review, image refresh, TEST DR, update runbooks

GOLDEN RULE
   The best clusters are boring. Catch it before users do. ◄
```

---

## Closing Thought

Building a reliable ECS cluster isn't the initial setup from Part 1 — it's the observability, automation, and habits in Part 2 that catch problems early and compound over time.

Every outage is a lesson. When something breaks (and it will), update the runbook, add monitoring for that exact failure mode, and make the system a little more resilient than it was yesterday. Do that consistently and your cluster drifts toward the goal that matters most: **boring.**
