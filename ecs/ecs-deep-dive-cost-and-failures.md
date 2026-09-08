# Deep Dive: ECS Cost Optimization and Failure Domains

*Advanced analysis of when to use Fargate vs EC2, and how ECS handles failures*

---

## Part 1: Cost Optimization - The Math Behind the Decision

Let's get into the numbers. The "EC2 vs Fargate" decision isn't just about convenience—it's about understanding your workload patterns and doing the math.

### Understanding the Pricing Models

**Fargate Pricing** (us-east-1, as of writing):
- Per vCPU-hour: ~$0.04048
- Per GB-hour: ~$0.004445
- Billed per second with 1-minute minimum
- No additional charges for data transfer within the same AZ

**EC2 Pricing** (using t3.medium as baseline):
- On-Demand: ~$0.0416/hour
- 1-Year Reserved Instance (No Upfront): ~$0.0250/hour
- 3-Year Reserved Instance (All Upfront): ~$0.0152/hour
- Savings Plans: Similar to RIs but more flexible

**t3.medium specs**: 2 vCPU, 4 GB RAM

### The Break-Even Analysis

Let's calculate the cost for running equivalent workloads.

#### Scenario 1: Single Task Running 24/7

**Task Requirements**: 1 vCPU (1024 CPU units), 2 GB RAM

**Fargate Cost (monthly)**:
```
vCPU cost: 1 vCPU × $0.04048/hour × 730 hours = $29.55
Memory cost: 2 GB × $0.004445/GB-hour × 730 hours = $6.49
Total Fargate: $36.04/month
```

**EC2 Cost (t3.medium, can fit 2 of these tasks)**:
```
On-Demand: $0.0416/hour × 730 hours = $30.37/month
With 1-Year RI: $0.0250/hour × 730 hours = $18.25/month
With 3-Year RI: $0.0152/hour × 730 hours = $11.10/month
```

**Per-task cost on EC2** (since t3.medium can run 2 tasks):
```
On-Demand: $30.37 / 2 = $15.19/task/month
1-Year RI: $18.25 / 2 = $9.13/task/month
3-Year RI: $11.10 / 2 = $5.55/task/month
```

**First Insight**: For 24/7 workloads, EC2 is significantly cheaper, especially with Reserved Instances.

But this assumes **100% utilization** of the EC2 instance. Let's look at what happens with real-world utilization patterns.

### The Utilization Percentage Breakpoint

Here's the critical question: At what point does EC2's cost advantage disappear?

**The Formula**:
```
Fargate Cost = EC2 Cost / Utilization %
```

Let me work through this with a concrete example.

#### Scenario 2: Variable Workload

You have a batch processing job that runs:
- 8 hours per day on weekdays (5 days)
- 0 hours on weekends
- Total: 40 hours/week = 173 hours/month

**Fargate Cost**:
```
1 vCPU × $0.04048 × 173 hours = $7.00
2 GB × $0.004445 × 173 hours = $1.54
Total: $8.54/month
```

**EC2 On-Demand Cost**:
```
$0.0416 × 730 hours = $30.37/month (running 24/7 even though we only use it 173 hours)
```

**Utilization**: 173 / 730 = 23.7%

**Cost Comparison**:
- Fargate: $8.54
- EC2: $30.37
- **Fargate is 71% cheaper!**

#### The Break-Even Point

Let's calculate exactly when EC2 becomes cheaper than Fargate.

For a 1 vCPU, 2 GB task on t3.medium (which can fit 2 such tasks):

**Fargate hourly cost**: $0.04048 + (2 × $0.004445) = $0.04937/hour per task

**EC2 hourly cost** (on-demand, per task): $0.0416 / 2 = $0.0208/hour per task

**Break-even occurs when**:
```
Fargate hourly cost × Hours Used = EC2 monthly cost

$0.04937 × Hours Used = $30.37 (monthly EC2 cost)

Hours Used = $30.37 / $0.04937 = 615 hours/month
```

**As a percentage**: 615 / 730 = **84.2% utilization**

**Critical Finding**: You need to run your tasks at least **84% of the time** for on-demand EC2 to be cheaper than Fargate.

### How Reserved Instances Change the Math

Now let's see how RIs affect this calculation.

**With 1-Year RI** ($18.25/month for t3.medium):
```
Break-even: $18.25 / $0.04937 = 370 hours/month
As percentage: 370 / 730 = 50.7% utilization
```

**With 3-Year RI** ($11.10/month):
```
Break-even: $11.10 / $0.04937 = 225 hours/month
As percentage: 225 / 730 = 30.8% utilization
```

**Revised Finding**: With Reserved Instances, EC2 becomes cheaper at much lower utilization:
- 1-Year RI: 51% utilization
- 3-Year RI: 31% utilization

### Multi-Task Density Impact

The analysis above assumes perfect bin-packing. In reality, you rarely achieve 100% instance utilization.

#### Real-World Scenario: Mixed Workload

You have:
- 3 small tasks: 256 CPU, 512 MB each
- 2 medium tasks: 512 CPU, 1024 MB each
- 1 large task: 1024 CPU, 2048 MB

**Total requirements**:
```
CPU: (3 × 256) + (2 × 512) + (1 × 1024) = 2816 CPU units
Memory: (3 × 512) + (2 × 1024) + (1 × 2048) = 6144 MB
```

**Option 1: Fargate**
```
Small tasks: 3 × (0.25 vCPU × $0.04048 + 0.5 GB × $0.004445) × 730 = $26.94
Medium tasks: 2 × (0.5 vCPU × $0.04048 + 1 GB × $0.004445) × 730 = $35.92
Large task: 1 × (1 vCPU × $0.04048 + 2 GB × $0.004445) × 730 = $36.04
Total: $98.90/month
```

**Option 2: EC2 with t3.large** (2 vCPU, 8 GB RAM):
```
Capacity check:
- CPU: 2048 units available vs 2816 needed → Need 2 instances
- Memory: 8192 MB available vs 6144 needed → Could fit on 1 instance

Reality: Need 2× t3.large due to CPU constraint

On-Demand cost: 2 × $0.0832 × 730 = $121.47/month
1-Year RI cost: 2 × $0.050 × 730 = $73.00/month
3-Year RI cost: 2 × $0.030 × 730 = $43.80/month
```

**Cost comparison**:
- Fargate: $98.90
- EC2 On-Demand: $121.47 (23% more expensive)
- EC2 1-Year RI: $73.00 (26% cheaper than Fargate)
- EC2 3-Year RI: $43.80 (56% cheaper than Fargate)

**The Waste Factor**: Notice we're paying for 2× t3.large (4 vCPU, 16 GB RAM) but only using 2.75 vCPU and 6 GB. That's:
- CPU waste: (4 - 2.75) / 4 = 31%
- Memory waste: (16 - 6) / 16 = 62.5%

With Fargate, you pay exactly for what you use. With EC2, you pay for instance capacity whether you use it or not.

### Savings Plans: The Middle Ground

AWS Compute Savings Plans offer flexibility:
- Commitment to spend $X/hour for 1 or 3 years
- Applies to EC2, Fargate, and Lambda
- ~66% discount compared to on-demand

**Example**: Commit to $50/hour for 1 year
- Can mix EC2 and Fargate
- Covers base workload with EC2 RIs
- Use Fargate for spiky/unpredictable workloads
- Overflow goes to on-demand pricing

This hybrid approach often yields the best economics.

### The Decision Matrix

Here's when to use each:

| Workload Pattern | Best Choice | Reasoning |
|-----------------|-------------|-----------|
| 24/7 steady-state, predictable | EC2 with RIs | Up to 70% cheaper, waste is minimal |
| Runs <50% of the time | Fargate | Pay only for actual usage |
| Highly variable (spiky) | Fargate or EC2 Spot | Avoid paying for idle capacity |
| Dev/Test environments | Fargate | Stop when not in use, zero waste |
| Batch jobs (scheduled) | Fargate or EC2 Spot | Short-lived, precise billing |
| Mission-critical, stable | EC2 with 3-Year RIs | Lowest cost, predictable |
| Mix of stable + variable | Hybrid (EC2 RI + Fargate) | Optimize each workload type |

### Advanced Cost Optimization: Spot Instances

We haven't even touched on Spot yet. Let's add it to the analysis.

**Fargate Spot Pricing**: ~70% discount on Fargate
```
1 vCPU + 2 GB task:
Regular Fargate: $36.04/month
Fargate Spot: ~$10.81/month (70% discount)
```

**EC2 Spot Pricing**: 50-90% discount on on-demand
```
t3.medium on-demand: $30.37/month
t3.medium spot: ~$9.11/month (70% discount typical)
```

**The catch**: Spot can be interrupted with 2-minute warning.

**When to use Spot**:
- Fault-tolerant workloads
- Batch processing
- CI/CD build agents
- Stateless services with graceful shutdown

### Real-World Cost Optimization Strategy

Here's a production-grade approach I've implemented:

**Tier 1 - Base Capacity** (predictable, always-on):
- EC2 Reserved Instances (3-year)
- Covers minimum workload
- ~70% cost savings

**Tier 2 - Variable Capacity** (daily peaks, predictable patterns):
- EC2 On-Demand or 1-Year RIs
- Handles known scaling patterns
- ~30-50% of total capacity

**Tier 3 - Burst Capacity** (unpredictable spikes):
- Fargate On-Demand
- Instant scaling, no pre-provisioning
- Pay-per-use for peaks

**Tier 4 - Fault-Tolerant Workloads**:
- Fargate Spot or EC2 Spot
- 70-90% savings
- Automated retry logic

**Example Monthly Bill**:
```
Tier 1 (EC2 3-Year RI): $2,000 (50% of compute time)
Tier 2 (EC2 1-Year RI): $1,500 (30% of compute time)
Tier 3 (Fargate On-Demand): $800 (15% of compute time)
Tier 4 (Spot): $150 (5% of compute time)
Total: $4,450/month

All-Fargate equivalent: ~$8,500/month
Savings: 48%
```

### The Hidden Costs

Don't forget to factor in:

**EC2 Additional Costs**:
- Data transfer out (first GB free, then $0.09/GB)
- EBS volumes ($0.10/GB-month for gp3)
- Elastic IPs if not attached ($0.005/hour)
- NAT Gateway ($0.045/hour + $0.045/GB processed)
- Load balancer costs

**Fargate Additional Costs**:
- Ephemeral storage >20 GB ($0.000111/GB-hour)
- Same data transfer, NAT, and LB costs as EC2

**Operational Costs** (often overlooked):
- EC2: Time spent managing instances, patching, scaling, monitoring
- Fargate: Near-zero operational overhead
- **Rule of thumb**: Factor in 20-40 hours/month of engineering time for EC2 fleet management
- At $100/hour loaded cost: $2,000-$4,000/month in hidden labor

Sometimes Fargate's "premium" disappears when you factor in operational efficiency.

---

## Part 2: Failure Domains and High Availability

Now let's tackle how ECS handles failures—this is where architecture meets reality.

### Understanding Failure Domains

In AWS, the hierarchy of failure domains is:

**Region** > **Availability Zone** > **Container Instance** > **Task**

Each level can fail independently:
- **Task failure**: Container crashes (app bug, OOM)
- **Instance failure**: EC2 hardware failure, OS crash
- **AZ failure**: Power outage, network partition, natural disaster
- **Region failure**: Extremely rare, but possible (meteor strike, war, etc.)

### Task Placement Across Availability Zones

When you configure an ECS service, you specify subnets. These subnets determine which AZs tasks can run in.

**Example Service Configuration**:
```json
{
  "serviceName": "api-service",
  "taskDefinition": "api:12",
  "desiredCount": 6,
  "launchType": "FARGATE",
  "networkConfiguration": {
    "awsvpcConfiguration": {
      "subnets": [
        "subnet-abc123 (us-east-1a)",
        "subnet-def456 (us-east-1b)",
        "subnet-ghi789 (us-east-1c)"
      ]
    }
  },
  "placementStrategy": [
    {
      "type": "spread",
      "field": "attribute:ecs.availability-zone"
    }
  ]
}
```

**What ECS Does**:

With 6 desired tasks and 3 AZs, ECS spreads evenly:
```
us-east-1a: 2 tasks
us-east-1b: 2 tasks
us-east-1c: 2 tasks
```

This is **best-effort spreading**. ECS tries to balance, but doesn't guarantee perfect distribution.

### Partial AZ Failure Scenario

Let's walk through what happens when an AZ goes down.

#### Initial State
```
us-east-1a: 2 tasks (RUNNING)
us-east-1b: 2 tasks (RUNNING)
us-east-1c: 2 tasks (RUNNING)

ALB Health Checks: 6/6 healthy
Desired Count: 6
```

#### us-east-1c Goes Dark

**T+0 seconds**: Network connectivity to us-east-1c is lost
- Tasks in 1c can't be reached
- ALB marks 1c targets as unhealthy (after health check failures)
- ECS loses connection to tasks in 1c

**T+30-60 seconds**: ALB stops routing traffic to us-east-1c
- Only 4 tasks receiving traffic (in 1a and 1b)
- Traffic doubles on remaining tasks

**T+60-90 seconds**: ECS detects task health check failures
- Tasks in 1c transition from RUNNING → UNKNOWN → STOPPED
- Service scheduler sees: Desired = 6, Running = 4
- **Service scheduler initiates task replacement**

**T+90 seconds**: New tasks launching
```
ECS launches 2 new tasks:
- If subnet config includes all 3 AZs: tries to launch in 1a and 1b (1c is unhealthy)
- With spread strategy: distributes across available AZs

Result:
us-east-1a: 3 tasks (RUNNING)
us-east-1b: 3 tasks (RUNNING)
us-east-1c: 0 tasks (stopped/unreachable)
```

**T+120-180 seconds** (Fargate): New tasks fully running and healthy
- New containers started
- ALB registers new targets
- Health checks pass
- Traffic normalizes

**Total downtime impact**: 
- Partial degradation: 30-60 seconds (until ALB removes bad targets)
- Capacity reduced: 60-180 seconds (until new tasks healthy)
- Full restoration: ~2-3 minutes

#### EC2 vs Fargate: The Key Difference

**Fargate Task Replacement**:
```
Timeline:
T+0:    AZ failure detected
T+60:   Task marked stopped, replacement initiated
T+90:   New Fargate task provisioned (microVM allocated)
T+120:  Container image pulled
T+150:  Container started
T+180:  Health checks pass, task healthy

Total: ~3 minutes from failure to full recovery
```

**EC2 Task Replacement** (assuming spare capacity exists):
```
Timeline:
T+0:    AZ failure detected
T+60:   Task marked stopped, replacement initiated
T+90:   New task scheduled on available EC2 instance
T+100:  Container image pulled (may be cached)
T+110:  Container started
T+120:  Health checks pass, task healthy

Total: ~2 minutes (faster if image cached)
```

**EC2 Task Replacement** (if capacity is full - worst case):
```
Timeline:
T+0:    AZ failure detected
T+60:   Task marked stopped, replacement initiated
T+90:   No available instance capacity
T+90:   Cluster Auto Scaling triggered (if configured)
T+120:  New EC2 instance launch initiated
T+420:  EC2 instance running (5-6 minutes for boot)
T+450:  ECS agent registers instance
T+460:  Task scheduled
T+470:  Container started
T+480:  Health checks pass

Total: ~8 minutes (severely degraded during this time)
```

**Critical Insight**: Fargate provides more predictable recovery times because capacity is always available. With EC2, you need to over-provision for failure scenarios.

### The SLA Difference

AWS doesn't publish specific ECS task replacement SLAs, but we can derive them from observed behavior and ECS Service SLAs.

**ECS Service Level Agreement**:
- 99.99% uptime SLA for ECS control plane
- No SLA for task-level availability (that's on you to design)

**Observed Task Replacement Times**:

| Scenario | Fargate | EC2 (with capacity) | EC2 (no capacity) |
|----------|---------|---------------------|-------------------|
| Task crash | 30-60s | 20-40s | 20-40s |
| Instance failure | N/A | 60-120s | 5-10 minutes |
| AZ failure | 2-3 minutes | 2-4 minutes | 8-15 minutes |
| Health check fail | 30-90s | 30-90s | 30-90s or 5-10m |

**Factors Affecting Recovery Time**:

1. **Health Check Configuration**:
```json
"healthCheckGracePeriodSeconds": 60,
"healthCheck": {
  "interval": 30,
  "timeout": 5,
  "healthyThreshold": 2,
  "unhealthyThreshold": 3
}
```
- Aggressive health checks: Faster detection, more false positives
- Lenient health checks: Slower detection, fewer false positives

2. **Image Size**:
- Small image (50 MB): Pulls in 5-10 seconds
- Large image (2 GB): Pulls in 60-120 seconds
- **Pro tip**: Use ECR with image caching and layer optimization

3. **Container Startup Time**:
- Simple app (nginx): <1 second
- Spring Boot app: 30-60 seconds
- Machine learning model loading: 2-5 minutes

### Advanced HA Patterns

#### Pattern 1: Over-Provisioned Desired Count

Instead of running exactly what you need, run N+1 or N+2:

```
Actual need: 6 tasks
Configured desired count: 8 tasks

During normal operation:
- 8 tasks running across 3 AZs
- Extra capacity handles small failures instantly
- ALB distributes load across all 8

During AZ failure (lose 3 tasks):
- 5 tasks remain (still above minimum 6 needed)
- Service launches 3 replacements
- Degradation is minimal
```

**Cost**: ~25% more for 2 extra tasks  
**Benefit**: Near-zero downtime during failures

#### Pattern 2: Cross-Region Failover

For critical services, deploy across multiple regions:

```
Primary: us-east-1 (6 tasks)
Secondary: us-west-2 (6 tasks, standby or active-active)

Route 53 Health Checks:
- Monitor ALB in us-east-1
- If unhealthy, failover to us-west-2
- TTL: 60 seconds

Disaster scenario:
- us-east-1 region fails
- Route 53 detects failure (30-60s)
- DNS switches to us-west-2
- Traffic flows to backup region
- Total user impact: 1-2 minutes (DNS propagation)
```

**Cost**: 2x infrastructure  
**Benefit**: Survive region-level failures

#### Pattern 3: Chaos Engineering

Proactively test failure handling:

```python
# Task Killer Script (runs as cron job)
import boto3
import random

ecs = boto3.client('ecs')

def kill_random_task():
    # List all running tasks in cluster
    tasks = ecs.list_tasks(
        cluster='production',
        serviceName='api-service',
        desiredStatus='RUNNING'
    )
    
    # Pick a random task
    task_to_kill = random.choice(tasks['taskArns'])
    
    # Stop it
    ecs.stop_task(
        cluster='production',
        task=task_to_kill,
        reason='Chaos engineering test'
    )
    
    print(f"Killed task: {task_to_kill}")
    print("Watch how fast ECS replaces it...")

# Run every hour during business hours
kill_random_task()
```

By regularly inducing failures, you:
- Verify auto-scaling works
- Validate monitoring alerts
- Train team on incident response
- Find issues before customers do

### Monitoring Failure Recovery

**Key CloudWatch Metrics**:

```
CPUUtilization (per service):
- Spike during failure = remaining tasks handling more load
- Normal after recovery

MemoryUtilization (per service):
- Similar pattern to CPU

TargetResponseTime (ALB):
- Increases during capacity reduction
- Returns to baseline after recovery

HealthyHostCount (ALB target group):
- Drops immediately when tasks unhealthy
- Recovers as new tasks become healthy

RunningTaskCount (ECS service):
- Drops when tasks stop
- Climbs back to desired count

DesiredTaskCount - RunningTaskCount:
- Should always be 0 in steady state
- Non-zero = service struggling to maintain desired count
```

**Alerting Strategy**:

```yaml
Alert 1: Tasks Not Reaching Desired Count
Metric: DesiredTaskCount - RunningTaskCount
Threshold: > 1 for 5 minutes
Severity: Warning
Action: Page on-call

Alert 2: High Task Failure Rate
Metric: Custom metric from task state changes
Threshold: > 3 tasks stopped in 5 minutes
Severity: Critical
Action: Page on-call + trigger runbook

Alert 3: ALB Unhealthy Targets
Metric: UnhealthyHostCount
Threshold: > 20% of total
Severity: Warning
Action: Slack notification

Alert 4: Service CPU Sustained High
Metric: CPUUtilization
Threshold: > 80% for 10 minutes
Severity: Warning
Action: Auto-scale + notify team
```

### The Reality of Failure Handling

Here's what I've learned from production incidents:

**Myth**: "ECS automatically handles all failures."  
**Reality**: ECS handles task replacement, but you must design for graceful degradation.

**Myth**: "Fargate is always more resilient than EC2."  
**Reality**: Fargate has faster, more predictable recovery, but EC2 with proper capacity planning can be just as resilient.

**Myth**: "Spreading across 3 AZs guarantees high availability."  
**Reality**: You also need sufficient task count, proper health checks, and over-provisioned capacity.

**Successful HA Formula**:
```
High Availability = 
  (Multiple AZs) × 
  (Sufficient Task Count) × 
  (Proper Health Checks) × 
  (Fast Task Startup) × 
  (Over-Provisioned Capacity) × 
  (Monitoring & Alerts)
```

Miss any one of these, and you have a single point of failure.

---

## Combining Both: Cost-Optimized HA Architecture

Let's design a production system that balances cost and resilience.

**Requirements**:
- 99.95% availability (4.38 hours downtime/year)
- Handle AZ failure without service degradation
- Minimize cost

**Architecture**:

```
Service: API Gateway + ALB + ECS

Base Capacity (Tier 1):
- EC2 with 3-Year RIs
- 3 instances across 3 AZs (m5.large: 2 vCPU, 8 GB)
- Cost: 3 × $11.10 = $33.30/month
- Can run: 6 tasks (2 per instance)
- Covers minimum load

Variable Capacity (Tier 2):
- Fargate Auto Scaling
- Scales from 0-10 tasks based on CPU/request count
- Distributed across 3 AZs
- Average cost: ~$200/month (varies with load)

Failure Scenario - AZ Goes Down:
- Lose 2 EC2 tasks + ~3 Fargate tasks
- Remaining: 4 EC2 tasks + ~7 Fargate tasks = 11 tasks
- Auto-scaling kicks in, launches 5 more Fargate tasks
- Total: 16 tasks (more than enough)
- Recovery time: 2-3 minutes
- Cost spike: $50 for the day (worth it for uptime)

Monthly Cost:
- Base EC2: $33.30
- Fargate variable: $200 (average)
- Total: ~$233/month

Compared to:
- All-Fargate: ~$430/month
- All-EC2 On-Demand: ~$365/month
- Savings: 46% vs all-Fargate, 36% vs all-EC2
```

**Why This Works**:
- EC2 RIs cover predictable base load (cheap)
- Fargate handles spikes (no over-provisioning)
- Both tiers spread across AZs (resilient)
- Auto-scaling reacts to failures (self-healing)

---

## Key Takeaways

**Cost Optimization**:
1. EC2 is cheaper at >50% utilization with RIs
2. Fargate wins for <50% utilization or unpredictable workloads
3. Hidden operational costs favor Fargate
4. Hybrid approach often yields best economics
5. Spot instances offer 70%+ savings for fault-tolerant workloads

**Failure Domains**:
1. Fargate has faster, more predictable recovery (2-3 min)
2. EC2 can be faster if you pre-provision capacity (2 min)
3. EC2 without capacity buffer can take 8-15 min
4. Always spread across 3+ AZs
5. Over-provision by 20-30% for instant failover
6. Monitor task replacement metrics religiously

**The Wisdom**:
> "In God we trust; all others must bring data."

Run the numbers for YOUR workload. Every architecture is different. What works for Netflix doesn't work for a startup. What works for steady-state batch processing doesn't work for real-time APIs.

---

## Questions for Further Exploration

1. **Network Costs**: How does ENI-per-task (Fargate/awsvpc) affect data transfer costs compared to EC2 bridge mode? What about cross-AZ data transfer during replication?

2. **State Management**: When a task is killed during an AZ failure, how do you handle in-flight requests? What's the difference between graceful shutdown in Fargate (SIGTERM + 30s) vs EC2?

3. **Database Connections**: If you're running 20 tasks, each with a connection pool of 10 connections, that's 200 DB connections. How does task scaling affect database load during failures?

Want me to explore any of these in detail? I can also walk through specific failure scenarios with timing diagrams or build cost calculators for your exact use case!
