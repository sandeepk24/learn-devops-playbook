# Multi-Region Architecture

A single AWS region gives you three availability zones. That's enough to survive hardware failures, AZ-level events, and most networking incidents. It is not enough to survive a regional event — a large-scale power failure, a software defect in regional control plane infrastructure, a natural disaster affecting a geographic area.

For most systems, single-region is the right call. The operational complexity of multi-region is significant and the events it protects against are rare. But for systems where availability SLAs require four nines or better, where regulatory requirements mandate geographic distribution, or where latency to global users matters, multi-region is the design you build toward.

The hard part isn't replicating data across regions. It's deciding what happens when the regions disagree.

## Fundamentals

### Active-passive

One region serves all traffic. A second region runs a warm standby — infrastructure deployed, data replicated, but no production traffic flowing through it. If the primary region fails, traffic is redirected to the secondary.

Simpler to operate than active-active. Data consistency is straightforward — one region writes, the other receives the replication stream. You don't have to reconcile writes from two sources.

The cost: failover is not instant. DNS propagation takes time. Application connections need to re-establish. The standby database needs to finish applying any replication lag before it can serve consistent reads. RTO (Recovery Time Objective) for active-passive failover is typically minutes, not seconds.

The other cost: the standby region is running infrastructure that isn't handling any user traffic. You're paying for a warm copy. This is acceptable for disaster recovery requirements. It's wasteful if you wanted multi-region primarily for latency.

### Active-active

Both regions serve production traffic simultaneously. Users in Europe hit the European region. Users in the US hit the US region. Both regions accept reads and writes. Data replicates between them asynchronously.

Better latency for geographically distributed users. Better utilization — both regions are earning their keep. If one region goes down, the other absorbs all traffic (assuming it's sized for the load).

The hard problem: writes happen in both regions. Eventually those writes must be reconciled. If a user updates their profile in us-east-1 and another process updates the same profile in eu-west-1 in the same 50ms replication window, one of those updates will win and one will be silently discarded, unless you've built conflict resolution logic.

Most applications avoid this problem by routing the same user's writes consistently to the same region — sticky routing by user ID or geography. But sticky routing means a region failure dumps all the traffic from those users onto the surviving region, which needs to be sized for it.

```
Active-Passive:                      Active-Active:

  Users ──► Primary Region            EU Users ──► EU Region
             │ replication                          │ async replication
             ▼                        US Users ──► US Region ◄──────────┘
          Standby Region
          (receives traffic
           only on failover)         (both regions write, replication
                                      reconciles — conflict handling required)
```

### RTO and RPO

Two metrics that define the disaster recovery requirement.

**RTO (Recovery Time Objective).** How long the system can be unavailable after a failure before the business impact is unacceptable. Two minutes? Thirty minutes? Four hours? This drives how fast failover must complete.

**RPO (Recovery Point Objective).** How much data loss is acceptable. If the primary region fails and the standby is 30 seconds behind on replication, up to 30 seconds of transactions are lost. If the business requires RPO of zero, you need synchronous replication — which means write latency includes a cross-region round trip.

Cross-region synchronous replication is expensive in latency. us-east-1 to eu-west-1 is roughly 80ms round trip. Every write waits for confirmation from the other region. For interactive user workloads with p99 latency targets under 200ms, synchronous cross-region replication is often incompatible with the latency SLO. The trade-off is explicit: zero RPO costs write latency. Most systems accept a small RPO to preserve write latency.

## Operations

### Data residency and sovereignty

Multi-region isn't just about availability. Regulatory requirements often mandate that specific data stays within a geographic boundary. GDPR requires personal data of EU residents to be processed and stored within the EU (with conditions on transfers). Some financial regulations require transaction data to remain within national borders.

These requirements interact directly with replication architecture. You cannot replicate personal data from eu-west-1 to us-east-1 unless the transfer satisfies legal requirements. Multi-region data replication must be designed with these constraints in mind from the start — retrofitting data residency controls onto an existing replication topology is significantly harder.

DynamoDB Global Tables, Aurora Global Database, and S3 Cross-Region Replication all replicate data globally. They need to be scoped carefully when residency requirements apply.

### Traffic routing between regions

Three patterns.

**DNS failover.** Route 53 health checks monitor the primary region endpoint. If it fails, Route 53 returns the secondary region's IP. TTL-dependent failover speed — typically 60–120 seconds for detection plus TTL propagation. Sufficient for active-passive with a few minutes of RTO tolerance.

**Latency-based routing.** Route 53 routes each user to the region with lowest measured latency. Good for active-active, transparent to the user, no manual failover required. When a region becomes unhealthy, health checks remove it from the routing pool.

**Geolocation routing.** Route European users to the EU region, US users to the US region. Explicit, predictable, useful when data residency rules require specific users to hit specific regions. Less dynamic than latency-based — doesn't automatically route around partial degradation within a region.

**Global Accelerator.** AWS-managed anycast routing. Routes traffic to the nearest healthy region endpoint over the AWS backbone, bypassing the public internet for the majority of the path. Faster than DNS-based routing because it uses static IP addresses — no DNS propagation delay on failover. Worth the cost for latency-sensitive applications with a global user base.

### The split-brain problem

Both regions are running. The network link between them degrades or fails. Each region continues serving traffic but can no longer replicate to the other. Both are making progress independently. The replication lag grows. When the link recovers, both sides have writes the other doesn't know about.

Split-brain is the scenario every multi-region architecture has to handle explicitly. Options:

- **Conflict-free replicated data types (CRDTs).** Data structures that merge automatically without conflicts. Counters that always add, sets that only grow (or only shrink). Narrow use case but clean.
- **Last-writer-wins.** Each write carries a timestamp. On reconciliation, the latest timestamp wins. The earlier write is discarded. Correct in many cases. Dangerous when both writes represent legitimate user intent (two users editing the same record from different regions simultaneously).
- **Application-level conflict resolution.** Detect conflicts, surface them to the application, resolve based on business logic. Most correct. Most work.
- **Avoid by design.** Route all writes for a given entity to a designated "home region." Read replicas in other regions serve reads. The write path is single-region — no conflicts possible. The trade-off: writes to a user's data always go to their home region, which means cross-region write latency for users who travel.

### Runbook for regional failover

A failover executed for the first time during an incident is a failover that takes longer and causes more errors than necessary. Write the runbook. Test it with a drill.

The runbook typically covers:
1. Detection — how do you know the region is actually failing and not just a monitoring blip?
2. Decision — who authorizes the failover? What's the approval threshold?
3. Execution — the exact commands or automated pipeline that shifts traffic and promotes the secondary database.
4. Verification — how do you confirm the secondary is serving traffic correctly after failover?
5. Communication — who gets notified internally and externally?
6. Recovery — what's the path back to the primary region once it recovers?

The last step is often omitted. Failing back to the primary after a regional recovery is itself a data migration — the primary is now behind, needs to catch up with all the writes that went to the secondary during the outage, and the cutover back introduces the same risks as the original failover.

## Deep Dive: multi-region on AWS

**Aurora Global Database.** One primary region accepts writes. Up to five secondary regions receive asynchronous replications typically under one second lag. Reads can be served from any region. On a regional failure, a secondary can be promoted to primary in under a minute (managed failover) or under 30 seconds in some configurations.

RPO with Aurora Global Database: typically under one second (replication lag). RTO: under a minute for managed failover. The write path goes through the primary region — cross-region write latency applies if the application server and primary database are in different regions.

**DynamoDB Global Tables.** Multi-region, multi-master. All regions accept writes simultaneously. Replication is asynchronous, typically sub-second. Conflict resolution is last-writer-wins on the item level. Deletes replicate globally. If two regions write the same item concurrently, one write is silently dropped.

The operational simplicity of Global Tables comes at the cost of conflict resolution choice — you get last-writer-wins and nothing else. Design the data model to avoid conflicting concurrent writes across regions.

**S3 Cross-Region Replication (CRR).** Replicates objects from a source bucket to a destination bucket in another region. Asynchronous. Replication time is variable — most objects within minutes, but no hard SLA unless you enable S3 Replication Time Control (RTC), which provides a 15-minute SLA for 99.99% of objects with a CloudWatch metric for replication lag.

**Route 53 Application Recovery Controller (ARC).** Manages the routing controls for multi-region failover. Defines "routing controls" (switches that direct traffic to a region) and "safety rules" (constraints that prevent invalid configurations — can't turn off both regions simultaneously). ARC maintains its own highly available control plane, separate from the Route 53 data plane, so routing changes survive control plane events.

**Global Accelerator.** Two static anycast IP addresses. Traffic enters the AWS network at the nearest PoP and routes internally to the nearest healthy region. Failover is sub-minute — when an endpoint fails its health check, Global Accelerator reroutes within seconds without DNS propagation delay. Works with ALB, NLB, EC2, and Elastic IP endpoints.

| Architecture | RTO | RPO | Write latency impact | Best for |
|---|---|---|---|---|
| Single-region multi-AZ | Seconds (AZ failover) | Near zero | None | Most production workloads |
| Active-passive multi-region | Minutes | Seconds (async lag) | None (secondary is passive) | DR requirement, occasional failover |
| Active-active multi-region | Seconds (traffic shift) | Seconds (async lag) | None (regional routing) | Global latency, high availability SLA |
| Synchronous cross-region | Seconds | Zero | High (cross-region RTT per write) | Zero-RPO regulatory requirement |

## What's next

Day 26: deployment strategies — blue/green, canary, rolling, and feature flags, the failure modes of each, and when the strategy choice is a business decision more than a technical one.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
