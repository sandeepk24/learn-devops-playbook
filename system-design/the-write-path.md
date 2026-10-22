# The Write Path

A client submits data. That data travels through a chain of components — load balancer, application server, cache, queue, database — and at each step something happens to it. Understanding exactly what happens at each layer, in what order, and what the failure modes are, is the difference between a system that loses data under failure and one that doesn't.

Most reliability bugs live in the write path. A read that returns stale data is annoying. A write that silently disappears is a data loss incident. The write path deserves more deliberate design than it usually gets.

## Fundamentals

### The layered write journey

A typical write request traverses this sequence:

```
Client
  │
  ▼
Load Balancer (TLS termination, routing)
  │
  ▼
Application Server (validation, auth, business logic)
  │
  ├──► Cache (invalidate or update)
  │
  ├──► Message Queue (async side effects)
  │
  └──► Database (durable commit)
         │
         └──► Replica (async replication)
```

Each hop is a potential failure point. Each failure point needs a defined behavior.

### Durability guarantees per layer

Not every layer has the same durability guarantee. Understanding which layer is the durability boundary is critical.

**Database with fsync.** A committed transaction on a properly configured database is durable — the data is on disk, the write-ahead log is flushed, and a crash after the commit will recover the write. PostgreSQL's `synchronous_commit = on` (default) flushes the WAL to disk before acknowledging the commit. Turning it off improves throughput but risks losing the last few milliseconds of commits on a crash.

**In-memory store (Redis without persistence).** A write acknowledged by Redis may be in memory only. If the Redis process restarts before an RDB snapshot or AOF append, the write is gone. Redis is not a durable write destination by default. Using it as one is a common source of data loss.

**Message queue.** SQS Standard: at-least-once delivery, data replicated across multiple AZs. Messages are durable after the SendMessage call returns. A write to SQS followed by a database write is a common pattern — but if the database write fails after the SQS send succeeds, the message was sent for data that was never committed. The outbox pattern (Day 21) fixes this.

**Application server memory.** No durability. A buffered write that hasn't reached the database is lost on process restart. Batching writes in application memory for throughput improvement must be paired with a crash recovery mechanism.

### Write ordering and conflicts

Multiple writers. Same data. Order matters.

**Last-writer-wins (LWW).** The most recent write by timestamp wins. Simple. Silently discards concurrent writes. Safe when writes from different clients rarely conflict. Dangerous when they frequently do — DynamoDB Global Tables uses LWW; two concurrent writes to the same item from different regions means one disappears.

**Optimistic concurrency control.** Read the current version, write the update with a conditional check that the version hasn't changed. If someone else wrote in between, the conditional fails and the writer retries. No locks held during the write. High throughput, with retry cost on conflict. Common pattern: include a `version` field in the row, use `WHERE version = :expected_version` in the update.

**Pessimistic locking.** Lock the row before reading, hold it through the update, release after commit. Prevents conflicts entirely. Serializes concurrent writes. Throughput bottleneck under high concurrency. Correct for operations where conflict resolution is complex or impossible.

```
Optimistic concurrency control:

SELECT id, balance, version FROM accounts WHERE id = 123
-- balance = 1000, version = 5

-- compute new balance
new_balance = 1000 - 200 = 800

UPDATE accounts
SET balance = 800, version = 6
WHERE id = 123 AND version = 5   -- fails if another write changed version
-- rowcount = 0? Someone else wrote. Retry.
-- rowcount = 1? Success.
```

## Operations

### The dual-write problem

Write to the database. Write to the cache. Write to the search index. Write to the event bus. Four writes. Four failure points. If the database write succeeds but any of the others fail, the system is inconsistent.

Dual-write is a design antipattern. It can never be made perfectly atomic across different systems without a distributed transaction (Day 21), and distributed transactions have their own costs.

The solutions:
- **Outbox pattern.** Write to the database only. A relay process reads the database and propagates to other systems. The database write is the single durable anchor. Everything else derives from it.
- **CDC (Change Data Capture).** Read the database's WAL or binlog. Every committed write produces an event. The search indexer, the cache invalidator, and the event bus consumer all read from the same CDC stream. One database write fans out reliably without dual-write in the application.
- **Cache write-through.** Cache updates are part of the database write transaction in a write-through cache. Still dual-write, but the cache library handles the coordination and typically accepts eventual failure of the cache write (the cache becomes a miss, origin is hit, cache is re-populated on next read).

### Write amplification

One logical write triggers multiple physical writes. A database insert updates the table, updates every index on that table, writes the WAL entry, and writes the undo log entry. An EBS volume with RAID 1 writes every byte twice. A DynamoDB table with five GSIs writes the item once and fans out to all five GSIs.

Write amplification isn't always a problem — it's the cost of durability, indexing, and replication. It becomes a problem when it's invisible and drives resource consumption you didn't account for.

Know the write amplification factor of your stack. An application doing 1,000 logical writes per second to a database with three indexes is doing approximately 8–10 physical writes per second per logical write (table data, WAL, three indexes, undo log). Provision storage IOPS for physical writes, not logical writes.

### Backpressure on the write path

The application writes faster than the database can commit. The connection pool fills. New write requests queue for a connection. Queue depth grows. Response latency increases. Users experience timeouts.

This is backpressure propagating up the write path. The database's write throughput ceiling is the binding constraint, and everything upstream backs up when that ceiling is hit.

Mitigations:
- **Write queuing.** Accept writes into a queue (SQS, Kinesis). Acknowledge to the client immediately. A consumer writes to the database at a sustainable rate. Decouples client-facing latency from database throughput. Cost: writes are now asynchronous — the client acknowledgment is not a durability guarantee.
- **Write batching.** Accumulate writes and flush in batches. Reduces per-write overhead. DynamoDB `BatchWriteItem` reduces request count. SQL bulk insert reduces per-row transaction overhead.
- **Database vertical scaling.** More IOPS, more CPU, more memory for buffer pool. Moves the ceiling up. Not indefinite.
- **Write sharding.** Route writes across multiple database instances. Removes the single-instance write ceiling entirely. Adds the complexity of sharding (Day 11).

## Deep Dive: the write path on AWS

**RDS write path.** Client write → application tier → RDS primary. The primary writes to EBS. EBS is network-attached block storage — the write crosses a network hop from the RDS host to the EBS volume before the fsync is acknowledged. EBS Multi-AZ stores data on two physical storage nodes for durability. The application gets the commit acknowledgment only after EBS confirms the write.

For RDS Multi-AZ (synchronous standby), the primary additionally replicates the WAL to the standby before acknowledging the commit. The standby applies the WAL asynchronously after acknowledging receipt. The commit acknowledgment waits for the standby to receive, not apply, the WAL — so there's a small window where a primary crash could lose changes the standby received but hadn't applied. In practice, RDS Multi-AZ failover recovers this via WAL replay on the standby.

**Aurora write path.** Different. Aurora separates compute (the DB instance) from storage (the Aurora storage layer). Writes go from the compute node to the Aurora distributed storage service — six storage nodes across three AZs. A write is acknowledged when four of six nodes confirm receipt. Crash recovery reads from the storage nodes, which have the complete log. No WAL replication to a standby because the storage layer is shared. This is why Aurora failover is faster than RDS Multi-AZ — the new primary reads from the same storage the old primary was writing to.

**DynamoDB write path.** Write hits a request router, is forwarded to the primary node for the partition. The primary writes to local storage and replicates to two secondary nodes. The write is acknowledged when the primary and one secondary confirm receipt. This is the durability guarantee — two out of three nodes have the write before acknowledgment. The third node catches up asynchronously.

DynamoDB Streams captures every write as a stream record. Each record contains the before and after state of the item. Retention is 24 hours. Lambda can be triggered from the stream for real-time downstream propagation — the reliable fan-out alternative to application-level dual-write.

**SQS as a write buffer.** Application receives a high-velocity write request. Validates it. Writes to SQS (durable, fast). Returns 202 Accepted to the client. A Lambda consumer reads from SQS and writes to RDS at the sustainable rate. The queue absorbs bursts. If the database slows down, the queue depth grows instead of the client latency growing. Set a CloudWatch alarm on queue depth and age — sustained growth means the consumer can't keep up.

**Kinesis for high-throughput ordered writes.** Ordered write stream per shard. Records retained up to 365 days. Multiple consumers read the same stream. A writer producing 10,000 events/second to Kinesis can have a Lambda consumer writing to DynamoDB, an Firehose delivery to S3, and a Flink application doing aggregations — all from the same Kinesis stream, all at their own pace. The write path fan-out is handled by Kinesis, not by the application.

| Write durability guarantee | Acknowledgment means | Failure risk |
|---|---|---|
| PostgreSQL `synchronous_commit=on` | WAL on disk | None after ack |
| PostgreSQL `synchronous_commit=off` | WAL in OS buffer | Loss of last ~200ms on crash |
| Redis (no persistence) | In memory only | Lost on restart |
| Redis AOF `always` | Appended to AOF on every write | None after ack |
| RDS Multi-AZ | WAL received by standby | Near zero |
| Aurora | 4/6 storage nodes confirmed | Near zero |
| DynamoDB | 2/3 partition nodes confirmed | Near zero |
| SQS Standard | Replicated across multiple AZs | Near zero |

## What's next

Day 35: the read path — how queries traverse the stack, the caching hierarchy that reduces origin load, and the read patterns that break assumptions built into naive implementations.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
