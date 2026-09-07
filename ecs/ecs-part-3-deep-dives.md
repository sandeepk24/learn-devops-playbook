# 🚀 AWS ECS — Part 3: ALB Connectivity, Networking & Deep Dives

> **Learn DevOps Playbook** · ECS Series (Part 3 of 3)
>
> Part 3 is the deep-dive finale: exactly **how an ALB connects to target groups** (and every term in that chain), **networking internals** for `awsvpc`/Fargate, **EC2 container instances**, the full **IAM reference**, and the **kubectl→ECS cheat sheet**.
>
> 👈 **Part 1 — Fundamentals:** concepts, Task Definitions, Tasks, building a Fargate app.
> 👈 **Part 2 — Operations:** services, logs, scaling, deployments, ECS Exec, troubleshooting.

---

## 📚 Table of Contents

1. [ALB → Target Group: The Whole Chain](#-alb--target-group-the-whole-chain)
2. [Wiring an ALB to an ECS Service (End-to-End)](#-wiring-an-alb-to-an-ecs-service-end-to-end)
3. [The Two Health Checks](#-the-two-health-checks)
4. [Networking & awsvpc Internals](#-networking--awsvpc-internals)
5. [Container Instances (EC2 Launch Type)](#-container-instances-ec2-launch-type)
6. [IAM Permissions Reference](#-iam-permissions-reference)
7. [kubectl → ECS Cheat Sheet](#-kubectl--ecs-cheat-sheet)
8. [Further Reading](#-further-reading)

---

## 🔗 ALB → Target Group: The Whole Chain

This is the part people wave their hands at. Let's name every component and how requests actually flow from the internet to your container.

### The components, top to bottom

```
                    Internet
                       │
                       ▼
            ┌──────────────────────┐
            │  Application Load     │   DNS name: my-alb-123.us-east-1.elb.amazonaws.com
            │  Balancer (ALB)       │   Lives in ≥2 public subnets, has a security group
            └──────────┬───────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  Listener (:443)      │   "Listen on this port + protocol"
            └──────────┬───────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  Listener Rules       │   "If path = /api/* → forward to TG-api"
            │  (priority-ordered)   │   "Default → forward to TG-web"
            └──────────┬───────────┘
                       │  forward action
                       ▼
            ┌──────────────────────┐
            │  Target Group (TG)    │   Protocol + port + health check + target type
            └──────────┬───────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ Target  │   │ Target  │   │ Target  │   Each = one ECS task's IP:port
   │ (task)  │   │ (task)  │   │ (task)  │   (target type = "ip" for Fargate)
   └─────────┘   └─────────┘   └─────────┘
```

### Term by term

| Term | What it is | Key fields |
|---|---|---|
| **ALB** | Layer-7 load balancer. Has a stable DNS name, lives in ≥2 subnets across AZs, has its own security group | `scheme` (internet-facing / internal), `subnets`, `securityGroups` |
| **Listener** | A check on a port + protocol. The ALB has one listener per port it accepts traffic on (e.g. 80, 443) | `Port`, `Protocol`, `DefaultActions` |
| **Listener Rule** | Ordered conditions on a listener that decide *which* target group gets the request | `Priority`, `Conditions` (path, host, header), `Actions` |
| **Target Group (TG)** | A routing destination + health-check policy. Targets register here | `Protocol`, `Port`, `TargetType`, `HealthCheck*` |
| **Target** | One backend endpoint. For Fargate it's an **IP:port** (the task's ENI IP); for EC2 bridge mode it's an **instance:port** | `Id`, `Port` |
| **Target Type** | `ip` (Fargate / awsvpc), `instance` (EC2 bridge), or `lambda` | Set at TG creation, immutable |

### How a request flows

1. Client resolves the ALB's **DNS name** to one of its IPs (round-robin across AZs).
2. Request hits a **listener** matching the port (e.g. `:443`).
3. The listener evaluates its **rules** in priority order; the first match wins. A `forward` action sends the request to a **target group**.
4. The TG picks a healthy **target** (one task's IP:port) using its load-balancing algorithm (round robin by default).
5. The request reaches the container — *if* the task's security group allows inbound from the ALB's security group on the container port.

> 💡 **The #1 silent failure:** everything looks configured, but the **task security group** doesn't allow inbound from the **ALB security group** on the container port. Traffic dies between target group and target, and the target shows `unhealthy` with reason `Health checks failed`.

### Who registers the targets?

You don't register Fargate tasks by hand. When you attach a load balancer to an ECS **service**, ECS automatically:

- **registers** a task's IP:port as a target when the task reaches `RUNNING`, and
- **deregisters** it (respecting the TG's *deregistration delay* / connection draining) when the task is being replaced or scaled in.

This is the ECS equivalent of how a Kubernetes Service's endpoints controller keeps Endpoints in sync with Pods.

---

## 🧩 Wiring an ALB to an ECS Service (End-to-End)

Building directly on the Fargate app from **Part 1**. Goal: put the `hello-svc` service behind a public ALB.

### Step 1 — Two security groups

```bash
# (reuse $VPC_ID, $AWS_DEFAULT_REGION from Part 1)

# ALB SG: allow HTTP from the internet
export ALB_SG=$(aws ec2 create-security-group \
  --group-name hello-alb-sg --description "ALB inbound 80" \
  --vpc-id $VPC_ID --query GroupId --output text)

aws ec2 authorize-security-group-ingress \
  --group-id $ALB_SG --protocol tcp --port 80 --cidr 0.0.0.0/0

# Task SG: allow 8080 ONLY from the ALB SG (not the whole internet)
export TASK_SG=$(aws ec2 create-security-group \
  --group-name hello-task-sg --description "App 8080 from ALB" \
  --vpc-id $VPC_ID --query GroupId --output text)

aws ec2 authorize-security-group-ingress \
  --group-id $TASK_SG --protocol tcp --port 8080 \
  --source-group $ALB_SG
```

> This source-group rule (`--source-group $ALB_SG`) is the fix for the "#1 silent failure" above. The task accepts traffic *only* from the ALB.

### Step 2 — Create the ALB (needs ≥2 subnets in different AZs)

```bash
# Get two subnets in different AZs
export SUBNETS=$(aws ec2 describe-subnets \
  --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[:2].SubnetId' --output text)

export ALB_ARN=$(aws elbv2 create-load-balancer \
  --name hello-alb \
  --type application \
  --scheme internet-facing \
  --subnets $SUBNETS \
  --security-groups $ALB_SG \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)
```

### Step 3 — Create the target group (target type = ip for Fargate)

```bash
export TG_ARN=$(aws elbv2 create-target-group \
  --name hello-tg \
  --protocol HTTP \
  --port 8080 \
  --vpc-id $VPC_ID \
  --target-type ip \
  --health-check-protocol HTTP \
  --health-check-path /health \
  --health-check-interval-seconds 30 \
  --health-check-timeout-seconds 5 \
  --healthy-threshold-count 2 \
  --unhealthy-threshold-count 3 \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
```

> `--target-type ip` is mandatory for Fargate/awsvpc. `instance` is only for EC2 bridge mode. Target type is fixed at creation — you can't change it later.

### Step 4 — Create a listener that forwards to the target group

```bash
aws elbv2 create-listener \
  --load-balancer-arn $ALB_ARN \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN
```

To add path-based routing later (e.g. `/api/*` → a different TG):

```bash
LISTENER_ARN=$(aws elbv2 describe-listeners \
  --load-balancer-arn $ALB_ARN \
  --query 'Listeners[0].ListenerArn' --output text)

aws elbv2 create-rule \
  --listener-arn $LISTENER_ARN \
  --priority 10 \
  --conditions Field=path-pattern,Values='/api/*' \
  --actions Type=forward,TargetGroupArn=$TG_API_ARN
```

### Step 5 — Attach the load balancer to the ECS service

A service's load balancer config is set at create time. Recreate `hello-svc` with the LB wired in (and the new task SG):

```bash
aws ecs create-service \
  --cluster $CLUSTER \
  --service-name hello-svc \
  --task-definition hello-ecs \
  --desired-count 2 \
  --launch-type FARGATE \
  --load-balancers "targetGroupArn=$TG_ARN,containerName=web,containerPort=8080" \
  --health-check-grace-period-seconds 60 \
  --network-configuration "awsvpcConfiguration={
    subnets=[$(echo $SUBNETS | tr ' ' ',')],
    securityGroups=[$TASK_SG],
    assignPublicIp=ENABLED
  }"
```

`containerName` + `containerPort` tell ECS *which container* in the task definition to register as a target. From here ECS registers each task's IP in the target group automatically.

### Step 6 — Confirm targets are healthy, then hit the ALB

```bash
# Watch targets register and turn healthy
aws elbv2 describe-target-health \
  --target-group-arn $TG_ARN \
  --query 'TargetHealthDescriptions[*].{IP:Target.Id, Port:Target.Port, State:TargetHealth.State, Reason:TargetHealth.Reason}' \
  --output table

# Get the ALB's DNS name and curl it
ALB_DNS=$(aws elbv2 describe-load-balancers \
  --load-balancer-arns $ALB_ARN \
  --query 'LoadBalancers[0].DNSName' --output text)

echo "App: http://$ALB_DNS/"
curl http://$ALB_DNS/
```

### The same wiring with boto3

```python
import boto3

elbv2 = boto3.client("elbv2")
ecs = boto3.client("ecs")

def create_alb_stack(vpc_id, subnets, alb_sg, task_sg, cluster):
    alb_arn = elbv2.create_load_balancer(
        Name="hello-alb", Type="application", Scheme="internet-facing",
        Subnets=subnets, SecurityGroups=[alb_sg],
    )["LoadBalancers"][0]["LoadBalancerArn"]

    tg_arn = elbv2.create_target_group(
        Name="hello-tg", Protocol="HTTP", Port=8080, VpcId=vpc_id,
        TargetType="ip",                 # mandatory for Fargate
        HealthCheckProtocol="HTTP", HealthCheckPath="/health",
        HealthCheckIntervalSeconds=30, HealthCheckTimeoutSeconds=5,
        HealthyThresholdCount=2, UnhealthyThresholdCount=3,
    )["TargetGroups"][0]["TargetGroupArn"]

    elbv2.create_listener(
        LoadBalancerArn=alb_arn, Protocol="HTTP", Port=80,
        DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}],
    )

    ecs.create_service(
        cluster=cluster, serviceName="hello-svc",
        taskDefinition="hello-ecs", desiredCount=2, launchType="FARGATE",
        loadBalancers=[{
            "targetGroupArn": tg_arn,
            "containerName": "web",
            "containerPort": 8080,
        }],
        healthCheckGracePeriodSeconds=60,
        networkConfiguration={"awsvpcConfiguration": {
            "subnets": subnets, "securityGroups": [task_sg],
            "assignPublicIp": "ENABLED",
        }},
    )
    return alb_arn, tg_arn
```

---

## ❤️ The Two Health Checks

A constant source of confusion: there are **two independent health checks**, and a task can pass one while failing the other.

| | Container health check | Target group health check |
|---|---|---|
| **Defined in** | Task definition (`healthCheck` block) | Target group config |
| **Who runs it** | The ECS agent, *inside* the task | The ALB, *over the network* |
| **How** | Runs a command in the container (`curl localhost/health`) | HTTP request to the target's IP:port + path |
| **Failure means** | ECS marks the container unhealthy → may restart the task | ALB stops routing traffic to that target |
| **Reaches container via** | localhost (no SG involved) | the network (SG **must** allow ALB → task) |

### Why this matters for debugging

- **Container health check passes, TG health check fails** → almost always a **security group** or **port mismatch** (the container is fine, the ALB just can't reach it).
- **Both fail** → the app itself isn't serving the health path.
- **No container health check defined, TG unhealthy** → look at the TG path/port and the SG, not the task definition.

### Key timing knobs

| Setting | Where | What it controls |
|---|---|---|
| `healthCheckGracePeriodSeconds` | ECS **service** | How long ECS ignores ALB health-check failures after a task starts (slow boot apps) |
| `startPeriod` | Task def `healthCheck` | Grace window for the *container* health check |
| `HealthCheckIntervalSeconds` | Target group | Seconds between ALB probes |
| `HealthyThresholdCount` / `UnhealthyThresholdCount` | Target group | Consecutive passes/fails to flip state |
| Deregistration delay | Target group attribute | Connection draining window before a target is fully removed |

```bash
# Inspect the service's grace period
aws ecs describe-services --cluster $CLUSTER --services $SERVICE \
  --query 'services[0].healthCheckGracePeriodSeconds'

# Inspect a target group's health-check + deregistration settings
aws elbv2 describe-target-groups --target-group-arns $TG_ARN \
  --query 'TargetGroups[0].{Path:HealthCheckPath, Port:HealthCheckPort, Interval:HealthCheckIntervalSeconds, Healthy:HealthyThresholdCount, Unhealthy:UnhealthyThresholdCount}'

aws elbv2 describe-target-group-attributes --target-group-arn $TG_ARN \
  --query "Attributes[?Key=='deregistration_delay.timeout_seconds']"
```

---

## 🌐 Networking & awsvpc Internals

### What `awsvpc` actually does

On Fargate (and EC2 tasks using `awsvpc`), **every task gets its own elastic network interface (ENI)** with a private IP in your subnet. Consequences worth internalizing:

- The task's IP **is** the target registered in the target group (`target-type ip`).
- Security groups attach to the **task**, not a shared host — clean per-service isolation.
- Each task consumes **one IP** from the subnet. A `/24` subnet can host far fewer tasks than you'd expect once you account for AWS-reserved IPs. Subnet IP exhaustion shows up as tasks stuck in `PROVISIONING`.

### Public vs private subnet placement

| Placement | `assignPublicIp` | How it reaches ECR/internet | Use for |
|---|---|---|---|
| **Public subnet** | `ENABLED` | Directly via the subnet's internet gateway route | Demos, simple public services |
| **Private subnet** | `DISABLED` | Via a **NAT gateway** *or* **VPC endpoints** | Production |

> ⚠️ A Fargate task in a **private subnet** with `assignPublicIp=DISABLED` and **no NAT/endpoints** cannot pull its image. This surfaces as `CannotPullContainerError` (Part 2, issue #6) — a networking problem masquerading as a permissions one.

### VPC endpoints to keep Fargate fully private

To run Fargate in private subnets without a NAT gateway, add interface/gateway endpoints so image pulls and logging stay inside AWS:

- `com.amazonaws.<region>.ecr.api` (interface)
- `com.amazonaws.<region>.ecr.dkr` (interface)
- `com.amazonaws.<region>.s3` (gateway — ECR layers live in S3)
- `com.amazonaws.<region>.logs` (interface — CloudWatch Logs)
- `com.amazonaws.<region>.secretsmanager` (interface — if you inject secrets)

### Inspect a task's networking

```bash
# VPC/subnet/ENI details of a running task
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details'

# Security groups + subnets the service launches tasks into
aws ecs describe-services --cluster $CLUSTER --services $SERVICE \
  --query 'services[0].networkConfiguration.awsvpcConfiguration'

# All load balancers with DNS names
aws elbv2 describe-load-balancers \
  --query 'LoadBalancers[*].{Name:LoadBalancerName, DNS:DNSName, State:State.Code, Type:Type}' \
  --output table

# Which target group(s) a service is wired to
aws ecs describe-services --cluster $CLUSTER --services $SERVICE \
  --query 'services[0].loadBalancers'
```

---

## 🖥️ Container Instances (EC2 Launch Type)

> Only relevant if you use the **EC2 launch type**. Skip if you're on **Fargate**.

A **container instance** is an EC2 node running the ECS agent, registered to your cluster — the equivalent of a Kubernetes **node**.

### List & describe container instances

```bash
aws ecs list-container-instances --cluster $CLUSTER

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

### Check available CPU/memory per node

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

### Drain a node before maintenance

```bash
aws ecs update-container-instances-state \
  --cluster $CLUSTER \
  --container-instances $INSTANCE_ARN \
  --status DRAINING
```

Draining tells ECS to reschedule tasks elsewhere and stop placing new ones — the EC2 equivalent of `kubectl drain`.

---

## 🔑 IAM Permissions Reference

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
        "elasticloadbalancing:*",
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

> 🔐 `iam:PassRole` is required so you can assign the task/execution roles to a task definition — but it's powerful. In production, scope it with a `Condition` on `iam:PassedToService = ecs-tasks.amazonaws.com` and to specific role ARNs rather than `Resource: "*"`.

### The two task-definition roles (recap from Part 1)

```bash
# Execution role: ECS pulls images + writes logs + fetches secrets
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy

# For Secrets Manager-backed env vars, the execution role also needs read access
aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/SecretsManagerReadWrite
```

The **task role** (separate) is what your application code uses at runtime — grant it only the AWS actions your app actually makes (e.g. `dynamodb:GetItem`, `s3:GetObject`).

---

## 📖 kubectl → ECS Cheat Sheet

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
| `kubectl drain <node>` | `aws ecs update-container-instances-state --status DRAINING` |
| `kubectl logs <pod>` | `aws logs tail /ecs/$SERVICE --follow` |
| `kubectl logs <pod> \| grep ERROR` | `aws logs filter-log-events --log-group-name /ecs/$SERVICE --filter-pattern "ERROR"` |
| `kubectl exec -it <pod> -- sh` | `aws ecs execute-command --cluster $CLUSTER --task $TASK_ARN --interactive --command "/bin/sh"` |
| `kubectl rollout restart deployment` | `aws ecs update-service --cluster $CLUSTER --service $SERVICE --force-new-deployment` |
| `kubectl scale deployment --replicas=4` | `aws ecs update-service --cluster $CLUSTER --service $SERVICE --desired-count 4` |
| `kubectl rollout undo deployment` | `aws ecs update-service --task-definition your-app:PREV_REVISION` |
| `kubectl top pods` | CloudWatch `aws cloudwatch get-metric-statistics` |
| `kubectl get events` | `aws ecs describe-services --query 'services[0].events'` |
| `kubectl get endpoints` | `aws elbv2 describe-target-health --target-group-arn $TG_ARN` |

> The last row is the Part 3 payoff: a Kubernetes Service's **Endpoints** are the conceptual twin of an ALB **target group's registered targets** — both track "which backends are alive right now."

---

## 📌 Quick Reference Card

```
# CLUSTER
aws ecs describe-clusters --clusters $CLUSTER

# SERVICES (like Deployments)
aws ecs list-services --cluster $CLUSTER
aws ecs describe-services --cluster $CLUSTER --services $SERVICE

# TASKS (like Pods)
aws ecs list-tasks --cluster $CLUSTER
aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN

# TARGET HEALTH (like Endpoints)
aws elbv2 describe-target-health --target-group-arn $TG_ARN

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

## 📚 Further Reading

- [AWS ECS Developer Guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/Welcome.html)
- [AWS ECS CLI Reference](https://docs.aws.amazon.com/cli/latest/reference/ecs/index.html)
- [ECS Deployment Circuit Breaker](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html)
- [ECS Task Networking (awsvpc)](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-networking.html)
- [ECS Service Load Balancing](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service-load-balancing.html)
- [ALB Target Groups](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-target-groups.html)
- [ECS Exec Deep Dive](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ecs-exec.html)
- [CloudWatch Container Insights for ECS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ContainerInsights.html)

---

> 💬 **Contributions welcome!** Found a command that saved your day? Open a PR on `learn-devops-playbook` and add it.
>
> ⬅️ **Back to [Part 1 — Fundamentals](ecs-part-1-fundamentals.md)** · **[Part 2 — Operations](ecs-part-2-operations.md)**
