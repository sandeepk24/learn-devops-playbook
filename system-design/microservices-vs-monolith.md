# Microservices vs Monolith

The framing of this debate is usually wrong. "Monolith" gets treated as a problem to solve and "microservices" as the solution. In practice, the question is which architecture's failure modes you'd rather deal with, at your current scale, with your current team.

Both work. Both have real costs. The costs are different. Choosing microservices for a ten-person team on a two-year-old codebase that isn't hitting any scaling limits is a decision to trade one set of manageable problems for a different, harder set of problems in exchange for benefits that don't yet exist.

## Fundamentals

### What a monolith actually is

A monolith is a single deployable unit. All the code ships together, runs in the same process, shares the same database. The checkout service, user service, notification logic, and reporting queries are all in the same codebase and the same deployment.

This is not automatically bad. The criticism of monoliths is typically about poorly structured monoliths — a "big ball of mud" where everything depends on everything else and a change to the payment module breaks the user profile page. That's a code structure problem, not an architecture problem. A well-structured monolith with clear module boundaries, explicit internal interfaces, and a disciplined dependency graph is a coherent system that deploys simply, runs simply, and is debugged simply.

The real limits of a monolith are operational. Everything scales together. If the reporting queries are hammering the database, the checkout flow suffers. If a memory leak in the notification module takes down the process, all functionality goes down with it. Blast radius is the whole application.

### What microservices actually cost

Microservices split the monolith into independently deployable services. Each owns its data. Each scales independently. A failure in one service doesn't necessarily bring down others.

These benefits are real. So are the costs, which are rarely enumerated with the same enthusiasm.

**Network calls replace function calls.** Calling another module in a monolith is a function call — nanoseconds, no failure modes. Calling another service is a network call — milliseconds, timeout risk, retry logic required, circuit breaker needed, distributed tracing required to see what's happening.

**Data consistency gets harder.** In a monolith, a database transaction spans any set of tables. In microservices, each service owns its data. A transaction that used to be atomic now requires a distributed transaction, a saga, or accepting eventual consistency.

**Operational surface area multiplies.** Ten services means ten deployment pipelines, ten sets of logs, ten monitoring dashboards, ten on-call runbooks. The overhead that was once on one team is now distributed, but it hasn't gone away. It's often larger in aggregate.

**Testing gets harder.** Unit testing a monolith is straightforward. Integration testing ten services interacting requires either a full local environment, mocks that may diverge from reality, or a staging environment that's expensive to maintain.

```
Monolith                             Microservices

┌────────────────────────┐           ┌─────────┐  ┌─────────┐
│  Checkout              │           │Checkout │  │Payment  │
│  Payment               │   vs.     └────┬────┘  └────┬────┘
│  Notifications         │                │network      │
│  Reporting             │           ┌────┴──────────────┴───┐
│  [shared DB]           │           │  Notifications  Report│
└────────────────────────┘           │  [each with own DB]   │
                                     └───────────────────────┘
One deploy, one process,             N deploys, N processes,
one database, one blast radius       N databases, N blast radii
```

### The migration path

Most teams don't choose between a greenfield monolith and greenfield microservices. They have an existing monolith and are considering whether to break it up. The pattern that actually works: extract services at clear seams where the cost/benefit is favorable, leave the rest as-is.

Extract when:
- A specific capability needs to scale independently and vertical scaling won't help.
- A team boundary maps cleanly to a service boundary (Conway's Law is real — your architecture will mirror your communication structure).
- A capability has a different deployment cadence or availability requirement than the rest of the application.
- A specific module is a blast radius problem — its failures affect unrelated functionality.

Don't extract when the only reason is "microservices are modern." That's not a trade-off, it's a trend.

## Operations

### Where monoliths actually break

**Deployment coupling.** Every change requires a full deploy. A typo fix in a stylesheet forces a full regression of the payment flow. Teams can't deploy independently. Release trains form. Deploys become events instead of routine operations.

This is often the first real pain point. It's solvable within the monolith — modular design, trunk-based development, fast CI pipelines, and feature flags let teams move independently without splitting the codebase. But it requires deliberate investment.

**Database contention.** The shared database becomes a bottleneck. Long-running reports lock rows that checkout needs. Index changes require downtime windows because any query across the application might depend on the schema. Migrations become high-risk operations.

**Technology lock-in.** One language, one runtime, one framework. A part of the system that would benefit from a different stack (a compute-heavy processing job, a real-time WebSocket server) is stuck on the same technology as the rest.

### Where microservices actually break

**Distributed systems failures.** A call from service A to service B fails. Timeout. Service B is healthy but service A's connection pool to it is exhausted. Now service A is degraded. Service C, which calls A, is also degraded. The original cause — a slow database query on service B — has cascaded into a multi-service incident that's significantly harder to diagnose than a single-process failure.

In a monolith, this scenario is a slow function call that slows one request. In microservices, it's a potential incident.

**Operational complexity that exceeds team capacity.** Fifteen services, six engineers. Each service needs its own deployment pipeline, log aggregation, alerting, runbook, and on-call coverage. The team is spending more time on infrastructure than features. This is the most common way microservices fail in practice — not a technical failure, an organizational one.

**Data consistency bugs that are hard to detect.** The order was created. The payment service was down for 200ms. The payment event was lost. The order is in the system but was never charged. At 3 AM. No alarm fired because each individual service stayed healthy.

### Strangler fig pattern

The pragmatic migration approach. Don't rewrite the monolith. Gradually extract services by routing specific requests to new services while the monolith continues to handle everything else. Over time, the monolith shrinks as functionality migrates out. Named after the fig tree that grows around a host tree — the new system wraps the old one while the old one slowly becomes irrelevant.

The key: a routing layer (an API Gateway or reverse proxy) in front of both systems. Requests for `/api/payments` go to the new payment service; everything else goes to the monolith. No big-bang migration. Each extraction is independently deployable and independently rollback-able.

## Deep Dive: operational model on AWS

**Monolith on AWS.** ECS or EKS with a single service. One task definition, one target group, one ALB rule for everything. Simple. RDS as the database — one cluster, schema-per-environment. Deployment is one pipeline. Observability is one log group, one set of metrics. Runbook covers one service.

The scaling constraint surfaces clearly: if the monolith is CPU-bound due to one feature, you scale the entire task. You can't scale the reporting module without also scaling the checkout module. For most teams at most stages, this is an acceptable trade-off.

**Microservices on AWS.** Each service is an ECS service or EKS Deployment. Each gets its own task definition, target group, autoscaling policy, log group, and ALB path rule (or separate ALB). Each has its own RDS instance or Aurora cluster, or DynamoDB table, depending on the data model.

The infrastructure multiply is real. Fifteen services might mean fifteen RDS instances, fifteen CloudWatch dashboards, fifteen deployment pipelines. Service mesh (App Mesh or Istio on EKS) handles mutual TLS and observability between services but adds its own operational overhead. AWS Service Connect in ECS simplifies service-to-service discovery without a full service mesh.

**The cost difference is not hypothetical.** Fifteen small RDS instances often cost more than one medium RDS instance. Fifteen NAT Gateway data transfer charges add up. Fifteen CloudWatch log groups, fifteen X-Ray sampling configs, fifteen sets of WAF rules if you're applying them per-service. Run the numbers before committing to the architecture.

| | Monolith | Microservices |
|---|---|---|
| Deployment complexity | Low (one artifact) | High (N pipelines, versioned APIs) |
| Operational overhead | Low (one service to run) | High (N services, N runbooks) |
| Independent scaling | No | Yes |
| Fault isolation | Low (shared process) | High (if implemented correctly) |
| Data consistency | Easy (shared database) | Hard (distributed, eventual) |
| Team independence | Low (shared codebase) | High (clear ownership) |
| Best fit | Early stage, small team, unclear boundaries | Large team, proven scale need, clear domain boundaries |

## What's next

Day 21: distributed transactions — what ACID means across service boundaries, why two-phase commit is fragile, and how sagas handle long-running workflows without distributed locks.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
