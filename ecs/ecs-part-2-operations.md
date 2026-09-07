# 🚀 AWS ECS — Part 2: Operations, Scaling & Troubleshooting

> **Learn DevOps Playbook** · ECS Series (Part 2 of 3)
>
> Part 2 is the day-to-day operations playbook: managing **services**, reading **logs**, **scaling**, **deployments & rollbacks**, **ECS Exec**, and a battle-tested **troubleshooting** section.
>
> 👈 **Part 1 — Fundamentals:** concepts, Task Definitions, Tasks, and building a Fargate app from scratch.
> 👉 **Part 3 — Deep Dives:** ALB → target group connectivity, networking, IAM, kubectl→ECS cheat sheet.

> Assumes the `$CLUSTER`, `$SERVICE`, and `$AWS_DEFAULT_REGION` environment variables from Part 1.

---

## 📚 Table of Contents

1. [Services](#-services)
2. [Logs & Observability](#-logs--observability)
3. [Scaling](#-scaling)
4. [ECS Exec — Shell into a Container](#-ecs-exec--shell-into-a-container)
5. [Deployments & Rollbacks](#-deployments--rollbacks)
6. [Common Issues & Troubleshooting](#-common-issues--troubleshooting)
7. [Useful Aliases & Shell Helpers](#-useful-aliases--shell-helpers)

---

## 🚀 Services

> In ECS, a **Service** is the equivalent of a Kubernetes **Deployment**. It manages desired task count, rolling updates, and load balancer registration.

### List All Services in a Cluster

```bash
aws ecs list-services --cluster $CLUSTER
```

### Describe a Service (Full Details)

```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE
```

### Get Service Health at a Glance

```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].{
    Name:serviceName,
    Status:status,
    Desired:desiredCount,
    Running:runningCount,
    Pending:pendingCount,
    TaskDefinition:taskDefinition,
    LaunchType:launchType
  }'
```

### List All Services with Health Status

```bash
for svc in $(aws ecs list-services --cluster $CLUSTER --query 'serviceArns[]' --output text); do
  aws ecs describe-services --cluster $CLUSTER --services $svc \
    --query 'services[0].{Name:serviceName, Desired:desiredCount, Running:runningCount, Status:status}' \
    --output table
done
```

### Check Service Events (Recent Deployment Activity / Errors)

```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].events[:10]' \
  --output table
```

> 💡 **Tip:** Service events are the first place to look when a deployment is stuck or tasks keep failing.

### Check Service Deployment Status

```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].deployments[*].{
    Status:status,
    Desired:desiredCount,
    Running:runningCount,
    Pending:pendingCount,
    Created:createdAt,
    Updated:updatedAt,
    TaskDef:taskDefinition
  }' \
  --output table
```

### Check Service Auto-Scaling Configuration

```bash
aws application-autoscaling describe-scalable-targets \
  --service-namespace ecs \
  --query "ScalableTargets[?ResourceId=='service/$CLUSTER/$SERVICE']"
```

### Service health in boto3

```python
import boto3

ecs = boto3.client("ecs")

def service_health(cluster: str, service: str) -> dict:
    svc = ecs.describe_services(cluster=cluster, services=[service])["services"][0]
    return {
        "status": svc["status"],
        "desired": svc["desiredCount"],
        "running": svc["runningCount"],
        "pending": svc["pendingCount"],
        "task_definition": svc["taskDefinition"],
        # Most recent service events — the first stop when something's wrong
        "recent_events": [e["message"] for e in svc.get("events", [])[:5]],
    }

print(service_health("your-cluster", "your-service"))
```

---

## 📊 Logs & Observability

### View Logs for a Container (CloudWatch)

```bash
# Tail logs in real time (like kubectl logs -f)
aws logs tail /ecs/$SERVICE --follow

# Get recent log events
aws logs get-log-events \
  --log-group-name /ecs/$SERVICE \
  --log-stream-name ecs/your-container-name/$(echo $TASK_ARN | cut -d'/' -f3) \
  --limit 100

# Filter logs by a keyword (like kubectl logs | grep)
aws logs filter-log-events \
  --log-group-name /ecs/$SERVICE \
  --filter-pattern "ERROR"

# Get logs from the last 30 minutes
aws logs filter-log-events \
  --log-group-name /ecs/$SERVICE \
  --start-time $(date -d '30 minutes ago' +%s000) \
  --filter-pattern "ERROR" \
  --output table
```

### List All Log Streams for a Service (All Tasks)

```bash
aws logs describe-log-streams \
  --log-group-name /ecs/$SERVICE \
  --order-by LastEventTime \
  --descending \
  --query 'logStreams[*].{Stream:logStreamName, LastEvent:lastEventTimestamp}' \
  --output table
```

### CPU and Memory Utilization Metrics

```bash
# CPU Utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ClusterName,Value=$CLUSTER Name=ServiceName,Value=$SERVICE \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Average \
  --query 'Datapoints[*].{Time:Timestamp, CPU:Average}' \
  --output table

# Memory Utilization
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name MemoryUtilization \
  --dimensions Name=ClusterName,Value=$CLUSTER Name=ServiceName,Value=$SERVICE \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Average \
  --query 'Datapoints[*].{Time:Timestamp, Memory:Average}' \
  --output table
```

### Tailing logs from Python

```python
import time
import boto3

logs = boto3.client("logs")

def tail_errors(log_group: str, minutes: int = 30) -> list[str]:
    """Pull ERROR lines from the last N minutes across all streams."""
    start = int((time.time() - minutes * 60) * 1000)  # ms epoch
    paginator = logs.get_paginator("filter_log_events")
    out = []
    for page in paginator.paginate(
        logGroupName=log_group,
        startTime=start,
        filterPattern="ERROR",
    ):
        out.extend(e["message"] for e in page["events"])
    return out

for line in tail_errors("/ecs/your-service"):
    print(line)
```

---

## 📏 Scaling

### Manually Scale a Service (Change Desired Count)

```bash
# Scale up
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --desired-count 4

# Scale down
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --desired-count 1

# Scale to zero (stop all tasks)
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --desired-count 0
```

### View Auto-Scaling Policies

```bash
aws application-autoscaling describe-scaling-policies \
  --service-namespace ecs \
  --query "ScalingPolicies[?ResourceId=='service/$CLUSTER/$SERVICE']"
```

### Register Auto-Scaling Target

```bash
aws application-autoscaling register-scalable-target \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/$CLUSTER/$SERVICE \
  --min-capacity 1 \
  --max-capacity 10
```

### Put a Target Tracking Scaling Policy (CPU-Based)

```bash
aws application-autoscaling put-scaling-policy \
  --service-namespace ecs \
  --scalable-dimension ecs:service:DesiredCount \
  --resource-id service/$CLUSTER/$SERVICE \
  --policy-name cpu-target-tracking \
  --policy-type TargetTrackingScaling \
  --target-tracking-scaling-policy-configuration '{
    "TargetValue": 60.0,
    "PredefinedMetricSpecification": {
      "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
    },
    "ScaleInCooldown": 300,
    "ScaleOutCooldown": 60
  }'
```

> 💡 **Target tracking vs step scaling.** Target tracking ("keep CPU at 60%") is the right default — AWS computes the math for you. Reach for step scaling only when you need custom thresholds tied to specific CloudWatch alarms.

### Auto-scaling setup in boto3

```python
import boto3

aas = boto3.client("application-autoscaling")

CLUSTER = "your-cluster"
SERVICE = "your-service"
RESOURCE_ID = f"service/{CLUSTER}/{SERVICE}"

def enable_cpu_autoscaling(min_cap: int = 1, max_cap: int = 10, target: float = 60.0):
    aas.register_scalable_target(
        ServiceNamespace="ecs",
        ResourceId=RESOURCE_ID,
        ScalableDimension="ecs:service:DesiredCount",
        MinCapacity=min_cap,
        MaxCapacity=max_cap,
    )
    aas.put_scaling_policy(
        ServiceNamespace="ecs",
        ResourceId=RESOURCE_ID,
        ScalableDimension="ecs:service:DesiredCount",
        PolicyName="cpu-target-tracking",
        PolicyType="TargetTrackingScaling",
        TargetTrackingScalingPolicyConfiguration={
            "TargetValue": target,
            "PredefinedMetricSpecification": {
                "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
            },
            "ScaleInCooldown": 300,
            "ScaleOutCooldown": 60,
        },
    )

enable_cpu_autoscaling()
```

---

## 🔐 ECS Exec — Shell into a Container

> The ECS equivalent of `kubectl exec -it <pod> -- /bin/sh`

### Prerequisites

```bash
# Install the Session Manager plugin
curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o "session-manager-plugin.deb"
sudo dpkg -i session-manager-plugin.deb

# Verify
session-manager-plugin
```

### Enable ECS Exec on a Service (Required First)

```bash
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --enable-execute-command
```

> ⚠️ After enabling, force a new deployment so tasks are re-launched with exec enabled:
> ```bash
> aws ecs update-service --cluster $CLUSTER --service $SERVICE --force-new-deployment
> ```

### Exec into a Container

```bash
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER \
  --service-name $SERVICE \
  --query 'taskArns[0]' --output text)

aws ecs execute-command \
  --cluster $CLUSTER \
  --task $TASK_ARN \
  --container your-container-name \
  --interactive \
  --command "/bin/sh"
```

### Check if Exec is Enabled on a Task

```bash
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].enableExecuteCommand'
```

---

## 🔄 Deployments & Rollbacks

### Force a New Deployment (like kubectl rollout restart)

```bash
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --force-new-deployment
```

### Deploy a New Image Version

```bash
# Update the service to use a new task definition revision
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --task-definition your-task-def:NEW_REVISION
```

### Wait for a Deployment to Stabilize

```bash
aws ecs wait services-stable \
  --cluster $CLUSTER \
  --services $SERVICE

echo "✅ Deployment complete and stable"
```

### Rollback to a Previous Task Definition

```bash
# List revisions to find the one you want
aws ecs list-task-definitions \
  --family-prefix your-app \
  --sort DESC \
  --output table

# Roll back to a specific revision
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --task-definition your-app:PREVIOUS_REVISION

# Wait for rollback to complete
aws ecs wait services-stable --cluster $CLUSTER --services $SERVICE
```

> 🤔 **Answering Part 1's question:** rollback is trivial *because* task definitions are immutable. A previous revision still exists, unmodified, so "roll back" just means pointing the service at `your-app:10` again. During a rolling deploy the service legitimately runs two revisions (PRIMARY + ACTIVE) at once — if revisions were mutable, "which version is this task running?" would have no stable answer.

### Monitor Deployment Progress

```bash
watch -n 5 "aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].deployments[*].{Status:status, Desired:desiredCount, Running:runningCount, Pending:pendingCount}' \
  --output table"
```

### Deploy + wait in boto3

```python
import boto3

ecs = boto3.client("ecs")

def deploy_revision(cluster: str, service: str, task_def: str) -> None:
    """Point a service at a new task def revision and block until stable."""
    ecs.update_service(
        cluster=cluster,
        service=service,
        taskDefinition=task_def,  # e.g. "my-app:11"
    )
    ecs.get_waiter("services_stable").wait(cluster=cluster, services=[service])
    print(f"✅ {service} now running {task_def}")

# Rollback is the same call with an older revision:
# deploy_revision("your-cluster", "your-service", "my-app:10")
```

---

## 🔥 Common Issues & Troubleshooting

### 1. Tasks Stuck in PENDING State

**Symptoms:** `runningCount` is 0, `pendingCount` > 0

```bash
# Check service events for the reason
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].events[:5]' \
  --output table
```

**Common Causes:**
| Cause | What to Check |
|---|---|
| Not enough CPU/Memory | Check container instance capacity (`describe-container-instances`) or Fargate limits |
| No matching container instances | EC2 instance type/AMI might be wrong or unhealthy |
| Capacity provider issues | Check cluster capacity providers |
| ECS Agent disconnected | `agentConnected: false` in `describe-container-instances` |
| Subnet IP exhaustion | awsvpc/Fargate needs a free IP per task in the subnet |

```bash
# Check if container instances have enough resources (EC2 launch type)
aws ecs describe-container-instances \
  --cluster $CLUSTER \
  --container-instances $INSTANCE_ARNS \
  --query 'containerInstances[*].{Instance:ec2InstanceId, FreeCPU:remainingResources[?name==`CPU`].integerValue|[0], FreeMemory:remainingResources[?name==`MEMORY`].integerValue|[0], Status:status, AgentConnected:agentConnected}' \
  --output table
```

---

### 2. Tasks Keep Stopping / Crash Looping

**Symptoms:** Tasks start and immediately stop; `runningCount` keeps cycling

```bash
# Get stopped tasks and their exit codes
STOPPED=$(aws ecs list-tasks \
  --cluster $CLUSTER \
  --service-name $SERVICE \
  --desired-status STOPPED \
  --query 'taskArns[:3]' \
  --output text)

aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $STOPPED \
  --query 'tasks[*].{
    StopCode:stopCode,
    StoppedReason:stoppedReason,
    Container:containers[0].name,
    ExitCode:containers[0].exitCode,
    ContainerReason:containers[0].reason
  }' \
  --output table
```

**Common Exit Codes:**
| Exit Code | Meaning |
|---|---|
| `0` | Clean exit — but if essential, the task still stops (long-running apps shouldn't exit 0) |
| `1` | Application error — check app logs |
| `137` | OOMKilled (128+9/SIGKILL) — container ran out of memory, raise `memory` |
| `139` | Segmentation fault (128+11/SIGSEGV) |
| `143` | SIGTERM (128+15) — graceful stop timed out |

```bash
# Check application logs for the crash reason
aws logs filter-log-events \
  --log-group-name /ecs/$SERVICE \
  --start-time $(date -d '30 minutes ago' +%s000) \
  --filter-pattern "ERROR"
```

---

### 3. Service Won't Reach Desired Count (Stuck at 0 or partial)

**Symptoms:** Desired=3, Running=1, service events show failures

```bash
# Check deployment status and events together
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query '{
    Deployments:services[0].deployments[*].{Status:status, Desired:desiredCount, Running:runningCount, Failed:failedTasks},
    Events:services[0].events[:5]
  }'
```

**Things to Check:**
```bash
# 1. Is the task definition valid?
aws ecs describe-task-definition --task-definition $TASK_DEF

# 2. Is the image accessible? (check ECR or Docker Hub)
aws ecr describe-images \
  --repository-name your-repo-name \
  --image-ids imageTag=latest

# 3. Check IAM role attached to task definition
aws ecs describe-task-definition \
  --task-definition $TASK_DEF \
  --query 'taskDefinition.{TaskRole:taskRoleArn, ExecutionRole:executionRoleArn}'
```

---

### 4. Health Checks Failing / Tasks Unhealthy

**Symptoms:** Tasks start but are marked unhealthy, or target group shows unhealthy targets

```bash
# Check target group health
TARGET_GROUP_ARN="arn:aws:elasticloadbalancing:region:account:targetgroup/name/id"
aws elbv2 describe-target-health \
  --target-group-arn $TARGET_GROUP_ARN \
  --query 'TargetHealthDescriptions[*].{IP:Target.Id, Port:Target.Port, State:TargetHealth.State, Reason:TargetHealth.Reason, Desc:TargetHealth.Description}' \
  --output table

# Check task-level health
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].{HealthStatus:healthStatus, Containers:containers[*].{Name:name, Health:healthStatus}}'
```

**Common Health Check Failures:**
| Issue | Solution |
|---|---|
| Wrong port in target group | Verify container port matches target group port |
| Security group blocking health check | Allow inbound from load balancer SG on container port |
| App not ready at `/health` path | Fix health check path or increase `startPeriod` in task definition |
| Slow app startup | Increase `healthCheckGracePeriodSeconds` on the service |

```bash
# Check health check grace period on service
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].healthCheckGracePeriodSeconds'

# Update grace period (give app more time to start)
aws ecs update-service \
  --cluster $CLUSTER \
  --service $SERVICE \
  --health-check-grace-period-seconds 120
```

> 📎 The full ALB → target group health-check chain (and why there are *two* kinds of health check) is covered in **Part 3**.

---

### 5. Deployment Stuck / Not Completing

**Symptoms:** New deployment created but old tasks won't drain

```bash
# Check deployment rollout state
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].{
    DeploymentConfig:deploymentConfiguration,
    Deployments:deployments[*].{Status:status, Desired:desiredCount, Running:runningCount, Pending:pendingCount, Updated:updatedAt}
  }'

# Check deployment circuit breaker state
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].deployments[?status==`PRIMARY`].rolloutState'
```

**Check if Deployment Circuit Breaker Triggered:**
```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].deployments[0].{RolloutState:rolloutState, RolloutReason:rolloutStateReason}'
```

---

### 6. Cannot Pull Image (ImagePullBackOff equivalent)

**Symptoms:** Task stops with reason `CannotPullContainerError`

```bash
# Check stopped tasks for pull errors
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $STOPPED \
  --query 'tasks[*].containers[*].{Container:name, Reason:reason}' \
  --output table
```

**Common Causes:**
```bash
# 1. Check execution role has ECR permissions
aws iam get-role-policy \
  --role-name your-ecs-execution-role \
  --policy-name AmazonECSTaskExecutionRolePolicy

# 2. Check ECR image exists
aws ecr list-images \
  --repository-name your-repo \
  --query 'imageIds[*].imageTag'

# 3. Check ECR login (if using private registry)
aws ecr get-login-password --region $AWS_DEFAULT_REGION | \
  docker login --username AWS --password-stdin \
  YOUR_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com
```

> 💡 On Fargate in a **private subnet**, `CannotPullContainerError` is very often a *networking* problem, not a permissions one — no NAT gateway or no VPC endpoints means the task can't reach ECR. See Part 3.

---

### 7. ECS Exec Not Working

**Symptoms:** `execute-command` fails

```bash
# Check if execute command is enabled on the task
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].enableExecuteCommand'

# Check SSM Agent is running in the container
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].containers[*].managedAgents'
```

**Requirements Checklist:**
- [ ] `--enable-execute-command` set on service
- [ ] Tasks re-deployed after enabling exec
- [ ] Task role has `ssmmessages:*` permissions
- [ ] Session Manager Plugin installed on your machine
- [ ] Container has `/bin/sh` or `/bin/bash` available

```bash
# Required task role permissions
aws iam put-role-policy \
  --role-name your-task-role \
  --policy-name ECSExecPolicy \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Action":[
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel"
      ],
      "Resource":"*"
    }]
  }'
```

---

### 8. Service Discovery / DNS Issues

```bash
# Check service discovery config
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].serviceRegistries'

# Check Cloud Map namespaces
aws servicediscovery list-namespaces \
  --query 'Namespaces[*].{Name:Name, Type:Type, ID:Id}'

# Check registered instances
aws servicediscovery list-instances \
  --service-id YOUR_SERVICE_DISCOVERY_ID \
  --query 'Instances[*].{ID:Id, Attrs:Attributes}'
```

---

## 🛠️ Useful Aliases & Shell Helpers

Add these to your `~/.bashrc` or `~/.zshrc` to speed up day-to-day ECS work:

```bash
# ---- ECS Aliases ----

# Quick cluster overview
alias ecs-status='aws ecs describe-clusters --clusters $CLUSTER \
  --query "clusters[0].{Services:activeServicesCount, Running:runningTasksCount, Pending:pendingTasksCount, Status:status}" \
  --output table'

# List services with health
alias ecs-services='aws ecs describe-services \
  --cluster $CLUSTER \
  --services $(aws ecs list-services --cluster $CLUSTER --query "serviceArns[]" --output text) \
  --query "services[*].{Name:serviceName, Desired:desiredCount, Running:runningCount, Status:status}" \
  --output table'

# List running tasks
alias ecs-tasks='aws ecs list-tasks --cluster $CLUSTER --desired-status RUNNING'

# Tail logs for a service
ecs-logs() { aws logs tail /ecs/$1 --follow; }

# Get task ARN (first running task for a service)
ecs-task-arn() {
  aws ecs list-tasks --cluster $CLUSTER --service-name $1 \
    --query 'taskArns[0]' --output text
}

# Exec into a container
ecs-exec() {
  TASK=$(ecs-task-arn $1)
  aws ecs execute-command \
    --cluster $CLUSTER \
    --task $TASK \
    --container $1 \
    --interactive \
    --command "/bin/sh"
}

# Force redeploy a service
ecs-redeploy() {
  aws ecs update-service --cluster $CLUSTER --service $1 --force-new-deployment
  echo "🚀 Redeployment triggered for $1"
}

# Check service events (last 5)
ecs-events() {
  aws ecs describe-services \
    --cluster $CLUSTER \
    --services $1 \
    --query 'services[0].events[:5]' \
    --output table
}

# Get stopped tasks and their reasons
ecs-stopped() {
  STOPPED=$(aws ecs list-tasks --cluster $CLUSTER --service-name $1 \
    --desired-status STOPPED --query 'taskArns[:3]' --output text)
  aws ecs describe-tasks --cluster $CLUSTER --tasks $STOPPED \
    --query 'tasks[*].{StopCode:stopCode, Reason:stoppedReason, ExitCode:containers[0].exitCode}' \
    --output table
}
```

### Usage Examples

```bash
ecs-status                     # Cluster health at a glance
ecs-services                   # All services with desired/running counts
ecs-logs my-service            # Tail logs for my-service
ecs-exec my-container          # Shell into a container
ecs-redeploy my-service        # Force redeploy
ecs-events my-service          # Check recent events
ecs-stopped my-service         # Debug crash reasons
```

---

## 🎯 What's Next

**Part 3 — Deep Dives** ties the whole series together: exactly how an **ALB connects to target groups** (listeners, rules, target types, the two health checks, registration/deregistration), networking internals for `awsvpc`/Fargate, the full **IAM reference**, EC2 launch-type container instances, and the **kubectl→ECS cheat sheet**.

---

> 💬 **Contributions welcome!** Found a command that saved your day? Open a PR on `learn-devops-playbook`.
