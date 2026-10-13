# Consistent Hashing

Distribute data across nodes. Simple problem. The naive solution: `hash(key) % N` where N is the number of nodes. Works until N changes. Add a node, remove a node, and almost every key maps to a different node. Cache misses everywhere. Database connections scatter. The redistribution cost is enormous.

Consistent hashing solves this. When the fleet size changes, only the keys that need to move actually move. The rest stay put.

## Fundamentals

### The ring

Consistent hashing places both nodes and keys on a circular hash space — a ring of values from 0 to 2³². Each node is hashed to a position on that ring. Each key is hashed to a position on the ring. A key is owned by the first node encountered traveling clockwise from the key's position.

```
              0
           ●  │  ●
        ●     │     ●
      ●    Node A    ●
     ●    /         \ ●
    ●  Key X         ●
    ●                ●
     ● Node C     Node B ●
      ●    \       /   ●
        ●     \ /   ●
           ●  │  ●
             2³²

Key X hashes between Node C and Node A → owned by Node A
```

Add a new node between two existing nodes. Only the keys between the predecessor and the new node need to move — from the new node's clockwise neighbor to the new node itself. Remove a node. Only that node's keys need to move to its clockwise successor. Everything else is undisturbed.

In the naive `hash % N` approach, adding one node to a ten-node cluster moves roughly 90% of keys. With consistent hashing, it's roughly 1/N — in this case, 10%.

### Virtual nodes

Pure consistent hashing with one position per node has a problem: the distribution is uneven. Nodes land at arbitrary positions on the ring, and depending on spacing, one node might own 30% of the keyspace while another owns 5%.

Virtual nodes fix this. Each physical node is assigned multiple positions on the ring — typically dozens to hundreds. Each position is a "virtual node." The keyspace gets divided more evenly because each physical node is represented in many places.

Virtual nodes also simplify heterogeneous fleets. A larger node gets more virtual nodes, giving it a proportionally larger share of the keyspace. Remove a node and its virtual nodes' keys scatter to whichever physical nodes own the adjacent positions — a natural, even redistribution.

### Consistent hashing vs modular hashing

| | Modular hashing | Consistent hashing |
|---|---|---|
| Formula | `hash(key) % N` | Position on ring → clockwise owner |
| Keys moved on node add/remove | ~(N-1)/N ≈ most of them | ~1/N |
| Implementation complexity | Trivial | Moderate |
| Distribution evenness | Even (by definition) | Uneven without virtual nodes |
| Best for | Static, fixed-size fleets | Dynamic fleets, caches, distributed storage |

## Operations

### Where this actually matters

**Distributed caches.** The most common application. Consistent hashing is why adding a cache node doesn't cause a thundering herd against the origin — only the keys that migrate cause misses. Without it, a cache resize would blow the cache for every key simultaneously.

**Distributed databases.** Cassandra, DynamoDB, and Riak all use consistent hashing (or close variants) to partition data across nodes. Each token range on the ring corresponds to a partition. Adding nodes means moving only the affected token ranges, not a full reshard.

**Load balancing for stateful connections.** When backend state is tied to a specific server — game sessions, WebSocket connections, sticky caches — consistent hashing routes the same client to the same backend. Unlike cookie-based stickiness, it doesn't require the load balancer to track session affinity explicitly. The hash of the client identifier determines the backend.

### Hotspots

Consistent hashing distributes keys evenly across the ring, but it doesn't account for access patterns. A single very popular key — a celebrity account, a viral piece of content, a globally shared configuration object — still lands on one node. That node gets hammered regardless of how even the key distribution is.

Hotspots are a key distribution problem, not a node assignment problem. Mitigations: replicate hot keys to multiple nodes with a randomized suffix (`key:0`, `key:1`, `key:2`), scatter reads across the replicas. Or cache at a higher layer so the hotspot never reaches the consistent hashing tier. Consistent hashing doesn't solve hot keys. Know that going in.

### Replication factor

Production consistent hashing deployments don't just assign a key to one node. They replicate across the next N nodes clockwise on the ring. Cassandra calls this the replication factor. If a node is down, the key is still readable from its replicas.

This intersects with CAP theorem decisions covered in Day 4. Reading from the closest replica is faster but might return stale data. Reading from a quorum of replicas is slower but consistent. The ring topology is just the assignment mechanism — consistency guarantees are a separate layer on top.

## Deep Dive: consistent hashing on AWS

AWS doesn't expose consistent hashing directly as a primitive you configure, but it's the mechanism underneath several services.

**ElastiCache (Redis Cluster Mode).** When cluster mode is enabled, Redis shards data across multiple nodes using a hash slot scheme (16,384 slots). Nodes own ranges of slots. Adding or removing nodes redistributes only the affected slot ranges. This is consistent hashing under the surface, with Redis managing the ring internally. When you resize a cluster, client connections that hit migrating slots get a `MOVED` redirection; the client follows it transparently if using a cluster-aware client.

**DynamoDB.** Partitions data using consistent hashing internally. You don't see the ring. What you do see: partition keys that hash well distribute load evenly; partition keys with low cardinality create hot partitions. The operational implication of consistent hashing here is to choose partition keys with high cardinality and even access distribution — the hash is only as good as the input it's given.

**Elasticache Memcached.** Client-side consistent hashing. The Memcached cluster itself is dumb — it doesn't know about the other nodes. The client library hashes keys and routes to nodes. When you add a node to the ElastiCache Memcached cluster, you update the client configuration, and the client library redistributes only the affected keys. No server-side coordination required.

For services that need custom consistent hashing — building a distributed cache layer, sharding work across Lambda invocations, routing WebSocket connections — the implementation is straightforward in any language. The ring is a sorted array of virtual node positions; lookup is a binary search to find the first node clockwise from the key's hash.

## What's next

Day 11: database sharding — when a single node's storage or write capacity is the ceiling, and how to split data horizontally across multiple databases.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
