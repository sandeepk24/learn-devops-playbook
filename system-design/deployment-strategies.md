# Deployment Strategies

How you deploy is as much a risk management decision as a technical one. A deploy that replaces all instances simultaneously is fast. It's also the fastest way to take down production if the new version has a bug. A deploy that shifts 1% of traffic to the new version first is slower. It's also a deploy where 1% of users see the problem before 100% do.

The strategy you choose sets the blast radius of a bad deploy. That's the dimension worth optimizing.

## Fundamentals

### Rolling deployment

Replace instances one at a time (or in batches). Old version and new version run simultaneously during the rollout. Traffic shifts gradually as instances are replaced.

Simple. Requires no additional infrastructure. The deployment tool handles the sequencing. ECS rolling updates, Kubernetes rolling deployments, and CodeDeploy rolling configurations all implement this model.

The failure mode: you notice a problem when 40% of instances are on the new version. Rollback means redeploying the old version to those 40%. That's another deployment cycle, with its own timeline. During the rollback window, 40% of traffic is still going to broken instances.

The other failure mode: mixed-version traffic during the rollout window. If the new API version isn't backward-compatible with the old one — a schema change, a renamed field — requests can fail when they cross a version boundary mid-session.

**Deployment window:** minutes to an hour, depending on fleet size and health check configuration.

### Blue/green deployment

Two identical environments: blue (current) and green (new version). Traffic runs entirely on blue. Green gets deployed and validated. Traffic switches from blue to green in one atomic operation — a load balancer rule change, a DNS update, a Route 53 weighted routing shift. Blue stays running. If green has a problem, the switch back to blue is equally fast.

Rollback is the fastest of any strategy — one load balancer change, seconds. The blast radius of a bad deploy is bounded by how quickly you detect the problem and initiate rollback.

The costs: you're running two full environments simultaneously during deployment, which doubles infrastructure cost during the transition window. Database schema changes need to be backward-compatible with both versions simultaneously during any overlap period.

**Deployment window:** minutes (the switch is instantaneous; the validation period before the switch is variable).

### Canary deployment

Route a small percentage of traffic — 1%, 5% — to the new version. The rest stays on the old version. Monitor error rates, latency, and business metrics on the canary. If metrics look good, progressively increase the percentage. If metrics degrade, route all traffic back to the old version.

The best risk profile of any strategy. Problems are visible at low blast radius before they affect most users. The canary population gives you real production signal — real traffic, real users, real data — that staging environments can't replicate.

The requirement: a traffic routing mechanism that supports percentage-based splitting (weighted target groups in ALB, Istio/App Mesh traffic splitting in a service mesh, Argo Rollouts in Kubernetes). And an observability setup good enough to detect a problem at 1% traffic — which means your error rate dashboards need to be sensitive at low traffic volumes.

**Deployment window:** hours to days, depending on canary duration.

```
Rolling:                    Blue/Green:               Canary:

v1 v1 v1 v1  →             v1: [all traffic]         v1: 99% traffic
v2 v1 v1 v1  →             v2: [deployed, tested]    v2:  1% traffic
v2 v2 v1 v1  →             ↓ switch                       │
v2 v2 v2 v1  →             v2: [all traffic]          monitor
v2 v2 v2 v2                v1: [idle, standby]             │
                                                       10% → 50% → 100%
(gradual replace)          (instant switch,           (gradual traffic shift
                            fast rollback)             with validation gates)
```

### Feature flags

Decouples code deployment from feature activation. Deploy the new code with the feature disabled. Enable the feature for a subset of users (internal users first, then 1%, then broader rollout) via a configuration change with no redeployment.

Feature flags give the finest-grained control of any approach. You can enable a feature for specific user IDs, specific organizations, specific geographies. You can roll back a feature by toggling a flag — no deployment required. The new code is already deployed; you're just turning it on or off.

The operational discipline required: flag cleanup. A codebase with fifty active feature flags is genuinely difficult to reason about. Flags that were meant to be temporary persist for years. Dead code paths accumulate. Establish a lifecycle — flags get removed once a rollout is complete or a feature is abandoned.

## Operations

### Database migrations with deployments

The part most deployment strategies documentation glosses over. The application code and the database schema need to be compatible during the transition period.

**Backward-compatible migrations.** Adding a new column with a default value. Adding a new table. Renaming is done in multiple steps: add the new column, deploy code that writes to both old and new, backfill the new column, deploy code that reads from new only, drop the old column. Each step is a separate deploy. The rollout takes longer. Each step is independently reversible.

**Breaking migrations.** Removing a column that old code still reads. Changing a column type. Renaming a column in one deploy. These require that old and new code never run simultaneously — which means blue/green with an instantaneous cutover is the only viable strategy. Rolling deployments and canaries require a compatibility window.

**Expand/contract pattern.** Expand: add the new schema element alongside the old one. Deploy new application code that supports both. Contract: once all instances run new code, remove the old schema element. Two-phase, but each phase is backward-compatible.

### Rollback is a deployment

Rollback is not a magic undo button. It's deploying the previous version, with all the same risks of deployment. If the deployment strategy takes twenty minutes, the rollback takes twenty minutes too. If the deployment requires a database migration, the rollback may require undoing that migration — which might not be safe if data written in the new schema has already been committed.

Blue/green makes rollback fast because the old environment is still running and the switch is a single load balancer change. Rolling and canary rollbacks are slower because they require a redeployment.

Know the rollback time for your chosen strategy before an incident. "We can roll back in five minutes" is a different operational posture from "rollback takes thirty minutes and requires a database migration."

### Health checks as deployment gates

Automated health checks determine when an instance is safe to receive traffic and when a deployment should halt.

Three layers:
1. **Process check.** Is the process running?
2. **Dependency check.** Can the process reach its dependencies (database, cache, downstream services)?
3. **Request check.** Does the process correctly handle a sample request?

Many deployments use only layer 1. A process that starts, passes the basic health check, and immediately starts serving traffic — but has a misconfigured database connection string — will fail in production. A health check that verifies database connectivity before marking the instance healthy catches this before traffic arrives.

Configure a meaningful health check path, not just `GET /`. A `GET /health` that checks database connectivity, cache connectivity, and returns 200 only when genuinely ready to serve traffic is the gate that prevents bad deploys from becoming outages.

## Deep Dive: deployment strategies on AWS

**ECS rolling update.** `minimumHealthyPercent` and `maximumPercent` in the service configuration. At 100% minimum and 200% maximum: new tasks are started before old ones are stopped. At 50% minimum: half the tasks can be replaced simultaneously. The tradeoff is speed (lower minimum = faster rollout) vs availability (lower minimum = fewer running tasks during the update).

Deployment circuit breaker: enable it. If new tasks fail health checks, ECS stops the rollout and rolls back to the previous task definition automatically. Without the circuit breaker, a bad deployment simply stops rolling — you have a mixed fleet of old and new tasks, neither completing nor rolling back.

**CodeDeploy with ALB.** Supports blue/green and canary strategies for ECS and EC2. Blue/green: CodeDeploy creates a new target group, deploys new tasks, waits for validation, then shifts traffic. Canary: shift 10% of traffic to the new target group, wait a configurable period, then shift the rest. If an alarm fires during the wait period, rollback is automatic.

The test hook: `BeforeAllowTraffic` lifecycle hook in CodeDeploy runs a Lambda function or script before any traffic shifts to the new version. Use it to run smoke tests, check for expected database records, verify configuration. A hook that returns failure halts the deployment before a single user sees the new version.

**Argo Rollouts (EKS).** Kubernetes-native progressive delivery. Extends the Deployment spec with canary and blue/green strategies, analysis templates that query metrics providers (Prometheus, CloudWatch, Datadog) as automated rollout gates, and pause steps that wait for manual approval before progressing. An analysis that shows error rate > 1% on the canary automatically rolls back without human intervention.

**Lambda aliases and traffic shifting.** Lambda function aliases support weighted routing — point `LIVE` alias 95% at version 42 and 5% at version 43. Lambda automatically splits invocations between versions. CodeDeploy manages the traffic shift and integrates with CloudWatch alarms for automatic rollback.

**Feature flags with AppConfig.** AWS AppConfig manages configuration including feature flag values. Deployments of configuration follow the same strategies as code — canary, linear, all-at-once. CloudWatch alarm integration triggers automatic rollback if metrics degrade after a configuration change. AppConfig stores are polled by the application; updates propagate without redeployment.

| Strategy | Rollback speed | Blast radius | Infrastructure cost | Schema change support |
|---|---|---|---|---|
| Rolling | Slow (redeploy old version) | Grows during rollout | None extra | Requires backward compat |
| Blue/green | Fast (load balancer switch) | Zero (if caught before full switch) | 2x during transition | Requires backward compat (during overlap) |
| Canary | Fast (re-weight traffic) | Small (% of traffic) | Small (canary instances) | Requires backward compat |
| Feature flags | Instant (toggle) | Configurable (% of users) | None | Decoupled from schema |

## What's next

Day 27: data modeling — relational vs document vs wide-column vs graph, how the data model choice constrains query patterns, and the access pattern design that determines whether a DynamoDB table scales or throttles.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
