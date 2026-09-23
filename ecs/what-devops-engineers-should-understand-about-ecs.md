# AWS ECS Fundamentals — DevOps Reference Guide

> A hands-on reference for beginners and advanced DevOps engineers covering everything from basic cluster inspection to solving real-world ECS issues in day-to-day operations.

---

## Table of Contents

1. [ECS Core Concepts](#-ecs-core-concepts)
2. [Prerequisites & Setup](#-prerequisites--setup)
3. [Cluster Information](#-cluster-information)
4. [Services — The Equivalent of kubectl get deployments](#-services)
5. [Tasks — The Equivalent of kubectl get pods](#-tasks)
6. [Task Definitions](#-task-definitions)
7. [Container Instances (EC2 Launch Type)](#-container-instances-ec2-launch-type)
8. [Networking & Load Balancers](#-networking--load-balancers)
9. [Logs & Observability](#-logs--observability)
10. [Scaling](#-scaling)
11. [ECS Exec — Shell into a Container](#-ecs-exec--shell-into-a-container)
12. [Deployments & Rollbacks](#-deployments--rollbacks)
13. [kubectl → ECS Cheat Sheet](#-kubectl--ecs-cheat-sheet)
14. [Common Issues & Troubleshooting](#-common-issues--troubleshooting)
15. [IAM Permissions Reference](#-iam-permissions-reference)
16. [Useful Aliases & Shell Helpers](#-useful-aliases--shell-helpers)

---

## ECS Core Concepts

Understanding the ECS hierarchy is essential before running any commands.

```
ECS Cluster
├── Service (like a Deployment in k8s)
│   ├── Task Definition (like a Pod spec / Dockerfile manifest)
│   │   └── Container Definition (image, CPU, memory, env vars, ports)
│   └── Tasks (running instances of a Task Definition — like Pods)
│       └── Container (the actual running Docker container)
└── Container Instances (EC2 nodes — only for EC2 launch type)
```

| ECS Concept | Kubernetes Equivalent | Description |
|---|---|---|
| Cluster | Cluster | Logical grouping of services and tasks |
| Service | Deployment | Manages desired count, rolling updates, load balancer |
| Task | Pod | One running unit (one or more containers) |
| Task Definition | Pod Spec / Manifest | Blueprint for running a task (image, CPU, memory) |
| Container Instance | Node | EC2 instance registered to the cluster (EC2 only) |
| Fargate | Managed Node Pool | Serverless — AWS manages the underlying compute |

---

## Prerequisites & Setup

### Install AWS CLI v2 (Ubuntu/Debian)

```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
sudo apt install -y unzip
unzip awscliv2.zip
sudo ./aws/install
aws --version
```

### Install jq (essential for JSON parsing)

```bash
sudo apt install -y jq
```

### Configure Credentials

**Option A — IAM User (quick setup)**
```bash
aws configure
# Prompts for: Access Key, Secret Key, Region, Output format
```

**Option B — EC2 IAM Role (recommended if running on EC2)**
```bash
# Attach an IAM Role to your EC2 instance with ECS permissions
# No credentials needed — AWS SDK/CLI picks it up automatically
aws sts get-caller-identity  # Verify it works
```

**Option C — AWS SSO**
```bash
aws configure sso
aws sso login --profile your-profile
```

### Set Environment Variables (add to ~/.bashrc)

```bash
export CLUSTER="your-cluster-name"
export AWS_DEFAULT_REGION="us-east-1"
export SERVICE="your-service-name"
```

### Verify Everything Works

```bash
aws sts get-caller-identity          # Am I authenticated?
aws ecs list-clusters                # Can I reach ECS?
aws ecs list-services --cluster $CLUSTER  # Can I see my cluster?
```

---

## Cluster Information

### List All Clusters

```bash
aws ecs list-clusters
```

### Describe a Cluster (Health, Active Services, Running Tasks)

```bash
aws ecs describe-clusters --clusters $CLUSTER
```

### Get Cluster Summary (Active Services + Running Tasks Count)

```bash
aws ecs describe-clusters \
  --clusters $CLUSTER \
  --query 'clusters[0].{Name:clusterName, Status:status, ActiveServices:activeServicesCount, RunningTasks:runningTasksCount, PendingTasks:pendingTasksCount}'
```

### List All Clusters with Their Task Counts

```bash
aws ecs describe-clusters \
  --clusters $(aws ecs list-clusters --query 'clusterArns[]' --output text) \
  --query 'clusters[*].{Cluster:clusterName, Status:status, Services:activeServicesCount, RunningTasks:runningTasksCount}' \
  --output table
```

### Check Cluster Capacity Providers

```bash
aws ecs describe-clusters \
  --clusters $CLUSTER \
  --include CONFIGURATIONS \
  --query 'clusters[0].capacityProviders'
```

---

## Services

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

> **Tip:** Service events are the first place to look when a deployment is stuck or tasks keep failing.

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

---

## Tasks

> In ECS, a **Task** is the equivalent of a Kubernetes **Pod** — it's one running unit containing one or more containers.

### List All Running Tasks in a Cluster

```bash
aws ecs list-tasks --cluster $CLUSTER
```

### List Tasks for a Specific Service

```bash
aws ecs list-tasks --cluster $CLUSTER --service-name $SERVICE
```

### List Tasks by Status

```bash
# Running tasks
aws ecs list-tasks --cluster $CLUSTER --desired-status RUNNING

# Stopped tasks (useful for debugging crashes)
aws ecs list-tasks --cluster $CLUSTER --desired-status STOPPED
```

### Describe a Task (Full Details — like kubectl describe pod)

```bash
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER --service-name $SERVICE \
  --query 'taskArns[0]' --output text)

aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN
```

### Get Task IP Address

```bash
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`privateIPv4Address`].value' \
  --output text
```

### Get Task Status, Health, and Container Info

```bash
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].{
    TaskID:taskArn,
    Status:lastStatus,
    HealthStatus:healthStatus,
    CPU:cpu,
    Memory:memory,
    StartedAt:startedAt,
    Containers:containers[*].{Name:name, Status:lastStatus, Health:healthStatus}
  }'
```

### Describe All Running Tasks for a Service

```bash
TASK_ARNS=$(aws ecs list-tasks --cluster $CLUSTER --service-name $SERVICE \
  --query 'taskArns[]' --output text)

aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARNS \
  --query 'tasks[*].{
    Task:taskArn,
    Status:lastStatus,
    Health:healthStatus,
    StartedAt:startedAt
  }' \
  --output table
```

### Get Recently Stopped Tasks and Their Stop Reason (Debugging Crashes)

```bash
STOPPED_TASKS=$(aws ecs list-tasks \
  --cluster $CLUSTER \
  --service-name $SERVICE \
  --desired-status STOPPED \
  --query 'taskArns[:5]' \
  --output text)

aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $STOPPED_TASKS \
  --query 'tasks[*].{
    Task:taskArn,
    StopCode:stopCode,
    StoppedReason:stoppedReason,
    Containers:containers[*].{Name:name, ExitCode:exitCode, Reason:reason}
  }'
```

> **Tip:** `stoppedReason` and container `exitCode` are the most important fields for debugging why a task stopped.

---

## Task Definitions

> A **Task Definition** is the blueprint for your containers — equivalent to a Pod spec or a `docker-compose.yml`.

### List All Task Definitions

```bash
aws ecs list-task-definitions
```

### List Task Definitions for a Specific Family

```bash
aws ecs list-task-definitions --family-prefix your-app-name
```

### Describe the Latest Task Definition

```bash
aws ecs describe-task-definition \
  --task-definition your-task-def-name
```

### Get the Task Definition Currently Used by a Service

```bash
TASK_DEF=$(aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].taskDefinition' \
  --output text)

aws ecs describe-task-definition --task-definition $TASK_DEF
```

### Get Container Image Versions in Use

```bash
aws ecs describe-task-definition \
  --task-definition $TASK_DEF \
  --query 'taskDefinition.containerDefinitions[*].{Name:name, Image:image, CPU:cpu, Memory:memory}'
```

### Get Environment Variables from a Task Definition

```bash
aws ecs describe-task-definition \
  --task-definition $TASK_DEF \
  --query 'taskDefinition.containerDefinitions[*].{Container:name, EnvVars:environment}'
```

### Compare Two Task Definition Revisions

```bash
diff \
  <(aws ecs describe-task-definition --task-definition your-app:10 --output json) \
  <(aws ecs describe-task-definition --task-definition your-app:11 --output json)
```

---

## Container Instances (EC2 Launch Type)

> Only relevant if you are using the **EC2 launch type**. Skip this section if you use **Fargate**.

### List Container Instances (Nodes)

```bash
aws ecs list-container-instances --cluster $CLUSTER
```

### Describe Container Instances (CPU, Memory, Running Tasks)

```bash
INSTANCE_ARNS=$(aws ecs list-container-instances \
  --cluster $CLUSTER \
  --query 'containerInstanceArns[]' \
  --output text)

aws ecs describe-container-instances \
  --cluster $CLUSTER \
  --container-instances $INSTANCE_ARNS \
  --query 'containerInstances[*].{
    InstanceID:ec2InstanceId,
    Status:status,
    RunningTasks:runningTasksCount,
    PendingTasks:pendingTasksCount,
    AgentVersion:versionInfo.agentVersion,
    AgentConnected:agentConnected
  }' \
  --output table
```

### Check Available CPU and Memory on Each Node

```bash
aws ecs describe-container-instances \
  --cluster $CLUSTER \
  --container-instances $INSTANCE_ARNS \
  --query 'containerInstances[*].{
    Instance:ec2InstanceId,
    FreeCPU:remainingResources[?name==`CPU`].integerValue | [0],
    FreeMemory:remainingResources[?name==`MEMORY`].integerValue | [0]
  }' \
  --output table
```

### Drain a Container Instance (Before Maintenance)

```bash
aws ecs update-container-instances-state \
  --cluster $CLUSTER \
  --container-instances $INSTANCE_ARN \
  --status DRAINING
```

---

## Networking & Load Balancers

### Get Load Balancer Attached to a Service

```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].loadBalancers'
```

### List All Load Balancers with DNS Names

```bash
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[*].{Name:LoadBalancerName, DNS:DNSName, State:State.Code, Type:Type}' \
  --output table
```

### Check Target Group Health (Is Traffic Reaching Your Containers?)

```bash
# First get your target group ARN
aws elbv2 describe-target-groups \
  --query 'TargetGroups[*].{Name:TargetGroupName, ARN:TargetGroupArn, Port:Port}' \
  --output table

# Then check the health
TARGET_GROUP_ARN="arn:aws:elasticloadbalancing:..."
aws elbv2 describe-target-health \
  --target-group-arn $TARGET_GROUP_ARN \
  --query 'TargetHealthDescriptions[*].{Target:Target.Id, Port:Target.Port, Health:TargetHealth.State, Reason:TargetHealth.Reason}' \
  --output table
```

> **Tip:** If tasks are running but traffic isn't reaching them, check target health — `unhealthy` targets with reason `Health checks failed` is the most common culprit.

### Check VPC and Subnet of Running Tasks (Fargate)

```bash
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details'
```

### Check Security Groups on a Service

```bash
aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].networkConfiguration.awsvpcConfiguration'
```

---

## Logs & Observability

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

---

## Scaling

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

---

## ECS Exec — Shell into a Container

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

> After enabling, force a new deployment so tasks are re-launched with exec enabled:
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

## Deployments & Rollbacks

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

echo "Deployment complete and stable"
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

### Monitor Deployment Progress

```bash
watch -n 5 "aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].deployments[*].{Status:status, Desired:desiredCount, Running:runningCount, Pending:pendingCount}' \
  --output table"
```

---

## kubectl → ECS Cheat Sheet

| kubectl Command | AWS ECS CLI Equivalent |
|---|---|
| `kubectl get pods` | `aws ecs list-tasks --cluster $CLUSTER` |
| `kubectl get pods -o wide` | `aws ecs describe-tasks --cluster $CLUSTER --tasks $(...)` |
| `kubectl describe pod <pod>` | `aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN` |
| `kubectl get deployments` | `aws ecs list-services --cluster $CLUSTER` |
| `kubectl describe deployment <name>` | `aws ecs describe-services --cluster $CLUSTER --services $SERVICE` |
| `kubectl get svc` | `aws ecs describe-services + aws elbv2 describe-load-balancers` |
| `kubectl get nodes` | `aws ecs list-container-instances --cluster $CLUSTER` |
| `kubectl describe node <node>` | `aws ecs describe-container-instances --cluster $CLUSTER --container-instances $ARN` |
| `kubectl logs <pod>` | `aws logs tail /ecs/$SERVICE --follow` |
| `kubectl logs <pod> \| grep ERROR` | `aws logs filter-log-events --log-group-name /ecs/$SERVICE --filter-pattern "ERROR"` |
| `kubectl exec -it <pod> -- sh` | `aws ecs execute-command --cluster $CLUSTER --task $TASK_ARN --interactive --command "/bin/sh"` |
| `kubectl rollout restart deployment` | `aws ecs update-service --cluster $CLUSTER --service $SERVICE --force-new-deployment` |
| `kubectl scale deployment --replicas=4` | `aws ecs update-service --cluster $CLUSTER --service $SERVICE --desired-count 4` |
| `kubectl rollout undo deployment` | `aws ecs update-service --task-definition your-app:PREV_REVISION` |
| `kubectl top pods` | CloudWatch `aws cloudwatch get-metric-statistics` |
| `kubectl get events` | `aws ecs describe-services --query 'services[0].events'` |

---

## Common Issues & Troubleshooting

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

```bash
# Check if container instances have enough resources
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
| `1` | Application error — check app logs |
| `137` | OOMKilled — container ran out of memory, increase `memoryReservation` |
| `139` | Segmentation fault |
| `143` | Container received SIGTERM (graceful stop timed out) |

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

## IAM Permissions Reference

### Minimum Read-Only Policy (Monitoring / Debugging)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:List*",
        "ecs:Describe*",
        "logs:GetLogEvents",
        "logs:FilterLogEvents",
        "logs:DescribeLogStreams",
        "logs:TailLogEvents",
        "elasticloadbalancing:Describe*",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "ecr:DescribeImages",
        "ecr:ListImages"
      ],
      "Resource": "*"
    }
  ]
}
```

### Full DevOps Policy (Deploy, Scale, Exec)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecs:*",
        "ecr:*",
        "logs:*",
        "elasticloadbalancing:Describe*",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "application-autoscaling:*",
        "iam:PassRole",
        "ssm:StartSession",
        "ssmmessages:*"
      ],
      "Resource": "*"
    }
  ]
}
```

### Required Task Execution Role Policies

```bash
# Attach AWS managed policies to your ECS execution role
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# For Secrets Manager access
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite
```

---

## Useful Aliases & Shell Helpers

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
  echo "Redeployment triggered for $1"
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

## Quick Reference Card

```
# CLUSTER
aws ecs describe-clusters --clusters $CLUSTER

# SERVICES (like Deployments)
aws ecs list-services --cluster $CLUSTER
aws ecs describe-services --cluster $CLUSTER --services $SERVICE

# TASKS (like Pods)
aws ecs list-tasks --cluster $CLUSTER
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN

# LOGS
aws logs tail /ecs/$SERVICE --follow

# DEPLOY
aws ecs update-service --cluster $CLUSTER --service $SERVICE --force-new-deployment

# SCALE
aws ecs update-service --cluster $CLUSTER --service $SERVICE --desired-count 3

# EXEC
aws ecs execute-command --cluster $CLUSTER --task $TASK_ARN --container app --interactive --command "/bin/sh"

# WAIT FOR STABLE
aws ecs wait services-stable --cluster $CLUSTER --services $SERVICE
```

---

## Further Reading

- [AWS ECS Developer Guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html)
- [AWS ECS CLI Reference](https://docs.aws.amazon.com/cli/latest/reference/ecs/index.html)
- [ECS Deployment Circuit Breaker](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html)
- [ECS Task Networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-networking.html)
- [ECS Exec Deep Dive](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html)
- [CloudWatch Container Insights for ECS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html)

---

> **Contributions welcome!** Found a command that saved your day? Open a PR and add it to the troubleshooting section.
