# 🚀 AWS ECS — Part 1: Fundamentals, Task Definitions & Building Your First App

> **Learn DevOps Playbook** · ECS Series (Part 1 of 3)
>
> Part 1 covers the mental model, a deep dive on **Task Definitions** and **Tasks**, and a complete **Fargate walkthrough** to deploy a working app from zero.
>
> 👉 **Part 2 — Operations:** services, logs, scaling, deployments, ECS Exec, troubleshooting.
> 👉 **Part 3 — Deep Dives:** ALB → target group connectivity, networking internals, IAM, the kubectl→ECS cheat sheet.

---

## 📚 Table of Contents

1. [ECS Core Concepts](#-ecs-core-concepts)
2. [Prerequisites & Setup](#-prerequisites--setup)
3. [Cluster Information](#-cluster-information)
4. [Task Definitions — Deep Dive](#-task-definitions--deep-dive)
5. [Tasks — Deep Dive](#-tasks--deep-dive)
6. [Build a Basic ECS App on Fargate (End-to-End)](#-build-a-basic-ecs-app-on-fargate-end-to-end)
7. [What's Next](#-whats-next)

---

## 🧠 ECS Core Concepts

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

### The one distinction that trips people up

A **Task Definition** is a *versioned, immutable template*. A **Task** is a *running instance* of that template. You never edit a task definition in place — you register a new **revision** (`my-app:11` supersedes `my-app:10`) and point your service at it. This immutability is what makes rollbacks trivial: roll back = point the service at an older revision.

---

## ⚙️ Prerequisites & Setup

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

### Python (boto3) setup

Throughout this series, CLI examples are paired with `boto3` equivalents so you can drop them into scripts, Lambdas, or FastAPI handlers.

```bash
pip install boto3
```

```python
import boto3

# A single client is reused across calls; boto3 handles credential
# resolution the same way the CLI does (env vars → ~/.aws → IAM role).
ecs = boto3.client("ecs", region_name="us-east-1")

print(ecs.list_clusters()["clusterArns"])
```

---

## 🏗️ Cluster Information

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

### Python equivalent

```python
import boto3

ecs = boto3.client("ecs")

def cluster_summary(cluster: str) -> dict:
    resp = ecs.describe_clusters(clusters=[cluster])
    c = resp["clusters"][0]
    return {
        "name": c["clusterName"],
        "status": c["status"],
        "active_services": c["activeServicesCount"],
        "running_tasks": c["runningTasksCount"],
        "pending_tasks": c["pendingTasksCount"],
    }

print(cluster_summary("your-cluster-name"))
```

---

## 📋 Task Definitions — Deep Dive

> A **Task Definition** is the blueprint for your containers — equivalent to a Pod spec or a `docker-compose.yml`. It is *versioned* and *immutable*: every change creates a new revision.

### Anatomy of a Task Definition

A task definition is built from a handful of top-level fields plus one or more **container definitions**. Here is an annotated Fargate example you can use as a template:

```json
{
  "family": "my-app",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::123456789012:role/myAppTaskRole",
  "runtimePlatform": {
    "cpuArchitecture": "X86_64",
    "operatingSystemFamily": "LINUX"
  },
  "containerDefinitions": [
    {
      "name": "web",
      "image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/my-app:1.0.0",
      "essential": true,
      "cpu": 256,
      "memory": 512,
      "portMappings": [
        { "containerPort": 8080, "protocol": "tcp" }
      ],
      "environment": [
        { "name": "LOG_LEVEL", "value": "info" }
      ],
      "secrets": [
        {
          "name": "DB_PASSWORD",
          "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789012:secret:prod/db-AbCdEf"
        }
      ],
      "healthCheck": {
        "command": ["CMD-SHELL", "curl -f http://localhost:8080/health || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 60
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/my-app",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs",
          "awslogs-create-group": "true"
        }
      }
    }
  ]
}
```

### Field-by-field reference

| Field | Scope | What it does | Notes |
|---|---|---|---|
| `family` | Task | Logical name; revisions increment under it | `my-app:1`, `my-app:2`, … |
| `networkMode` | Task | `awsvpc`, `bridge`, `host`, `none` | **Fargate requires `awsvpc`** (each task gets its own ENI + private IP) |
| `requiresCompatibilities` | Task | `FARGATE` and/or `EC2` | Validates the def against that launch type |
| `cpu` / `memory` | Task | Task-level resource reservation | On Fargate these must be a [valid CPU/memory combo](#fargate-cpu--memory-combos) |
| `executionRoleArn` | Task | Role **ECS itself** uses to pull images & write logs | Needs ECR + CloudWatch Logs perms |
| `taskRoleArn` | Task | Role **your app** assumes at runtime | This is what your boto3 calls use inside the container |
| `name` | Container | Container name; referenced by load balancers, exec, logs | |
| `image` | Container | Full image URI | ECR, Docker Hub, etc. |
| `essential` | Container | If `true`, task stops when this container stops | At least one must be essential |
| `cpu` / `memory` | Container | Per-container limits | Sum should fit within task-level values |
| `portMappings` | Container | Ports exposed | On `awsvpc`, `hostPort` == `containerPort` |
| `environment` | Container | Plain-text env vars | Don't put secrets here |
| `secrets` | Container | Env vars sourced from Secrets Manager / SSM | Injected at start; needs execution-role perms |
| `healthCheck` | Container | Container-level (Docker) health check | Distinct from the ALB target-group health check — see Part 3 |
| `logConfiguration` | Container | Where stdout/stderr go | `awslogs` driver → CloudWatch |

> 💡 **Two roles, two jobs.** `executionRoleArn` is for the ECS *agent* (pull image, fetch secrets, ship logs). `taskRoleArn` is for *your code* (e.g. reading from S3 or DynamoDB via boto3). Mixing these up is the single most common task-definition mistake.

### Fargate CPU & memory combos

Fargate only accepts specific pairings. A few common ones:

| CPU (vCPU) | Valid memory values |
|---|---|
| 256 (.25) | 512, 1024, 2048 |
| 512 (.5) | 1024 – 4096 (1 GB increments) |
| 1024 (1) | 2048 – 8192 (1 GB increments) |
| 2048 (2) | 4096 – 16384 (1 GB increments) |
| 4096 (4) | 8192 – 30720 (1 GB increments) |

Pick the wrong pairing and `register-task-definition` fails immediately with a validation error.

### List & inspect task definitions

```bash
# List all task definition families
aws ecs list-task-definitions

# List revisions for one family (newest first)
aws ecs list-task-definitions --family-prefix my-app --sort DESC

# Describe the latest revision
aws ecs describe-task-definition --task-definition my-app
```

### Get the task definition currently used by a service

```bash
TASK_DEF=$(aws ecs describe-services \
  --cluster $CLUSTER \
  --services $SERVICE \
  --query 'services[0].taskDefinition' \
  --output text)

aws ecs describe-task-definition --task-definition $TASK_DEF
```

### Pull out just the bits you usually care about

```bash
# Image versions in use
aws ecs describe-task-definition \
  --task-definition $TASK_DEF \
  --query 'taskDefinition.containerDefinitions[*].{Name:name, Image:image, CPU:cpu, Memory:memory}'

# Environment variables
aws ecs describe-task-definition \
  --task-definition $TASK_DEF \
  --query 'taskDefinition.containerDefinitions[*].{Container:name, EnvVars:environment}'

# Which IAM roles are attached
aws ecs describe-task-definition \
  --task-definition $TASK_DEF \
  --query 'taskDefinition.{TaskRole:taskRoleArn, ExecutionRole:executionRoleArn}'
```

### Compare two revisions (what actually changed in a deploy)

```bash
diff \
  <(aws ecs describe-task-definition --task-definition my-app:10 --output json) \
  <(aws ecs describe-task-definition --task-definition my-app:11 --output json)
```

### Register a new revision

```bash
aws ecs register-task-definition --cli-input-json file://taskdef.json
```

### Registering & inspecting with boto3

```python
import boto3

ecs = boto3.client("ecs")

def register_revision(taskdef: dict) -> str:
    """Register a new revision and return its family:revision identifier."""
    resp = ecs.register_task_definition(**taskdef)
    td = resp["taskDefinition"]
    return f"{td['family']}:{td['revision']}"


def current_images(task_def: str) -> list[dict]:
    """Return the image of every container in a task definition."""
    td = ecs.describe_task_definition(taskDefinition=task_def)["taskDefinition"]
    return [
        {"name": c["name"], "image": c["image"]}
        for c in td["containerDefinitions"]
    ]

print(current_images("my-app"))
```

> 🤔 **Worth pausing on:** why is a task definition immutable instead of a mutable object you patch? Think about what a rollback would mean if revisions could be edited in place — and what happens to a service mid-deploy that's running two revisions at once. (Answer in Part 2's deployment section.)

---

## 📦 Tasks — Deep Dive

> A **Task** is a running instance of a task definition — the ECS equivalent of a Kubernetes **Pod**. One task can hold several containers that share the same network namespace (on `awsvpc`, the same ENI/IP).

### The task lifecycle

A task moves through a well-defined set of states. Knowing them turns "it's broken" into "it's stuck at `PROVISIONING`, so it's a networking/ENI problem":

```
PROVISIONING → PENDING → ACTIVATING → RUNNING → DEACTIVATING → STOPPING → DEPROVISIONING → STOPPED
```

| State | What's happening | If it's stuck here, suspect… |
|---|---|---|
| `PROVISIONING` | ENI being attached (Fargate/awsvpc) | Subnet IP exhaustion, ENI limits |
| `PENDING` | Waiting for capacity / pulling image | Capacity, image pull, resource limits |
| `ACTIVATING` | Containers starting, health checks warming up | Slow startup, failing container health check |
| `RUNNING` | Task is up | — |
| `STOPPING` / `STOPPED` | Shutting down | Check `stoppedReason` + container `exitCode` |

Each task also carries two status fields: `lastStatus` (where it is now) and `desiredStatus` (where ECS wants it). When these diverge, ECS is mid-transition.

### List tasks

```bash
# All running tasks in a cluster
aws ecs list-tasks --cluster $CLUSTER

# Tasks for one service
aws ecs list-tasks --cluster $CLUSTER --service-name $SERVICE

# By status (STOPPED is gold for debugging crashes)
aws ecs list-tasks --cluster $CLUSTER --desired-status RUNNING
aws ecs list-tasks --cluster $CLUSTER --desired-status STOPPED
```

### Describe a task (like `kubectl describe pod`)

```bash
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER --service-name $SERVICE \
  --query 'taskArns[0]' --output text)

aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN
```

### Status, health, and per-container detail

```bash
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].{
    TaskID:taskArn,
    LastStatus:lastStatus,
    DesiredStatus:desiredStatus,
    HealthStatus:healthStatus,
    CPU:cpu,
    Memory:memory,
    StartedAt:startedAt,
    Containers:containers[*].{Name:name, Status:lastStatus, Health:healthStatus, ExitCode:exitCode}
  }'
```

### Get a task's private IP (awsvpc / Fargate)

```bash
aws ecs describe-tasks \
  --cluster $CLUSTER \
  --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`privateIPv4Address`].value' \
  --output text
```

### Why did a task stop? (the most important debugging query)

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

`stopCode` tells you *who* stopped it (`TaskFailedToStart`, `EssentialContainerExited`, `UserInitiated`), while the container `exitCode` tells you *why*. Exit-code reference lives in Part 2's troubleshooting section.

### Run a one-off task (not tied to a service)

Handy for migrations, batch jobs, or smoke tests:

```bash
aws ecs run-task \
  --cluster $CLUSTER \
  --task-definition my-app \
  --launch-type FARGATE \
  --network-configuration 'awsvpcConfiguration={
    subnets=[subnet-0abc123],
    securityGroups=[sg-0def456],
    assignPublicIp=ENABLED
  }' \
  --count 1
```

### Tasks with boto3

```python
import boto3

ecs = boto3.client("ecs")

def stopped_task_reasons(cluster: str, service: str, limit: int = 5) -> list[dict]:
    """Return stop reasons + exit codes for recently stopped tasks."""
    arns = ecs.list_tasks(
        cluster=cluster,
        serviceName=service,
        desiredStatus="STOPPED",
    )["taskArns"][:limit]

    if not arns:
        return []

    tasks = ecs.describe_tasks(cluster=cluster, tasks=arns)["tasks"]
    return [
        {
            "stop_code": t.get("stopCode"),
            "stopped_reason": t.get("stoppedReason"),
            "containers": [
                {"name": c["name"], "exit_code": c.get("exitCode"), "reason": c.get("reason")}
                for c in t["containers"]
            ],
        }
        for t in tasks
    ]

for row in stopped_task_reasons("your-cluster", "your-service"):
    print(row)
```

---

## 🛠️ Build a Basic ECS App on Fargate (End-to-End)

This walkthrough takes you from a Dockerfile to a publicly reachable container on **Fargate**. We'll keep it deliberately minimal — a single FastAPI container behind a public IP. (Putting it behind an ALB is covered in Part 3.)

### Step 0 — The app

A tiny FastAPI app with a `/health` endpoint (so we can wire up health checks later):

```python
# app.py
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Hello from ECS Fargate 👋"}

@app.get("/health")
def health():
    return {"status": "ok"}
```

```dockerfile
# Dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY app.py .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Step 1 — Create an ECR repo and push the image

```bash
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export AWS_DEFAULT_REGION=us-east-1
export REPO=hello-ecs

# Create the repository
aws ecr create-repository --repository-name $REPO

# Authenticate Docker to ECR
aws ecr get-login-password --region $AWS_DEFAULT_REGION | \
  docker login --username AWS --password-stdin \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com

# Build, tag, push
docker build -t $REPO .
docker tag $REPO:latest \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$REPO:1.0.0
docker push \
  $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com/$REPO:1.0.0
```

### Step 2 — Create the execution role (if you don't have one)

ECS needs this role to pull from ECR and write logs.

```bash
# Trust policy: allow ECS tasks to assume the role
cat > trust.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Service": "ecs-tasks.amazonaws.com" },
    "Action": "sts:AssumeRole"
  }]
}
EOF

aws iam create-role \
  --role-name ecsTaskExecutionRole \
  --assume-role-policy-document file://trust.json

aws iam attach-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
```

### Step 3 — Create the cluster

```bash
export CLUSTER=hello-cluster
aws ecs create-cluster --cluster-name $CLUSTER
```

### Step 4 — Register the task definition

```bash
cat > taskdef.json <<EOF
{
  "family": "hello-ecs",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "executionRoleArn": "arn:aws:iam::${AWS_ACCOUNT_ID}:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "web",
      "image": "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com/hello-ecs:1.0.0",
      "essential": true,
      "portMappings": [{ "containerPort": 8080, "protocol": "tcp" }],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/hello-ecs",
          "awslogs-region": "${AWS_DEFAULT_REGION}",
          "awslogs-stream-prefix": "ecs",
          "awslogs-create-group": "true"
        }
      }
    }
  ]
}
EOF

aws ecs register-task-definition --cli-input-json file://taskdef.json
```

### Step 5 — Find a subnet and security group

For this minimal demo we'll give the task a public IP directly. Find a public subnet and create a security group that allows inbound on 8080:

```bash
# Grab the default VPC
export VPC_ID=$(aws ec2 describe-vpcs \
  --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)

# Pick one subnet in that VPC
export SUBNET_ID=$(aws ec2 describe-subnets \
  --filters Name=vpc-id,Values=$VPC_ID \
  --query 'Subnets[0].SubnetId' --output text)

# Create a security group allowing inbound 8080
export SG_ID=$(aws ec2 create-security-group \
  --group-name hello-ecs-sg \
  --description "Allow 8080" \
  --vpc-id $VPC_ID \
  --query 'GroupId' --output text)

aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp --port 8080 --cidr 0.0.0.0/0
```

> ⚠️ `--cidr 0.0.0.0/0` opens 8080 to the whole internet. Fine for a throwaway demo, never for anything real — restrict to your IP or an ALB security group (Part 3).

### Step 6 — Run the task

```bash
aws ecs run-task \
  --cluster $CLUSTER \
  --task-definition hello-ecs \
  --launch-type FARGATE \
  --count 1 \
  --network-configuration "awsvpcConfiguration={
    subnets=[$SUBNET_ID],
    securityGroups=[$SG_ID],
    assignPublicIp=ENABLED
  }"
```

### Step 7 — Find its public IP and test it

```bash
# Get the task ARN
TASK_ARN=$(aws ecs list-tasks --cluster $CLUSTER --query 'taskArns[0]' --output text)

# Wait until it's running
aws ecs wait tasks-running --cluster $CLUSTER --tasks $TASK_ARN

# Get the ENI, then resolve its public IP
ENI_ID=$(aws ecs describe-tasks --cluster $CLUSTER --tasks $TASK_ARN \
  --query 'tasks[0].attachments[0].details[?name==`networkInterfaceId`].value' \
  --output text)

PUBLIC_IP=$(aws ec2 describe-network-interfaces \
  --network-interface-ids $ENI_ID \
  --query 'NetworkInterfaces[0].Association.PublicIp' \
  --output text)

echo "App is at: http://$PUBLIC_IP:8080"
curl http://$PUBLIC_IP:8080/
curl http://$PUBLIC_IP:8080/health
```

### Step 8 — Turn it into a long-running Service

A bare `run-task` won't restart if it crashes. Wrap it in a **Service** so ECS keeps `desiredCount` tasks alive:

```bash
export SERVICE=hello-svc
aws ecs create-service \
  --cluster $CLUSTER \
  --service-name $SERVICE \
  --task-definition hello-ecs \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={
    subnets=[$SUBNET_ID],
    securityGroups=[$SG_ID],
    assignPublicIp=ENABLED
  }"
```

Now ECS will replace the task if it dies. Managing this service day-to-day — scaling, deploying new images, reading logs, debugging — is all of **Part 2**.

### The same flow in boto3

For automation, here's the create-cluster-through-create-service path as a script:

```python
import boto3

ecs = boto3.client("ecs")

CLUSTER = "hello-cluster"
SERVICE = "hello-svc"
SUBNET_ID = "subnet-0abc123"
SG_ID = "sg-0def456"

def deploy():
    ecs.create_cluster(clusterName=CLUSTER)

    ecs.create_service(
        cluster=CLUSTER,
        serviceName=SERVICE,
        taskDefinition="hello-ecs",
        desiredCount=1,
        launchType="FARGATE",
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": [SUBNET_ID],
                "securityGroups": [SG_ID],
                "assignPublicIp": "ENABLED",
            }
        },
    )

    # Block until the service settles into a steady state
    waiter = ecs.get_waiter("services_stable")
    waiter.wait(cluster=CLUSTER, services=[SERVICE])
    print("✅ Service is stable")

if __name__ == "__main__":
    deploy()
```

### Tear down (avoid surprise bills)

```bash
aws ecs update-service --cluster $CLUSTER --service $SERVICE --desired-count 0
aws ecs delete-service --cluster $CLUSTER --service $SERVICE --force
aws ecs delete-cluster --cluster $CLUSTER
aws ecr delete-repository --repository-name $REPO --force
aws ec2 delete-security-group --group-id $SG_ID
```

---

## 🎯 What's Next

You now have a working Fargate app and a solid grip on task definitions and tasks. The next two parts build on this exact setup:

- **Part 2 — Operations:** services in depth, logs & observability, scaling & auto-scaling, deployments & rollbacks, ECS Exec, and a full troubleshooting playbook with exit-code tables.
- **Part 3 — Deep Dives:** how an ALB connects to target groups (and every term in that chain), networking internals, the IAM reference, and the kubectl→ECS cheat sheet.

---

> 💬 **Contributions welcome!** Found a command that saved your day? Open a PR on `learn-devops-playbook` and add it.
