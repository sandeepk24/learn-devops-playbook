# 🔁 CrashLoopBackOff on EKS — Part 1: What It Is & The 5 Most Common Causes

> _"Your pod keeps dying and you don't know why. Welcome to the club."_

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Series:** CrashLoopBackOff on EKS · Part 1 of 2
**Tags:** `#Kubernetes` `#EKS` `#DevOps` `#Debugging` `#Beginner`

> 📌 **Part 2** covers the advanced causes: Init Container failures, Node Resource exhaustion, IAM/IRSA, Dependency race conditions, and Volume mount issues → [Read Part 2](./crashloopbackoff-part2-advanced.md)

---

## Table of Contents

1. [What Even Is CrashLoopBackOff?](#1-what-even-is-crashloopbackoff)
2. [The Exponential Backoff Mechanic — Why Your Pod Waits Longer Each Time](#2-the-exponential-backoff-mechanic)
3. [Your First Five Commands](#3-your-first-five-commands)
4. [Cause #1 — Application Crash on Startup](#4-cause-1--application-crash-on-startup)
5. [Cause #2 — Missing or Misconfigured ConfigMaps & Secrets](#5-cause-2--missing-or-misconfigured-configmaps--secrets)
6. [Cause #3 — Liveness Probe Killing a Healthy Pod](#6-cause-3--liveness-probe-killing-a-healthy-pod)
7. [Cause #4 — OOMKilled — The Silent Memory Assassin](#7-cause-4--oomkilled--the-silent-memory-assassin)
8. [Cause #5 — Bad Container Image or Entrypoint](#8-cause-5--bad-container-image-or-entrypoint)
9. [Part 1 Quick Reference Cheatsheet](#9-part-1-quick-reference-cheatsheet)

---

## 1. What Even Is CrashLoopBackOff?

Let's start at the beginning — because a solid mental model makes every debug session faster.

When Kubernetes runs a container, it expects it to **start and stay running**. If your container exits for any reason, Kubernetes does what any responsible system would do: it restarts it.

But here's the twist — **Kubernetes doesn't restart it immediately every single time**. After each failed restart, it waits a bit longer before trying again. This is called **exponential backoff**. The status you see in `kubectl get pods`:

```
NAME                    READY   STATUS             RESTARTS   AGE
my-api-7d9f8b-xk2zp     0/1     CrashLoopBackOff   6          12m
```

Is Kubernetes telling you:

> _"I've tried restarting this thing multiple times, it keeps failing, and right now I'm in a cooldown period before I try again."_

Notice the `RESTARTS` column — by the time you see `CrashLoopBackOff`, it has already failed multiple times. **The crash happened earlier. The backoff is happening now.**

### Why Should You Care?

 Your app is down and not serving traffic — you need to act |
 Production incident. SLA breach risk. You need to diagnose fast. |
 Design flaw that shouldn't reach prod. Let's fix the system. |

---

## 2. The Exponential Backoff Mechanic

This is the **"BackOff"** part of `CrashLoopBackOff` — and it's actually brilliant cluster-protection design.

Kubernetes uses this restart wait schedule:

| Restart # | Wait Before Next Attempt |
|---|---|
| 1st | 10 seconds |
| 2nd | 20 seconds |
| 3rd | 40 seconds |
| 4th | 80 seconds |
| 5th+ | 160 seconds → caps at **5 minutes** |

**Why does Kubernetes do this?** Because if your app keeps crashing, hammering restarts at full speed would flood the cluster with thrash, drain CPU and memory, and potentially cascade into taking down healthy workloads on the same node. The backoff is a safety valve.

**What this means when you're debugging:** A pod deep in `CrashLoopBackOff` with a high restart count may currently be *waiting*, not actively crashing. The logs from the current attempt might be empty. Always use `--previous` to see what happened last time:

```bash
# Your most important command when the pod is in backoff
kubectl logs <pod-name> --previous -n <namespace>
```

---

## 3. Your First Five Commands

Before chasing root causes, **run these five in this exact order**. They answer 80% of what you need.

```bash
# 1. See the status and how many times it's restarted
kubectl get pods -n <namespace>

# 2. Get the full event log and last known container state
kubectl describe pod <pod-name> -n <namespace>

# 3. Logs from the CURRENT attempt (may be empty if the container never started)
kubectl logs <pod-name> -n <namespace>

# 4. Logs from the PREVIOUS crashed attempt — THIS is where the answers are
kubectl logs <pod-name> --previous -n <namespace>

# 5. On EKS: check if the node itself is under pressure
kubectl describe node <node-name>
```

**Pro tip:** Skip straight to the events section in describe:

```bash
kubectl describe pod <pod-name> -n <namespace> | grep -A 20 "Events:"
```

The **Events** section is your crime scene report. The signals to look for:

| Event Message | What It Means |
|---|---|
| `Back-off restarting failed container` | Container keeps crashing — check logs |
| `OOMKilled` | App used more memory than its limit |
| `CreateContainerConfigError` | Missing ConfigMap or Secret |
| `Liveness probe failed` | Probe is killing a pod that may actually be fine |
| `exec ... not found` | Bad entrypoint in your container image |

---

## 4. Cause #1 — Application Crash on Startup

**How hard to debug:** ⭐⭐ Easy-Medium
**How often it happens:** Very common — especially on new deployments

### What's Happening

Your application code throws an unhandled exception, hits a fatal error, or calls `sys.exit()` during initialization. The container process exits with a non-zero code, Kubernetes marks it failed, and the restart loop begins.

This is the #1 cause when you've just deployed a new version of your app.

### How to Spot It

```bash
kubectl logs <pod-name> --previous -n <namespace>
```

In Python, it typically looks like this:

```
Traceback (most recent call last):
  File "/app/main.py", line 14, in <module>
    db_url = os.environ["DATABASE_URL"]
KeyError: 'DATABASE_URL'
```

Also check the exit code — it tells you the category of the failure:

```bash
kubectl describe pod <pod-name> -n <namespace> | grep "Exit Code"
```

| Exit Code | Meaning |
|---|---|
| `1` | Generic application error |
| `126` | Entrypoint not executable (permission denied) |
| `127` | Entrypoint binary not found |
| `132` | Wrong CPU architecture (ARM vs AMD64) |
| `137` | OOMKilled — memory limit exceeded |
| `143` | SIGTERM — graceful shutdown was requested |

### Real-World Python Example

```python
# ❌ BAD: This throws a cryptic KeyError at startup if the env var is missing
import os
DATABASE_URL = os.environ["DATABASE_URL"]

app = FastAPI()
```

```python
# ✅ GOOD: Fail fast with a clear, actionable message
import os
import sys

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("FATAL: DATABASE_URL is required but not set. Check your ConfigMap or Secret.")
    sys.exit(1)

app = FastAPI()
```

**Why does this matter?** The first approach gives a Python traceback that a junior engineer will spend 20 minutes decoding. The second gives an error any engineer can act on immediately — including at 2 AM during an incident.

### The Fix

1. Read `kubectl logs <pod> --previous` and find the exception
2. Fix the code — add startup validation with clear human-readable messages
3. Rebuild the image and redeploy

---

## 5. Cause #2 — Missing or Misconfigured ConfigMaps & Secrets

**How hard to debug:** ⭐⭐ Easy-Medium
**How often it happens:** Very common — especially across multi-environment setups

### What's Happening

Your Deployment references a ConfigMap or Secret that either:
- Doesn't exist in that namespace
- Has the wrong key names
- Exists with correct keys but wrong values (expired token, wrong DB host, etc.)

### Two Flavors of This Problem

**Flavor A — The resource doesn't exist at all**

Kubernetes won't even create the container. You'll see this in `kubectl describe`:

```
Events:
  Warning  Failed  CreateContainerConfigError
  Error: secret "db-credentials" not found
```

**Flavor B — The resource exists but the value is wrong**

The pod starts. Your app reads the env var, tries to connect with a stale password or wrong URL, and crashes. Now you're in `CrashLoopBackOff` with a generic connection error in the logs.

### How to Spot It

```bash
# Does the ConfigMap/Secret actually exist?
kubectl get configmap <name> -n <namespace>
kubectl get secret <name> -n <namespace>

# What keys are inside a ConfigMap?
kubectl describe configmap <name> -n <namespace>

# What's the actual value in a Secret? (decode base64)
kubectl get secret <name> -n <namespace> \
  -o jsonpath='{.data.DATABASE_URL}' | base64 -d
```

### Example: The YAML That Causes This

```yaml
# If this Secret doesn't exist, or the key 'database_url' is wrong → pod won't start
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: db-credentials    # Secret must exist in this namespace
        key: database_url       # This exact key must exist inside the Secret
        optional: false         # Default — pod won't start if this is missing
```

### The Fix

```bash
# Create the missing Secret
kubectl create secret generic db-credentials \
  --from-literal=database_url="postgresql://user:pass@host:5432/mydb" \
  -n <namespace>
```

```yaml
# If the env var is truly optional, mark it so
env:
  - name: FEATURE_FLAG
    valueFrom:
      configMapKeyRef:
        name: feature-flags
        key: enable_new_ui
        optional: true    # Pod starts even if configmap/key is missing
```

> **EKS note:** If you use AWS Secrets Manager via the Secrets Store CSI Driver, make sure the `SecretProviderClass` is deployed in the right namespace and the pod's IAM role has `secretsmanager:GetSecretValue` permission on the correct ARN.

---

## 6. Cause #3 — Liveness Probe Killing a Healthy Pod

**How hard to debug:** ⭐⭐⭐ Medium-Hard
**How often it happens:** Common — especially with copy-pasted probe configs

### What's Happening

This one is the most insidious cause in this list — **your application is actually working**, but Kubernetes keeps killing and restarting it because you told it to.

A liveness probe is meant to detect if your app is deadlocked or frozen. If it fails, Kubernetes restarts the container. But a misconfigured probe will restart pods that are **perfectly healthy**.

### The Three Most Common Probe Mistakes

**Mistake 1: `initialDelaySeconds` too short**

Your app takes 45 seconds to warm up (loading ML models, running DB migrations, etc.), but the probe starts checking at 5 seconds. Kubernetes sees a failure and kills the container before it's even ready.

```yaml
# ❌ BAD: Probe fires at 5s, app isn't ready until 45s
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 10
  failureThreshold: 3
```

**Mistake 2: `timeoutSeconds` too tight**

Your `/health` endpoint calls a downstream service and regularly takes 3 seconds, but your probe timeout is 1 second. Kubernetes sees repeated "failures" on a perfectly alive container.

```yaml
# ❌ BAD: 1s timeout on an endpoint that takes 3s to respond
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 30
  timeoutSeconds: 1        # Far too tight
  failureThreshold: 3
```

**Mistake 3: Liveness probe checks external dependencies**

Your `/health` endpoint pings your database or a downstream API. If that dependency has a momentary blip, Kubernetes kills your pod — even though your app itself is fine.

### How to Spot It

```bash
kubectl describe pod <pod-name> -n <namespace> | grep -A 5 "Events:"
```

You'll see:
```
Warning  Unhealthy  Liveness probe failed: HTTP probe failed with statuscode: 500
Warning  Killing    Container killed on liveness probe failure
```

### The Fix: Separate Liveness from Readiness

```yaml
# ✅ CORRECT: Two separate probes with two separate jobs
livenessProbe:
  httpGet:
    path: /healthz        # Simple — just confirms the process is alive
    port: 8080
  initialDelaySeconds: 60  # Generous — account for real boot time
  periodSeconds: 15
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /ready          # Confirms the app can serve traffic (can check deps)
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 5
  failureThreshold: 3
```

### The Golden Rule

| Probe | Job | Should It Check External Deps? |
|---|---|---|
| **Liveness** | Is the process alive and not deadlocked? | ❌ Never |
| **Readiness** | Is the app ready to receive traffic? | ✅ Yes |

### Python: Designing the Right Health Endpoints

```python
from fastapi import FastAPI, HTTPException, Depends

app = FastAPI()

@app.get("/healthz")
def liveness():
    """
    Liveness: Is this process running?
    Keep it dead simple. Never check databases, caches, or external APIs here.
    """
    return {"status": "alive"}

@app.get("/ready")
def readiness(db=Depends(get_db)):
    """
    Readiness: Can this pod serve traffic right now?
    It's fine to check dependencies here — if they're down, we remove this pod
    from the load balancer (readiness), but we don't kill it (liveness).
    """
    try:
        db.execute("SELECT 1")
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Database not reachable")
```

---

## 7. Cause #4 — OOMKilled — The Silent Memory Assassin

**How hard to debug:** ⭐⭐ Easy (once you know the exit code)
**How often it happens:** Very common in data-heavy or ML workloads

### What's Happening

You set a memory `limit` on your container. Your app exceeded it. The Linux kernel sent `SIGKILL` (exit code 137). This is not a Kubernetes bug — it's the OS protecting other pods on the same node from a runaway process.

### How to Spot It

```bash
kubectl describe pod <pod-name> -n <namespace> | grep -A 5 "Last State"
```

Output:
```
Last State:   Terminated
  Reason:     OOMKilled
  Exit Code:  137
```

```bash
# Real-time memory usage across pods
kubectl top pods -n <namespace>
kubectl top nodes
```

### Why Memory Limits Are Tricky in Python

Python's memory allocator and garbage collector don't always release memory back to the OS immediately. Libraries like `pandas`, `numpy`, PyTorch, and large Pydantic models can spike memory unexpectedly under load. Setting limits too tight is a very common mistake.

```yaml
# ❌ TOO TIGHT: Will OOMKill a Python app loading any real data
resources:
  requests:
    memory: "128Mi"
  limits:
    memory: "256Mi"

# ✅ MORE REALISTIC: Give real headroom
resources:
  requests:
    memory: "512Mi"   # What the app uses at baseline
  limits:
    memory: "1Gi"     # Ceiling — room for traffic spikes
```

### The Fix Strategy

1. Remove the memory limit temporarily (or set it very high)
2. Run realistic load through your app
3. Observe actual peak usage with `kubectl top pods`
4. Set `requests` to average usage, `limits` to ~2x the peak

> **EKS tip:** Enable Container Insights to get per-pod memory graphs in CloudWatch:
> ```bash
> aws eks update-addon \
>   --cluster-name my-cluster \
>   --addon-name amazon-cloudwatch-observability \
>   --resolve-conflicts OVERWRITE
> ```

---

## 8. Cause #5 — Bad Container Image or Entrypoint

**How hard to debug:** ⭐ Easy
**How often it happens:** Common — especially after Dockerfile changes

### What's Happening

Your container image has a problem that prevents it from even starting:

| Problem | Exit Code | Error Message |
|---|---|---|
| Entrypoint script not found | 127 | `exec: not found` |
| Entrypoint not executable | 126 | `permission denied` |
| Wrong CPU architecture (ARM vs AMD64) | 132 | `Illegal instruction` |
| Windows CRLF line endings in shell script | 127 | `no such file or directory` |

### How to Spot It

```bash
kubectl describe pod <pod-name> -n <namespace> | grep "Exit Code"
# 126 or 127 = entrypoint problem

kubectl logs <pod-name> --previous -n <namespace>
# exec /app/start.sh: no such file or directory
# exec /app/start.sh: permission denied
```

### Common Dockerfile Mistakes

```dockerfile
# ❌ BAD: Script is copied but never made executable
COPY start.sh /app/start.sh
CMD ["/app/start.sh"]

# ✅ FIX: Add the execute permission
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh
CMD ["/app/start.sh"]
```

```dockerfile
# ❌ BAD: Script edited on Windows has \r\n line endings
# Linux shell can't parse them → "no such file or directory" (misleading!)

# ✅ FIX: Strip Windows line endings during build
COPY start.sh /app/start.sh
RUN sed -i 's/\r//' /app/start.sh && chmod +x /app/start.sh
CMD ["/app/start.sh"]
```

### EKS-Specific: ARM vs AMD64 (Graviton Nodes)

EKS supports both `x86_64` and `arm64` (AWS Graviton) nodes. If your image was built for AMD64 but lands on a Graviton node:

```bash
# Check what architectures your image supports
docker manifest inspect your-image:tag | grep architecture

# Build a multi-arch image that works on both
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t your-image:tag \
  --push .
```

---

## 9. Part 1 Quick Reference Cheatsheet

### Diagnostic Commands

```bash
# See restart count
kubectl get pods -n <ns>

# Jump straight to events
kubectl describe pod <pod> -n <ns> | grep -A 20 "Events:"

# Logs from the LAST crashed attempt (use this first)
kubectl logs <pod> --previous -n <ns>

# Check the exit code
kubectl describe pod <pod> -n <ns> | grep "Exit Code"

# Real-time resource usage
kubectl top pods -n <ns>
kubectl top nodes
```

### Exit Code Reference

| Exit Code | Cause | Where to Look |
|---|---|---|
| `1` | App error | `--previous` logs |
| `126` | Entrypoint not executable | Dockerfile — add `chmod +x` |
| `127` | Entrypoint not found / CRLF | Dockerfile CMD/ENTRYPOINT |
| `132` | Wrong CPU arch | Check image manifest |
| `137` | OOMKilled | Increase memory limits |
| `143` | SIGTERM | Normal shutdown — check why it was triggered |

### Part 1 Root Cause Summary

| Cause | Fastest Signal | Fix |
|---|---|---|
| App crash on startup | Stack trace in `--previous` logs | Add startup validation; fix the exception |
| Missing ConfigMap/Secret | `CreateContainerConfigError` event | Create the resource in the right namespace |
| Liveness probe misconfigured | `Liveness probe failed` event | Increase `initialDelaySeconds`; separate liveness from readiness |
| OOMKilled | `Exit Code: 137` + `OOMKilled` reason | Profile memory, increase limits |
| Bad entrypoint | `Exit Code: 126/127` | Fix Dockerfile; `chmod +x`; strip CRLF |

---

> 📌 **Continue to Part 2** for the advanced root causes: Init Container failures, Node resource exhaustion, IAM/IRSA misconfigurations, dependency race conditions, and EBS/EFS volume issues → [Part 2: Advanced Causes & Production Prevention](./crashloopbackoff-part2-advanced.md)

---

> 💡 **Found this useful?** Star the repo at [`sandeepk24/learn-devops-playbook`](https://github.com/sandeepk24/learn-devops-playbook) and share it with your team.

*Part of the **Learn DevOps Playbook** series — production-grade references for engineers who'd rather fix it than Google it.*
