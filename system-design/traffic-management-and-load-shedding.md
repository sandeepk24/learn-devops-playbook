# Traffic Management and Load Shedding

A system sized for 10,000 requests per second receives 50,000. What happens next is either controlled or it isn't. If it's controlled, the system serves a fraction of users well and rejects the rest cleanly. If it's not, the system tries to serve everyone, queues fill, latency climbs, threads block, and eventually the system stops serving anyone.

Load shedding is the deliberate act of refusing work when capacity is exceeded so the work that does get accepted is handled correctly. It's the difference between degraded-but-functional and fully down. The decision to shed load should be made by design, not discovered during an incident.

## Fundamentals

### The queueing problem

When arrival rate exceeds processing rate, requests queue. A queue absorbs short bursts. But a queue that grows without bound eventually causes latency to climb for all requests — including the ones that arrived early and should have been served quickly. A request that arrived when the queue had 10,000 entries ahead of it doesn't get served quickly regardless of how fast the server can process it.

Little's Law (Day 24) describes this precisely. As queue depth grows, wait time grows proportionally. A server processing 1,000 requests per second with 5,000 requests queued has an average wait of 5 seconds before processing even begins. That 5 seconds is added to every request in the system, making the p99 unacceptable even when the server itself is healthy.

The implication: a queue that's growing is a liability, not a buffer. A buffer absorbs a burst and drains. A queue that grows under sustained overload just delays the failure while making it worse. Shed load before the queue grows; don't rely on the queue to absorb it indefinitely.

### Load shedding strategies

**Reject at the edge.** Rate limiting (Day 9) at the load balancer or API Gateway level. The simplest and cheapest rejection — the request never reaches the application tier. Returns 429 Too Many Requests. The application is fully protected from the traffic it can't handle.

**Reject at the application.** The application measures its own load — connection pool utilization, CPU, queue depth, request latency — and rejects requests when above a threshold. More granular than edge rejection. Can differentiate by request type: shed low-priority traffic first, preserve capacity for high-priority operations.

**Timeout-based shedding.** Requests that have been queued beyond a threshold age are discarded rather than processed. By the time a request has waited 10 seconds, the user has likely already retried or given up. Processing it consumes resources to produce a response that will arrive too late to matter.

**Weighted shedding by priority.** Not all traffic is equal. A checkout request and a "load more recommendations" request are different in business value. Under load, shed non-critical traffic first. Requires the system to classify incoming requests by priority — either via dedicated endpoints, request headers set by the calling service, or traffic metadata.

```
Incoming traffic: 50,000 RPS
Capacity: 10,000 RPS

Priority-based shedding:

Critical (checkout, auth):    5,000 RPS → accept all   (5,000 served)
Standard (product pages):    20,000 RPS → accept 50%  (10,000 served, 10,000 shed)
Low (recommendations, ads):  25,000 RPS → accept 0%   (all shed)

Total served: 15,000 RPS
System remains stable. Critical path protected.
```

### Backpressure vs load shedding

Two different responses to overload.

**Backpressure.** Slow down the producer. Signal upstream that the system is at capacity so the producer stops sending at full rate. Works when the producer is internal and controllable. A producer feeding a queue that slows its send rate when the queue is deep. A gRPC stream that pauses when the consumer signals congestion. Doesn't work for external traffic — you can't tell a browser to slow down.

**Load shedding.** Drop work at the edge. Works for any traffic source. The producer may not slow down, but the system selectively accepts only what it can handle.

The two are complementary. Backpressure within the system prevents internal overload propagation. Load shedding at the perimeter prevents external traffic from overwhelming the internal systems before backpressure can operate.

## Operations

### Measuring saturation correctly

Load shedding triggers on saturation. Measuring saturation poorly means triggering too early (shedding unnecessary traffic) or too late (already overwhelmed).

Useful saturation signals:
- **Request queue depth.** How many requests are waiting, not being actively processed. Direct measure of load that exceeds current capacity.
- **Connection pool utilization.** Percentage of pool connections in active use. Above 80%: contention is developing. Above 95%: requests are queuing for connections.
- **CPU utilization trend.** Not just current value but rate of change. CPU at 70% and climbing is a different situation from CPU at 70% and stable.
- **p99 latency relative to target.** The canary for emerging overload. Latency degrades before errors appear. If p99 is 3x the normal value, the system is under stress before it's failing.

Avoid triggering load shedding on average CPU or average latency. Averages mask the tail. The system can look healthy on averages while the p99 is already unacceptable.

### Graceful rejection

A rejected request should fail fast with a useful response.

**HTTP 429 Too Many Requests** with a `Retry-After` header. Tell the client when to retry. Well-behaved clients back off. Clients that don't observe the header will retry immediately, amplifying load — their problem, not yours, but worth noting in the response body.

**HTTP 503 Service Unavailable** with a `Retry-After` header. When the service is temporarily overwhelmed rather than the client being rate-limited. Semantically correct for capacity-based shedding.

**gRPC RESOURCE_EXHAUSTED** status code. The gRPC equivalent. Include a backoff hint in the response metadata.

What not to do: timeout silently. A client waiting 30 seconds for a response that never comes holds resources on both sides — the client is blocked, the server may have the request queued. A fast rejection is better for everyone.

### Admission control

Admission control decides which requests get into the system before they consume any resources. It's load shedding at the front door rather than mid-flight.

The Google SRE practice of adaptive admission control (described in the SRE Workbook) uses a client-side algorithm: the client measures its own accept rate vs request rate. When the ratio drops below a threshold (the service is rejecting more than it's accepting), the client probabilistically drops requests before even sending them. The overhead of rejected requests reaches the service in proportion to how much capacity is available, not in proportion to how much traffic is trying to arrive.

Envoy's `MaxRequestsCircuitBreaker` and Hystrix's semaphore-based isolation implement admission control at the proxy and library level. Configure a maximum pending requests limit — requests that would queue beyond this limit are rejected immediately.

## Deep Dive: traffic management on AWS

**ALB listener rules and target group weights.** ALB supports weighted routing between multiple target groups on a single listener rule. Route 90% of traffic to the stable version target group, 10% to the new version (canary deployment, Day 26). Under load testing, temporarily route a larger percentage to a higher-capacity target group. Weight shifts take effect within seconds without DNS propagation delay.

**ALB slow start mode.** Newly registered targets receive a gradually increasing share of traffic over a configurable ramp-up period (30 seconds to 15 minutes). Prevents a cold instance from immediately receiving full traffic before its caches are warm and connection pools are established. Reduces the "new instance effect" where fresh instances show worse latency than established ones.

**API Gateway throttling and usage plans.** Stage-level throttling provides a ceiling for all traffic to the stage. Usage plans add per-client throttling. When a client exceeds its quota, API Gateway returns 429 before the request reaches Lambda or the backend integration. The backend is never invoked. This is the cleanest load shedding for API workloads — the rejection happens at the managed layer with zero backend compute cost.

**Lambda reserved and provisioned concurrency.** Reserved concurrency on a Lambda function limits its total concurrent executions. Requests that would exceed the reserved concurrency receive a 429 throttle. This is load shedding at the function level — the function never attempts to process more requests than its reservation. Pair with SQS as a buffer: Lambda throttles → messages stay in SQS → processed when concurrency is available. Backpressure within the system, rejection at the edge.

**Application Load Balancer access logs + CloudWatch.** Track `elb_status_code` distribution in ALB access logs. A spike in 5xx suggests backend overload. A spike in 429 (if your application returns them) suggests you're shedding load. Both are worth distinct alarms. The difference: backend 5xx means the system is failing. 429 means the system is correctly protecting itself. You want the 429 alarm to fire before the 5xx alarm does — that's the sign the shedding is working.

**AWS Auto Scaling with predictive scaling.** Reactive scaling adds capacity after load increases. Predictive scaling uses historical patterns to add capacity before anticipated load increases. For workloads with predictable patterns (business hours, weekly cycles, scheduled events), predictive scaling reduces the window where the fleet is at capacity and shedding is necessary. Predictive scaling is not a substitute for load shedding — events that deviate from historical patterns still require it — but it reduces how often shedding is needed.

| Mechanism | Rejection point | Granularity | AWS implementation |
|---|---|---|---|
| Rate limiting | Edge (CDN/Gateway) | Per-IP, per-key | WAF rate rules, API Gateway throttling |
| Concurrency limit | Function/service | Per-function | Lambda reserved concurrency |
| Connection pool threshold | Application | Per-service | Application-level check before acquiring connection |
| Queue age timeout | Queue | Per-message | SQS message retention, Lambda `maximumConcurrency` |
| Weighted target group | Load balancer | Per-target-group | ALB listener rule weights |
| Admission control | Client-side | Per-client | Envoy circuit breaker, client backoff libraries |

## What's next

Day 38: service mesh — what a service mesh actually does below the marketing language, when the operational overhead is justified, and how Istio and App Mesh implement traffic control, mTLS, and observability at the sidecar layer.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
