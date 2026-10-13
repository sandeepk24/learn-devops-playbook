# Circuit Breakers

A downstream service slows down. Your service calls it. Calls block waiting for a response. Threads accumulate. Your connection pool fills up. Now your service is slow too, and everything upstream of you is also backing up. The original problem was isolated to one dependency. The cascading failure is yours.

Circuit breakers stop this. They track the health of a downstream call and, when failure crosses a threshold, open the circuit — fail fast instead of waiting. The downstream gets breathing room. Your service stays responsive. The failure stays contained.

## Fundamentals

### The three states

Circuit breakers operate as a state machine with three states.

**Closed.** Normal operation. Requests flow through. Failures are counted. If the failure rate stays below the threshold, nothing changes.

**Open.** Failure threshold crossed. Requests are rejected immediately without attempting the downstream call. Returns an error or a fallback response right away. Downstream gets no traffic. After a configured timeout, the circuit moves to half-open.

**Half-open.** A probe. Allow a limited number of requests through. If they succeed, assume the downstream has recovered — close the circuit and resume normal traffic. If they fail, open the circuit again and restart the timeout.

```
          failures exceed threshold
Closed ──────────────────────────────► Open
  ▲                                      │
  │                                      │ timeout expires
  │                                      ▼
  └────────── probes succeed ─────── Half-Open
                                         │
                                         │ probes fail
                                         ▼
                                        Open (reset timeout)
```

### What counts as a failure

This is where most implementations get nuanced. Not every error should count toward the threshold.

**Errors to count:** timeouts, 5xx responses from the downstream, connection failures. These indicate the downstream is unhealthy or unreachable.

**Errors not to count:** 4xx responses. A 404 or 400 is the downstream working correctly and telling you the request was invalid. Counting client errors as circuit-breaking failures means a caller sending bad requests can trip the breaker and affect all other callers.

**Slow calls.** Slow is more dangerous than failed. A 10-second response time is a blocked thread for 10 seconds. Circuit breakers that only trip on errors, not latency, will miss the most common failure mode in distributed systems. Configure a timeout threshold alongside an error threshold.

### Threshold configuration

Two common approaches:

**Count-based.** Trip after N consecutive failures. Simple. But in low-traffic scenarios, N failures over an hour is very different from N failures in one second. Doesn't scale well with variable traffic.

**Rate-based.** Trip when the failure rate over a rolling window exceeds a percentage — 50% failure rate over the last 10 seconds. Requires a minimum number of calls before evaluating the rate, to avoid opening the circuit on 1 failure out of 1 call.

Rate-based is generally better for production systems. Resilience4j and Hystrix both use this model. AWS App Mesh and similar service meshes implement it at the sidecar level, outside application code.

## Operations

### Fallback responses

An open circuit rejects requests fast. What the caller does with that rejection matters.

Options, roughly in order of desirability:

1. **Return cached data.** Stale but useful. A product page served from a cache is better than a 500.
2. **Return a degraded response.** Recommendations service is down? Return an empty list. The page still loads.
3. **Return a default.** Known safe value. Fail to the conservative case.
4. **Return an error.** Honest, but the impact falls on the user. Acceptable for non-critical paths. Unacceptable for anything load-bearing.

The worst outcome: no fallback, and the error propagates to the user as an unhandled exception. The circuit breaker did its job but the application didn't plan for the open state.

### Cascading circuit breakers

One service depends on several downstream services, each of which has circuit breakers. Service B trips. Service A's circuit for B opens, and A returns a fallback. Service A is still healthy. Service C depends on A, and A's fallback changes C's behavior in a way C doesn't handle well. C starts erroring.

Cascading failures can flow through circuit breakers, not just despite them. Each circuit isolates its own dependency, but the system-level behavior emerges from how all the fallbacks compose. Testing circuit breaker behavior in isolation isn't enough. The important question is what the system does as multiple circuits open simultaneously.

Chaos engineering — deliberately tripping dependencies in staging — is the only reliable way to know the answer. Documentation about what the fallback does is not a substitute for having actually seen it run.

### Circuit breakers vs retries

Retries and circuit breakers pull in opposite directions. Retries say "try again, it might work." Circuit breakers say "stop trying, you'll make it worse." Both are correct in different situations.

Rule of thumb: retry on transient errors — network hiccups, brief unavailability, 429s with a `Retry-After` header. Don't retry on errors that indicate a systemic problem, and don't retry when a circuit is open. Retrying into an open circuit defeats the purpose.

The combination: retry a small number of times with exponential backoff and jitter before counting a failure toward the circuit breaker threshold. This handles transient errors at the retry layer without suppressing the signal that tells the circuit breaker the dependency is actually unhealthy.

## Deep Dive: circuit breakers on AWS

AWS doesn't provide a managed circuit breaker you plug into your service. Implementation is in the application or in the service mesh.

**Resilience4j (Java) / Polly (.NET) / pybreaker (Python).** Library-level circuit breakers. You wrap the call, configure thresholds, define the fallback. Most mature approach for services that own the implementation. Resilience4j has excellent CloudWatch metric integration — emit circuit state transitions as metrics and alarm on `OPEN` state.

**AWS App Mesh / AWS Cloud Map.** Service mesh circuit breaking at the Envoy sidecar level. Configure outlier detection — remove a host from the load balancing pool if it produces enough consecutive 5xx responses. Similar concept, different layer. Doesn't require application code changes. Useful when you can't modify the application or when you want consistent circuit breaking behavior across a polyglot fleet.

**Lambda with SQS.** A queue in front of a Lambda function acts as a natural circuit breaker for batch processing workloads. If Lambda is failing, messages accumulate in SQS rather than causing upstream failures. The DLQ catches messages that exhaust retries. The upstream service (writing to SQS) stays healthy regardless of Lambda's state. Not a circuit breaker in the traditional sense, but the queue absorbs the failure mode that circuit breakers are designed to handle.

**API Gateway with circuit breaking.** API Gateway doesn't implement circuit breakers natively, but Stage-level throttling and integration timeouts limit the blast radius of a slow backend. A 29-second integration timeout on a Lambda that's hanging is still 29 seconds of blocked connection — configure timeouts aggressively, as short as your p99 allows, so hung calls fail fast rather than queue.

Alarm worth setting: CloudWatch alarm on circuit breaker state transitions if you're publishing them as metrics. A circuit that opens and closes frequently — "flapping" — indicates a dependency that's intermittently degraded, which is harder to notice than one that's cleanly down.

| Pattern | What it solves | What it doesn't solve |
|---|---|---|
| Circuit breaker | Stops cascading failure from a slow/failed dependency | Doesn't fix the dependency itself |
| Retry with backoff | Handles transient errors | Amplifies load on a degraded dependency without a breaker |
| Timeout | Bounds the worst-case latency of a call | Doesn't prevent the call from being made |
| Bulkhead | Isolates resource pools so one dependency can't exhaust all threads | Adds configuration complexity, doesn't help with slow responses |
| Fallback | Keeps user experience degraded-but-functional when a dependency fails | Requires deliberate design; stale or default data has its own risks |

## What's next

Day 13: indexes — how databases find rows without reading every row, the trade-offs in index design, and the cases where an index makes writes slower without making reads faster.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
