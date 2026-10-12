# Message Queues and Async Messaging

Two services need to talk. The obvious solution: one calls the other directly. Synchronous. Simple. Works until one of them is slow, or down, or overwhelmed — and then the failure propagates immediately to the caller.

A queue sits between them. Decouples the two sides. Producer drops a message and moves on. Consumer picks it up when it's ready. The systems no longer need to be healthy at the same time.

That's the value. The trade-off is you've now introduced delivery guarantees that need to be understood, failures that are asynchronous and therefore harder to trace, and a system that can accumulate a backlog in ways a synchronous call never would.

## Fundamentals

### Queues vs pub/sub

Two distinct patterns often lumped under "async messaging."

**Queue.** One producer, one consumer (or a pool of competing consumers). Each message is delivered once and only once to one consumer. Order may or may not be preserved depending on implementation. Good for distributing work across workers — job queues, task processing, anything where each unit of work should be handled by exactly one thing.

**Pub/sub.** One producer, many subscribers. Each subscriber gets every message. Producer doesn't know or care who's listening. Good for broadcasting events — something happened, multiple downstream systems need to know. Audit log, notification service, and analytics pipeline all get the same event independently.

```
Queue (competing consumers)          Pub/sub (fan-out)

Producer                             Publisher
   │                                    │
   ▼                                    ▼
[Queue]                              [Topic]
   │                                 /  |  \
   ├──► Consumer A (gets message 1) /   |   \
   ├──► Consumer B (gets message 2) ▼   ▼    ▼
   └──► Consumer C (gets message 3) Sub Sub  Sub
        (each message goes to one)  (each gets all)
```

### Delivery guarantees

This is where people get surprised. Guarantees sound absolute in documentation. They're not.

**At-most-once.** Message is delivered zero or one times. Fast. Simple. Acceptable only when lost messages don't matter. Logs, metrics, fire-and-forget notifications.

**At-least-once.** Message is delivered one or more times. The standard guarantee for most production queues. The consumer must be idempotent — processing the same message twice should have the same result as processing it once. If it isn't, you get duplicate side effects. Order records created twice. Emails sent twice.

**Exactly-once.** Delivered exactly one time, no duplicates, no losses. Sounds ideal. Genuinely difficult to implement across distributed systems. Some queues claim it but only within specific constraints. Read the fine print.

Most systems are designed around at-least-once delivery and idempotent consumers. That's the safe, practical default.

### Dead letter queues

Message arrives. Consumer fails to process it. Consumer retries. Fails again. This can loop indefinitely, blocking the queue or burning compute on a message that will never succeed.

Dead letter queues (DLQs) are where messages go after exhausting their retry attempts. They stop blocking the main queue, they preserve the message for investigation, and they give you a place to alarm on. A DLQ with messages in it means something is failing silently. If you're not alarming on DLQ depth, you won't know.

The message in the DLQ also tells you why it failed — if you're logging enough context in the consumer. Without that, DLQ debugging becomes guesswork.

## Operations

### Backpressure and queue depth

Consumers process at a fixed rate. Producer can write faster than that rate. Queue depth grows. Given enough time and a persistent imbalance, it grows unboundedly.

This is backpressure, and the failure mode is deceptive. The producer is healthy. The queue is healthy. Everything looks fine in the dashboard until someone notices messages are taking twenty minutes to process instead of ten seconds. The queue has depth that's hours old.

Alarm on queue depth, not just consumer errors. Sustained queue growth is a signal that the consumer fleet needs to scale, or that a consumer is stuck, before the depth becomes a user-visible latency problem.

### Consumer idempotency isn't optional

With at-least-once delivery, duplicate messages will arrive. Network retries, queue redelivery after consumer crashes mid-process, Lambdas being invoked twice — all of it happens. A consumer that isn't idempotent turns rare infrastructure events into data integrity bugs.

The standard approach: each message carries a unique ID. Consumer checks whether it's seen that ID before, either in a database or a short-lived cache. If yes, skip. If no, process and record. Adds a read per message but keeps the logic clean.

Systems that skip this work fine in development, fail intermittently in staging, and create production incidents on the worst possible days.

### Ordering guarantees

Most distributed queues don't guarantee strict global ordering, and the ones that do trade throughput for it. SQS standard queues, for example, are best-effort ordered. Messages can arrive out of sequence.

If ordering matters — event sourcing, financial transaction sequences, audit trails — either use a queue that provides ordering guarantees within a partition (Kafka, SQS FIFO), or design the consumer to reconstruct order using timestamps or sequence numbers in the message itself.

FIFO queues typically have lower throughput limits than standard queues. Know the limit before you choose one.

## Deep Dive: async messaging on AWS

Three services cover most use cases. They're not interchangeable.

**SQS (Simple Queue Service).** Queue. At-least-once delivery on standard queues. FIFO queues add exactly-once processing and ordered delivery within a message group, at the cost of throughput (3,000 messages/sec with batching vs. effectively unlimited for standard). Long polling reduces empty receives and costs. Visibility timeout controls how long a message is hidden from other consumers while being processed — set it to at least your p99 processing time or messages will be redelivered before the first consumer finishes.

**SNS (Simple Notification Service).** Pub/sub. Topic receives a message, fans out to all subscribers. Subscribers can be SQS queues, Lambda functions, HTTP endpoints, email addresses. SNS to SQS is the canonical fan-out pattern — broadcast to a topic, each SQS queue gets its own copy, each downstream service processes independently at its own pace.

**EventBridge.** Event bus. More structured than SNS — events have a schema, routing rules filter on content. Better for event-driven architectures where different consumers care about different event types. Native integration with dozens of AWS services as event sources. EventBridge Pipes connects sources to targets with optional filtering and transformation, reducing the glue code between services.

The SNS + SQS combination is worth knowing well:

```
Service A
    │
    ▼
[SNS Topic]
   / | \
  /  |  \
 ▼   ▼   ▼
SQS SQS SQS
 │   │   │
 ▼   ▼   ▼
Svc Svc Svc
 B   C   D
```

Each downstream service gets a dedicated queue, controls its own consumption rate, has its own DLQ, and scales independently. Adding a new consumer means adding a new SQS subscription to the SNS topic — no changes to Service A.

Lambda trigger configuration on SQS: batch size and batch window control how many messages Lambda receives per invocation. Concurrency controls how many invocations run in parallel. Set reserved concurrency on the Lambda to prevent it from consuming the entire account's concurrency and starving other functions under queue surge.

| | SQS Standard | SQS FIFO | SNS | EventBridge |
|---|---|---|---|---|
| Model | Queue | Queue | Pub/sub | Event bus |
| Ordering | Best-effort | Strict (per group) | N/A | N/A |
| Delivery | At-least-once | Exactly-once | At-least-once | At-least-once |
| Throughput | Unlimited | 3k/sec (batched) | Unlimited | 10k/sec default |
| Best for | Work distribution, decoupling | Ordered processing | Fan-out | Event-driven routing |

## What's next

Day 9: rate limiting — the algorithms behind it, where to enforce it, and what happens when you don't.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
