# Rate Limiting

Every system has a capacity ceiling. Rate limiting is how you enforce it before the ceiling enforces itself on you.

Without it, a single misbehaving client — or a traffic spike, or a misconfigured retry loop — can consume resources that belong to everyone else. The system degrades for all users because it wasn't defended against any of them. Rate limiting is not just an API concern. It applies to database connections, downstream service calls, job queues, background processors — anywhere the cost of excess traffic falls on shared infrastructure.

## Fundamentals

### The algorithms

Different algorithms make different trade-offs between simplicity, burst tolerance, and accuracy.

**Token bucket.** A bucket holds tokens up to a maximum capacity. Tokens are added at a fixed rate. Each request consumes one or more tokens. If tokens are available, request proceeds. If not, it's rejected or queued. The bucket allows bursts up to its capacity — a client that's been idle accumulates tokens and can use them all at once. Widely used because it naturally accommodates legitimate traffic spikes while bounding the long-term rate.

**Leaky bucket.** Requests enter a queue. They drain out at a fixed rate regardless of input rate. Smooths traffic to a constant output rate. No bursting allowed. Good for downstream systems that need predictable load — database connections, third-party APIs with strict rate limits of their own. Bursty upstream traffic gets queued, not rejected, which can introduce latency if the bucket fills.

**Fixed window.** Count requests per time window — 100 requests per minute. Counter resets at the window boundary. Simple to implement. Has a well-known edge case: a client can send 100 requests at 00:59 and 100 more at 01:01, getting 200 requests in two seconds with no violation. The window boundary is exploitable.

**Sliding window log.** Track a timestamp for every request. On each new request, count how many timestamps fall within the last window. More accurate than fixed window. Memory-intensive — you're storing every timestamp.

**Sliding window counter.** Hybrid of fixed window and sliding window log. Estimate the count for the current window using the previous window's count weighted by how much of it overlaps the current window. Accurate enough for most purposes, much cheaper on memory.

```
Token bucket                         Fixed window problem

     ┌──────────────┐                Time:  00:59       01:00       01:01
     │  ●●●●●●●●●  │ ← tokens        Reqs:  100    │    0    │    100
     │  ●●●●●●●●●  │   added                       │         │
     └──────────────┘   at fixed rate          window resets
            │
      request arrives ── has tokens? ── yes ──► proceed, consume token
                                  └── no  ──► reject / queue
```

### Where to enforce it

Layer matters. Different enforcement points catch different problems.

**Edge / CDN.** Closest to the user. Catches volumetric abuse before it touches your infrastructure. AWS WAF rate-based rules, CloudFront functions. Coarse-grained — typically per-IP, not per-user. Can be bypassed by distributing traffic across many IPs.

**API Gateway.** Per-method, per-stage, per-key throttling. Protects backend services from API misuse. Usage plans let you define different limits per customer tier. Built into API Gateway and ALB listener rules.

**Application layer.** Highest granularity. Per-user, per-action, per-tenant. Understands the semantics of the request — can limit "password reset attempts" differently from "list items." Requires implementation, usually backed by Redis for distributed state.

**Service-to-service.** Rate limit outbound calls to downstream services, not just inbound calls from clients. If your service calls a third-party API with a rate limit of 100 requests/second, your application needs to enforce that limit internally. Otherwise, one traffic spike causes your entire service to receive 429s from downstream, which surfaces as errors to your users for reasons invisible to them.

## Operations

### What happens at the limit

Two choices when a request exceeds the rate limit: reject it or queue it.

**Reject with 429.** Standard HTTP response for rate limiting. Include a `Retry-After` header. Well-behaved clients back off and retry. Poorly-behaved clients don't — which is often the whole problem. Rejection is fast and doesn't consume queue resources.

**Queue it.** Holds the request until capacity is available. Smooths over short bursts. Hides the rate limit from callers. But it adds latency, and a deep enough queue starts looking like a timeout rather than a rate limit. For user-facing requests, a fast 429 is usually better than a slow success two seconds later.

**Circuit breaking** is the adjacent pattern: if a downstream service is failing or overwhelmed, stop sending requests entirely rather than hammering it further. Rate limiting controls inbound traffic. Circuit breaking controls outbound. Both belong in any system calling external dependencies.

### Distributed rate limiting

Rate limiting is easy when there's one instance. One counter, one check. The moment you have multiple instances — which is most of the time — a counter per instance doesn't work. Each instance sees only its own traffic. Ten instances each allowing 100 requests/second means 1,000 requests/second get through.

Distributed rate limiting requires a shared store. Redis is the standard choice — fast, atomic increment operations, TTL-based key expiration for sliding windows. The pattern: `INCR` the key, check the count, set expiry on first write. Atomic operations prevent race conditions between concurrent increments.

The cost: every request now has a Redis round trip. For high-throughput services, that's non-trivial. Common mitigation: batch the check — allow a small local bucket per instance that refills from the central counter periodically. Slightly less accurate but dramatically lower Redis load.

### Rate limit granularity

Coarse limits are easy to implement and easy to bypass. Per-IP rate limiting blocks one IP — distribute traffic across a botnet of ten thousand IPs and it does nothing. Finer limits require more state and more coordination.

Practical hierarchy:

1. **Per-IP** — catch volumetric abuse, DDoS mitigation. Cheapest to enforce.
2. **Per-API key / token** — enforce per-client contract limits. Standard for API products.
3. **Per-user** — right granularity for authenticated user-facing features.
4. **Per-tenant** — for multi-tenant SaaS, isolate one customer's traffic from another's. Noisy neighbor problem lives here.
5. **Per-action** — most expensive, most correct. "User X can attempt login 5 times per 15 minutes." Requires application-level logic.

Most production systems combine several layers: per-IP at the edge, per-key at API Gateway, per-user in the application. Each layer catches a different failure mode.

## Deep Dive: rate limiting on AWS

**API Gateway.** Default throttling: 10,000 requests/second at the account level, 5,000 burst. Configurable per stage and per method. Usage plans tie API keys to custom throttle limits and quotas — useful for offering different service tiers. When a request is throttled, API Gateway returns 429 immediately; it doesn't queue.

**AWS WAF.** Rate-based rules count requests per IP over a five-minute window. When the threshold is exceeded, the rule action fires — block, count, or challenge. Can be applied to CloudFront, ALB, API Gateway, AppSync. Works at the edge before traffic reaches application code. Not granular enough for per-user limits, but the right tool for volumetric abuse at scale.

**Application-layer with ElastiCache Redis.** The implementation that most teams end up with for fine-grained limits. Atomic `INCR` with `EXPIRE` for fixed-window counting; sorted sets with timestamps for sliding-window log approach. Lambda and ECS/EKS services both connect to the same Redis cluster for consistent counting across the fleet.

A sliding window counter in Redis, roughly:

```python
import redis
import time

r = redis.Redis()

def is_allowed(user_id: str, limit: int, window_seconds: int) -> bool:
    now = time.time()
    window_start = now - window_seconds
    key = f"rate:{user_id}"

    pipe = r.pipeline()
    pipe.zremrangebyscore(key, 0, window_start)   # remove expired entries
    pipe.zadd(key, {str(now): now})                # add current request
    pipe.zcard(key)                                # count in window
    pipe.expire(key, window_seconds)               # reset TTL
    _, _, count, _ = pipe.execute()

    return count <= limit
```

**Lambda concurrency as a rate limit.** Reserved concurrency on a Lambda function is effectively a rate limit on parallel executions. Set reserved concurrency to 10 and you've capped the function at 10 simultaneous invocations — excess requests get throttled with 429 or added back to the queue. Useful for protecting downstream systems that can't handle more than a known concurrency level.

| Approach | Granularity | Accuracy | Cost |
|---|---|---|---|
| WAF rate-based rules | Per-IP | High (5-min window) | Low |
| API Gateway usage plans | Per-API key | Exact | Low |
| Redis token bucket / sliding window | Per-user / per-action | High | Medium (Redis RTT) |
| Lambda reserved concurrency | Per-function | Concurrency, not rate | Low |
| Local in-process counter | Per-instance | Low (not distributed) | Minimal |

## What's next

Day 10: consistent hashing — how distributed systems route requests to nodes without reshuffling everything when the fleet size changes.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
