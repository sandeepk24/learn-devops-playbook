# Idempotency and Exactly-Once Semantics

Networks fail. Processes crash. Retries happen. A request sent twice should not charge a credit card twice, create two orders, or send two confirmation emails. The property that makes retry-safe operations possible is idempotency: performing an operation multiple times produces the same result as performing it once.

Idempotency is not a framework feature. It's a design property you implement deliberately. And the places where systems skip it are where duplicate-processing bugs live — bugs that are rare enough not to appear in testing, common enough to appear in production, and difficult to detect because the system looks correct from the outside until someone checks the data.

## Fundamentals

### Idempotent vs non-idempotent operations

**Idempotent:** setting a value, updating a record to a specific state, deleting a record. Run the same operation ten times — the result after the tenth is the same as after the first.

**Non-idempotent:** incrementing a counter, inserting a row without uniqueness constraints, charging a payment, sending an email. Run twice, get two different outcomes.

HTTP methods carry idempotency semantics by convention. GET, PUT, and DELETE are idempotent. POST is not. A PUT to `/users/123` with a new email address can be repeated safely — the user has the new email regardless of how many times the request arrived. A POST to `/orders` creates a new order. Two identical POST requests create two orders.

Convention doesn't enforce anything. A poorly implemented PUT handler that logs an "update" event on every call is non-idempotent despite using the correct HTTP method.

### The idempotency key pattern

The standard mechanism for making non-idempotent operations safe to retry.

Client generates a unique key for the operation — a UUID, a hash of the request content, a combination of user ID and timestamp. The key is sent with the request (typically as an `Idempotency-Key` header or a field in the request body). Server stores the key alongside the result of the operation. If the same key arrives again, the server returns the stored result without re-executing.

```
First request:
Client ──► POST /payments { amount: 100, idempotency_key: "abc-123" }
Server:
  1. Check: has "abc-123" been processed? No.
  2. Execute: charge the card.
  3. Store: { key: "abc-123", result: { payment_id: "pay_789", status: "success" } }
  4. Return result.

Retry (network failure caused client to retry):
Client ──► POST /payments { amount: 100, idempotency_key: "abc-123" }
Server:
  1. Check: has "abc-123" been processed? Yes.
  2. Return stored result: { payment_id: "pay_789", status: "success" }
  3. No second charge.
```

Implementation requirements:
- The idempotency key store must be durable. An in-memory store loses keys on restart, and a restart during a payment retry is exactly the wrong time to lose keys.
- Lookup must be atomic with the operation. Check-then-execute with a gap between them allows two concurrent requests with the same key to both pass the check and both execute before either stores the result.
- Keys need a TTL. Storing idempotency keys forever grows the store unboundedly. 24 hours is standard. After the TTL, a retry is treated as a new request.

### Atomic check-and-store

The race condition: two requests with the same key arrive simultaneously. Both check the store, both find nothing, both execute, both try to store. One wins the store write. The other either overwrites it or fails. Either way, the operation ran twice.

Preventing this requires an atomic operation: check for the key and insert it in one operation that either succeeds or fails with a uniqueness violation. PostgreSQL: `INSERT ... ON CONFLICT DO NOTHING` returns a row count — zero means the key already exists. DynamoDB: conditional put with `attribute_not_exists(pk)` — succeeds only if the key isn't there.

```sql
-- PostgreSQL: atomic idempotency key reservation
INSERT INTO idempotency_keys (key, created_at)
VALUES ('abc-123', NOW())
ON CONFLICT (key) DO NOTHING
RETURNING key;

-- If RETURNING returns nothing, key already existed → return cached result
-- If RETURNING returns the key, proceed with the operation
```

### Exactly-once vs at-least-once

**At-least-once delivery:** every message is delivered, possibly more than once. The safe default for messaging systems. The consumer handles duplicates.

**Exactly-once delivery:** every message is delivered once and only once. Technically difficult to guarantee end-to-end. Requires coordination between the producer, the broker, and the consumer. In practice, "exactly-once" in most systems means "at-least-once with idempotent consumers" — the system may deliver duplicates, but the consumer's idempotent handling means duplicates don't produce duplicate effects.

True exactly-once requires:
1. The producer guarantees no duplicate production (Kafka's idempotent producer, enabled with `enable.idempotence=true`).
2. The broker guarantees each message is stored and delivered once.
3. The consumer's processing and offset commit happen atomically — if the consumer crashes after processing but before committing the offset, the message will be redelivered and reprocessed.

In Kafka, transactional producers enable atomic writes across multiple partitions and topics. Combined with transactional consumers that commit offsets and produce output in the same transaction, you get exactly-once semantics — but only within the Kafka ecosystem. If the consumer writes to an external database, you're back to at-least-once unless the database write itself is idempotent.

## Operations

### Idempotency in distributed transactions

Sagas (Day 21) are sequences of local transactions with compensating transactions. Each step in a saga needs to be idempotent. The saga orchestrator may retry a failed step. The message that triggers a choreography step may be delivered twice.

Step idempotency in a saga: each step receives an event with a unique event ID. Before executing, check whether this event ID has already been processed. If yes, return the stored result. If no, execute and store. The event ID is the idempotency key.

Compensating transactions also need to be idempotent. A compensation triggered twice — the orchestrator retried, the message was redelivered — should have the same result as one triggered once.

### Detecting duplicate processing

Even with idempotency keys, bugs happen. Idempotency key collisions, incorrect key generation, store failures before the key is written. Worth instrumenting.

Metrics to track:
- Count of idempotency key collisions per endpoint. A spike means clients are retrying, which indicates upstream failures.
- Count of operations where the key existed but the stored result was a failure state. These are retries of previously failed operations — clients should be using new keys, not retrying with the same key on a non-transient failure.
- Duplicate payment detection in the billing layer — cross-reference payment IDs against charges. An alert when two charges share the same order ID but different payment IDs is a canary for idempotency failures.

### The two generals problem

A client sends a request. The server processes it. The response is lost. The client doesn't know whether the operation succeeded. Should it retry?

If the operation is idempotent: yes, retry safely.

If the operation isn't idempotent and the client can't make it so: the client is stuck. It can assume success and not retry (risk of missing a real failure), or assume failure and retry (risk of duplicate execution). This is the two generals problem — reliable communication over an unreliable channel requires some form of shared state or acknowledgment protocol.

The answer for production systems: make operations idempotent, make the server return acknowledgments in a format clients can safely retry, and design client retry logic with idempotency keys. Don't leave the client in a position where it can't safely determine the outcome.

## Deep Dive: idempotency on AWS

**SQS and Lambda.** Lambda processes SQS messages with at-least-once delivery. On Lambda failure, the message returns to the queue and is redelivered. The Lambda function must be idempotent. Standard pattern: use the SQS message ID as the idempotency key. Check a DynamoDB table for the message ID before processing. Insert with a conditional put if not exists. If it exists, return without reprocessing.

**DynamoDB for idempotency key storage.** Conditional writes make DynamoDB a good fit for idempotency key stores. `attribute_not_exists(PK)` on a put item is atomic and guaranteed consistent. TTL on idempotency key items handles cleanup. DynamoDB's single-digit millisecond latency keeps the overhead of the idempotency check small.

The Powertools for AWS Lambda library (Python, Java, TypeScript) includes a built-in idempotency decorator backed by DynamoDB. A function decorated with `@idempotent` becomes safe to retry automatically, with configurable TTL and key extraction. Worth using rather than re-implementing the same pattern.

**API Gateway + Lambda idempotency.** API Gateway does not deduplicate requests. Two identical requests reach the Lambda function separately. The idempotency must be in the Lambda handler, not in API Gateway. For payment and order endpoints, always implement explicit idempotency key handling.

**Kinesis exactly-once with Flink.** Kinesis Data Analytics for Apache Flink implements exactly-once using checkpointing. Flink checkpoints application state and Kinesis shard offsets atomically at a configured interval (e.g., every 60 seconds). On failure, Flink restores the last checkpoint and re-reads from the saved Kinesis offsets. If the sink supports idempotent writes (writing to S3 with unique object keys, writing to DynamoDB with conditional puts), the end-to-end result is exactly-once.

**SNS message deduplication.** SNS does not deduplicate. SNS FIFO topics support message deduplication IDs — messages with the same deduplication ID within a 5-minute window are delivered once to each subscriber. For SQS FIFO queues receiving from SNS FIFO topics, deduplication is enforced by the queue. For standard SQS or Lambda subscribers, deduplication must be implemented in the consumer.

| Pattern | Mechanism | Atomic? | Durability | Best for |
|---|---|---|---|---|
| Idempotency key + DB | Check-then-insert with conditional write | Yes (with DB transactions) | Durable | REST APIs, payment endpoints |
| SQS message ID dedup | Message ID as key in DynamoDB | Yes | Durable | Lambda/SQS consumers |
| Kafka idempotent producer | Sequence numbers per partition | Yes | Broker-level | Kafka producer dedup |
| Kafka transactions | Atomic offset commit + output write | Yes | Broker-level | Exactly-once within Kafka |
| Flink checkpointing | State + offset checkpoint | Yes | S3-backed | Stateful stream processing |
| DynamoDB conditional put | `attribute_not_exists` | Yes | Durable | Any DynamoDB write dedup |

## What's next

Day 31: security and authentication — OAuth2, JWT, API keys, mTLS, and the authorization models that determine what authenticated identities can actually do.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
