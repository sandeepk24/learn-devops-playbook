# 🔁 CrashLoopBackOff on EKS — Part 2: Advanced Causes & Production Prevention

> _"You checked the logs. The app looks fine. The pod still crashes. This is Part 2 territory."_

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Series:** CrashLoopBackOff on EKS · Part 2 of 2
**Tags:** `#Kubernetes` `#EKS` `#AWS` `#IRSA` `#Production` `#Intermediate`

> 📌 **New here?** Start with [Part 1](./crashloopbackoff-part1-foundations.md) which covers what CrashLoopBackOff is, the exponential backoff mechanic, your first five diagnostic commands, and the five most common app-level causes.

---

## Table of Contents

1. [Quick Recap from Part 1](#1-quick-recap-from-part-1)
2. [Cause #6 — Init Container Failures](#2-cause-6--init-container-failures)
3. [Cause #7 — Insufficient Node Resources on EKS](#3-cause-7--insufficient-node-resources-on-eks)
4. [Cause #8 — IAM / IRSA Permission Failures (EKS-Specific)](#4-cause-8--iam--irsa-permission-failures-eks-specific)
5. [Cause #9 — Dependency Not Ready (DB, API, Cache)](#5-cause-9--dependency-not-ready-db-api-cache)
6. [Cause #10 — Filesystem & Volume Mount Issues](#6-cause-10--filesystem--volume-mount-issues)
7. [The CrashLoopBackOff Decision Tree](#7-the-crashloopbackoff-decision-tree)
8. [Production Prevention Checklist](#8-production-prevention-checklist)
9. [Full Quick Reference Cheatsheet](#9-full-quick-reference-cheatsheet)

---

## 1. Quick Recap from Part 1

Before we get into the advanced causes, here's a fast summary of what Part 1 covered and the diagnostic commands you always start with:

```bash
# Always run these first — in this order
kubectl get pods -n <namespace>
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace>
kubectl logs <pod-name> --previous -n <namespace>   # ← most useful
kubectl describe node <node-name>
```

**Part 1 causes (app-level):**

| # | Cause | Fastest Signal |
|---|---|---|
| 1 | App crash on startup | Stack trace in `--previous` logs |
| 2 | Missing ConfigMap / Secret | `CreateContainerConfigError` event |
| 3 | Liveness probe misconfigured | `Liveness probe failed` event |
| 4 | OOMKilled | `Exit Code: 137` |
| 5 | Bad container image / entrypoint | `Exit Code: 126 / 127` |

**Part 2 covers the causes that are harder to spot** — they require understanding Kubernetes internals, EKS-specific AWS behavior, and distributed systems patterns.

---

## 2. Cause #6 — Init Container Failures

**How hard to debug:** ⭐⭐ Easy-Medium (once you know init containers exist)
**How often it happens:** Medium — very common in database-backed services

### What's Happening

Init containers run **before** your main container starts. They're commonly used for:
- Running database migrations
- Waiting for a service (DB, cache) to be reachable
- Seeding config files or certificates

If an init container exits with a non-zero code, Kubernetes **never starts your main container**. Instead, it keeps retrying the init container — producing `CrashLoopBackOff`.

The tricky part: your main application logs will be empty. People spend 20 minutes debugging the wrong thing because they don't realize init containers exist.

### How to Spot It

```bash
kubectl describe pod <pod-name> -n <namespace>
```

Look for the `Init Containers:` section:

```
Init Containers:
  db-migrate:
    State:      Terminated
    Reason:     Error
    Exit Code:  1
    ...
Containers:
  my-app:
    State:      Waiting
    Reason:     PodInitializing      ← main container never started
```

Then fetch logs from the init container specifically:

```bash
# Current attempt
kubectl logs <pod-name> -c db-migrate -n <namespace>

# Previous (crashed) attempt
kubectl logs <pod-name> -c db-migrate --previous -n <namespace>
```

### Example: DB Migration Init Container

```yaml
initContainers:
  - name: db-migrate
    image: my-app:latest
    command: ["python", "manage.py", "migrate"]
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: db-credentials
            key: database_url
```

If the database isn't reachable yet, this init container fails, and your app never gets a chance to start.

### The Fix: Add a Wait-for Gate Before the Migration

```yaml
initContainers:
  # Step 1: Wait until the DB port is open
  - name: wait-for-db
    image: busybox:1.35
    command:
      - sh
      - -c
      - |
        until nc -z postgres-service 5432; do
          echo "Waiting for PostgreSQL at postgres-service:5432..."
          sleep 3
        done
        echo "PostgreSQL is up — proceeding."

  # Step 2: Run migrations only after DB is confirmed reachable
  - name: db-migrate
    image: my-app:latest
    command: ["python", "manage.py", "migrate"]
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: db-credentials
            key: database_url
```

**Why two init containers instead of one?** Each does one job. The wait gate is generic and reusable. The migration step stays clean. If the migration fails, you know the DB was reachable — it's an application-level failure, not a connectivity failure.

---

## 3. Cause #7 — Insufficient Node Resources on EKS

**How hard to debug:** ⭐⭐⭐ Medium-Hard
**How often it happens:** Medium — more common in cost-optimized or auto-scaling clusters

### What's Happening

This is different from OOMKilled (where *your container* exceeds its memory limit). Here, the **node itself** is under memory or disk pressure. The kubelet's eviction manager starts forcibly terminating pods to reclaim resources on the node, and your pod gets evicted, restarts, potentially lands on the same stressed node, and cycles again.

### How to Spot It

```bash
kubectl describe node <node-name> | grep -A 10 "Conditions:"
```

Watch for these node conditions:

```
MemoryPressure=True    ← Node is running out of RAM
DiskPressure=True      ← Node is running out of disk space
PIDPressure=True       ← Node is running out of process IDs
```

Also check what's consuming the most resources:

```bash
# Which pods are using the most memory across the cluster?
kubectl top pods --all-namespaces --sort-by=memory | head -20
```

### The EKS Cluster Autoscaler Gotcha

If you're using Cluster Autoscaler (CAS) or Karpenter, here's a critical thing to understand:

> **Cluster Autoscaler does NOT scale up for `CrashLoopBackOff` pods.**

CAS only adds nodes when pods are in `Pending` state (can't be scheduled). A pod that keeps crashing but *does* get scheduled somewhere looks fine to CAS — it won't trigger scale-out. You have to fix the root cause.

```bash
# Is autoscaler doing anything at all?
kubectl logs -n kube-system deployment/cluster-autoscaler --tail=50

# Are there any pods stuck in Pending? (those DO trigger CAS)
kubectl get pods --all-namespaces | grep Pending
```

### The Fix

```yaml
# Set accurate resource requests so the scheduler places pods on nodes that can support them
resources:
  requests:
    cpu: "500m"       # 0.5 core reserved on the node
    memory: "512Mi"   # 512MB reserved on the node
  limits:
    cpu: "1000m"
    memory: "1Gi"
```

```yaml
# Use a PodDisruptionBudget to protect critical workloads from eviction
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: my-app-pdb
  namespace: production
spec:
  minAvailable: 1       # Always keep at least 1 replica running
  selector:
    matchLabels:
      app: my-app
```

> **Why `requests` matter so much:** Without them, the scheduler may place too many pods on the same node. When real load hits, they compete for the same limited RAM and one of them gets evicted. Requests are a *promise to the scheduler* — they're what make placement decisions reliable.

---

## 4. Cause #8 — IAM / IRSA Permission Failures (EKS-Specific)

**How hard to debug:** ⭐⭐⭐⭐ Hard
**How often it happens:** Very common on EKS — this is the EKS-specialist root cause

### What's Happening

**IRSA (IAM Roles for Service Accounts)** is how pods on EKS authenticate to AWS services — S3, DynamoDB, Secrets Manager, SQS, Parameter Store, and so on. It works by binding an IAM Role to a Kubernetes ServiceAccount using an OIDC token.

If anything in that binding is wrong, your app calls the AWS SDK, gets an `AccessDeniedException`, and crashes.

### The IRSA Chain — Every Link Must Be Correct

```
Your Pod
  └── ServiceAccount           (must exist, must have the IAM role annotation)
        └── IAM Role           (must have a Trust Policy allowing this exact SA to assume it)
              └── IAM Policy   (must grant the specific actions your app needs)
```

Break any one of these four links → `CrashLoopBackOff`.

### How to Spot It

```bash
kubectl logs <pod-name> --previous -n <namespace>
```

**If IRSA is set up but permissions are wrong:**
```
botocore.exceptions.ClientError: An error occurred (AccessDeniedException)
  when calling the GetSecretValue operation: User: arn:aws:sts::123456789:assumed-role/my-role
  is not authorized to perform: secretsmanager:GetSecretValue on resource: my-secret
```

**If IRSA isn't configured at all** (pod uses node instance profile, which has no app permissions):
```
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

### The Diagnostic Checklist

```bash
# Step 1: Does the ServiceAccount exist?
kubectl get serviceaccount <sa-name> -n <namespace>

# Step 2: Does it have the IRSA annotation?
kubectl describe serviceaccount <sa-name> -n <namespace>
# You MUST see: eks.amazonaws.com/role-arn: arn:aws:iam::ACCOUNT:role/ROLE_NAME

# Step 3: Does the IAM Role's Trust Policy allow this SA to assume it?
aws iam get-role --role-name <role-name> \
  --query 'Role.AssumeRolePolicyDocument' --output json

# Step 4: What policies are attached to the role?
aws iam list-attached-role-policies --role-name <role-name>

# Step 5: Simulate a specific permission to verify it works
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::ACCOUNT:role/ROLE_NAME \
  --action-names secretsmanager:GetSecretValue \
  --resource-arns arn:aws:secretsmanager:REGION:ACCOUNT:secret:MY_SECRET
```

### What the Correct Trust Policy Looks Like

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/oidc.eks.REGION.amazonaws.com/id/OIDC_ID"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.REGION.amazonaws.com/id/OIDC_ID:sub": "system:serviceaccount:NAMESPACE:SERVICE_ACCOUNT_NAME",
          "oidc.eks.REGION.amazonaws.com/id/OIDC_ID:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
```

The `StringEquals` conditions are exact-match. If the namespace or service account name is even slightly off, the assume-role will fail silently and fall back to the node instance profile (which has no app permissions).

### The Deployment Must Reference the ServiceAccount

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      serviceAccountName: my-app-sa   # ← This is what binds the pod to IRSA
      containers:
        - name: my-app
          image: my-app:latest
```

Forgetting `serviceAccountName` means the pod uses the `default` service account, which has no IAM role → no AWS access → crash.

### Python: Validate IRSA at Startup

```python
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
import sys

def validate_aws_identity():
    """
    Call at startup to fail fast with a clear IRSA error
    rather than a cryptic crash mid-operation.
    """
    try:
        sts = boto3.client("sts")
        identity = sts.get_caller_identity()
        print(f"[STARTUP] AWS Identity confirmed: {identity['Arn']}")
    except NoCredentialsError:
        print("FATAL: No AWS credentials found. Is IRSA configured? "
              "Check ServiceAccount annotation and IAM Role trust policy.")
        sys.exit(1)
    except ClientError as e:
        print(f"FATAL: AWS access check failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    validate_aws_identity()
    # ... rest of app startup
```

---

## 5. Cause #9 — Dependency Not Ready (DB, API, Cache)

**How hard to debug:** ⭐⭐ Easy-Medium
**How often it happens:** Very common during initial deployments and after cluster restarts

### What's Happening

Your app boots, immediately tries to establish a connection to PostgreSQL, Redis, or a downstream microservice — and that service isn't ready yet. The connection fails, the app crashes before it can retry, and the restart loop begins.

This is a **race condition at deployment time**. It's especially common when:
- You deploy everything in a Helm chart at once and the DB pod hasn't finished starting
- Your cluster just restarted after maintenance and services are coming up in random order
- A downstream service is deploying and returning 503s for a few seconds

### How to Spot It

```bash
kubectl logs <pod-name> --previous -n <namespace>
```

```
# SQLAlchemy / PostgreSQL
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError)
  could not connect to server: Connection refused.
  Is the server running on host "postgres-service" and accepting TCP/IP connections on port 5432?

# Redis
redis.exceptions.ConnectionError: Error connecting to redis:6379. Connection refused.

# Generic HTTP dependency
requests.exceptions.ConnectionError: HTTPSConnectionPool: Max retries exceeded with url: /api/health
```

### Fix 1: Build Retry Logic Into Your App

Don't rely purely on Kubernetes restarts. Build resilience directly into your startup code:

```python
import time
import redis
import sys

def connect_redis(host: str, port: int, max_retries: int = 10) -> redis.Redis:
    """Connect to Redis with exponential backoff — resilient to slow starts."""
    for attempt in range(1, max_retries + 1):
        try:
            client = redis.Redis(host=host, port=port, socket_connect_timeout=5)
            client.ping()
            print(f"[STARTUP] Connected to Redis on attempt {attempt}/{max_retries}")
            return client
        except (redis.ConnectionError, redis.TimeoutError) as e:
            if attempt == max_retries:
                print(f"FATAL: Could not connect to Redis after {max_retries} attempts. Giving up.")
                sys.exit(1)
            wait = min(3.0 * (2 ** (attempt - 1)), 30.0)  # Exponential backoff, capped at 30s
            print(f"[STARTUP] Redis not ready (attempt {attempt}/{max_retries}). "
                  f"Retrying in {wait:.1f}s... Error: {e}")
            time.sleep(wait)
```

### Fix 2: Use Init Containers as Dependency Gates

```yaml
initContainers:
  - name: wait-for-redis
    image: busybox:1.35
    command:
      - sh
      - -c
      - |
        until nc -z redis-service 6379; do
          echo "Waiting for Redis at redis-service:6379..."
          sleep 3
        done
        echo "Redis is reachable."

  - name: wait-for-postgres
    image: busybox:1.35
    command:
      - sh
      - -c
      - |
        until nc -z postgres-service 5432; do
          echo "Waiting for PostgreSQL at postgres-service:5432..."
          sleep 3
        done
        echo "PostgreSQL is reachable."
```

**Which approach should you use?** Both, ideally. Init containers gate the pod from starting until dependencies are up. In-app retry logic handles transient blips during normal operation (network hiccups, rolling restarts of dependencies). They complement each other.

---

## 6. Cause #10 — Filesystem & Volume Mount Issues

**How hard to debug:** ⭐⭐⭐ Medium
**How often it happens:** Medium — surfaces more often with EFS, EBS, or custom PVCs on EKS

### What's Happening

Your pod references a volume — a PersistentVolumeClaim, a ConfigMap volume, a Secret volume — and something about that volume is broken:
- The PVC doesn't exist or isn't bound
- The volume is mounted to a path where your app expects write access but the permissions are wrong
- It's an EBS volume already attached to another node (EBS is single-node only)

### How to Spot It

```bash
kubectl describe pod <pod-name> -n <namespace>
```

Look for:
```
Warning  FailedMount  Unable to attach or mount volumes:
  MountVolume.SetUp failed for volume "app-config":
  configmap "app-config" not found

Warning  FailedAttachVolume  Multi-Attach error for volume "pvc-xyz":
  Volume is already exclusively attached to one node
```

Check PVC status:

```bash
kubectl get pvc -n <namespace>
# Status should be "Bound" — if it's "Pending", it's not provisioned yet

kubectl describe pvc <pvc-name> -n <namespace>
# Events section will tell you why it's stuck
```

### The Classic EKS Gotcha: EBS Multi-Attach

EBS volumes are **single-AZ** and can only attach to **one EC2 node at a time**. If you run a Deployment with multiple replicas backed by an EBS PVC, only one pod gets the volume. The others crash.

```yaml
# ❌ BAD: EBS PVC used with a multi-replica Deployment
kind: PersistentVolumeClaim
spec:
  storageClassName: gp3
  accessModes:
    - ReadWriteOnce        # Means: single node only

---
kind: Deployment
spec:
  replicas: 3              # 2 of these 3 pods will fail to mount the volume
```

```yaml
# ✅ OPTION 1: Use a StatefulSet for single-instance stateful workloads
kind: StatefulSet
spec:
  replicas: 1              # EBS works fine with a single replica

# ✅ OPTION 2: Use EFS for multi-pod shared storage (ReadWriteMany)
kind: PersistentVolumeClaim
spec:
  storageClassName: efs-sc
  accessModes:
    - ReadWriteMany        # Multiple pods across multiple nodes can mount this simultaneously
```

### Volume Permission Issues

If your app runs as a non-root user but the volume is owned by root, writes will fail:

```yaml
# ✅ FIX: Set fsGroup so Kubernetes chowns the volume to your app's group
spec:
  securityContext:
    fsGroup: 1000           # All files in mounted volumes will belong to group 1000
    runAsUser: 1000
    runAsGroup: 1000
  containers:
    - name: my-app
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true    # Best practice: read-only root, writable only where needed
```

---

## 7. The CrashLoopBackOff Decision Tree

Use this under pressure when you need to diagnose fast and systematically:

```
🔴 CrashLoopBackOff Detected
│
├─ STEP 1: kubectl logs <pod> --previous
│   │
│   ├─ Stack trace / Python exception?
│   │   └─ → Cause #1: App crash. Fix the code or env vars.
│   │
│   ├─ "AccessDeniedException" / "NoCredentialsError"?
│   │   └─ → Cause #8: IRSA broken. Check SA annotation + IAM trust policy.
│   │
│   ├─ "Connection refused" / "could not connect"?
│   │   └─ → Cause #9: Dependency not ready. Add retry logic or wait init containers.
│   │
│   └─ Logs are empty?
│       └─ Container never started. Go to Step 2.
│
├─ STEP 2: kubectl describe pod <pod> — check Events section
│   │
│   ├─ "secret/configmap not found" or CreateContainerConfigError?
│   │   └─ → Cause #2: Missing ConfigMap/Secret. Create it in the right namespace.
│   │
│   ├─ "Liveness probe failed"?
│   │   └─ → Cause #3: Probe misconfiguration. Fix initialDelaySeconds / timeoutSeconds.
│   │
│   ├─ "OOMKilled" or Exit Code 137?
│   │   └─ → Cause #4: Memory limit too low. Profile usage, increase limits.
│   │
│   ├─ "exec not found" or Exit Code 126/127?
│   │   └─ → Cause #5: Bad image/entrypoint. Fix Dockerfile, chmod +x, check CRLF.
│   │
│   ├─ Init container Terminated with error?
│   │   └─ → Cause #6: Init container failing. Run: kubectl logs <pod> -c <init-name> --previous
│   │
│   └─ "MountVolume.SetUp failed" or "Multi-Attach error"?
│       └─ → Cause #10: Volume issue. Check PVC status, EBS AZ, permissions.
│
└─ STEP 3: kubectl describe node <node>
    │
    └─ MemoryPressure=True or DiskPressure=True?
        └─ → Cause #7: Node resource exhaustion.
               Set resource requests, add PodDisruptionBudget, scale nodes.
```

---

## 8. Production Prevention Checklist

Copy this into your team's deployment runbook. Run it before every production release.

### ✅ Code & Application

- [ ] App logs a clear startup error before `sys.exit()` for any missing required config
- [ ] App has retry logic with exponential backoff for all external dependency connections
- [ ] No secrets or credentials hardcoded in the container image or source code
- [ ] Dockerfile uses `RUN chmod +x` for every script used as an entrypoint
- [ ] Shell scripts don't have Windows CRLF line endings
- [ ] Image is built and tested for the correct CPU architecture (AMD64 / ARM64)

### ✅ Kubernetes Configuration

- [ ] All referenced ConfigMaps and Secrets exist in the target namespace **before** deploying
- [ ] `initialDelaySeconds` on liveness probes accounts for actual measured cold-start time
- [ ] Liveness probe endpoint (`/healthz`) does **not** check external dependencies
- [ ] Readiness probe endpoint (`/ready`) is separate from liveness
- [ ] `resources.requests` and `resources.limits` are set on every container
- [ ] Init containers have dependency-wait logic before running migrations or setup tasks
- [ ] PodDisruptionBudgets are set for all production workloads with `>1` replica

### ✅ EKS-Specific

- [ ] ServiceAccount exists in the correct namespace with `eks.amazonaws.com/role-arn` annotation
- [ ] IAM Role Trust Policy uses the exact `oidc.eks...` provider and the exact `sub` condition for this namespace + SA
- [ ] IAM Policy grants only the specific actions needed (least privilege)
- [ ] Verified with `aws iam simulate-principal-policy` before deploying
- [ ] PVCs using EBS (`gp3`) use `ReadWriteOnce` and are matched with StatefulSets or single-replica deployments only
- [ ] Multi-pod shared storage uses EFS with `ReadWriteMany`
- [ ] Deployment spec explicitly sets `serviceAccountName` — never relies on `default`

### ✅ Observability

- [ ] Container Insights or Prometheus/Grafana is configured for the cluster
- [ ] CloudWatch log group is set up for application logs
- [ ] Alert configured on `kube_pod_container_status_restarts_total > threshold` per namespace
- [ ] Alert configured on node `MemoryPressure` and `DiskPressure` conditions

---

## 9. Full Quick Reference Cheatsheet

```bash
# ─────────────────────────────────────────────────────
# PART 1 & 2 COMBINED DIAGNOSTIC COMMANDS
# ─────────────────────────────────────────────────────

# Pod overview + restart count
kubectl get pods -n <ns>

# Full event log (your crime scene report)
kubectl describe pod <pod> -n <ns> | grep -A 30 "Events:"

# Logs from LAST crashed attempt ← start here
kubectl logs <pod> --previous -n <ns>

# Logs from a specific init container
kubectl logs <pod> -c <init-container-name> --previous -n <ns>

# Exit code of last termination
kubectl describe pod <pod> -n <ns> | grep "Exit Code"

# Node health — memory/disk pressure
kubectl describe node <node> | grep -A 10 "Conditions:"

# Real-time resource usage
kubectl top pods -n <ns>
kubectl top nodes

# ─────────────────────────────────────────────────────
# EKS-SPECIFIC COMMANDS
# ─────────────────────────────────────────────────────

# Confirm IRSA annotation on the ServiceAccount
kubectl describe sa <sa-name> -n <ns> | grep role-arn

# Decode a Secret value
kubectl get secret <name> -n <ns> -o jsonpath='{.data.<key>}' | base64 -d

# Check PVC binding status
kubectl get pvc -n <ns>
kubectl describe pvc <pvc-name> -n <ns>

# Check Cluster Autoscaler activity
kubectl logs -n kube-system deployment/cluster-autoscaler --tail=50

# Simulate IAM permissions for IRSA role
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::ACCOUNT:role/ROLE \
  --action-names s3:GetObject \
  --resource-arns arn:aws:s3:::my-bucket/*

# ─────────────────────────────────────────────────────
# EXIT CODE REFERENCE
# ─────────────────────────────────────────────────────
# 0   = Clean exit (shouldn't happen for a long-running service)
# 1   = Generic application error
# 126 = Entrypoint not executable (chmod +x missing)
# 127 = Entrypoint not found (bad CMD, CRLF issue)
# 132 = SIGILL — wrong CPU architecture
# 137 = OOMKilled (SIGKILL from kernel — memory limit exceeded)
# 143 = SIGTERM — graceful shutdown was requested
```

### All 10 Causes at a Glance

| # | Cause | Fastest Signal | Key Fix |
|---|---|---|---|
| 1 | App crash on startup | Stack trace in `--previous` logs | Add startup validation; fix the exception |
| 2 | Missing ConfigMap / Secret | `CreateContainerConfigError` event | Create the resource in the right namespace |
| 3 | Liveness probe misconfigured | `Liveness probe failed` event | Increase `initialDelaySeconds`; separate liveness from readiness |
| 4 | OOMKilled | `Exit Code: 137` | Profile memory; increase limits |
| 5 | Bad image / entrypoint | `Exit Code: 126 / 127` | Fix Dockerfile; `chmod +x`; strip CRLF |
| 6 | Init container failure | Init container `Terminated` in describe | Fetch init container logs; add wait gate before migration |
| 7 | Node resource exhaustion | `MemoryPressure=True` on node | Set resource requests; add PDB; scale nodes |
| 8 | IAM / IRSA misconfiguration | `AccessDeniedException` in logs | Fix SA annotation; fix IAM trust policy `sub` condition |
| 9 | Dependency not ready | `Connection refused` in logs | Add retry backoff in app; use wait init containers |
| 10 | Volume mount failure | `FailedMount` / `Multi-Attach` event | Create PVC; fix permissions; use EFS for multi-pod |

---

> 💡 **Found this useful?** Star the repo at [`sandeepk24/learn-devops-playbook`](https://github.com/sandeepk24/learn-devops-playbook) and share it with your team.
> Have a root cause I missed or a fix that worked for you? Open a PR — this guide grows with the community.

---

*Part of the **Learn DevOps Playbook** series — production-grade references for engineers who'd rather fix it than Google it.*
