# Database Sharding

A single database node has limits. Storage. Write throughput. Connection count. At some point, no amount of vertical scaling closes the gap between what the hardware can do and what the system needs. Sharding splits the data horizontally across multiple database instances so each node handles a fraction of the total load.

It's one of the more expensive architectural decisions you can make. Cross-shard queries get complicated. Transactions that span shards lose ACID guarantees unless you build them back in. Rebalancing shards is operationally heavy. The right question before sharding is always: have you actually exhausted the alternatives?

## Fundamentals

### What sharding is

One logical dataset lives across multiple physical databases. Each shard holds a subset of the rows. A user with ID 1001 might be on shard 1. A user with ID 8742 might be on shard 4. The application knows how to route queries to the right shard.

This is different from read replicas. Replicas copy the same data to multiple nodes for read scaling. Shards partition the data — each shard holds data that the others don't. Writes scale horizontally because writes to different users go to different shards simultaneously.

### Sharding strategies

**Range-based sharding.** Divide the keyspace into ranges. Users 1–1,000,000 on shard 1. Users 1,000,001–2,000,000 on shard 2. Simple. Supports range queries efficiently — "get all users created this month" maps to one or two shards rather than a full scatter-gather. Problem: access patterns are rarely uniform. If users with IDs in the first million are most active, shard 1 runs hot while the others idle.

**Hash-based sharding.** Hash the shard key, assign to a shard by modulo. Even distribution across shards regardless of key values. Range queries are now expensive — "get all users created this month" means hitting every shard because hashed IDs are scattered everywhere. Can't predict which shard a range falls on.

**Directory-based sharding.** Maintain a lookup table that maps keys to shards. Maximum flexibility — move data between shards without changing the key. Cost: every query hits the directory first. The directory becomes a bottleneck and a single point of failure unless it's heavily cached and replicated.

```
Range-based                      Hash-based

Shard 1: IDs 1–1M                hash(user_id) % 4
Shard 2: IDs 1M–2M       vs.     → routes to shard 0, 1, 2, or 3
Shard 3: IDs 2M–3M               (even distribution, no range locality)
Shard 4: IDs 3M–4M
(range queries fast,             (range queries scatter,
 hot shard risk)                  writes always even)
```

### Choosing a shard key

The shard key determines how data distributes across shards. A bad shard key creates hotspots that defeat the purpose of sharding entirely.

Properties of a good shard key:

- **High cardinality.** Enough distinct values to distribute data across all shards. Sharding by a boolean column gives two shards, maximum.
- **Even access distribution.** Not just even data distribution. If 80% of reads touch 20% of shard key values, those shards run hot regardless of how evenly data is distributed.
- **Query locality.** The most common queries should, ideally, touch one shard. Cross-shard queries require scatter-gather or application-side joins — expensive and complex.
- **Stability.** Don't shard on something that changes. If a user changes country and you sharded by country, you're migrating that user's data between shards. That's an operational problem.

User ID is the canonical good shard key for user-centric applications. High cardinality, stable, and most queries for a user's data are naturally co-located on one shard.

## Operations

### Cross-shard queries

The query that works trivially on a single database becomes expensive when data is sharded. "Find all orders placed in the last 24 hours" touches every shard. The application issues the query to all shards, waits for all responses, merges and sorts them. Scatter-gather.

This is manageable when done deliberately. It's a trap when it happens accidentally because someone added a new report or dashboard query without thinking about shard topology.

Audit your query patterns before choosing a shard key. Queries that need to span shards frequently are a signal that either the shard key is wrong, or the data that needs to be queried together shouldn't be sharded at all.

### Resharding

Shard count is not forever. The system grows. Shards that were fine at launch become bottlenecks. You need to split shards or add new ones.

Resharding is painful. It means migrating data while the system is live, updating routing logic to reflect the new topology, and managing a window where the source and destination shards are both in play. Double-writes during migration, careful cutover, rollback plan if something goes wrong.

This is why consistent hashing (Day 10) matters for cache layers — minimizing data movement on resize. Relational databases don't have the same luxury. Resharding a Postgres cluster is a multi-week operational project. Plan shard count conservatively but with growth in mind. Over-sharding at the start — more shards than you need — is generally safer than under-sharding, because merging shards is at least as hard as splitting them.

### Transactions across shards

ACID transactions within a single shard work normally. Transactions that span shards require distributed transaction coordination — two-phase commit, sagas, or accepting eventual consistency.

Two-phase commit is correct but slow and fragile. The coordinator becomes a bottleneck. If the coordinator fails after phase one but before phase two, shards are left in a prepared state waiting for resolution.

Sagas break the cross-shard operation into a sequence of local transactions with compensating transactions for rollback. More complex to implement, but more resilient. Appropriate when the operation can be decomposed into independent steps.

Most teams avoid cross-shard transactions by designing shard keys such that the operations they need are co-located. When that isn't possible, they accept eventual consistency and build compensating logic.

## Deep Dive: sharding on AWS

**DynamoDB.** Sharding is managed for you. You choose the partition key; DynamoDB handles the physical distribution across partitions using consistent hashing internally. The operational implication: DynamoDB's partition limits (3,000 RCUs and 1,000 WCUs per partition) mean a hot partition key can become a throttling problem even when overall capacity looks fine. Design your partition key for even distribution. Use write sharding (appending a random suffix to partition keys for high-volume items) to spread writes across multiple partitions for genuinely hot items.

**Aurora Sharding.** Aurora doesn't shard natively. For horizontal write scaling on Aurora, the options are Aurora Limitless Database (sharded Aurora, managed), Vitess as a sharding proxy in front of MySQL, or application-level sharding where the application routes to multiple Aurora clusters. Aurora Limitless handles distributed transactions and cross-shard queries internally — the application sees one endpoint.

**RDS with application-level sharding.** Multiple RDS instances, one per shard. Application holds the routing logic — typically a shard map in configuration or a lightweight lookup service. Requires discipline: schema changes have to be applied to every shard, deployment and operations tooling needs to handle the multi-instance topology, and monitoring needs to aggregate across all shards to show a coherent picture.

**Amazon Keyspaces (Managed Cassandra).** Cassandra's data model is built around sharding. Partition key determines the shard (called a partition in Cassandra). All the shard key selection guidance above applies directly. Wide partitions — millions of rows under one partition key — are a well-known Cassandra performance problem. Keyspaces inherits this fully.

| Strategy | Range queries | Write distribution | Resharding complexity | Best for |
|---|---|---|---|---|
| Range-based | Efficient | Uneven (hotspot risk) | Moderate | Time-series, ordered data |
| Hash-based | Scatter-gather | Even | High | User data, even access patterns |
| Directory-based | Depends on directory | Flexible | Low (directory update) | Frequent shard reassignment |
| Managed (DynamoDB) | Via GSI | Automatic | Handled by service | Variable or unknown scale |

## What's next

Day 12: circuit breakers — how to stop a failing dependency from taking down everything that depends on it, and the failure modes that circuit breakers don't catch.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
