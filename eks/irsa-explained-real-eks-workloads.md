# 🔐 IRSA Explained Through Real EKS Workloads

> _"Your pod needs to talk to AWS. You need to stop giving it a user's access key to do it."_

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#IRSA` `#IAM` `#AWS` `#Kubernetes` `#Security` `#Production`

---

## Table of Contents

1. [What Is IRSA and Why Does It Exist?](#1-what-is-irsa-and-why-does-it-exist)
2. [How IRSA Works — The Mechanism Behind the Magic](#2-how-irsa-works--the-mechanism-behind-the-magic)
3. [The Four-Link Chain You Must Get Right](#3-the-four-link-chain-you-must-get-right)
4. [Setting Up IRSA — Step by Step](#4-setting-up-irsa--step-by-step)
5. [Real Workload #1 — Reading Secrets from AWS Secrets Manager](#5-real-workload-1--reading-secrets-from-aws-secrets-manager)
6. [Real Workload #2 — A FastAPI App Reading and Writing to S3](#6-real-workload-2--a-fastapi-app-reading-and-writing-to-s3)
7. [Real Workload #3 — A Worker Pod Publishing to SQS and Writing to DynamoDB](#7-real-workload-3--a-worker-pod-publishing-to-sqs-and-writing-to-dynamodb)
8. [Real Workload #4 — Cluster Autoscaler and Karpenter (System-Level IRSA)](#8-real-workload-4--cluster-autoscaler-and-karpenter-system-level-irsa)
9. [Common IRSA Mistakes and How to Diagnose Them](#9-common-irsa-mistakes-and-how-to-diagnose-them)
10. [IRSA vs Other Auth Methods — When to Use What](#10-irsa-vs-other-auth-methods--when-to-use-what)
11. [Quick Reference Cheatsheet](#11-quick-reference-cheatsheet)

---

## 1. What Is IRSA and Why Does It Exist?

Before IRSA existed, teams had two options for giving a Kubernetes pod access to AWS services:

**Option A — Hardcode AWS credentials as environment variables**

```yaml
# ❌ The old (terrible) way
env:
  - name: AWS_ACCESS_KEY_ID
    value: "AKIAIOSFODNN7EXAMPLE"
  - name: AWS_SECRET_ACCESS_KEY
    value: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
```

Problems: Keys are visible in your YAML. They get committed to Git. They don't rotate. If an attacker gets one pod, they get the keys. And the same key often gets copy-pasted across environments.

**Option B — Attach an IAM Role to the EC2 node (node-level IAM)**

Every pod on that node inherits the node's IAM role. It works, but it's a security nightmare — a compromised pod in one namespace can access AWS services it was never meant to touch, because all pods on the node share the same identity.

**IRSA (IAM Roles for Service Accounts)** solves both problems. It gives **each pod its own distinct AWS identity**, scoped to exactly the permissions it needs, without storing any credentials anywhere.

### The Core Idea in One Sentence

> IRSA lets a Kubernetes ServiceAccount impersonate an IAM Role using a cryptographically signed token — so your pod authenticates to AWS as *itself*, not as the node or a shared user.

### Why Every EKS Team Needs to Understand This

| Without IRSA | With IRSA |
|---|---|
| Credentials in YAML / environment | Zero credentials stored anywhere |
| All pods on a node share one identity | Each pod has its own IAM identity |
| Key rotation is a manual, risky process | AWS handles token rotation automatically |
| Audit logs show the node, not the pod | CloudTrail shows the exact pod's role |
| Blast radius = the entire node | Blast radius = this pod's specific permissions |

---

## 2. How IRSA Works — The Mechanism Behind the Magic

Let's build the mental model before touching any YAML.

### The Players

| Component | What It Is |
|---|---|
| **OIDC Provider** | A trust bridge between your EKS cluster and AWS IAM. EKS exposes an OIDC endpoint; you register it in IAM so AWS knows to trust tokens signed by your cluster. |
| **ServiceAccount** | A Kubernetes identity assigned to one or more pods. Think of it as the pod's "username" within the cluster. |
| **IAM Role** | An AWS identity that can be *assumed* temporarily. It has policies that define what AWS actions it can perform. |
| **IAM Role Trust Policy** | The gatekeeper on the IAM Role that answers: "Who is allowed to assume this role?" |
| **Projected Service Account Token** | A short-lived JWT (JSON Web Token), automatically mounted into your pod, signed by your EKS cluster's OIDC key. The AWS SDK uses this token to call `sts:AssumeRoleWithWebIdentity`. |

### The Authentication Flow — What Happens at Runtime

```
┌─────────────────────────────────────────────────────────────┐
│                     EKS Cluster                             │
│                                                             │
│  ┌─────────────┐     ① Mount JWT token into pod            │
│  │   kubelet   │ ──────────────────────────────────────►   │
│  └─────────────┘                                            │
│                       ┌──────────────────────────────────┐  │
│                       │  Pod                              │  │
│                       │  /var/run/secrets/eks.amazonaws  │  │
│                       │  .com/serviceaccount/token       │  │
│                       │                                  │  │
│                       │  AWS SDK reads this token        │  │
│                       └──────────────┬───────────────────┘  │
└──────────────────────────────────────┼──────────────────────┘
                                       │
                         ② SDK calls AWS STS with the token
                         AssumeRoleWithWebIdentity(token, roleARN)
                                       │
                                       ▼
                              ┌─────────────────┐
                              │    AWS STS      │
                              │                 │
                              │ ③ Validates     │
                              │    token with   │
                              │    OIDC         │
                              │    Provider     │
                              └────────┬────────┘
                                       │
                         ④ Returns temporary credentials
                            (AccessKeyId, SecretKey, SessionToken)
                            Valid for 1 hour, auto-refreshed
                                       │
                                       ▼
                              ┌─────────────────┐
                              │   Your App      │
                              │  calls S3,      │
                              │  DynamoDB,      │
                              │  Secrets Mgr    │
                              │  etc. using     │
                              │  temp creds     │
                              └─────────────────┘
```

### The Key Insight

Your pod never stores credentials. It gets a short-lived JWT from Kubernetes, exchanges it with AWS STS for temporary credentials (valid ~1 hour), and those credentials are auto-refreshed by the AWS SDK. If the pod is compromised, the credentials expire in at most 1 hour and can't be renewed without the JWT — which only exists inside the cluster.

---

## 3. The Four-Link Chain You Must Get Right

Every IRSA setup is exactly four links. Break one → access denied → `CrashLoopBackOff`.

```
Link 1: EKS Cluster has an OIDC provider registered in IAM
    ↓
Link 2: Kubernetes ServiceAccount has the IAM Role ARN annotation
    ↓
Link 3: IAM Role's Trust Policy allows THIS ServiceAccount to assume it
    ↓
Link 4: IAM Role has a Policy granting the specific AWS actions needed
```

Most IRSA failures are in Link 2 or Link 3 — either the annotation is missing, or the Trust Policy's `sub` condition has a typo in the namespace or service account name.

---

## 4. Setting Up IRSA — Step by Step

### Prerequisites

- An EKS cluster (any version)
- `eksctl`, `aws` CLI, and `kubectl` installed and configured
- A namespace and application already planned

### Step 1 — Enable the OIDC Provider for Your Cluster

This is a one-time setup per cluster. It registers your cluster's OIDC endpoint with AWS IAM so IAM knows to trust tokens your cluster signs.

```bash
# Check if OIDC is already enabled (look for an OIDC issuer URL)
aws eks describe-cluster \
  --name my-cluster \
  --query "cluster.identity.oidc.issuer" \
  --output text
# Example output: https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B716D3041E

# Associate the OIDC provider with IAM (one-time per cluster)
eksctl utils associate-iam-oidc-provider \
  --cluster my-cluster \
  --region us-east-1 \
  --approve

# Verify: you should now see the provider listed
aws iam list-open-id-connect-providers
```

### Step 2 — Create the Kubernetes ServiceAccount

```yaml
# serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: production
  annotations:
    # This annotation is the binding between Kubernetes and IAM
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/my-app-role
```

```bash
kubectl apply -f serviceaccount.yaml

# Verify the annotation is there
kubectl describe serviceaccount my-app-sa -n production
# Look for: eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/my-app-role
```

### Step 3 — Create the IAM Role with the Trust Policy

First, find your OIDC provider ID (the part after `/id/`):

```bash
OIDC_ID=$(aws eks describe-cluster \
  --name my-cluster \
  --query "cluster.identity.oidc.issuer" \
  --output text | cut -d '/' -f 5)

echo $OIDC_ID
# Example: EXAMPLED539D4633E53DE1B716D3041E
```

Create the trust policy file:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION="us-east-1"

cat > trust-policy.json << EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:sub": "system:serviceaccount:production:my-app-sa",
          "oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
EOF
```

Create the IAM Role:

```bash
aws iam create-role \
  --role-name my-app-role \
  --assume-role-policy-document file://trust-policy.json \
  --description "IRSA role for my-app in production namespace"
```

### Step 4 — Attach an IAM Policy to the Role

```bash
# Attach an AWS managed policy (or create a custom one — see workloads below)
aws iam attach-role-policy \
  --role-name my-app-role \
  --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

# Or create and attach a custom least-privilege policy
aws iam put-role-policy \
  --role-name my-app-role \
  --policy-name my-app-s3-access \
  --policy-document file://my-app-policy.json
```

### Step 5 — Reference the ServiceAccount in Your Deployment

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-app
  template:
    metadata:
      labels:
        app: my-app
    spec:
      serviceAccountName: my-app-sa   # ← Critical: bind the pod to IRSA
      containers:
        - name: my-app
          image: my-app:latest
          ports:
            - containerPort: 8080
```

### Step 6 — Verify It's Working

```bash
# Exec into a running pod and confirm the token and env vars are mounted
kubectl exec -it <pod-name> -n production -- env | grep AWS
# AWS_WEB_IDENTITY_TOKEN_FILE=/var/run/secrets/eks.amazonaws.com/serviceaccount/token
# AWS_ROLE_ARN=arn:aws:iam::123456789012:role/my-app-role

# Confirm the assumed identity from inside the pod
kubectl exec -it <pod-name> -n production -- \
  aws sts get-caller-identity
# Should show the role ARN, not the node's instance profile
```

---

## 5. Real Workload #1 — Reading Secrets from AWS Secrets Manager

**The scenario:** A FastAPI service needs database credentials stored in AWS Secrets Manager. No credentials should live in Kubernetes Secrets or environment variables.

### IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadAppSecrets",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret"
      ],
      "Resource": [
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:production/my-app/db-credentials-*"
      ]
    }
  ]
}
```

> **Why the `-*` suffix?** Secrets Manager appends a random 6-character suffix to every secret ARN (e.g., `db-credentials-AbCdEf`). Without the wildcard, the ARN won't match and you'll get an AccessDeniedException even though the secret name looks right.

### Kubernetes Resources

```yaml
# serviceaccount.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: api-sa
  namespace: production
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/api-secrets-role

---
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: production
spec:
  replicas: 3
  template:
    spec:
      serviceAccountName: api-sa
      containers:
        - name: api
          image: my-api:latest
          # No AWS credentials anywhere in here — IRSA handles it
```

### Python Application Code

```python
import boto3
import json
import sys
from functools import lru_cache
from botocore.exceptions import ClientError


@lru_cache(maxsize=None)
def get_secret(secret_name: str, region: str = "us-east-1") -> dict:
    """
    Fetch a secret from AWS Secrets Manager.
    Cached per process — secrets are fetched once at startup.
    IRSA provides the credentials automatically via the mounted token.
    """
    client = boto3.client("secretsmanager", region_name=region)

    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "AccessDeniedException":
            print(
                f"FATAL: AccessDeniedException fetching '{secret_name}'. "
                f"Check IRSA — IAM role may be missing secretsmanager:GetSecretValue "
                f"on this resource ARN."
            )
        elif error_code == "ResourceNotFoundException":
            print(f"FATAL: Secret '{secret_name}' not found in Secrets Manager.")
        else:
            print(f"FATAL: Unexpected error fetching secret: {e}")
        sys.exit(1)


def get_db_config() -> dict:
    """Return DB connection params from Secrets Manager."""
    return get_secret("production/my-app/db-credentials")


# At startup: fetch and validate before accepting traffic
if __name__ == "__main__":
    db = get_db_config()
    print(f"[STARTUP] DB config loaded — host: {db['host']}, db: {db['db_name']}")
```

### What Happens Under the Hood

When your Python code calls `boto3.client("secretsmanager")`, the AWS SDK:

1. Detects `AWS_WEB_IDENTITY_TOKEN_FILE` and `AWS_ROLE_ARN` environment variables (auto-injected by EKS because of the SA annotation)
2. Reads the JWT from the mounted file path
3. Calls `sts:AssumeRoleWithWebIdentity` with that token
4. Receives temporary credentials (AccessKey, SecretKey, SessionToken) valid for 1 hour
5. Uses those credentials to call Secrets Manager
6. Auto-refreshes the credentials before they expire — you never manage this

**You wrote zero credential-management code.** The SDK, EKS, and IAM handle everything.

---

## 6. Real Workload #2 — A FastAPI App Reading and Writing to S3

**The scenario:** A document processing API that accepts file uploads, stores them in S3, and reads processed results back. Needs `s3:PutObject` and `s3:GetObject` on a specific bucket. No `s3:DeleteObject`, no other buckets.

### IAM Policy (Least Privilege)

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadWriteAppBucket",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:GetObjectTagging",
        "s3:PutObjectTagging"
      ],
      "Resource": "arn:aws:s3:::my-app-documents-prod/*"
    },
    {
      "Sid": "ListAppBucket",
      "Effect": "Allow",
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": "arn:aws:s3:::my-app-documents-prod"
    }
  ]
}
```

> **Note the two separate statements:** `s3:ListBucket` applies to the bucket ARN (no `/*`), while `s3:GetObject` and `s3:PutObject` apply to objects inside the bucket (with `/*`). This is a common IAM mistake — putting both on `/*` will break `ListBucket`.

### Kubernetes Resources

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: document-api-sa
  namespace: production
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/document-api-s3-role

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: document-api
  namespace: production
spec:
  replicas: 3
  template:
    spec:
      serviceAccountName: document-api-sa
      containers:
        - name: api
          image: document-api:latest
          resources:
            requests:
              cpu: "250m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
```

### Python Application Code

```python
import boto3
import uuid
from fastapi import FastAPI, UploadFile, HTTPException
from botocore.exceptions import ClientError

app = FastAPI()

# boto3 automatically uses IRSA credentials — no configuration needed
s3 = boto3.client("s3", region_name="us-east-1")
BUCKET = "my-app-documents-prod"


@app.post("/upload")
async def upload_document(file: UploadFile):
    """Upload a document to S3. IRSA provides s3:PutObject access."""
    object_key = f"uploads/{uuid.uuid4()}/{file.filename}"

    try:
        contents = await file.read()
        s3.put_object(
            Bucket=BUCKET,
            Key=object_key,
            Body=contents,
            ContentType=file.content_type,
        )
        return {"key": object_key, "bucket": BUCKET}

    except ClientError as e:
        if e.response["Error"]["Code"] == "AccessDenied":
            # This means IRSA is misconfigured or the policy is missing PutObject
            raise HTTPException(
                status_code=500,
                detail="S3 access denied. Check IRSA role policy for s3:PutObject."
            )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/document/{object_key:path}")
async def get_document(object_key: str):
    """Download a document from S3. IRSA provides s3:GetObject access."""
    try:
        response = s3.get_object(Bucket=BUCKET, Key=object_key)
        return {
            "key": object_key,
            "size": response["ContentLength"],
            "content_type": response["ContentType"],
        }
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            raise HTTPException(status_code=404, detail="Document not found")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents")
async def list_documents(prefix: str = "uploads/"):
    """List documents in S3. IRSA provides s3:ListBucket access."""
    try:
        response = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
        objects = [obj["Key"] for obj in response.get("Contents", [])]
        return {"objects": objects, "count": len(objects)}
    except ClientError as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Important: Different Pods, Different Roles

If you also run a batch processing job that only *reads* from S3, give it its own ServiceAccount with a read-only policy:

```yaml
# batch processor gets read-only S3 access — separate role, separate SA
apiVersion: v1
kind: ServiceAccount
metadata:
  name: batch-processor-sa
  namespace: production
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/batch-s3-readonly-role
```

This is the security principle of **least privilege per workload** — something that's impossible with node-level IAM roles.

---

## 7. Real Workload #3 — A Worker Pod Publishing to SQS and Writing to DynamoDB

**The scenario:** An event-processing worker that consumes from SQS, processes messages, and writes results to a DynamoDB table. This is a common pattern for async background jobs on EKS.

### IAM Policy

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "SQSWorkerAccess",
      "Effect": "Allow",
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:GetQueueAttributes",
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:us-east-1:123456789012:my-app-events"
    },
    {
      "Sid": "DynamoDBWriteResults",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:GetItem"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:123456789012:table/ProcessingResults"
    }
  ]
}
```

### Kubernetes Resources

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: event-worker-sa
  namespace: production
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/event-worker-role

---
# Workers run as a Deployment — scale replicas based on queue depth
apiVersion: apps/v1
kind: Deployment
metadata:
  name: event-worker
  namespace: production
spec:
  replicas: 5    # Multiple workers, each with their own IRSA identity
  template:
    spec:
      serviceAccountName: event-worker-sa
      containers:
        - name: worker
          image: event-worker:latest
          env:
            - name: SQS_QUEUE_URL
              value: "https://sqs.us-east-1.amazonaws.com/123456789012/my-app-events"
            - name: DYNAMODB_TABLE
              value: "ProcessingResults"
            - name: AWS_REGION
              value: "us-east-1"
```

### Python Worker Code

```python
import boto3
import json
import os
import time
import logging
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# IRSA provides credentials automatically — just specify region
sqs = boto3.client("sqs", region_name=os.environ["AWS_REGION"])
dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])

QUEUE_URL = os.environ["SQS_QUEUE_URL"]
TABLE_NAME = os.environ["DYNAMODB_TABLE"]
table = dynamodb.Table(TABLE_NAME)


def process_message(message: dict) -> dict:
    """Your business logic here."""
    body = json.loads(message["Body"])
    # ... process the event ...
    return {"event_id": body["id"], "status": "processed"}


def write_result(result: dict) -> None:
    """Write processing result to DynamoDB. IRSA provides dynamodb:PutItem."""
    table.put_item(Item=result)
    logger.info(f"Wrote result for event_id={result['event_id']}")


def run_worker():
    """Main poll loop — runs indefinitely in the container."""
    logger.info(f"Worker started. Polling {QUEUE_URL}")

    while True:
        try:
            response = sqs.receive_message(
                QueueUrl=QUEUE_URL,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=20,        # Long polling — cheaper, more efficient
                VisibilityTimeout=300,     # 5 min processing window before re-delivery
            )

            messages = response.get("Messages", [])
            if not messages:
                continue

            for message in messages:
                try:
                    result = process_message(message)
                    write_result(result)

                    # Delete from SQS only after successful processing
                    sqs.delete_message(
                        QueueUrl=QUEUE_URL,
                        ReceiptHandle=message["ReceiptHandle"],
                    )
                    logger.info(f"Processed and deleted message {message['MessageId']}")

                except Exception as e:
                    # Don't delete — let it become visible again for retry
                    logger.error(f"Failed to process message {message['MessageId']}: {e}")

        except ClientError as e:
            logger.error(f"SQS polling error: {e}")
            time.sleep(5)  # Back off on AWS API errors


if __name__ == "__main__":
    run_worker()
```

### A Note on KEDA for Auto-Scaling Workers

If you're running workers like this, consider **KEDA (Kubernetes Event-Driven Autoscaling)** to scale the Deployment based on SQS queue depth:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: event-worker-scaler
  namespace: production
spec:
  scaleTargetRef:
    name: event-worker
  minReplicaCount: 1
  maxReplicaCount: 50
  triggers:
    - type: aws-sqs-queue
      authenticationRef:
        name: keda-irsa-auth        # KEDA also uses IRSA!
      metadata:
        queueURL: https://sqs.us-east-1.amazonaws.com/123456789012/my-app-events
        queueLength: "10"           # Target: 10 messages per worker replica
        awsRegion: us-east-1
```

KEDA itself needs an IRSA role with `sqs:GetQueueAttributes` to read queue depth. Yes — even your autoscaler has its own IRSA identity.

---

## 8. Real Workload #4 — Cluster Autoscaler and Karpenter (System-Level IRSA)

IRSA isn't just for your applications. EKS system components like Cluster Autoscaler, Karpenter, the AWS Load Balancer Controller, and ExternalDNS all use IRSA to perform their AWS-level operations.

### Cluster Autoscaler IRSA Setup

Cluster Autoscaler needs to describe, scale, and tag Auto Scaling Groups:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "autoscaling:DescribeAutoScalingGroups",
        "autoscaling:DescribeAutoScalingInstances",
        "autoscaling:DescribeLaunchConfigurations",
        "autoscaling:DescribeScalingActivities",
        "autoscaling:DescribeTags",
        "autoscaling:SetDesiredCapacity",
        "autoscaling:TerminateInstanceInAutoScalingGroup",
        "ec2:DescribeImages",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeLaunchTemplateVersions",
        "ec2:GetInstanceTypesFromInstanceRequirements",
        "eks:DescribeNodegroup"
      ],
      "Resource": "*"
    }
  ]
}
```

```yaml
# Cluster Autoscaler ServiceAccount (deployed to kube-system)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: cluster-autoscaler
  namespace: kube-system
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/cluster-autoscaler-role
```

### Karpenter IRSA Setup

Karpenter has a broader permission set because it provisions EC2 instances directly:

```bash
# eksctl makes Karpenter IRSA setup straightforward
eksctl create iamserviceaccount \
  --cluster my-cluster \
  --name karpenter \
  --namespace karpenter \
  --role-name karpenter-role \
  --attach-policy-arn arn:aws:iam::123456789012:policy/KarpenterControllerPolicy \
  --approve
```

### AWS Load Balancer Controller

The LBC needs to create and manage ALBs and NLBs for your Ingress and Service resources:

```bash
# Create the IRSA for AWS Load Balancer Controller
eksctl create iamserviceaccount \
  --cluster my-cluster \
  --namespace kube-system \
  --name aws-load-balancer-controller \
  --role-name AmazonEKSLoadBalancerControllerRole \
  --attach-policy-arn arn:aws:iam::123456789012:policy/AWSLoadBalancerControllerIAMPolicy \
  --approve
```

> **Pattern recognition:** Any EKS addon that manages AWS resources will need its own IRSA role. This is the standard pattern — each component gets a scoped identity, not a catch-all admin role.

---

## 9. Common IRSA Mistakes and How to Diagnose Them

### Mistake #1 — Missing ServiceAccount Annotation

**Symptom:** `NoCredentialsError: Unable to locate credentials`

The pod uses the default service account, which has no IAM role annotation. The SDK finds no IRSA token, no instance profile (if IMDSv2 is restricted), and fails.

```bash
# Diagnose: check the SA annotation
kubectl describe serviceaccount <sa-name> -n <namespace>
# Missing: eks.amazonaws.com/role-arn annotation

# Fix: add the annotation
kubectl annotate serviceaccount <sa-name> \
  -n <namespace> \
  eks.amazonaws.com/role-arn=arn:aws:iam::123456789012:role/my-role
```

---

### Mistake #2 — Wrong Namespace or SA Name in Trust Policy

**Symptom:** `AccessDeniedException` even though the role exists and has the right policy

The Trust Policy `sub` condition is an exact string match. A single character off — wrong namespace, wrong SA name, extra space — and the `AssumeRoleWithWebIdentity` call fails.

```json
// ❌ Wrong: namespace typo, SA name doesn't match what's actually deployed
"StringEquals": {
  "oidc.eks...id/OIDC_ID:sub": "system:serviceaccount:producton:my-app"
                                                              ↑ typo
}

// ✅ Correct
"StringEquals": {
  "oidc.eks...id/OIDC_ID:sub": "system:serviceaccount:production:my-app-sa"
}
```

```bash
# Diagnose: confirm the exact namespace and SA name that are deployed
kubectl get serviceaccount -n production
# Use the exact names you see here in your trust policy

# Verify the trust policy's sub condition
aws iam get-role \
  --role-name my-app-role \
  --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'
```

---

### Mistake #3 — Deployment Not Referencing the ServiceAccount

**Symptom:** IRSA is configured perfectly, but the pod still gets `NoCredentialsError`

The pod is using the `default` service account because `serviceAccountName` was never set in the Deployment spec.

```bash
# Diagnose: check what SA the pod is actually using
kubectl describe pod <pod-name> -n <namespace> | grep "Service Account"
# If it shows "default" instead of your IRSA SA → this is the problem

# Fix: add serviceAccountName to your Deployment spec
spec:
  template:
    spec:
      serviceAccountName: my-app-sa   # ← This is required
```

---

### Mistake #4 — Secrets Manager ARN Wildcard Missing

**Symptom:** `AccessDeniedException` specifically for `secretsmanager:GetSecretValue`

```bash
# What the secret ARN looks like in the console:
arn:aws:secretsmanager:us-east-1:123456789012:secret:production/db-creds-AbCdEf

# ❌ Wrong: exact ARN without suffix wildcard
"Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:production/db-creds"

# ✅ Correct: wildcard matches the auto-appended suffix
"Resource": "arn:aws:secretsmanager:us-east-1:123456789012:secret:production/db-creds-*"
```

---

### Mistake #5 — OIDC Provider Not Registered

**Symptom:** `An error occurred (InvalidIdentityToken): No OpenIDConnect provider found in your account for oidc.eks...`

```bash
# Diagnose: check if the OIDC provider is registered
aws iam list-open-id-connect-providers

# If the cluster's OIDC URL isn't in the list:
eksctl utils associate-iam-oidc-provider \
  --cluster my-cluster \
  --region us-east-1 \
  --approve
```

---

### The Full Diagnostic Runbook

When IRSA isn't working, run through these in order:

```bash
# 1. What error is the app getting?
kubectl logs <pod> --previous -n <ns>

# 2. What SA is the pod actually using?
kubectl describe pod <pod> -n <ns> | grep "Service Account"

# 3. Does that SA have the IRSA annotation?
kubectl describe sa <sa-name> -n <ns> | grep role-arn

# 4. Does the IAM Role exist?
aws iam get-role --role-name <role-name>

# 5. Is the Trust Policy's sub condition exactly right?
aws iam get-role \
  --role-name <role-name> \
  --query 'Role.AssumeRolePolicyDocument' \
  --output json

# 6. Does the role have the right policies?
aws iam list-attached-role-policies --role-name <role-name>
aws iam list-role-policies --role-name <role-name>

# 7. Simulate the exact permission to verify
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::ACCOUNT:role/ROLE_NAME \
  --action-names secretsmanager:GetSecretValue \
  --resource-arns arn:aws:secretsmanager:REGION:ACCOUNT:secret:MY_SECRET-*

# 8. From inside the pod — what identity does AWS see?
kubectl exec -it <pod> -n <ns> -- aws sts get-caller-identity
# If this shows the node's instance profile → IRSA isn't being picked up
# If this shows your role ARN → IRSA is working, check the policy
```

---

## 10. IRSA vs Other Auth Methods — When to Use What

| Method | How It Works | Use When | Avoid When |
|---|---|---|---|
| **IRSA** | Pod-level IAM role via OIDC token | Any EKS workload needing AWS access | Running outside EKS |
| **Node IAM Role** | All pods on a node share the EC2 instance profile | Lowest-common-denominator access (IMDSv2 metadata only) | When pods need different permissions |
| **AWS Access Keys in Secrets** | Static credentials stored in Kubernetes Secrets | Local dev, non-EKS environments | Production EKS — credentials don't rotate |
| **EKS Pod Identity (newer)** | AWS-managed alternative to IRSA, simpler setup | New clusters on EKS 1.24+ | Legacy tooling that hasn't added Pod Identity support yet |
| **Secrets Store CSI Driver** | Mount Secrets Manager / Parameter Store values as files | When the app reads secrets as files, not env vars | When you want the simplest path — IRSA directly is simpler for most cases |

### IRSA vs EKS Pod Identity

AWS released **EKS Pod Identity** as a simpler alternative to IRSA in late 2023. The key differences:

| | IRSA | EKS Pod Identity |
|---|---|---|
| Setup | Manual OIDC + Trust Policy | One `aws eks create-pod-identity-association` command |
| Trust Policy | Required — must match namespace + SA exactly | Not needed — managed by EKS |
| Cross-account | Supported | Not supported (as of mid-2025) |
| Maturity | Battle-tested since 2019 | Newer — check addon support |
| Token expiry | Configurable (default 1hr) | Managed by EKS |

For new clusters, evaluate Pod Identity. For existing IRSA setups, there's no urgency to migrate.

---

## 11. Quick Reference Cheatsheet

### IRSA Setup Commands

```bash
# ── ONE-TIME CLUSTER SETUP ──────────────────────────────────
# Enable OIDC provider
eksctl utils associate-iam-oidc-provider \
  --cluster <cluster> --region <region> --approve

# Get your OIDC provider ID
aws eks describe-cluster --name <cluster> \
  --query "cluster.identity.oidc.issuer" --output text | cut -d'/' -f5

# ── PER-WORKLOAD SETUP ──────────────────────────────────────
# Create ServiceAccount (or add annotation to existing)
kubectl annotate serviceaccount <sa-name> -n <ns> \
  eks.amazonaws.com/role-arn=arn:aws:iam::ACCOUNT:role/ROLE

# Create IAM role (eksctl shorthand)
eksctl create iamserviceaccount \
  --cluster <cluster> \
  --namespace <ns> \
  --name <sa-name> \
  --role-name <role-name> \
  --attach-policy-arn <policy-arn> \
  --approve

# ── VERIFICATION ────────────────────────────────────────────
# Confirm SA annotation
kubectl describe sa <sa-name> -n <ns> | grep role-arn

# Confirm pod identity from inside the container
kubectl exec -it <pod> -n <ns> -- aws sts get-caller-identity

# Check env vars injected by EKS (IRSA is working if these exist)
kubectl exec -it <pod> -n <ns> -- env | grep AWS_

# Simulate IAM permissions before deploying
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::ACCOUNT:role/ROLE \
  --action-names <action> \
  --resource-arns <resource-arn>
```

### Trust Policy Template

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/oidc.eks.REGION.amazonaws.com/id/OIDC_ID"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "oidc.eks.REGION.amazonaws.com/id/OIDC_ID:sub": "system:serviceaccount:NAMESPACE:SA_NAME",
        "oidc.eks.REGION.amazonaws.com/id/OIDC_ID:aud": "sts.amazonaws.com"
      }
    }
  }]
}
```

### Common IAM Policy Gotchas

| Service | Common Mistake | Fix |
|---|---|---|
| Secrets Manager | ARN without `-*` suffix wildcard | Add `-*` to all Secrets Manager resource ARNs |
| S3 ListBucket | Putting `s3:ListBucket` on `bucket/*` | `ListBucket` goes on `bucket`, `GetObject`/`PutObject` on `bucket/*` |
| DynamoDB index | Forgetting GSI ARN | Add `table/TableName/index/*` for queries on Global Secondary Indexes |
| SQS | Missing `GetQueueAttributes` | Required for queue depth checks; add alongside `ReceiveMessage` |
| KMS | Forgetting `kms:GenerateDataKey` | Required alongside `kms:Decrypt` when using SSE on S3 or DynamoDB |

### Error → Root Cause Quick Lookup

| Error | Root Cause | Fix |
|---|---|---|
| `NoCredentialsError` | SA annotation missing, or `serviceAccountName` not set in Deployment | Add annotation; set `serviceAccountName` |
| `AccessDeniedException` | Policy missing the action, or wrong resource ARN | Check attached policies; verify resource ARN |
| `InvalidIdentityToken` | OIDC provider not registered | Run `associate-iam-oidc-provider` |
| `AccessDenied` on `AssumeRoleWithWebIdentity` | Trust policy `sub` condition mismatch | Verify namespace and SA name in trust policy exactly |
| `ResourceNotFoundException` (Secrets Mgr) | Secret doesn't exist, or wrong region | Verify secret name and region |

---

> 💡 **Found this useful?** Star the repo at [`sandeepk24/learn-devops-playbook`](https://github.com/sandeepk24/learn-devops-playbook) and share it with your team.
> Battle-tested a pattern that isn't here? Open a PR.

---

*Part of the **Learn DevOps Playbook** series — production-grade references for engineers who'd rather fix it than Google it.*
