# Observability

Monitoring tells you something is wrong. Observability tells you why.

The distinction matters in practice. A dashboard that shows CPU at 90% tells you there's a problem. It doesn't tell you which request type is causing it, which service is responsible, or what changed. Getting from "there's a problem" to "here's the cause" is the work of observability — and how long that work takes in a production incident determines how long the outage lasts.

Observability is built on three signal types: metrics, logs, and traces. Each answers a different question. None of them alone is sufficient. The system works when all three are present, connected, and instrumented correctly before the incident happens.

## Fundamentals

### Metrics

Numeric values over time. CPU utilization, request count, error rate, queue depth, p99 latency. Cheap to store — a data point is a timestamp and a number. Aggregatable across instances and time windows. Good for alerting because thresholds are easy to define on numbers.

Metrics answer "what is the system doing right now" and "what was it doing an hour ago." They don't answer "why." A spike in error rate in a metric tells you errors are happening. It tells you nothing about which errors, from which code path, triggered by which input.

Cardinality is the tension in metrics design. High-cardinality labels — user ID per metric, request ID per metric — give granular data but explode storage. A counter with a user_id label has as many time series as users. Most metrics backends can't handle that. Standard practice: keep labels to low-cardinality dimensions (service name, environment, endpoint path, status code) and use logs or traces for high-cardinality data.

### Logs

Discrete records of events. Unstructured text is what most systems historically produced. Structured logs — JSON, key-value pairs — are what production systems should produce. The difference: structured logs are queryable. Grep through unstructured logs and you're extracting meaning manually. Query structured logs on `status_code=500 AND user_id=12345` and you get a filtered result set.

Logs answer "what happened, specifically." They carry the context metrics can't: the exact request parameters, the user ID, the error message, the stack trace, the downstream service call that failed. High-cardinality data lives in logs because each log line is independent — no time series to multiply.

The cost is volume. A high-traffic service produces enormous log volumes. Storing, transmitting, and querying all of it is expensive. Log sampling — keeping 100% of errors and exceptions, sampling down to 1–5% of successful requests — reduces cost while preserving signal for the cases that matter.

### Traces

A trace follows a single request through all the services it touches. Each service records a span — start time, end time, operation name, metadata. Spans link together by a trace ID that propagates through the request via headers. The result: a complete picture of where a request spent its time, across every service boundary.

Traces answer "why is this request slow" and "where did this request fail." A p99 latency spike in a metric tells you something is slow. A trace for one of those slow requests shows you exactly which service added 800ms and why.

The instrumentation cost is real. Every service in the call chain needs to propagate the trace context. Every span needs to be emitted. Sampling is almost always necessary at scale — tracing 100% of requests at high traffic volumes produces data volumes that are expensive to store and slow to query. Tail-based sampling — keeping traces for requests that were slow or errored, sampling down the rest — is more valuable than head-based sampling at uniform rates.

### The three together

```
Alert fires: p99 latency > 2s
         │
         ▼
Metric: which endpoints? which services? ──► /checkout endpoint, payment-service
         │
         ▼
Trace: find a slow /checkout trace ──────► payment-service took 1.8s
         │                                  └─► downstream call to fraud-check-api
         ▼
Log: what happened in fraud-check-api? ──► connection timeout, pool exhausted
```

Each signal narrows the problem. Metric identifies the surface. Trace identifies the location. Log identifies the cause. Remove any one of the three and the diagnostic chain breaks.

## Operations

### The four golden signals

Coined by Google's SRE book. Four metrics that, together, describe the health of any service:

1. **Latency.** How long requests take. Separately track successful requests vs failed ones — a fast error is not the same as a fast successful response.
2. **Traffic.** Request volume. Requests per second, messages per second, transactions per second. Contextualizes everything else — a 10% error rate at 10 RPS is different from 10% at 10,000 RPS.
3. **Errors.** Rate of failed requests. Define "failed" precisely — HTTP 5xx, timeouts, business logic failures that return 200 with an error payload.
4. **Saturation.** How full the service is. CPU, memory, connection pool utilization, queue depth. A service at 95% CPU has no headroom for a traffic spike.

These four are the minimum viable signal set. Before adding dashboards and alerts, make sure these four are instrumented and alarmed on for every service.

### SLIs, SLOs, and error budgets

**SLI (Service Level Indicator).** The metric you're measuring. "The fraction of requests with latency under 500ms."

**SLO (Service Level Objective).** The target for that metric. "99% of requests should complete in under 500ms, measured over a rolling 28-day window."

**Error budget.** The allowed failure rate implied by the SLO. 99% availability over 28 days means 1% can fail — roughly 403 minutes. Burn the budget too fast and reliability work takes priority over feature work. Budget remaining means you can take on risk.

SLOs make reliability concrete and discussable. Without them, every incident is a judgment call about severity. With them, "we've burned 80% of our error budget this month" is an objective statement that drives prioritization.

### Alerting on symptoms, not causes

Alert on what users experience, not on what's happening inside the system.

**Bad alert:** CPU > 80% for 5 minutes. CPU is a cause, not a symptom. High CPU might not affect users at all. Low CPU doesn't mean users are happy.

**Good alert:** p99 latency > 1s for 5 minutes, or error rate > 1% for 3 minutes. These measure user experience directly.

Cause-based alerts generate noise. Every CPU spike, every memory fluctuation, every disk I/O burst fires an alert, most of which resolve on their own without user impact. Engineers learn to ignore them. The alert that matters — real user-facing degradation — gets lost in the noise.

Alert on SLO burn rate. If you're consuming your monthly error budget at 10x the normal rate, that's actionable and urgent regardless of what's causing it.

## Deep Dive: observability on AWS

**CloudWatch.** AWS's native observability platform. Metrics from every AWS service flow in automatically. Custom metrics via PutMetricData API or CloudWatch agent. Metric math for derived signals — error rate as errors/total, saturation as utilization/capacity.

CloudWatch Logs Insights: SQL-like query language over log groups. Fast for operational queries. Works without a separate log aggregation service. The limitation is that it queries log groups in isolation — correlating logs from multiple services requires separate queries and manual correlation.

**X-Ray.** Distributed tracing for AWS workloads. Instruments Lambda, API Gateway, ECS, EKS (via AWS Distro for OpenTelemetry), and any service running the X-Ray SDK. Trace maps show service topology and latency distribution. Sampling rules configurable at the service level — keep all traces for slow requests, sample down fast ones.

The gap: X-Ray service map shows you where latency is, but for fine-grained span data and correlation with logs you need to query the X-Ray API or push traces to a trace backend. Many teams use X-Ray for AWS service tracing and OpenTelemetry for application-level spans, exporting to a third-party backend (Jaeger, Tempo, Honeycomb) that handles correlation.

**CloudWatch Container Insights.** ECS and EKS cluster, service, and task/pod level metrics without manual instrumentation. CPU, memory, network, storage per container. In EKS, requires the CloudWatch agent or ADOT collector as a DaemonSet. Gives you the cluster-level view automatically; application-level metrics still need explicit instrumentation.

**EMF (Embedded Metric Format).** Structured log format that CloudWatch recognizes and automatically extracts as metrics. Write a JSON log line with the right structure and CloudWatch creates time series from the numeric fields. No PutMetricData API calls, no SDK integration for custom metrics. Useful for Lambda — emit business metrics alongside logs in the same write operation.

**OpenTelemetry on AWS.** AWS Distro for OpenTelemetry (ADOT) is AWS's supported distribution. Collector runs as a sidecar or DaemonSet, receives spans and metrics from instrumented services, exports to X-Ray, CloudWatch, or third-party backends. The value: instrument once with OTel, route to any backend without re-instrumenting. Vendor lock-in at the instrumentation layer is expensive to undo.

| Signal | Answers | Cost | Cardinality |
|---|---|---|---|
| Metrics | What is happening / when | Low (aggregated numbers) | Low (keep labels simple) |
| Logs | What happened specifically / context | High (volume scales with traffic) | High (each line is independent) |
| Traces | Where in the call chain / why slow | Medium (sampling required at scale) | High (per-request) |

## What's next

Day 19: consensus and leader election — how distributed systems agree on a single truth, what Raft and Paxos are actually doing, and the operational implications of systems built on consensus protocols.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
