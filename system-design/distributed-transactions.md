# Distributed Transactions

A transaction in a single database is straightforward. Begin, execute operations, commit or rollback. ACID guarantees hold. Either everything happened or nothing did.

Across service boundaries, this breaks. Service A writes to its database. Service B writes to its database. No shared transaction coordinator. If service A succeeds and service B fails, the system is in an inconsistent state. The data is partially written and there's no automatic rollback.

Distributed transactions are the attempt to get ACID-like guarantees across multiple systems. The solutions range from technically correct but operationally fragile, to practically useful but requiring careful design. None of them are as clean as a local transaction, and that's the real lesson: the right architecture often avoids the distributed transaction problem rather than solving it.

## Fundamentals

### Why local transactions don't cross service boundaries

ACID properties assume a single transaction coordinator with access to all the data being modified. The coordinator writes the changes, ensures they're durable, and commits atomically.

In a distributed system, each service owns its data. There's no shared coordinator. Service A's PostgreSQL instance and service B's DynamoDB table have no awareness of each other. Telling both "commit or rollback together" requires a protocol that coordinates across them — and that protocol introduces its own failure modes.

### Two-phase commit (2PC)

The classic distributed transaction protocol. A coordinator manages the protocol across participants.

**Phase 1 — Prepare.** Coordinator asks all participants: "can you commit?" Each participant writes the changes to a durable log and responds yes or no. Saying yes is a promise: "I will commit if you tell me to."

**Phase 2 — Commit or abort.** If all participants said yes, coordinator sends commit. All participants apply the changes. If any said no, coordinator sends abort. All participants roll back.

```
Coordinator
    │
    ├──► Service A: "prepare?" ──► "yes" (changes written to log)
    ├──► Service B: "prepare?" ──► "yes" (changes written to log)
    │
    └── all yes? ──► Coordinator sends "commit" to both
                     both apply changes
```

Correct in theory. Fragile in practice.

**The coordinator failure problem.** If the coordinator crashes between phase 1 and phase 2, participants are stuck. They've promised to commit but haven't received the commit message. They hold locks. They can't proceed and they can't unilaterally abort because the coordinator might recover and send commit. The system is blocked until the coordinator recovers or a timeout forces a decision — and forcing a decision without knowing the coordinator's intent risks inconsistency.

**Blocking nature.** 2PC holds locks across both phases. Long-running transactions hold locks for their entire duration across all participants. At scale, under concurrent load, this is a throughput killer.

**Latency.** Two network round trips to the coordinator, minimum, plus the latency of each participant. For any operation requiring sub-100ms response times, 2PC is often too slow.

2PC is used in practice — XA transactions across relational databases, some distributed SQL systems — but it's brittle under failure and slow under load. Systems that require strong cross-service consistency and use 2PC invest significant engineering effort in coordinator fault tolerance.

### Sagas

The practical alternative. A saga is a sequence of local transactions, each with a corresponding compensating transaction that undoes it.

Instead of "either everything commits or nothing does," sagas say "execute each step in sequence; if any step fails, run the compensating transactions for all completed steps to undo the work."

**Choreography-based saga.** Each service publishes an event when its local transaction completes. Other services react to the event and execute their step. On failure, a failure event triggers compensating transactions in reverse order. No central coordinator.

**Orchestration-based saga.** A central orchestrator calls each service in sequence. On failure, the orchestrator calls the compensating transactions explicitly. Easier to reason about because the workflow is in one place.

```
Choreography saga — successful path:
OrderService: create order ──emit OrderCreated──►
PaymentService: charge card ──emit PaymentProcessed──►
InventoryService: reserve stock ──emit StockReserved──►
ShippingService: schedule delivery ──emit OrderComplete

Choreography saga — failure at payment:
OrderService: create order ──emit OrderCreated──►
PaymentService: charge fails ──emit PaymentFailed──►
OrderService: listens for PaymentFailed ──► cancel order (compensating)
```

The critical requirement: compensating transactions must be idempotent. They might be called more than once — at-least-once delivery, retry storms, duplicate events. Running the compensation twice must produce the same result as running it once.

Not all compensating transactions are straightforward. "Refund the payment" is clear. "Unsend the email" is not possible. Sagas work cleanly for reversible operations and require careful design for operations that can't be undone.

### Outbox pattern

A subtle but important pattern for making event emission reliable in a saga.

Service A writes to its database and emits an event. What if the database write succeeds but the event emission fails? The downstream services never trigger. The saga is stuck. Service A thinks it succeeded. Everything else thinks nothing happened.

The outbox pattern: write both the business data and the event to the same database, in the same local transaction. A separate process (the outbox relay) reads the events from the database and publishes them to the message bus. The event is only published after the database commit confirms it's durable. The relay handles retries on publish failure.

```
Service A (single local transaction):
┌─────────────────────────────────────┐
│  INSERT INTO orders ...              │
│  INSERT INTO outbox (event) ...      │  ← same transaction
└─────────────────────────────────────┘
           │
           ▼
Outbox relay reads outbox table ──► publishes to SNS/EventBridge
           │
           ▼
Event arrives at downstream services reliably
```

The outbox pattern eliminates the dual-write problem — writing to the database and publishing an event as two separate operations where either can fail independently.

## Operations

### Saga failure visibility

Sagas fail silently if you're not instrumenting them. A step fails. A compensating transaction runs. The user gets an error. From the outside, the saga completed — it just completed by rolling back.

What you need: a correlation ID that spans all steps of the saga, emitted with every event and log line. The ability to query "show me all events for saga X" and see the full sequence. An alert when a compensating transaction fires — compensation means something went wrong, and the frequency of compensations tells you about reliability.

Without correlation IDs, a saga failure is a mystery spread across multiple service logs with no obvious thread connecting them.

### Timeouts and stuck sagas

What happens if a service in the middle of a saga becomes unreachable? The saga is waiting for an event that never comes. It's stuck, indefinitely, unless you build a timeout.

Saga timeouts are not automatic. They need to be designed explicitly. Common approach: a timeout event published by a scheduler service (or Step Functions' built-in wait state) that triggers compensation if the saga hasn't completed within a window. The timeout is itself a compensating trigger.

Step Functions is particularly useful here. Built-in wait states, task timeouts, and catch states handle the "what if this step never responds" problem without custom timeout logic.

### Idempotency is non-negotiable

Every step in a saga, and every compensating transaction, will potentially execute more than once. At-least-once delivery from the event bus. Lambda retries. Network timeouts that cause re-sends. Design every operation to be safe to run twice.

The idempotency key pattern from Day 15 applies directly: each event carries a unique ID, each service checks whether it's processed that ID before executing, stores the result, and returns it on duplicate delivery.

## Deep Dive: distributed transactions on AWS

**Step Functions.** The managed saga orchestrator. Define a state machine with explicit states, transitions, retry policies, catch conditions, and compensating states. Execution history is durable — every state transition is logged. If a step fails, the state machine follows the catch path to compensating states.

Express Workflows for high-throughput short-duration sagas (order processing, payment flows). Standard Workflows for long-running processes where durability of execution history matters (multi-day approval workflows, batch processing pipelines).

Built-in integrations with Lambda, SQS, SNS, DynamoDB, ECS, and others reduce glue code. Waitress state can wait days for an asynchronous callback — useful for workflows that include human approval steps or third-party async responses.

**DynamoDB Transactions.** `TransactWriteItems` and `TransactGetItems` provide ACID transactions within a single DynamoDB account and region. Up to 100 items, across multiple tables, in one atomic operation. This is the closest thing to a local transaction available in DynamoDB. The limit: same region, same account. Cross-region or cross-service transactions still require saga patterns.

**Amazon MWAA / EventBridge Pipes.** For saga choreography where the workflow is a sequence of transformations on an event stream, Pipes connect sources to targets with filtering and enrichment. Simple linear workflows without compensation logic are handled cleanly. Complex workflows with error handling and compensating steps benefit from explicit orchestration.

**Outbox relay on AWS.** DynamoDB Streams as the outbox. Write business data and event to DynamoDB in a transaction. DynamoDB Streams captures the write. Lambda reads the stream and publishes to EventBridge or SNS. Reliable because Streams guarantees at-least-once delivery of every write. The Lambda must be idempotent on re-delivery.

| Approach | Consistency | Latency | Complexity | Best for |
|---|---|---|---|---|
| 2PC (XA) | Strong | High (two round trips + locks) | High (coordinator fault tolerance) | Same-technology cross-DB, rarely in services |
| Saga (orchestration) | Eventual + compensation | Low (async steps) | Medium (orchestrator + compensating transactions) | Multi-service workflows with rollback |
| Saga (choreography) | Eventual + compensation | Low | Medium-High (event tracing required) | Loosely coupled services, simple workflows |
| Outbox pattern | Reliable event delivery | Low overhead | Low-Medium | Eliminating dual-write between DB and event bus |
| DynamoDB Transactions | Strong (within DynamoDB) | Low | Low | Multi-table writes in DynamoDB |

## What's next

Day 22: storage systems — block storage, object storage, and file systems, when each one is the right tool, and the failure modes that appear when you use the wrong one.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
