# CAP Theorem

Everyone's heard of it. Most people can recite it. Fewer apply it correctly under pressure.

CAP stands for Consistency, Availability, Partition Tolerance. The theorem says a distributed system can guarantee at most two of the three. That framing has caused more confusion than clarity, because it implies you're making a peaceful architectural choice at design time. You're not. You're deciding what your system does when things break.

## Fundamentals

### What the three letters actually mean

**Consistency** here means every read receives the most recent write, or an error. Not "data is correct" in the general sense. Specifically: after a write completes, any subsequent read — from any node — returns that value.

**Availability** means every request gets a response. Not a correct response necessarily. A response. No timeouts, no errors, something comes back.

**Partition Tolerance** means the system continues operating when network messages between nodes are dropped or delayed. Nodes can't communicate. System keeps running.

Now the important part: you don't choose whether to tolerate partitions. Partitions happen. Network links drop. Packages get lost. If you're running any distributed system at scale, you will experience partitions. Partition tolerance isn't optional. The real choice, the only real choice, is what happens during a partition — do you stay consistent, or do you stay available?

### CP vs AP. That's the actual decision.

**CP systems** — consistent, partition-tolerant. During a partition, they refuse to serve stale data. Return an error instead. Bank transaction. Inventory count. Anything where a wrong answer is worse than no answer.

**AP systems** — available, partition-tolerant. During a partition, they keep responding. Possibly with stale data. Shopping cart. Social feed. Anything where "might be slightly out of date" beats "site is down."

```
                     Network Partition Occurs
                              │
                              ▼
               ┌──────────────────────────┐
               │  Node A ←──✗──→ Node B  │
               └──────────────────────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                              ▼
          Stay Consistent               Stay Available
          (refuse the read,             (return what you have,
           return an error)              possibly stale)
               │                              │
               ▼                              ▼
          CP System                      AP System
    (HBase, Zookeeper,              (Cassandra, CouchDB,
     etcd, Consul)                   DynamoDB in some configs)
```

### The "CA" trap

You'll occasionally see "CA system" mentioned. Ignore it. A CA system — consistent and available, no partition tolerance — can only exist if the network never fails. That's a single node. Or nodes connected by a link that never drops. In practice, this doesn't exist at distributed scale. The CA label is a theoretical artifact.

## Operations

### Where people get this wrong

The mistake is treating CAP as a system-wide binary. Real systems aren't fully CP or fully AP. Different operations have different requirements.

DynamoDB is a good example. By default it's AP — eventually consistent reads, always available. But you can request strongly consistent reads, making that specific operation CP at the cost of higher latency and the possibility of errors during a partition. Same database. Both behaviors. The choice is per operation.

Same with Cassandra. Tunable consistency. You pick a consistency level per query. `ONE` is fast and AP. `QUORUM` or `ALL` moves toward CP. You're not "using a CP database" or "using an AP database." You're making a call per operation, based on what that data actually requires.

Know your data. Financial balances need consistency. User preferences probably don't. Apply the right behavior at the right layer instead of picking one camp for the whole system.

### Eventual consistency isn't "eventually maybe correct"

AP systems under partition reach consistency eventually — once the partition heals and nodes can sync. This confuses people into thinking eventual consistency means data can be wrong indefinitely. It doesn't. It means there's a window of inconsistency whose length depends on your replication topology and sync intervals.

DNS is the classic example. You update a record. Not every resolver sees it immediately. Eventually they all converge. That window might be seconds, might be hours depending on TTL. During it, different clients get different answers. All of them correct for their moment. The system isn't broken. It's working exactly as designed.

## Deep Dive: CAP on AWS

DynamoDB exposes this directly. Global Tables — multi-region replication — are AP by default. A write in us-east-1 replicates asynchronously to eu-west-1. During a network event between regions, eu-west-1 keeps serving reads from its local copy. Stale, but available. Heal the partition, replication catches up.

For CP behavior on AWS: etcd inside EKS control plane, ElastiCache in cluster mode with specific consistency settings, RDS with synchronous Multi-AZ replication (single-region, same partition domain — partition tolerance isn't the concern there, availability is).

Aurora Global Database is worth understanding specifically. Writes go to the primary region. Replication to secondary regions is asynchronous — AP across regions. But within a single region, Aurora is strongly consistent. Different CAP posture at different scopes. That's not a quirk, it's a deliberate design.

The operational implication: know which operations in your system cannot tolerate stale reads, and make sure the path those operations travel is consistent. Everything else can probably be AP. Most systems run the majority of their operations on AP paths and reserve CP behavior for the minority of operations where it actually matters.

| | CP | AP |
|---|---|---|
| During partition | Returns error or blocks | Returns potentially stale data |
| Priority | Correctness over availability | Availability over correctness |
| Use case | Financial data, leader election, distributed locks | Shopping carts, social feeds, DNS, caches |
| AWS examples | etcd, RDS Multi-AZ (intra-region) | DynamoDB Global Tables, Aurora cross-region |
| Risk if misapplied | Unnecessary downtime | Silent data inconsistency |

## What's next

Day 5: load balancing. Not the basics — every engineer knows what a load balancer does. The failure modes, the routing algorithms, and what actually happens to in-flight requests when a backend disappears.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
