# CKAD Jobs and CronJobs — Completion Traps and Manual Triggers

*The exam tests whether Jobs actually complete. A Job that sleeps forever scores zero. This guide covers the completion patterns, deadline fields, and the manual trigger technique that saves you from waiting.*

---

## Why Jobs trip candidates

Jobs are meant to run to completion. Unlike Deployments that run forever, a Job succeeds when its container exits with code 0. The CKAD tests this by giving you:

1. A CronJob where the container never exits
2. A Job that needs specific completion, parallelism, or backoff settings
3. A requirement to trigger a CronJob manually without waiting for the schedule

r/ckad March 2026: "The Job had to exit after completion. If the container sleeps forever, the Job never completes."

r/ckad Jan 2026: "CronJob + create a job" listed as a core topic.

---

## Job fundamentals

A Job creates one or more Pods and ensures a specified number of them successfully terminate.

### Basic Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: data-export
  namespace: batch
spec:
  backoffLimit: 4              # Retry up to 4 times on failure
  activeDeadlineSeconds: 300   # Kill if running longer than 5 minutes
  ttlSecondsAfterFinished: 60  # Delete Job 60s after completion
  template:
    spec:
      restartPolicy: Never     # Must be Never or OnFailure
      containers:
      - name: export
        image: busybox:1.35
        command: ["sh", "-c", "echo exporting data; sleep 10; echo done"]
```

### The restartPolicy trap

Jobs require `restartPolicy: Never` or `restartPolicy: OnFailure`. Setting `restartPolicy: Always` causes an API rejection:

```
The Job "data-export" is invalid: spec.template.spec.restartPolicy: 
Unsupported value: "Always": supported values: "OnFailure", "Never"
```

The difference between the two valid options:

| restartPolicy | On failure behavior | Pod count |
|---|---|---|
| `Never` | Failed Pod stays failed, new Pod created | Multiple Pods for retries |
| `OnFailure` | Container restarted in same Pod | Single Pod, multiple container restarts |

Use `Never` when you want clean separation between attempts. Use `OnFailure` when you want to reuse the same Pod.

---

## The completion trap

A Job completes when its container exits 0. If the container runs forever, the Job stays in `Running` state indefinitely.

### Bad: never completes

```yaml
command: ["sh", "-c", "while true; do echo running; sleep 60; done"]
```

This loops forever. The Job never transitions to `Complete`.

### Bad: sleeps forever

```yaml
command: ["sleep", "infinity"]
```

Same problem. The container never exits.

### Good: exits after work

```yaml
command: ["sh", "-c", "echo processing; sleep 5; echo done"]
```

The `echo done` runs, then the shell exits 0. Job completes.

### Good: explicit exit

```yaml
command: ["sh", "-c", "python process.py && exit 0"]
```

Explicit exit after the work finishes.

---

## activeDeadlineSeconds — the safety net

When you cannot control whether a command exits, use `activeDeadlineSeconds` to force termination:

```yaml
spec:
  activeDeadlineSeconds: 120   # Kill the Job after 2 minutes
  template:
    spec:
      containers:
      - name: worker
        command: ["sh", "-c", "some-potentially-hanging-process"]
```

If the process hangs, Kubernetes terminates the Job after 120 seconds and marks it failed. This prevents a stuck Job from blocking everything.

### Where activeDeadlineSeconds lives

`activeDeadlineSeconds` is a Job-level field, not a CronJob-level field:

```yaml
apiVersion: batch/v1
kind: CronJob
spec:
  jobTemplate:
    spec:
      activeDeadlineSeconds: 120   # Here, on the Job spec
```

---

## CronJob structure

A CronJob creates Jobs on a schedule. The hierarchy:

```
CronJob → Job → Pod → Container
```

### Full CronJob with all relevant fields

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: report
  namespace: batch
spec:
  # Schedule (required)
  schedule: "*/5 * * * *"              # Every 5 minutes
  timeZone: "America/New_York"         # Explicit timezone (K8s 1.27+)
  
  # Concurrency control
  concurrencyPolicy: Forbid            # Allow, Forbid, or Replace
  
  # Deadline for missed schedules
  startingDeadlineSeconds: 60          # Skip if more than 60s late
  
  # Pause scheduling
  suspend: false
  
  # History retention
  successfulJobsHistoryLimit: 3        # Keep last 3 successful Jobs
  failedJobsHistoryLimit: 1            # Keep last 1 failed Job
  
  # The Job template
  jobTemplate:
    spec:
      backoffLimit: 2                  # Retry twice before marking failed
      activeDeadlineSeconds: 120       # Hard kill after 2 minutes
      template:
        spec:
          restartPolicy: Never
          containers:
          - name: report
            image: busybox:1.35
            command: ["sh", "-c", "date; echo report generated"]
            resources:
              requests:
                cpu: "100m"
                memory: "64Mi"
              limits:
                cpu: "200m"
                memory: "128Mi"
```

---

## concurrencyPolicy — the field that matters

Controls what happens when a new scheduled run fires while the previous is still running.

| Policy | Behavior | Use when |
|---|---|---|
| `Allow` (default) | Multiple Jobs run simultaneously | Jobs are independent, idempotent |
| `Forbid` | Skip the new run, let current finish | Shared state, can't overlap |
| `Replace` | Kill the running Job, start new one | Only latest run matters |

### The classic exam scenario

A backup job runs every 5 minutes but sometimes takes 8 minutes. With default `Allow`, you get overlapping backups corrupting each other.

Fix: `concurrencyPolicy: Forbid`

```yaml
spec:
  schedule: "*/5 * * * *"
  concurrencyPolicy: Forbid
```

Now if the 5-minute mark arrives and the previous job is still running, the new run is skipped entirely. The schedule tick is lost, not queued.

---

## startingDeadlineSeconds versus activeDeadlineSeconds

These two fields confuse everyone. They live at different levels and do different things.

| Field | Level | What it controls |
|---|---|---|
| `startingDeadlineSeconds` | CronJob | How late a missed schedule can still start |
| `activeDeadlineSeconds` | Job | How long a running Job can execute |

### startingDeadlineSeconds example

Controller was down from 3:00 to 3:10. CronJob scheduled for 3:05.

- If `startingDeadlineSeconds: 300` (5 min), the Job starts at 3:10 (5 min late, within deadline)
- If `startingDeadlineSeconds: 60` (1 min), the Job is skipped (6 min late, past deadline)
- If unset, the Job starts unless more than 100 schedules were missed

### activeDeadlineSeconds example

Job starts at 3:10. `activeDeadlineSeconds: 120`.

- If Job completes by 3:12, normal completion
- If Job still running at 3:12, Kubernetes kills it and marks it failed

---

## Manual Job trigger — do not wait for schedule

The exam gives you a CronJob with a 5-minute schedule. Do not wait 5 minutes. Trigger it manually:

```bash
kubectl create job --from=cronjob/report manual-run-001 -n batch
```

This creates a one-off Job from the CronJob's template immediately.

### Full workflow

```bash
# Create or fix the CronJob
kubectl apply -f cronjob.yaml

# Trigger immediately
kubectl create job --from=cronjob/report test-run -n batch

# Watch the Job
kubectl get jobs -n batch --watch

# Check Job status
kubectl describe job test-run -n batch

# Get logs
kubectl logs job/test-run -n batch

# Verify completion
kubectl get job test-run -n batch -o jsonpath='{.status.conditions[*].type}'
# Expected: Complete
```

### Job name uniqueness

Each manual trigger needs a unique name:

```bash
kubectl create job --from=cronjob/report run-001 -n batch
kubectl create job --from=cronjob/report run-002 -n batch
```

Using the same name twice fails with `AlreadyExists`.

---

## Generating Jobs and CronJobs imperatively

### Create a Job

```bash
kubectl create job data-job --image=busybox:1.35 -n batch \
  --dry-run=client -o yaml -- sh -c "echo processing; sleep 5" > job.yaml
```

The `--` separator is critical. Everything after `--` becomes the container command.

### Create a CronJob

```bash
kubectl create cronjob report --image=busybox:1.35 \
  --schedule="*/5 * * * *" -n batch \
  --dry-run=client -o yaml -- sh -c "date; echo done" > cronjob.yaml
```

Then edit the YAML to add `concurrencyPolicy`, `activeDeadlineSeconds`, etc.

### The -- separator trap

Without `--`, the command is silently dropped:

```bash
# Wrong: command dropped
kubectl create cronjob report --image=busybox --schedule="*/1 * * * *" sh -c "echo hi"

# Correct: command captured
kubectl create cronjob report --image=busybox --schedule="*/1 * * * *" -- sh -c "echo hi"
```

---

## Debugging Jobs

### Job never completes

```bash
kubectl describe job NAME -n NS
kubectl get pods -n NS -l job-name=NAME
kubectl logs -n NS -l job-name=NAME
```

Check if the container is still running. If yes, the command does not exit.

### Job keeps failing

```bash
kubectl describe job NAME -n NS | grep -A5 "Pods Statuses"
kubectl logs -n NS -l job-name=NAME --previous
```

Check `backoffLimit`. After that many failures, the Job stops retrying.

### CronJob not creating Jobs

```bash
kubectl describe cronjob NAME -n NS
kubectl get events -n NS --sort-by=.metadata.creationTimestamp | tail -20
```

Check `suspend: true`, `startingDeadlineSeconds` exceeded, or schedule syntax error.

---

## Exam task walkthrough

### Task

```
CronJob 'cleanup' in namespace 'ops' runs every 10 minutes but Jobs never complete.
Fix the command to exit properly. Set concurrencyPolicy to Forbid.
Set activeDeadlineSeconds to 60. Keep 2 successful and 1 failed Job in history.
Trigger a manual run and verify it completes.
```

### Solution

```bash
# Export current CronJob
kubectl get cronjob cleanup -n ops -o yaml > cleanup.yaml
```

Edit the YAML:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup
  namespace: ops
spec:
  schedule: "*/10 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 2
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      activeDeadlineSeconds: 60
      template:
        spec:
          restartPolicy: Never
          containers:
          - name: cleanup
            image: busybox:1.35
            command: ["sh", "-c", "echo cleaning up old files; sleep 5; echo done"]
```

Apply and verify:

```bash
kubectl apply -f cleanup.yaml

# Trigger manual run
kubectl create job --from=cronjob/cleanup manual-test -n ops

# Watch completion
kubectl get jobs -n ops --watch

# Verify logs
kubectl logs job/manual-test -n ops

# Check settings
kubectl get cronjob cleanup -n ops -o jsonpath='{.spec.concurrencyPolicy}{" "}{.spec.jobTemplate.spec.activeDeadlineSeconds}'
# Expected: Forbid 60
```

---

## Speed commands

```bash
# Create CronJob
kubectl create cronjob NAME --image=IMG --schedule="CRON" -n NS --dry-run=client -o yaml -- CMD

# Manual trigger
kubectl create job --from=cronjob/NAME manual-run -n NS

# Watch Jobs
kubectl get jobs -n NS --watch

# Job logs
kubectl logs job/NAME -n NS

# Check CronJob last schedule
kubectl get cronjob NAME -n NS

# Delete old Jobs manually
kubectl delete jobs -n NS -l job-name=NAME
```
