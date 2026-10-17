# Consensus and Leader Election

Distributed systems need to agree on things. Which node is the leader. Whether a transaction committed. What the current configuration is. Getting multiple nodes to agree on a single value, in the presence of failures and network delays, is the consensus problem. It's one of the harder problems in distributed systems, and the reason it matters operationally is that the systems you depend on every day — etcd, ZooKeeper, your database's failover mechanism — are built on consensus protocols.

You don't need to implement a consensus algorithm. You need to understand what they guarantee, what they cost, and what breaks when the cluster running them loses quorum.

## Fundamentals

### Why consensus is hard

Two nodes. Node A writes a value. Node B reads it. If the network between them drops after the write, B reads stale data. If A crashes after writing but before B reads, the write might be lost. If both think they're the leader and both accept writes, data diverges.

Solving any one of these problems in isolation is straightforward. Solving all of them simultaneously, without a central coordinator that's itself a single point of failure, requires a protocol that can tolerate partial failures without producing inconsistent results.

The fundamental result is FLP impossibility: in an asynchronous network where nodes can fail, there is no deterministic consensus algorithm that is guaranteed to terminate. In practice, systems work around this by assuming that failures are eventually detected and that the network eventually delivers messages — weak timing assumptions that hold most of the time.

### Raft

The readable consensus algorithm. Designed explicitly to be understandable, unlike Paxos. Used in etcd, CockroachDB, TiKV, and others.

Three roles: **leader**, **follower**, **candidate**.

One leader at a time. The leader accepts all writes, replicates them to followers, and commits once a majority (quorum) acknowledges receipt. Followers are passive — they receive log entries from the leader and respond to client reads if the deployment allows it.

Leader election: if followers don't hear from the leader within an election timeout, they become candidates and request votes. A candidate wins if it receives votes from a majority of nodes. The winner becomes the new leader. Election timeouts are randomized to prevent split votes where multiple candidates run simultaneously and no one gets a majority.

```
Normal operation:

Client ──write──► Leader
                    │ replicate to followers
                    ├──► Follower A ──ack──►┐
                    ├──► Follower B ──ack──►┤ quorum (2 of 3) ──► commit
                    └──► Follower C         │
                         (slow or down)
```

The write is committed once a majority acknowledges it — not all nodes. A three-node cluster tolerates one failure. A five-node cluster tolerates two. The quorum requirement is `floor(N/2) + 1`. Below quorum, the cluster can no longer commit writes. It becomes read-only, or stops entirely, depending on configuration. This is the correct behavior — accepting writes without quorum risks data loss.

### Paxos

The original consensus algorithm. Proven correct. Notoriously difficult to understand and implement. Most production systems that claim to use Paxos use a heavily modified variant (Multi-Paxos, Fast Paxos, Flexible Paxos). Google's Chubby, Spanner, and Megastore are built on Paxos variants.

Understanding Paxos at the protocol level matters less for operational work than understanding what Raft gives you — the concepts are equivalent in guarantees, and Raft's design maps more cleanly to operational reasoning.

### Quorum math

This is the part with immediate operational implications.

A cluster of N nodes requires a quorum of `floor(N/2) + 1` nodes to make progress.

- 1 node: quorum = 1. No fault tolerance. One failure stops the cluster.
- 3 nodes: quorum = 2. Tolerates 1 failure.
- 5 nodes: quorum = 3. Tolerates 2 failures.
- 7 nodes: quorum = 4. Tolerates 3 failures.

Even-numbered clusters are almost always wrong. A 4-node cluster has quorum of 3 — it tolerates 1 failure, same as a 3-node cluster. You're paying for an extra node without gaining fault tolerance. The 4th node adds availability for reads in some configurations, but for write quorum it's equivalent to 3 nodes. Always use odd-numbered clusters unless you have a specific reason.

## Operations

### What happens when quorum is lost

The cluster stops accepting writes. In etcd: `etcdserver: no leader` errors. In RDS Multi-AZ: failover initiates but might not complete if the standby is also unreachable. In Consul: no leader, service discovery returns stale data or errors.

The cluster doesn't know whether it lost quorum due to a real failure or a network partition. If it's a partition — two sides, both healthy — allowing writes on both sides would create a split-brain. The safe behavior is to stop. This is the availability cost of consistency: CAP theorem in practice.

Recovery from quorum loss depends on the system. etcd in a bad state may require manual intervention to restore a member, bootstrap from a snapshot, or in extreme cases re-initialize the cluster from backup. These are recoverable situations but they require knowing the procedure ahead of time. Reading the etcd disaster recovery documentation before you need it is time better spent than during an incident.

### Election storms

Repeated leader elections in a short period — election storm — indicate instability. Common causes: network latency fluctuations causing followers to time out on a healthy leader, a leader under heavy load not sending heartbeats fast enough, misconfigured election timeouts too short for the network conditions, or a node repeatedly crashing and triggering re-elections.

Each election causes a brief window where no writes are accepted. Frequent elections mean frequent write unavailability, even if each individual election resolves quickly. Monitor election frequency as a cluster health signal.

### etcd in Kubernetes

Every Kubernetes API write goes to etcd. All cluster state lives there. etcd runs in the control plane — three or five instances in a production cluster.

etcd performance is dominated by disk latency. Heartbeats and log appends go to disk before being acknowledged. SSDs are not optional for etcd. On slow disks, heartbeat timeouts fire, elections happen, and the API server degrades. EKS manages the etcd cluster; self-managed Kubernetes means you're responsible for etcd disk I/O, backup schedules, and knowing how to restore from a snapshot.

The EKS control plane includes etcd on managed infrastructure. You don't directly operate it. What you do affect: API write load. Heavy use of the Kubernetes API — controllers running tight reconciliation loops, excessive `kubectl apply` in CI pipelines, admission webhooks that do synchronous work — translates directly to etcd write load. etcd compaction (periodic squashing of old log entries) is a normal operation but causes brief latency spikes under high write load.

## Deep Dive: consensus on AWS

**EKS control plane.** etcd-backed, managed by AWS. Multi-AZ by default on production tiers. etcd health is not directly observable; the signal is API server availability and latency. CloudWatch metrics for the EKS control plane: `APIServerRequestCount`, `APIServerRequestLatency`. A latency spike on the control plane often traces back to etcd pressure.

**RDS Multi-AZ (synchronous).** Not Raft, but implements a form of consensus for failover. Primary and synchronous standby. On primary failure, RDS automatically promotes the standby. The decision to fail over is made by the RDS internal monitoring infrastructure, not by a Raft quorum — but the effect is similar: only one writer at a time, promotion is automatic, failover takes 60–120 seconds.

**Amazon MQ / MSK (Kafka).** Kafka used to depend on ZooKeeper for leader election and cluster metadata. KRaft mode (Kafka without ZooKeeper) uses Raft internally. MSK clusters running KRaft no longer require a separate ZooKeeper cluster, simplifying operations and reducing the number of systems that can lose quorum.

**Route 53 and DynamoDB.** AWS's global infrastructure services use internal consensus mechanisms you don't operate directly. The operational implication: they have availability SLAs built on the assumption that their consensus infrastructure works. When an AWS region has a control plane event, it often affects services that depend on internal consensus for routing and metadata — not because the data plane failed, but because the control plane couldn't elect a leader or commit a configuration change.

| System | Protocol | Quorum | Failure tolerance (3-node) |
|---|---|---|---|
| etcd | Raft | Majority | 1 node |
| Consul | Raft | Majority | 1 node |
| ZooKeeper | ZAB (Raft-like) | Majority | 1 node |
| CockroachDB | Raft (per-range) | Majority | 1 node |
| RDS Multi-AZ | AWS-managed | N/A (2-node + arbiter) | 1 node |

## What's next

Day 20: microservices vs monolith — not a rehash of the usual arguments, but a look at the operational costs that accumulate on each side, and the signals that tell you which direction to move.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
