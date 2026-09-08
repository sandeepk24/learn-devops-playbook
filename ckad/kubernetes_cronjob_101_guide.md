# Kubernetes CronJobs: A Complete 101 Guide

> *Written for everyone — from the engineer who just `kubectl apply`'d their first Pod, to the CKAD candidate who needs to nail this in the exam, to the architect designing scheduled workloads for production.*

---

## Table of Contents

1. [The Mental Model: What Even Is a CronJob?](#1-the-mental-model)
2. [The Family Tree: Pod → Job → CronJob](#2-the-family-tree)
3. [Anatomy of a CronJob (The Full Field Breakdown)](#3-anatomy-of-a-cronjob)
4. [Cracking the Cron Schedule Syntax](#4-cracking-the-cron-schedule-syntax)
5. [The Critical Fields You MUST Understand](#5-the-critical-fields)
6. [Concurrency Policy: The Field That Trips Everyone Up](#6-concurrency-policy)
7. [History Limits & Deadlines: Housekeeping Matters](#7-history-limits--deadlines)
8. [The Job Template Inside (restartPolicy & backoffLimit)](#8-the-job-template-inside)
9. [Full Production-Grade Example](#9-full-production-grade-example)
10. [CKAD Speed Run: Imperative Commands](#10-ckad-speed-run)
11. [Troubleshooting Playbook](#11-troubleshooting-playbook)
12. [Architect's Corner: Production Wisdom](#12-architects-corner)
13. [Quick Reference Cheatsheet](#13-quick-reference-cheatsheet)

---

## 1. The Mental Model

Imagine you hired an assistant. Most of your staff (your **Deployments**) show up every day and stay running — answering phones, serving customers, always *on*. But you also need someone to do a specific task **at a specific time and then leave** — like "take out the trash every night at 2 AM" or "generate the monthly report on the 1st."

That second kind of worker is a **CronJob**.

A **CronJob** is Kubernetes' built-in scheduler. It says: *"On this schedule, create a Job for me."* The Job then runs a Pod to completion, the work gets done, and the Pod exits. Nobody lingers.

The name comes from the classic Unix `cron` daemon that Linux admins have used for decades. Kubernetes took that battle-tested idea and made it cloud-native.

**Think of it this way:**
- A **Deployment** is a restaurant that's open 24/7.
- A **CronJob** is the cleaning crew that comes in at 3 AM, mops the floors, and leaves.

---

## 2. The Family Tree

You can't understand CronJobs without understanding what they *create*. There's a clean hierarchy here, and it matters:

```
CronJob  ──(on a schedule, creates)──►  Job  ──(creates & manages)──►  Pod(s)  ──►  Container(s)
```

| Object | Job in life | Lifespan |
|--------|-------------|----------|
| **CronJob** | The scheduler. Watches the clock. | Lives forever (until you delete it) |
| **Job** | Runs a task to **completion**. Retries on failure. | Lives until task succeeds, then sticks around as history |
| **Pod** | The actual running workload. | Runs, finishes, exits |

> **Key insight:** A CronJob does *not* run your container directly. It **stamps out a new Job object** every time the schedule fires. That Job is what actually runs the Pod. This indirection is why so many fields on a CronJob are about *managing the Jobs it spawns*.

---

## 3. Anatomy of a CronJob

Here is a fully-annotated CronJob. Read the comments — this is the whole map in one picture:

```yaml
apiVersion: batch/v1            # CronJob lives in the batch API group
kind: CronJob
metadata:
  name: report-generator       # Name of the CronJob object
spec:
  # ───────── SCHEDULING FIELDS (the "when") ─────────
  schedule: "0 2 * * *"         # REQUIRED: cron expression. Runs daily at 02:00
  timeZone: "America/New_York"  # Optional (k8s 1.27+): timezone for the schedule
  startingDeadlineSeconds: 200  # Optional: if a run is missed, how long is it still allowed to start?

  # ───────── CONCURRENCY & HISTORY (the "how it behaves") ─────────
  concurrencyPolicy: Forbid     # Allow | Forbid | Replace
  suspend: false                # If true, pause scheduling (existing jobs unaffected)
  successfulJobsHistoryLimit: 3 # Keep last 3 successful Jobs
  failedJobsHistoryLimit: 1     # Keep last 1 failed Job

  # ───────── THE JOB TEMPLATE (the "what to run") ─────────
  jobTemplate:                  # REQUIRED: this is a full Job spec
    spec:
      backoffLimit: 4           # Retry the Job up to 4 times before marking it failed
      activeDeadlineSeconds: 600 # Kill the Job if it runs longer than 600s
      template:                 # ── Pod template ──
        spec:
          restartPolicy: OnFailure  # MUST be OnFailure or Never (NOT Always!)
          containers:
            - name: report
              image: my-registry/report-tool:1.4.2
              command: ["python", "generate_report.py"]
```

That's the entire structure. Everything else is detail. Let's go deep on the fields that actually matter — and the ones that show up on the CKAD exam.

---

## 4. Cracking the Cron Schedule Syntax

The `schedule` field is the heart of a CronJob, and it uses standard cron syntax. **Five fields, separated by spaces:**

```
┌───────────── minute (0 - 59)
│ ┌───────────── hour (0 - 23)
│ │ ┌───────────── day of month (1 - 31)
│ │ │ ┌───────────── month (1 - 12)
│ │ │ │ ┌───────────── day of week (0 - 6) (Sunday = 0 or 7)
│ │ │ │ │
* * * * *
```

### The special characters that make everything else possible:

| Symbol | Meaning | Example | Reads as |
|--------|---------|---------|----------|
| `*` | "every" / any value | `* * * * *` | Every minute |
| `,` | List of values | `0 0,12 * * *` | At midnight AND noon |
| `-` | Range | `0 9-17 * * *` | Every hour from 9 AM to 5 PM |
| `/` | Step / interval | `*/15 * * * *` | Every 15 minutes |

### Real-world schedules you'll actually write:

| You want... | Cron expression |
|-------------|-----------------|
| Every minute | `* * * * *` |
| Every 5 minutes | `*/5 * * * *` |
| Every hour, on the hour | `0 * * * *` |
| Every day at midnight | `0 0 * * *` |
| Every day at 2:30 AM | `30 2 * * *` |
| Every Monday at 9 AM | `0 9 * * 1` |
| First of every month at midnight | `0 0 1 * *` |
| Weekdays at 6 PM | `0 18 * * 1-5` |
| Every 6 hours | `0 */6 * * *` |

### Handy macros (shortcuts):

Kubernetes also accepts these named schedules:
- `@hourly` → `0 * * * *`
- `@daily` (or `@midnight`) → `0 0 * * *`
- `@weekly` → `0 0 * * 0`
- `@monthly` → `0 0 1 * *`
- `@yearly` (or `@annually`) → `0 0 1 1 *`

> 💡 **Pro tip:** Bookmark [crontab.guru](https://crontab.guru). It translates any cron expression into plain English instantly. Even 10-year veterans use it to sanity-check.

> ⚠️ **Timezone gotcha:** Before k8s 1.27, CronJobs ran in the timezone of the **kube-controller-manager** (usually UTC). Since 1.27, the `timeZone` field lets you pin it explicitly. *Always set `timeZone` in production* — relying on cluster UTC and doing mental math at 3 AM is how incidents happen.

---

## 5. The Critical Fields

Let's slow down on the fields that genuinely shape behavior. These are the ones interviewers and the CKAD exam love.

### `schedule` *(required)*
The cron expression. No schedule, no CronJob. This is the only field that is truly non-negotiable alongside `jobTemplate`.

### `jobTemplate` *(required)*
This is a **complete Job specification** nested inside the CronJob. Everything about *what actually runs* lives here. The CronJob is essentially a "Job factory," and this is the blueprint it stamps from.

### `suspend`
A simple boolean on/off switch.
- `suspend: true` → the scheduler stops creating new Jobs. **Jobs already running are NOT affected.**
- This is your "pause button." Incident at 2 AM and you don't want the backup job piling on? `kubectl patch cronjob mycron -p '{"spec":{"suspend":true}}'`.

### `startingDeadlineSeconds`
This answers: *"If my CronJob missed its scheduled time (controller was down, cluster was busy), how late is it still acceptable to start?"*

- Set to `200` → if the job is more than 200 seconds late, **skip this run entirely**.
- If you leave it unset, there's no deadline — but if more than **100 schedules are missed**, the controller stops scheduling and logs an error. This 100-miss safety valve catches misconfigured schedules.

---

## 6. Concurrency Policy

This is **the single most important behavioral field** — and the one most likely to bite you in production or appear as a tricky exam question.

The question it answers: *"My last scheduled Job is still running, and it's time to start a new one. What do I do?"*

```yaml
concurrencyPolicy: Allow | Forbid | Replace
```

| Policy | Behavior | Use it when... |
|--------|----------|----------------|
| **`Allow`** *(default)* | Let them overlap. Multiple Jobs run side-by-side. | Jobs are independent and idempotent — e.g., sending separate emails. |
| **`Forbid`** | Skip the new run. The currently-running Job finishes first; the new schedule is **missed, not queued**. | A job must never run twice at once — e.g., a database migration or a job that locks a shared resource. |
| **`Replace`** | Kill the running Job, start the new one. | Only the latest run matters — e.g., "sync current state" where stale work is worthless. |

> 🎯 **The classic trap:** A backup job runs every 5 minutes but sometimes takes 8 minutes. With the default `Allow`, you'll get **overlapping backups** corrupting each other. The fix is almost always `Forbid`. Memorize this scenario — it's the canonical CronJob interview question.

> ⚠️ **Subtle point on `Forbid`:** It does **not** queue the skipped run. That schedule tick is simply lost. If you need eventual execution, `Forbid` is *not* what you want.

---

## 7. History Limits & Deadlines

Every time a CronJob fires, it leaves behind a completed Job object (and its Pod). Without limits, these pile up forever and clutter your cluster. These fields are the cleanup crew.

### `successfulJobsHistoryLimit` *(default: 3)*
How many **successful** completed Jobs to keep around for inspection. Older ones get garbage-collected.

### `failedJobsHistoryLimit` *(default: 1)*
How many **failed** Jobs to keep. You usually want to keep at least one failure around so you can debug what went wrong.

> 💡 Setting either to `0` means "keep nothing." Useful for high-frequency CronJobs (every minute) where retained Jobs would flood `kubectl get jobs`. But set failed history to `0` and you lose your debugging trail — trade carefully.

### `activeDeadlineSeconds` (on the Job template)
A hard wall-clock timeout. *"If this Job runs longer than N seconds, kill it — success or not."* Prevents a hung job from running indefinitely and blocking the next scheduled run (especially nasty combined with `Forbid`).

---

## 8. The Job Template Inside

The Pod template inside `jobTemplate` has one rule that catches *everyone* at least once:

### `restartPolicy` — it canNOT be `Always`

```yaml
jobTemplate:
  spec:
    template:
      spec:
        restartPolicy: OnFailure   # ✅ valid
        # restartPolicy: Never     # ✅ also valid
        # restartPolicy: Always    # ❌ REJECTED — won't even apply
```

**Why?** A Deployment's Pods use `Always` because they're meant to run forever — if they stop, restart them. But a Job-run Pod is meant to **finish and exit**. `Always` would restart a successfully-completed Pod into an infinite loop, which defeats the entire purpose. Kubernetes rejects it outright.

- **`OnFailure`** → if the container exits non-zero, restart the **same Pod**. Lighter weight.
- **`Never`** → if it fails, the Pod is marked failed and a **brand new Pod** is created (up to `backoffLimit`). Better when you want a clean slate and separate Pod records per attempt.

### `backoffLimit` *(default: 6)*
How many times the Job retries before giving up and declaring failure. After each failure, Kubernetes waits with **exponential backoff** (10s, 20s, 40s...) before the next attempt — to avoid hammering a broken dependency.

> 🧠 **Mental model:** `restartPolicy` controls *how* a retry happens (same Pod vs. new Pod). `backoffLimit` controls *how many* retries happen. They work together.

---

## 9. Full Production-Grade Example

Here's a CronJob you'd actually be comfortable shipping — a nightly database backup with all the guardrails in place:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nightly-db-backup
  namespace: data-platform
  labels:
    app: db-backup
    tier: maintenance
spec:
  schedule: "0 3 * * *"                # 3 AM daily
  timeZone: "America/New_York"         # explicit — no UTC guesswork
  concurrencyPolicy: Forbid            # never two backups at once
  startingDeadlineSeconds: 300         # if >5 min late, skip this run
  successfulJobsHistoryLimit: 5        # keep a week-ish of successes
  failedJobsHistoryLimit: 3            # keep failures for debugging
  suspend: false
  jobTemplate:
    spec:
      backoffLimit: 2                  # retry twice, then alert
      activeDeadlineSeconds: 3600      # hard kill after 1 hour
      template:
        metadata:
          labels:
            app: db-backup
        spec:
          restartPolicy: Never
          containers:
            - name: backup
              image: my-registry/pg-backup:2.1.0
              command: ["/bin/sh", "-c"]
              args:
                - |
                  pg_dump "$DATABASE_URL" | gzip | \
                  aws s3 cp - "s3://my-backups/db-$(date +%F).sql.gz"
              env:
                - name: DATABASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: db-credentials
                      key: connection-string
              resources:
                requests:
                  cpu: "250m"
                  memory: "256Mi"
                limits:
                  cpu: "500m"
                  memory: "512Mi"
```

Every field here earns its place. This is what "production-grade" looks like.

---

## 10. CKAD Speed Run

In the exam, **speed is everything**. You will almost never hand-write YAML from scratch — you generate it imperatively and tweak. Memorize these:

```bash
# Create a CronJob imperatively (the money command)
kubectl create cronjob my-cron \
  --image=busybox \
  --schedule="*/1 * * * *" \
  -- /bin/sh -c "date; echo Hello from k8s"

# Generate YAML WITHOUT creating it (--dry-run + -o yaml)
kubectl create cronjob my-cron \
  --image=busybox \
  --schedule="*/1 * * * *" \
  --dry-run=client -o yaml > cron.yaml
  # ↑ then edit cron.yaml to add concurrencyPolicy, etc.

# Inspect
kubectl get cronjob
kubectl get cronjob my-cron -o yaml
kubectl describe cronjob my-cron

# See the Jobs it has spawned
kubectl get jobs --watch

# See the Pods those Jobs created
kubectl get pods

# Suspend / resume quickly
kubectl patch cronjob my-cron -p '{"spec":{"suspend":true}}'
kubectl patch cronjob my-cron -p '{"spec":{"suspend":false}}'

# Manually trigger a CronJob NOW (create a Job from it on demand)
kubectl create job --from=cronjob/my-cron manual-run-001

# Check logs of a completed run
kubectl logs job/<job-name>
```

> 🎯 **Exam gold:** `kubectl create job --from=cronjob/<name>` is the way to test a CronJob without waiting for the schedule. Examiners love when you don't sit idle waiting for `*/1`.

> 🎯 **The `--` separator:** Everything after `--` in `kubectl create cronjob` becomes the container's command. Forget the `--` and your command silently disappears. This is a top-3 exam mistake.

---

## 11. Troubleshooting Playbook

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| CronJob exists but **no Jobs ever appear** | `suspend: true`, or schedule hasn't hit yet, or controller missed >100 runs | Check `kubectl get cronjob` LAST SCHEDULE column; verify `suspend`; check schedule syntax |
| Jobs created but **Pods stuck Pending** | No resources / scheduling constraints | `kubectl describe pod` — look at Events |
| Job runs but **immediately fails repeatedly** | Bad image, bad command, missing secret | `kubectl logs job/<name>`; check `backoffLimit` exhaustion |
| **Overlapping runs** causing chaos | `concurrencyPolicy: Allow` (default) | Switch to `Forbid` or `Replace` |
| Validation error on apply | `restartPolicy: Always` in template | Change to `OnFailure` or `Never` |
| Job runs at the **wrong time** | Timezone mismatch (UTC vs local) | Set `timeZone` field explicitly |
| Old Jobs **piling up** | History limits too high | Lower `successfulJobsHistoryLimit` |

**The universal debug flow:**
```
CronJob → describe it → did it create a Job?
   └─ No  → check suspend, schedule, controller logs
   └─ Yes → check the Job → did it create a Pod?
              └─ check Pod status → check Pod logs
```
Follow the chain down. The problem is always at one specific link.

---

## 12. Architect's Corner

Production wisdom that separates "it works on my cluster" from "it works at 3 AM during an incident":

1. **CronJobs guarantee *at-least-once*, not *exactly-once*.** Under rare conditions (controller restarts at the wrong moment), a CronJob may create **two Jobs** or **zero Jobs** for a single tick. **Design your jobs to be idempotent.** Running the same backup twice should be harmless. This is the most important architectural truth about CronJobs.

2. **Always set resource requests and limits.** A scheduled job without limits can balloon and evict your real workloads. Batch jobs are notorious memory hogs.

3. **Set `timeZone` explicitly.** Daylight Saving Time will silently shift your "2 AM job" if you rely on cluster UTC and do the math yourself.

4. **Use `Forbid` as your default mental starting point** for anything touching shared state, then loosen to `Allow` only when you've proven the job is safe to overlap.

5. **Pair `activeDeadlineSeconds` with `Forbid`.** Otherwise a single hung job blocks every future run indefinitely — a silent outage that's brutal to diagnose.

6. **Don't use CronJobs for sub-minute scheduling.** The minimum granularity is one minute. If you need "every 10 seconds," you need a long-running Deployment with an internal timer, not a CronJob.

7. **Emit metrics and alerts on failures.** A CronJob that silently fails every night for two weeks is a classic horror story. Wire `failedJobsHistoryLimit` together with monitoring (e.g., a Prometheus alert on `kube_job_status_failed`).

---

## 13. Quick Reference Cheatsheet

```
┌─────────────────────────────────────────────────────────────────┐
│                  KUBERNETES CRONJOB CHEATSHEET                    │
├─────────────────────────────────────────────────────────────────┤
│ API:  batch/v1   │   kind: CronJob                               │
└─────────────────────────────────────────────────────────────────┘

REQUIRED FIELDS
  schedule            cron expression — when to run
  jobTemplate         the Job spec to stamp out each time

SCHEDULE SYNTAX        ┌min ┌hour ┌dom ┌mon ┌dow
  "* * * * *"          *    *     *    *    *
  */5  = every 5       0    = on the hour
  1-5  = range (dow=weekdays)        ,  = list
  Macros: @hourly @daily @weekly @monthly @yearly

SCHEDULING FIELDS
  timeZone                  IANA tz, e.g. "America/New_York" (1.27+)
  startingDeadlineSeconds   how late a missed run may still start
  suspend                   true = pause scheduling (running jobs OK)

CONCURRENCY POLICY  (what if last run still going?)
  Allow    (default)  overlap freely
  Forbid              skip new run — never overlap   ◄ most common fix
  Replace             kill old, start new

HISTORY
  successfulJobsHistoryLimit   default 3
  failedJobsHistoryLimit       default 1

JOB TEMPLATE (jobTemplate.spec)
  backoffLimit            retries before failure (default 6)
  activeDeadlineSeconds   hard wall-clock timeout

POD TEMPLATE (...template.spec)
  restartPolicy   OnFailure | Never   ◄ NEVER "Always"!

ESSENTIAL COMMANDS
  kubectl create cronjob NAME --image=IMG --schedule="*/1 * * * *" \
      --dry-run=client -o yaml -- CMD
  kubectl create job --from=cronjob/NAME run-now     # trigger now
  kubectl patch cronjob NAME -p '{"spec":{"suspend":true}}'
  kubectl get cronjob / get jobs / get pods
  kubectl logs job/JOBNAME

TOP 3 GOTCHAS
  1. restartPolicy: Always  → REJECTED. Use OnFailure/Never.
  2. Default Allow overlaps  → use Forbid for shared state.
  3. Forget the "--"         → your command vanishes.

GOLDEN RULE
  ► CronJobs are at-least-once. MAKE YOUR JOBS IDEMPOTENT. ◄
```

---

*End of guide. Keep this handy — for the exam, for the interview, and for that 3 AM page.*
