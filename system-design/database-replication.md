# Database Replication

Replication copies data from one node to others. The reason you care: a single database node is a single point of failure, and at some point it becomes a read bottleneck. Replication solves both. What it doesn't solve — what it introduces — is a consistency problem you now have to manage deliberately.

## Fundamentals

### Primary and replica

One node accepts writes. The primary. Replicas receive a copy of those writes and apply them. Reads can go to either. Writes go to one place.

That asymmetry is the whole model. Everything else is a consequence of it.

**Synchronous replication.** The primary waits for at least one replica to confirm the write before acknowledging success to the client. Data loss on primary failure: zero. Cost: every write's latency now includes a network round trip to the replica. If the replica is in another AZ or region, that cost is real. If the replica is slow or unreachable, writes block.

**Asynchronous replication.** Primary acknowledges success immediately, replicates in the background. Write latency stays low. But there's now a window — replication lag — where the replica is behind. Primary dies in that window, and the replica promotes with missing writes. Data loss is possible. How much depends on how wide that lag was.

Neither is better. They're different bets on what you can tolerate.

```
Synchronous                          Asynchronous

Client                               Client
  │                                    │
  ▼                                    ▼
Primary ──write──► Replica           Primary ──ack──► Client
  │        │                           │
  │      ack                           └──write──► Replica
  │        │                                        (background)
  ▼        ▼
  ack to client (after replica confirms)
```

### Replication lag

Lag is the delay between a write landing on the primary and that write being visible on a replica. Under normal load it's milliseconds. Under high write load, a slow replica, or a network hiccup, it grows. Minutes, occasionally more.

The problem isn't the lag itself. The problem is forgetting it exists and routing reads to replicas that silently return stale data. User updates their email address, gets routed to a replica, sees the old one. Support ticket. "The site is broken." The site isn't broken. The read routing is wrong.

Know your replication lag. Set an alarm on it. Route reads that require freshness to the primary.

### Read replicas vs standby replicas

Not the same thing.

**Read replicas** are for scaling read throughput. Offload SELECT-heavy workloads — reports, search, analytics — to replicas so the primary handles writes without competing with queries that don't need to be there.

**Standby replicas** are for failover. Warm copy of the primary, ready to be promoted if the primary goes down. Some standbys accept reads; others don't. The important thing: their job is availability, not capacity. Treating a standby as a read replica adds read traffic to a node whose health you depend on for failover, which is a choice with consequences.

## Operations

### The failover sequence

Primary goes down. Replica needs to promote. Clients need to point at the new primary. This sequence is where most of the pain lives.

Automatic failover is better than manual — you don't want to be fumbling for a runbook at 2 AM. But automatic failover requires the system to confidently detect that the primary is actually down, not just slow or temporarily unreachable. Promote too early and you might have two nodes that both think they're primary, both accepting writes, diverging. That's a split-brain scenario, and cleaning it up is not a quick job.

Promotion time matters. During the window between primary failure and replica promotion, writes are failing. For most systems, a few seconds is acceptable. A few minutes is not. Know your promotion time before the incident, not during it.

After failover, old connections pointing at the original primary need to reconnect to the new one. If your application is holding a hardcoded IP or a connection that doesn't know to retry against a new endpoint, it doesn't automatically follow the failover. DNS-based failover with short TTLs is the standard approach — the endpoint stays the same, the DNS record updates. Connection pools need to respect the TTL and re-resolve.

### Replication lag under write spikes

Replicas apply writes sequentially by default. Primary can parallelize writes across tables and indexes. Under a write-heavy spike, the replica falls behind because it's doing single-threaded replay of a multi-threaded write stream. Modern database engines have improved this with parallel replication, but it's still a common failure mode.

If your read replicas are used for time-sensitive reads and you're running a batch import or migration on the primary, lag will spike. Plan for it. Either pause the traffic on those replicas, or route those reads back to the primary during the window, or accept that users will see stale data and make sure that's actually acceptable.

### Cascading replicas

In large fleets, replicas sometimes replicate from other replicas rather than directly from the primary. Reduces load on the primary. Adds a second hop of lag. A replica replicating from another replica is always at least as far behind as its source, often more. Fine for analytics workloads that already tolerate lag. Not fine for anything that needs reasonable freshness.

## Deep Dive: replication on AWS

**RDS Multi-AZ.** Synchronous replication to a standby in a second AZ. Not a read replica — the standby doesn't serve reads by default. Exists purely for failover. Failover time is typically 60–120 seconds, though AWS has gotten this down in newer configurations. The endpoint doesn't change; DNS flips to the new primary automatically.

**RDS Read Replicas.** Asynchronous. Up to 15 replicas for MySQL and MariaDB, 5 for PostgreSQL. Each has its own endpoint. Application is responsible for routing. Can be promoted to standalone databases — useful for migrations, but promotion breaks the replication chain.

**Aurora.** Different model. Storage is shared across all instances in the cluster — primary and up to 15 read replicas all read from the same distributed storage layer. Replication lag is typically under 10ms because replicas don't receive and apply a write stream; they read from storage that's already been written. Failover is faster than standard RDS Multi-AZ, under 30 seconds in most cases. Aurora Global Database extends this across regions asynchronously, typical lag under a second.

**DynamoDB Global Tables.** Multi-region, multi-primary. All regions accept writes. Replication is asynchronous. Conflicts are resolved by last-writer-wins. If two regions write the same item simultaneously, one write is silently dropped. Know this before you design a workflow that assumes global write consistency.

The monitoring signal that matters most: replication lag per replica, tracked over time. In RDS, `ReplicaLag` in CloudWatch. For Aurora, `AuroraReplicaLag`. Set an alarm at whatever threshold starts to affect your application — for most OLTP systems, lag over a second on a read replica is worth knowing about.

| | Synchronous | Asynchronous |
|---|---|---|
| Write latency | Higher (waits for replica ack) | Lower (fire and forget) |
| Data loss on failure | None | Possible (lag window) |
| Replica availability dependency | Write blocks if replica is down | Write succeeds regardless |
| Best for | Financial data, anything zero-RPO | Read scaling, analytics, cross-region copies |
| AWS examples | RDS Multi-AZ standby | RDS Read Replicas, Aurora cross-region, DynamoDB Global Tables |

## What's next

Day 8: message queues and async messaging — when to put a queue between two systems, what you gain, and the guarantees that sound stronger than they are.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
