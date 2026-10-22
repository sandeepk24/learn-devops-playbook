# The Read Path

Reads outnumber writes in almost every system. A user loads a page: ten reads, one write. A dashboard renders: fifty reads, zero writes. The read path bears the majority of production traffic, and its performance determines what most users experience most of the time.

The read path is also where most of the caching, replication, and consistency complexity lives. A write goes to one place and propagates outward. A read can come from any number of places — CDN edge, application cache, read replica, primary database — and the answer it returns depends on where in that hierarchy the cache hierarchy it lands.

## Fundamentals

### The caching hierarchy

Reads travel through layers. Each layer is faster and less durable than the one below it. A read that hits the topmost layer returns in microseconds. A read that falls through to the bottom returns in milliseconds — and under load, those milliseconds become seconds.

```
Browser cache (local, zero network)
        │ miss
        ▼
CDN edge cache (regional, milliseconds)
        │ miss
        ▼
Application cache (in-process or Redis, sub-millisecond to milliseconds)
        │ miss
        ▼
Read replica (milliseconds, possible replication lag)
        │ miss or consistency requirement
        ▼
Primary database (milliseconds, always current)
```

A well-designed read path keeps the vast majority of reads at the upper layers. A poorly designed one sends most reads to the primary database — which is expensive, slow under load, and fragile because the primary is also handling writes.

### Cache hit rate and its impact

Cache hit rate is the percentage of reads served from cache without reaching the origin. The arithmetic of hit rate is unforgiving.

At 99% hit rate: origin serves 1% of requests. At 90% hit rate: origin serves 10x more. At 80%: 5x more than 90%, 25x more than 99%. The relationship is not linear. A 10-point drop in hit rate from 99% to 89% multiplies origin load by a factor of 11. This is why cache warmup matters for new deployments, and why a cache eviction policy change that drops hit rate by a few percent can cause a database incident.

Monitor hit rate as a primary metric, not a secondary one. A CloudWatch alarm on ElastiCache `CacheHitRate` dropping below 95% is more actionable than an alarm on database CPU, because it fires before the database is affected.

### Read-your-writes consistency

The user submits a form. The write goes to the primary database. The redirect sends them to a page that reads from a read replica. The replica is 200ms behind. The user sees the old data. "My change didn't save."

Read-your-writes consistency guarantees that a user always sees their own writes, even in an eventually consistent system. Implementation options:

- **Route reads to primary for one second after a write.** Simple. Wasteful — sends unnecessary reads to the primary.
- **Per-user sticky reads.** After a write, mark the user's session as "recently wrote." Route subsequent reads for that user to the primary for a bounded window (one to five seconds). Other users continue hitting replicas.
- **Replication position check.** After a write, record the WAL position or LSN. Before reading from a replica, check whether the replica has caught up to that position. If not, wait or fall through to primary. PostgreSQL LSN-based routing is available in some connection poolers and frameworks.
- **Always read from primary.** Correct. Expensive. Unscalable if the workload is read-heavy.

The right approach depends on how often users write and how much read-your-writes consistency matters for the UX. For most applications, session-sticky routing for a short window after a write is sufficient and inexpensive.

### N+1 queries

The most common read path performance problem. Load a list of ten posts. For each post, issue a query to load the author. Ten posts → eleven queries (one for the list, ten for authors). Load one hundred posts → one hundred and one queries.

The pattern appears at every scale. It's invisible at small data volumes and catastrophic at production scale.

The fix: JOIN or batched fetch. One query that returns posts with their authors via JOIN. Or fetch all post IDs, batch-fetch all authors for those IDs in a single `WHERE id IN (...)` query, and assemble in the application. Either eliminates the linear query count.

ORM frameworks generate N+1 queries by default unless eager loading is explicitly configured. `eager_load` in ActiveRecord, `select_related`/`prefetch_related` in Django ORM, `JOIN FETCH` in JPA/Hibernate. The logs showing hundred-query page loads are the tell. Enable query logging in development and look for repeated queries with different single-ID parameters — that's N+1.

## Operations

### Hot keys

A single cache key receiving a disproportionate share of reads. The cache node serving that key becomes the bottleneck while others sit idle. Common causes: celebrity accounts, viral content, globally shared configuration objects, feature flag values cached under a single key.

Detection: ElastiCache has a "hot key" analysis in the ElastiCache console. CloudWatch `CurrConnections` per shard in Redis cluster mode shows imbalanced connection distribution. Application-level access pattern logging.

Mitigations:
- **Key sharding.** Store the value under multiple keys (`config:v1:0` through `config:v1:9`), randomize which key is read. Each read hits a different cache node. At the cost of storing N copies of the value.
- **Local in-process cache.** Cache the hot value in application memory (per-instance, not shared). Zero network hop. Invalidation is the challenge — a TTL-based in-process cache with a 5-second TTL serves stale data for up to 5 seconds but completely eliminates pressure on the distributed cache.
- **Read-through with jitter.** When the hot item expires, multiple concurrent requests all miss and stampede to origin. Add a randomized TTL to spread expirations, or use probabilistic early expiration to re-populate before the item expires.

### Slow queries and the read replica problem

Read replicas exist to offload read traffic from the primary. They're also the natural destination for long-running analytical queries, reports, and batch reads. The problem: a slow analytical query on a read replica holds locks, consumes IOPS, and saturates the replica's resources — while the application's fast OLTP queries are also hitting the same replica.

Use separate replicas for OLTP reads and analytical workloads. Route application reads to one replica group. Route reporting, dashboards, and batch jobs to a separate replica. When the analytics query runs for three minutes and saturates the replica's disk I/O, the application's reads degrade — but only if they're on the same replica.

On RDS, you can have up to fifteen read replicas for MySQL and MySQL-compatible Aurora. Designate specific replicas for specific workloads. Connection strings in the application's configuration, not a single generic `READ_ENDPOINT`.

### Partial reads and projection

Fetching more data than necessary is a quiet tax on read performance. `SELECT *` when only three columns are needed fetches all columns, consuming more I/O, more network bandwidth, and more memory. At scale, the difference between a three-column projection and a fifteen-column `SELECT *` on millions of rows is significant.

Projections at every layer:
- SQL `SELECT` specifies only the columns needed.
- DynamoDB `ProjectionExpression` returns only the specified attributes.
- GraphQL client specifies exactly the fields needed; the server fetches only those.
- API response shapes are versioned and stable — not "return everything in the row and let the client pick."

This also applies to cache values. Caching an entire 50KB user object to serve a request that only needs the user's name and email wastes cache memory and increases serialization cost. Cache the minimal data that the consuming operation actually needs.

## Deep Dive: the read path on AWS

**CloudFront → ALB → Application → ElastiCache → RDS Aurora.**

The full stack read path for a typical web application. Each layer has tuning knobs.

**CloudFront.** Behavior-level cache policies. Static assets: `Cache-Control: public, max-age=31536000, immutable`. Semi-static pages: `Cache-Control: public, max-age=300, stale-while-revalidate=60`. The `stale-while-revalidate` directive tells the CDN it can serve a stale response for up to 60 seconds while fetching a fresh one in the background — the user sees an instant response, the cache refreshes without a synchronous origin fetch.

**ALB with sticky sessions.** For read-your-writes: configure session stickiness via cookie. Requests from the same user go to the same application instance. That instance's in-process cache has the recently-written data. Stickiness duration should match the application's session length, not the replication lag. Stateless applications should not need stickiness — use Redis for session storage instead.

**ElastiCache Redis cluster mode.** Reads distribute across shards. Replica nodes within each shard can serve reads. Configure `read_from_replicas = true` in the Redis client for read-heavy workloads — reads can go to any replica in the shard, not just the primary. The latency is the same; the throughput is multiplied by the replica count.

Pipeline commands in Redis: if a read operation requires multiple Redis commands (get several keys, compute a value, set the result), use `PIPELINE` to send them as a batch rather than sequentially. Eliminates round-trip latency for each command. The result set arrives in one network response.

**Aurora read replicas.** Aurora's shared storage architecture means read replicas see writes within milliseconds of the primary committing them — replication lag is typically under 10ms, significantly lower than RDS read replicas. For read-your-writes requirements with Aurora, a 100ms window after a write is usually sufficient to ensure the replica has caught up before routing reads to it.

Reader endpoint: Aurora provides a single reader endpoint that automatically distributes reads across all available read replicas with round-robin load balancing. Use it for general application reads. Use specific replica endpoints when you need to pin specific workloads to specific replicas.

**RDS Proxy for read path connection management.** At high concurrency, application instances hold many connections to the database. RDS Proxy multiplexes thousands of application connections into a smaller number of actual database connections. For read-heavy workloads with many short-lived connections, RDS Proxy reduces connection overhead and allows the application tier to scale without proportionally increasing database connection count.

**DAX for DynamoDB read acceleration.** DAX (DynamoDB Accelerator) sits transparently in front of DynamoDB, caching item-level reads. Cache hits return in microseconds. Compatible with the DynamoDB SDK — point the client at DAX endpoint, no other code changes. Useful when DynamoDB read costs or millisecond latency is a constraint. DAX only helps read-heavy workloads; write-intensive tables don't benefit.

| Read layer | Latency | Consistency | Best for |
|---|---|---|---|
| Browser/CDN cache | 0–5ms | May be stale (TTL) | Public static and semi-static content |
| In-process application cache | <1ms | Stale by TTL | Hot reference data, feature flags |
| Redis (ElastiCache) | 1–3ms | Stale by TTL | Session data, computed aggregates, leaderboards |
| Aurora read replica | 1–5ms | ~10ms lag from primary | OLTP reads, most application queries |
| RDS read replica | 1–10ms | Variable lag | Secondary read workloads |
| Primary database | 1–10ms | Always current | Write-after-read, consistency-sensitive reads |

## What's next

Day 36: connection pooling and resource management — why connection counts are a scarce resource, what happens when they run out, and the pooling strategies that let large application fleets share a small number of database connections.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
