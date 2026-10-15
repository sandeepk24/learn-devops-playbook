# Event-Driven Architecture

Two services can communicate two ways. One calls the other directly — synchronous, coupled, the caller waits for a response. Or one emits an event describing what happened, and any service that cares reacts to it — asynchronous, decoupled, the emitter doesn't know or care who's listening.

Event-driven architecture is the second model. It reduces coupling between services. It makes adding new consumers trivial — subscribe to the event stream, no changes to the producer. It's also harder to debug, harder to reason about consistency, and produces failure modes that are genuinely non-obvious until you've seen them in production.

It's not a better architecture. It's an architecture with different trade-offs, appropriate for specific problems.

## Fundamentals

### Events vs commands

The distinction matters and gets blurred constantly.

**Command.** "Do this thing." Directed at a specific service. Implies the sender wants something to happen. The receiver either does it or rejects it. One sender, one receiver. `CreateOrder`, `SendEmail`, `ChargeCard`.

**Event.** "This thing happened." Broadcast to anyone interested. No assumption about what anyone will do with it. Past tense. `OrderPlaced`, `PaymentProcessed`, `UserRegistered`. The producer doesn't know about the consumers. Adding a new consumer that reacts to `OrderPlaced` requires no changes to the order service.

Building an event-driven system on top of commands defeats the purpose. If your "events" are named `SendConfirmationEmail` or `UpdateInventoryCount`, those are commands dressed up as events. The producer is still dictating behavior to the consumer.

### Event sourcing vs event-driven

Often conflated. Different things.

**Event-driven.** Services communicate via events. The current state of a service is stored normally (relational database, document store). Events are the communication mechanism between services.

**Event sourcing.** The current state of an entity is derived from its event history. No mutable state stored. Want to know the current balance of an account? Replay all `Deposited` and `Withdrawn` events from the beginning. The event log is the source of truth, not a derived record.

Event sourcing is a data storage and modeling pattern. Event-driven is a communication pattern. You can use one without the other. Most systems using event-driven architecture don't use event sourcing.

Event sourcing is powerful for audit trails, time-travel queries, and systems where history is as important as current state. It's also expensive to implement correctly, and replaying thousands of events to reconstruct state has real performance implications unless you add snapshots. Reach for it when the problem genuinely calls for it.

### Choreography vs orchestration

Two ways to coordinate a multi-step process using events.

**Choreography.** Each service knows what to do when it receives an event. No central coordinator. Order service emits `OrderPlaced`. Payment service subscribes, processes payment, emits `PaymentProcessed`. Fulfillment service subscribes to `PaymentProcessed`, ships the order, emits `OrderShipped`. The workflow emerges from each service doing its part.

Simple to add new steps — subscribe a new service to an existing event. Hard to understand the full workflow without tracing through each service's event subscriptions. Hard to debug when something goes wrong mid-flow because there's no central place to check state.

**Orchestration.** A central workflow service coordinates the process. Calls payment service, waits for result, calls fulfillment service. Explicit, visible. The workflow is in one place. Adding a new step means changing the orchestrator. Easier to debug, easier to monitor, easier to implement compensating transactions on failure.

```
Choreography                         Orchestration

OrderService                         OrderService
    │ emits OrderPlaced                   │ calls
    ▼                                     ▼
PaymentService ──── PaymentProcessed ──► Orchestrator ──► PaymentService
                                         │
FulfillmentService ◄─── subscribes       └──────────────► FulfillmentService
    │ emits OrderShipped
    ▼
(emergent flow, no central view)     (explicit flow, central coordinator)
```

Neither is strictly better. Choreography works well for loosely coupled, independent reactions. Orchestration works better for complex workflows with conditional logic, error handling, and compensating transactions.

## Operations

### The ordering problem

Events are emitted, travel through a queue or bus, arrive at consumers. The order they're emitted in is not necessarily the order they arrive in — especially across partitions or with at-least-once delivery and retries.

`UserUpdated` arrives before `UserCreated`. Consumer processes an update for a user that doesn't exist yet. Depending on how the consumer handles this, it silently drops the update or crashes, and either way the data is wrong.

Solutions: sequence numbers in events, ordered partitions (Kafka partitions are ordered within a partition), consumer idempotency and upsert logic that handles out-of-order arrival, or accepting that some events will be out of order and designing data flows that tolerate it.

This isn't hypothetical. At-least-once delivery combined with retries reliably produces out-of-order delivery for a small percentage of events. Design for it from the start.

### Eventual consistency and the user experience

User places an order. Order service emits `OrderPlaced`. Inventory service subscribes and decrements stock. User immediately refreshes the product page, which reads from inventory service. Stock hasn't decremented yet — the event is still in the queue. User sees the old stock count.

This is correct behavior in an eventually consistent system. It's also confusing to users and a support ticket waiting to happen if the delay is long enough.

Strategies: read-your-writes consistency within a single service (the order service shows the order immediately from its own store); user-facing UX that acknowledges the async nature ("your order is being processed"); short event processing latency so the window of inconsistency is milliseconds, not seconds.

Eventual consistency is a real constraint. It needs to be a deliberate product decision, not a side effect that nobody talked about until a user complained.

### Dead letter queues and poison messages

A consumer fails to process an event. Retries. Fails again. After exhausting retries, the event goes to a dead letter queue.

Events in a DLQ mean something is broken and needs human attention. Without a DLQ, a poison message — one the consumer will never be able to process — blocks the queue indefinitely. With a DLQ, it gets moved aside after retries exhaust, and the queue unblocks.

Alarm on DLQ depth. An unmonitored DLQ is a silent data loss mechanism — events pile up, nobody notices, and the downstream effect surfaces weeks later as a data discrepancy. The DLQ message contains everything needed to replay or investigate once the underlying issue is fixed.

## Deep Dive: event-driven on AWS

**EventBridge.** Event bus with content-based routing. Rules filter events by pattern — source, detail type, specific field values — and route to targets. Decouples producers from consumers completely: new consumers add a rule, no changes to the producer. Supports event archives (replay historical events) and schema registry (document event structures).

Default event bus receives events from AWS services. Custom buses for application events. Cross-account event routing for multi-account architectures.

EventBridge Pipes: point-to-point integration between a source (SQS, DynamoDB Streams, Kinesis) and a target, with optional filtering and enrichment in between. Reduces glue Lambda functions for common patterns.

**SNS + SQS fan-out.** The workhorse pattern. SNS topic receives events, fans out to multiple SQS queues. Each consumer has its own queue, its own DLQ, its own processing rate and concurrency. Adding a consumer means adding an SQS subscription to the topic — producer unchanged.

**DynamoDB Streams + Lambda.** Every write to a DynamoDB table produces a stream record. Lambda reads from the stream in order, per shard. The pattern: write to DynamoDB, trigger downstream processing via stream. Useful for change data capture, maintaining projections, triggering side effects on data changes. The constraint: stream records expire after 24 hours. If Lambda is broken and not consuming the stream, records are lost after the retention window.

**Kinesis Data Streams.** High-throughput ordered event stream. Data retention up to 365 days (configurable). Multiple consumer applications read the same stream independently, each maintaining its own position (shard iterator). Unlike SQS, consuming an event doesn't remove it — all consumers get all events. Appropriate for analytics pipelines, log aggregation, real-time processing where multiple consumers need the same data.

**Step Functions for orchestration.** When choreography produces a workflow too complex to reason about, Step Functions adds an explicit state machine. Visual workflow editor, built-in retry and error handling, integration with most AWS services without glue code. Express Workflows for high-throughput short-duration flows; Standard Workflows for long-running processes with audit history.

| Pattern | Coupling | Visibility | Error handling | Best for |
|---|---|---|---|---|
| Choreography (SNS/EventBridge) | Low | Distributed | DLQ per consumer | Loosely coupled reactions |
| Orchestration (Step Functions) | Higher | Centralized | Built-in retries, catch states | Complex multi-step workflows |
| Streaming (Kinesis) | Low | Per-consumer checkpoint | Retry within retention window | High-throughput, multi-consumer |
| DynamoDB Streams | Low | Per-shard | Lambda retry + DLQ | Change data capture, projections |

## What's next

Day 18: observability — metrics, logs, and traces as a system, why each one alone is insufficient, and the instrumentation decisions that determine whether you can diagnose a production incident in minutes or hours.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
