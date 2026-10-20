# Streaming and Batch Processing

Data arrives. Something has to process it. The fundamental question: does it need to be processed now, or can it wait?

Streaming processes data as it arrives — event by event, in near-real-time. Batch processes data in bulk, periodically — everything that accumulated over the last hour, or the last day. Neither is universally better. The choice comes from the latency requirement: how old can the output be before it's no longer useful?

Most systems need both. Real-time fraud detection on every transaction. Nightly billing aggregations across all customers. The architectures are different; the data pipelines are different; the failure modes are different.

## Fundamentals

### Streaming

Events arrive. They're processed immediately. Output is produced within seconds or milliseconds of the input event. The system maintains state across events when needed — a running count, a sliding window, a join between two event streams.

The data model: an unbounded, continuous sequence of events. There's no "end" of the data to wait for. Processing happens incrementally.

**Stateless stream processing.** Each event is processed independently. Apply a transformation, emit a result, discard the event. Fast. Simple. No memory of previous events. Good for: filtering events, transforming formats, routing to downstream sinks.

**Stateful stream processing.** Processing requires memory of previous events. Count events per user in the last five minutes. Detect when a user makes three failed login attempts. Join two event streams by a common key. State must be persisted somewhere — in-memory on the processing node (fast, not durable), in a remote state store (slower, durable and shareable across nodes).

**Windowing.** Grouping events by time for aggregation. Three window types:
- *Tumbling window:* fixed, non-overlapping time buckets. "Count events per minute." Each event belongs to exactly one window.
- *Sliding window:* fixed duration, moves continuously. "Count events in the last 5 minutes, updated every 30 seconds." Events can belong to multiple windows.
- *Session window:* variable duration, closes after a gap of inactivity. Groups events belonging to the same user session regardless of clock time.

### Batch processing

Collect data. Process it all at once. Produce output. Repeat on a schedule.

The data model: a bounded dataset. A file, a database table, a set of S3 objects. There's an end. Processing reads from start to end, produces output, and stops.

Batch processing is simpler to reason about than streaming. The input is fixed. There's no late-arriving data to handle. Failed jobs can be retried from the beginning. The processing framework can optimize across the entire dataset — sort it, partition it, shuffle it — in ways that aren't possible on an unbounded stream.

The cost: latency. Data processed in a nightly batch job is at minimum 24 hours stale when the output is produced. Hourly batches improve this to an hour. The minimum latency of batch is the batch interval.

### The Lambda architecture (not the AWS service)

The classical hybrid: two parallel pipelines on the same data. A streaming pipeline ("speed layer") produces approximate, low-latency results. A batch pipeline ("batch layer") produces accurate, high-latency results. Queries merge both. Recent data comes from the stream. Historical data comes from the batch.

The problem: two codebases, two sets of bugs, two places where business logic must stay synchronized. The batch and stream implementations of the same aggregation will diverge.

The Kappa architecture simplifies this: one streaming pipeline, but data is retained long enough to replay from the beginning. "Batch" is just a stream replay at higher throughput. One codebase, one set of business logic. Kafka's long retention makes this practical.

```
Lambda architecture:
  Events ──► Speed layer (streaming) ──────────────────┐
         └──► Batch layer (periodic batch) ──► merge ──► Query
         
Kappa architecture:
  Events ──► Retained stream ──► Streaming processor ──► Query
                    │
                    └── replay from offset 0 = "batch" reprocessing
```

## Operations

### Late-arriving data

Events don't always arrive in the order they were produced. A mobile device offline for an hour sends buffered events when it reconnects. A network delay puts event B before event A. In batch processing, you wait for all the data before processing. In streaming, you're processing continuously — when does "the data for this window is complete" hold?

Watermarks are the streaming answer. The watermark represents the system's estimate of event time progress — "I believe all events with timestamp before T have arrived." Events with timestamps before the watermark are on-time. Events arriving after the watermark for their window are late.

Late data handling strategies:
- **Drop.** Ignore late-arriving events. Simplest. Correct when late data is rare and small.
- **Reprocess the window.** Allow the window to receive late events up to a maximum lateness. Re-emit corrected results. The downstream system must handle result updates.
- **Side output.** Route late events to a separate output for manual inspection or later reprocessing.

The choice depends on how late is acceptable and whether the output can handle corrections.

### Exactly-once semantics in streaming

Delivering each event exactly once, in the presence of failures and retries, is hard. At-least-once is practical — events may be reprocessed on failure. Exactly-once requires coordinated transactions between the source, the processor state, and the sink.

Apache Flink implements exactly-once via distributed snapshots — periodic consistent checkpoints of all operator state and source offsets. On failure, restart from the last checkpoint. Everything after the checkpoint is reprocessed. If the sink supports idempotent writes or transactional writes, the result is exactly-once end-to-end. If the sink doesn't, it's at-least-once from the user's perspective regardless of what the engine guarantees.

Kafka Streams provides exactly-once semantics when both source and sink are Kafka topics, using transactional producers and atomic commits of offsets and output in the same Kafka transaction.

### Backpressure in streaming pipelines

Producer generates events faster than consumers process them. Messages accumulate in the queue. Queue depth grows. Memory pressure. Latency increases.

This is the streaming equivalent of the throughput problem from Day 3. Solutions:
- Scale the consumer tier to match producer rate.
- Apply backpressure upstream — slow the producer when the queue is full (works when the producer is internal to the system; doesn't work for external event sources).
- Shed load — drop events when backlog exceeds a threshold (appropriate for non-critical data; never for transactional events).

Queue depth is the signal to monitor. Sustained growth means the consumer can't keep up. Alarm on queue age (time since oldest message) rather than just queue length — a queue of one million messages processed in seconds is fine; a queue of 100 messages sitting for 30 minutes is not.

## Deep Dive: streaming and batch on AWS

**Kinesis Data Streams.** The AWS streaming primitive. Ordered, partitioned, retained for up to 365 days. Multiple consumer applications read the same stream independently. Producers write to shards; consumers read from shards. Throughput scales by adding shards. Enhanced fan-out: dedicated 2 MB/s throughput per consumer per shard, compared to the shared 2 MB/s across all consumers in standard mode.

Kinesis is the right choice when multiple downstream systems need the same event stream, event replay is a requirement, or retention needs to be longer than SQS's 14-day maximum.

**Kinesis Data Firehose.** Streaming delivery to a destination — S3, Redshift, OpenSearch, Splunk — with built-in batching, compression, and optional transformation via Lambda. The "I just need to get streaming data into a sink" service. Not a full stream processor — no state, no windowing, no joins. Buffer window of 60 seconds to 15 minutes before delivering to S3. The Lambda transformation hook processes records in the buffer before delivery.

**AWS Glue Streaming ETL.** Apache Spark Structured Streaming managed on Glue. Reads from Kinesis or Kafka, applies transformations defined in PySpark or Spark Scala, writes to S3, Redshift, or other sinks. Use when the processing logic is complex enough to warrant Spark — joins, aggregations, schema evolution — and you don't want to manage the cluster.

**Amazon EMR.** Managed Hadoop/Spark for batch processing. The heavy-duty option for large-scale batch workloads: petabyte-scale transformations, complex multi-stage pipelines, ML feature engineering on large datasets. EMR Serverless eliminates cluster management — submit a Spark or Hive job, capacity is provisioned automatically. EMR on EC2 or EKS gives more control over instance types and cluster configuration.

**AWS Batch.** Managed batch job scheduler. Not Spark — it runs containerized jobs. The right tool for: parallel batch processing with Docker containers, HPC workloads, jobs that need GPU instances, compute-intensive workloads that don't need Spark's distributed data processing model. Manages job queues, priority, retry, and compute environment scaling (Spot instances for cost reduction).

**Apache Kafka on MSK.** Fully managed Kafka. Use when Kinesis doesn't fit: existing Kafka ecosystem tooling, need for Kafka Streams or Kafka Connect, message sizes over 1 MB (Kinesis limit), need for compacted topics. MSK Connect runs managed Kafka Connect connectors — source connectors pull data from databases via CDC; sink connectors push to S3, OpenSearch, Redshift.

**Step Functions for batch orchestration.** Coordinates multi-step batch workflows — trigger EMR job, wait for completion, run Lambda validation, trigger Glue crawler, notify on success. Replaces custom orchestration scripts with durable, visual state machines. Retry and error handling built in.

| Service | Model | State | Best for |
|---|---|---|---|
| Kinesis Data Streams | Streaming | No (external state needed) | Multi-consumer event stream, replay |
| Kinesis Firehose | Streaming delivery | No | Simple stream-to-sink delivery |
| Glue Streaming ETL | Streaming with Spark | Yes (Spark state) | Complex stateful stream processing |
| EMR / EMR Serverless | Batch | N/A | Large-scale Spark/Hadoop batch |
| AWS Batch | Batch | N/A | Containerized parallel batch jobs |
| MSK (Kafka) | Streaming | Via Kafka Streams | Kafka ecosystem, CDC, complex routing |
| Lambda + SQS | Event-driven | No (stateless) | Simple per-event processing |

## What's next

Day 30: idempotency and exactly-once semantics — why "process each message once" is harder than it sounds, the patterns that make systems safe to retry, and where the guarantees actually break down.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
