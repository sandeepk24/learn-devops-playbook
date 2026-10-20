# Reliability and Fault Tolerance

Reliability is not the absence of failure. Failures happen — hardware dies, software has bugs, networks partition, deployments go wrong. A reliable system is one that continues to serve users acceptably despite those failures, and recovers from them quickly when it doesn't.

Fault tolerance is the property that makes reliability possible. A fault-tolerant system is designed to handle specific failure modes without losing the ability to function. The design question isn't "how do we prevent failures?" — you can't, not completely. It's "when this specific thing fails, what does the system do, and is that behavior acceptable?"

## Fundamentals

### Failure modes and blast radius

Start every reliability conversation with failure modes, not solutions. What can fail? What's the blast radius when it does?

**Single points of failure (SPOFs).** Any component whose failure takes down the entire system. A single-instance database. A single load balancer. A single NAT Gateway. A deployment pipeline that writes to only one region. SPOFs are the first thing to eliminate for any system with meaningful availability requirements.

**Correlated failures.** Multiple components failing simultaneously because they share a dependency. All application instances in the same AZ fail when that AZ loses power. All services that call the same third-party API degrade when that API has an incident. Multi-AZ deployment addresses the first. Circuit breakers and fallbacks address the second.

**Cascading failures.** One component failing puts pressure on others, which fail, which puts more pressure on the rest. The classic: a slow database causes application threads to back up, which causes the connection pool to fill, which causes new requests to queue, which causes latency to spike for all users, not just those hitting the database. Circuit breakers, bulkheads, timeouts, and rate limiting are all mechanisms to prevent cascading.

**Gray failures.** A component that's degraded but not completely down. Returns responses, but slowly. Returns correct responses for most inputs, incorrect for specific ones. These are harder to detect than hard failures and harder to route around, because health checks may still pass.

### Redundancy models

**Active-active.** Multiple instances all serving production traffic. A failure removes capacity but the remaining instances absorb the load. Zero-downtime failure handling if the fleet has headroom. The standard for stateless application tiers.

**Active-passive (warm standby).** Primary handles traffic, secondary is ready but idle. Failover requires promoting the secondary. Downtime during promotion. Lower cost than active-active because the standby isn't sized for full production load. Database replicas are the common case.

**Active-passive (cold standby).** Secondary is provisioned but not running. Must be started, configured, and warmed before taking traffic. Cheapest. Highest RTO.

The right redundancy level depends on RTO and cost tolerance. Every availability improvement above single-instance has a cost. Be explicit about what you're buying.

### Graceful degradation

A fully functioning system is the ideal state. An unusable system is the failure state. Between them is a spectrum of degraded-but-functional states. Graceful degradation is designing the system to occupy a degraded state rather than failing completely when components are unavailable.

Recommendations service is down. The product page can still load without recommendations — it just doesn't show them. Payment service is slow. The checkout flow can queue the payment attempt and confirm asynchronously rather than timing out and showing the user an error.

Every feature and service dependency is either **critical** (the core user journey fails without it) or **non-critical** (the page loads, the transaction completes, but with reduced functionality). Non-critical dependencies should be isolated so their failure doesn't propagate to the critical path. Circuit breakers, timeouts, and fallback responses are the implementation of this principle.

## Operations

### Timeouts everywhere

A service without timeouts is a service that can hang indefinitely waiting for a response that will never come. That hung thread holds resources. Enough hung threads, and the service is unresponsive.

Configure timeouts at every I/O boundary:
- HTTP client calls to upstream services
- Database queries (query timeout, connection acquisition timeout)
- Cache operations
- External API calls
- Queue polling

The timeout value should be informed by the p99 of the normal operation, plus a reasonable buffer. A database query with a p99 of 50ms probably shouldn't have a 30-second timeout — that's 30 seconds of held resources for a query that's clearly stuck. Set it at 500ms. Log the timeout when it fires. The timeout log is a signal about a real problem, not just an error to suppress.

Nested timeouts need to be ordered. If service A calls service B with a 5-second timeout, and service B calls service C with a 10-second timeout, B will time out before C does — and B will surface that as an error to A, which is correct. But if service A has a 3-second timeout to B, and B has a 10-second timeout to C, A will give up on B before B gives up on C. B is still waiting and consuming resources after A has already responded to the caller with an error. Set child service timeouts shorter than parent service timeouts.

### Retry policies

Retries handle transient failures. A network hiccup, a brief service restart, a 429 with a short retry window. Without retries, these transient failures become permanent errors from the user's perspective.

With retries, transient failures become invisible. But retries amplify load on a degraded service. If every client retries three times, a service handling 1,000 RPS that becomes temporarily slow suddenly receives 3,000 RPS during the retry window. That can turn a brief degradation into a full outage.

Exponential backoff with jitter is the standard mitigation. Each retry waits longer than the last (exponential). Jitter adds randomness to prevent all retrying clients from hitting the service simultaneously on the same schedule (thundering herd on retry).

```
Retry with exponential backoff and jitter:

attempt 1: wait 0s (immediate)
attempt 2: wait base * 2^1 + random(0, jitter)  → ~2s ± 1s
attempt 3: wait base * 2^2 + random(0, jitter)  → ~4s ± 1s
attempt 4: wait base * 2^3 + random(0, jitter)  → ~8s ± 1s
                                                   (cap at max_wait)
```

Only retry idempotent operations. Retrying a POST that creates a resource creates duplicates unless the operation is idempotent (Day 30). Use idempotency keys on any retried write operation.

### Bulkheads

Isolate resource pools so that a problem in one area doesn't exhaust resources for everything else. Named after the watertight compartments in a ship — a breach in one compartment floods that compartment, not the whole ship.

Thread pool bulkhead: separate thread pools for different downstream dependencies. If the recommendations service is slow and the threads calling it are all busy waiting, those threads don't block the threads handling checkout. Each dependency has its own pool.

Connection pool bulkhead: separate connection pools for different database instances or services. A connection leak to the analytics database doesn't prevent checkout from getting a database connection.

Kubernetes resource limits: separate CPU and memory limits per container, per namespace. A resource-hungry batch job in one namespace doesn't starve the API service in another.

### Chaos engineering

Controlled failure injection in production (or a production-like environment). Deliberately terminate instances. Inject latency into service calls. Block a network path. The goal is to find reliability gaps before real failures find them.

The prerequisite: a hypothesis. "If I kill one of three application instances, the remaining two should absorb the load and p99 latency should not increase by more than 20%." Run the experiment. Measure the outcome. If the hypothesis is wrong, that's a finding worth fixing.

Chaos experiments without a hypothesis are just chaos. The value is in the gap between expected behavior and observed behavior — that gap is where reliability work lives.

GameDays: scheduled events where the team runs failure scenarios and practices incident response. Not just technical — the human coordination, communication, and decision-making under pressure is what gets practiced.

## Deep Dive: reliability on AWS

**Multi-AZ as the baseline.** Every production workload should span at least two AZs. Application tier: ASG or ECS service with instances spread across AZs. Database tier: RDS Multi-AZ or Aurora with replicas in multiple AZs. Load balancer: ALB spans AZs automatically. A single-AZ system has an AZ failure as a SPOF.

**Health checks as the gate.** ALB health checks determine which targets receive traffic. ECS/EKS use the same health check results for task replacement decisions. A health check that only tests whether the process is running misses the category of failures where the process is running but can't serve requests. Configure a meaningful health check path — one that verifies database connectivity, upstream dependencies, and the ability to handle requests.

ALB unhealthy threshold: 2 consecutive failures at 30-second intervals = 60 seconds before a bad instance stops receiving traffic. For fast failover, reduce the interval to 10 seconds. Two failures at 10 seconds = 20 seconds to pull a bad instance. Worth the increased health check request volume.

**AWS Fault Injection Service (FIS).** Managed chaos engineering. Define experiments that inject AWS-level faults: terminate instances, throttle API calls, inject CPU pressure, pause container tasks, drop network packets. Experiments run against real infrastructure with guardrails — stop conditions that abort the experiment if metrics exceed thresholds. Integrates with CloudWatch and SSM.

Start with low-blast-radius experiments: inject CPU pressure on one instance in a fleet, verify autoscaling responds correctly. Progress to higher-impact: terminate an AZ's worth of capacity, verify the other AZs absorb the load. Run on production during low-traffic hours after the basics are validated in staging.

**Route 53 health checks and DNS failover.** For multi-region reliability, Route 53 health checks monitor endpoint health and route traffic only to healthy endpoints. Combine with CloudWatch alarms as health check inputs — a health check that reads a CloudWatch alarm state allows business-logic conditions (not just HTTP 200) to drive traffic routing.

**AWS Resilience Hub.** Evaluates an application against an RTO/RPO target. Analyzes the architecture (from CloudFormation, Terraform state, or manual resource groups), identifies resiliency gaps, and generates recommendations. Useful for a structured assessment of a system against formal recovery objectives. More systematic than an ad-hoc review.

| Failure mode | Detection | Mitigation | AWS mechanism |
|---|---|---|---|
| Instance failure | ALB health check | ASG replacement, traffic reroute | ALB + ASG with health check replacement |
| AZ failure | AZ health metrics | Traffic shifts to other AZs | Multi-AZ + cross-zone load balancing |
| Slow downstream | Latency metrics, trace spans | Circuit breaker, timeout, fallback | App Mesh outlier detection, FIS for testing |
| Database failover | RDS event, CloudWatch | Connection string DNS resolves to new primary | RDS Multi-AZ or Aurora failover |
| Cascading failure | Error rate spike across services | Bulkheads, circuit breakers, load shedding | Per-service reserved concurrency, SQS |
| Deployment regression | Error rate increase post-deploy | Automated rollback | CodeDeploy alarm-triggered rollback |

## What's next

Day 34: the write path — how data flows from a client write request through every layer of the stack, and the design decisions at each layer that determine durability, consistency, and performance.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
