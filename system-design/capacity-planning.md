# Capacity Planning

Systems fail in two ways. They're under-provisioned and can't handle the load. Or they're over-provisioned and cost too much to justify. Capacity planning is the work of staying between those two failure modes — close enough to the actual requirement that you're not wasting money, with enough headroom that traffic spikes don't cause outages.

The goal isn't to predict the future precisely. It's to make informed decisions with explicit assumptions, revisit those assumptions as data comes in, and avoid being surprised by events that were foreseeable.

## Fundamentals

### Working backward from requirements

Start with what the business actually needs, not with what the infrastructure can currently do.

**Peak concurrent users.** Not average, not total. The worst-case simultaneous load the system needs to handle. For consumer products this often means a specific event — a product launch, a sale, a TV spot. For B2B products it might be end-of-month billing runs or Monday morning usage spikes.

**Request rate.** Requests per second at peak. If you know peak concurrent users and average session request rate, this is arithmetic. If you don't know session request rate, instrument it. Guessing is expensive.

**Request cost.** Not all requests are equal. A static asset fetch is sub-millisecond of compute. A checkout flow with database writes, payment processing, and email dispatch might consume a second of CPU across three services. Capacity is consumed by the cost of requests, not just the count.

**Target response time.** The p99 you're committing to. This sets the acceptable queue depth — if a request takes 100ms to process and you need p99 under 500ms, the maximum queuing time is 400ms, which constrains how saturated any component can get before new requests start failing the SLO.

**Availability target.** Four nines (52 minutes downtime per year) requires different architecture than two nines (87 hours). The target determines how much redundancy, how many AZs, how fast failover needs to be.

### Little's Law

The most useful formula in capacity planning. For any stable system:

**L = λW**

Where:
- L = average number of requests in the system (concurrent requests being processed)
- λ (lambda) = average arrival rate (requests per second)
- W = average time a request spends in the system (seconds)

Rearranged: if you know your target throughput (λ) and your service latency (W), you know how many concurrent requests you need to support (L). If a service handles 1,000 requests per second and average latency is 200ms (0.2 seconds), then at any moment there are on average 200 requests in flight. Size thread pools, connection pools, and instance concurrency for at least that number with headroom.

```
λ = 1000 req/s
W = 0.2s (200ms average latency)
L = λ × W = 1000 × 0.2 = 200 concurrent requests

Thread pool or connection pool minimum: 200
With headroom for spikes (2×): 400
```

This is not a simulation. It's an average. Real traffic is bursty. Size for the burst, not the average.

### The resource model

Every system has a binding constraint — the resource that runs out first under load. Identify it before it finds you.

Common binding constraints:
- **CPU.** Compute-heavy workloads. Image processing, cryptography, serialization/deserialization at scale.
- **Memory.** In-memory caches, JVM heap, large dataset processing.
- **Database connections.** Connection pools are finite. Under high concurrency, requests queue for a connection. The queue is the bottleneck, not the database itself.
- **Database IOPS.** Write-heavy transactional workloads. The storage throughput is the ceiling, not the CPU on the database instance.
- **Network bandwidth.** Rarely the bottleneck for API workloads. Common for data-intensive workloads — video processing, large file transfers, analytics pipelines.
- **External API rate limits.** If your service depends on a third-party API with rate limits, that third party is your ceiling, not your own infrastructure.

Identify the constraint. Size for it explicitly. Monitor it. The alert on the binding constraint is the most important alert in your system.

## Operations

### Building a traffic model

Don't model "average requests per second." Model the shape of traffic over time.

Pull historical request rate metrics. Identify:
- Daily pattern. When are the peaks? When are the troughs?
- Weekly pattern. Is Monday morning 2x Friday afternoon?
- Seasonal pattern. Does traffic spike at year-end? Black Friday? End of fiscal quarter?
- Event-driven spikes. Product launches, marketing campaigns, third-party integrations that fire in batch.

The ratio of peak to average determines how much headroom you need. A system with a flat traffic profile (3x average = peak) needs less headroom than one with sharp spikes (10x average = peak). Autoscaling handles the former well. The latter may require pre-provisioning before known events.

For a new system without historical data: start with a reasonable assumption, write it down explicitly, and plan to revisit it after the first 30 days of production traffic. The assumption isn't the plan — the plan is to replace the assumption with data quickly.

### Headroom and the autoscaling boundary

Autoscaling adds capacity in response to load. It is not instantaneous. A new EC2 instance takes 2–5 minutes from launch to serving traffic. A new ECS task takes 30–90 seconds. A new Lambda invocation is cold-start milliseconds but the concurrency limit still applies.

The headroom rule: keep the current fleet operating at a load where, if traffic doubled immediately, the existing fleet could absorb the traffic during the scaling lag. For most workloads, this means running at 50–60% of capacity in steady state and scaling out before reaching 70–80%. Scaling policies that trigger at 80% CPU mean you're already degraded by the time autoscaling kicks in.

Pre-provisioning for known events bypasses the scaling lag entirely. Scale out proactively before the event. Scale in afterward. The cost of running extra capacity for a few hours is almost always less than the cost of an outage during a traffic spike.

### The database is usually the ceiling

Applications scale horizontally. Databases scale with friction. An application tier behind an autoscaling group absorbs traffic spikes by adding instances. The database behind it typically does not.

For read-heavy workloads: read replicas, caching (Day 6). For write-heavy workloads: connection pooling (RDS Proxy, PgBouncer), write batching, DynamoDB provisioned capacity or on-demand mode.

Know the connection limit of your database instance class. A `db.t3.medium` RDS PostgreSQL instance supports roughly 170 simultaneous connections. An application tier with 10 instances, 20 threads each, and a pool of 10 connections per instance is sending potentially 200 connections to that database. At the boundary. When autoscaling adds a few more application instances, connections start getting refused.

RDS Proxy sits between the application and the database, multiplexing connections. The application tier can have as many connections as it wants; RDS Proxy sends a bounded number of real connections to the database. This changes the ceiling from "database max connections" to "RDS Proxy capacity" — a much higher number.

### Estimating resource requirements

Back-of-envelope math that's actually useful:

**CPU sizing.** Benchmark the service under load. Measure CPU per request. Multiply by peak request rate. Add 50% headroom. That's your required compute capacity. Translate to instance count.

**Memory sizing.** Profile the application's memory footprint under load. Identify whether there's a per-connection or per-request memory cost (common in Java applications with per-request heap allocation). Calculate memory at peak concurrency. Add buffer for GC overhead. Size instances to fit.

**Storage sizing.** Data volume today × expected growth rate × retention period. Add overhead for indexes (20–30% for most relational databases), WAL/binlog space, and OS reserved space. For S3: estimate monthly write volume and multiply by retention months. Run lifecycle policy numbers against this.

**Bandwidth.** Average response size × request rate. For most API workloads, this is surprisingly small — a 10KB JSON response at 1,000 RPS is 10 MB/s. Well within a single instance's capacity. Watch for workloads that return large payloads (reports, exports, media) or receive large payloads (file uploads).

## Deep Dive: capacity planning on AWS

**AWS Compute Optimizer.** Analyzes CloudWatch metrics for EC2, ECS, Lambda, and EBS volumes and recommends right-sizing. Tells you which instances are over-provisioned (opportunity to save cost) or under-provisioned (risk of performance problems). Free to enable. Start here before any instance resizing exercise.

**CloudWatch metrics for capacity signals.** The metrics that matter per tier:

- Application tier: `CPUUtilization`, `MemoryUtilization` (custom via agent), request latency and error rate from ALB.
- Database tier: `CPUUtilization`, `DatabaseConnections`, `ReadIOPS`, `WriteIOPS`, `FreeStorageSpace`, `ReplicaLag`.
- Cache tier: `CurrConnections`, `Evictions`, `CacheHitRate`, `BytesUsedForCache`.
- Queue depth: `ApproximateNumberOfMessagesVisible` on SQS, custom CloudWatch metrics from Kinesis consumer lag.

**Lambda capacity.** Concurrency, not instances. Reserved concurrency caps a function. Provisioned concurrency eliminates cold starts for latency-sensitive functions. The account-level concurrency limit (default 1,000 per region) is shared across all functions — a function that consumes all concurrency during a spike can starve other functions. Set reserved concurrency on critical functions to guarantee they get what they need.

**DynamoDB capacity modes.** On-demand: pay per request, scales instantly, higher per-request cost. Provisioned: specify read and write capacity units, lower per-unit cost, throttled if you exceed provisioned capacity. Auto scaling adjusts provisioned capacity based on CloudWatch alarms. For workloads with predictable traffic, provisioned with auto scaling costs less than on-demand. For unpredictable or spiky workloads, on-demand absorbs spikes without throttling and avoids the over-provisioning cost.

**Load testing before launch.** CloudWatch historical data is the input to capacity planning. For new systems or before major events, load testing generates that data artificially. AWS Distributed Load Testing (DLT) on Fargate, k6, or Locust in ECS. Generate peak + 2x peak load in a staging environment that mirrors production. Identify the binding constraint. Fix it. Re-test. This is the only reliable way to know where the ceiling is before users find it.

## What's next

Day 25: multi-region architecture — why single-region deployments have an upper availability bound, the active-active vs active-passive trade-offs, and what it actually takes to fail over between regions without losing data.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
