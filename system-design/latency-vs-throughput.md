# Latency vs. Throughput

These two get lumped together constantly. Same conversation, two names. They're not.

You can improve one and wreck the other without touching anything else. Miss that, and you optimize for the wrong number while users keep complaining — even though dashboards look great.

Short version: latency is how long one request takes. Throughput is how many requests get through in a given window. Both involve "speed." They answer completely different questions. A system can excel at one while being mediocre at the other.

## Fundamentals

### Latency: the wait

Start the clock. Do the work. Stop the clock. That's latency. When someone says "the API feels slow," they mean latency. That's what humans experience. Nobody sitting at a keyboard feels throughput. They feel how long they waited.

Gets more useful once you stop treating it as one number. The average lies. Say average latency is 100ms. Sounds fine. But what if 95% of requests return in 20ms and 5% take two full seconds? Average still looks great. One in twenty users has a genuinely bad experience. This is why production systems rarely report average alone. You see p50, p95, p99 — 50th, 95th, 99th percentile — because those show what the tail looks like. The tail is where problems live.

### Throughput: the volume

Capacity, not experience. Requests per second. Transactions per minute. Whatever unit fits. It answers "how much can this handle," not "how did any individual request feel." A batch job processing ten million records overnight cares enormously about throughput. Doesn't care at all that one record took 50ms instead of 5ms. Nobody's staring at that record.

### Why they pull against each other

Here's what trips people up. Pushing throughput up often pushes latency up. Not a bug. Physics.

Batching is the clearest example. Process requests one at a time as they arrive, and latency per request is as low as possible — but you're leaving throughput on the table because you're not using any economy of scale. Batch twenty requests together, process as a group, and throughput jumps. More work per unit of overhead. But now the first request in that batch of twenty waits for nineteen others to show up before anything happens. Traded latency for throughput. On purpose. Often the right call. Not free.

```
Low latency, low throughput          High throughput, higher latency

  req ──► [process] ──► resp           req1 ─┐
  req ──► [process] ──► resp           req2 ─┼─► [batch] ──► resp×20
  req ──► [process] ──► resp           ...    │   (after waiting
  (one at a time, fast each time)      req20 ─┘    for the batch)
```

## Operations

### Match the metric to the actual system

Same mistake over and over: optimizing for the wrong one because it's easier to measure, or sounds better on a slide.

User-facing checkout flow needs to obsess over p99 latency. That tail is where you lose sales. Nobody forgives a two-second hang just because your average is fast. Nightly ETL pipeline moving billions of rows? Doesn't care about any individual row's latency. Cares whether the whole job finishes in its window. Optimizing that pipeline for latency means shaving milliseconds off something nobody watches in real time, while the actual lever — throughput — sits untouched.

Before optimizing anything, ask plainly: is a human waiting, or is this about total volume over time? That question tells you which metric deserves attention, and which one you can sacrifice to improve the other.

### Where this actually bites you in production

Connection pools. Small pool keeps latency low when traffic is light — requests get a connection immediately. Push more traffic through that same pool, and requests start queuing. Latency climbs. Backend didn't get slower. System's throughput ceiling became a latency problem.

Queues do this too. Counterintuitive at first. A queue can improve throughput — smooths bursts, lets you process at a sustainable pace instead of getting overwhelmed — while making individual message latency worse. Every message now sits behind whatever arrived before it. Both true. Same design decision. Not a contradiction. Two measurements of two concerns. Decide up front which one your system can afford to sacrifice.

## Deep Dive: measuring this on AWS

CloudWatch gives you both. Have to go looking for the right numbers.

ALB's `TargetResponseTime` gives latency. Default CloudWatch shows average — which hides exactly what you need to see. Switch to p99. Often a much less comfortable story.

For throughput, `RequestCountPerTarget` combined with target group health tells you whether load spreads evenly, or a handful of targets quietly absorb more traffic than the rest. Shows up as latency problems on those overloaded targets. Throughput imbalance disguising itself as latency if you're not looking in the right place.

Quick way to see the trade-off in your own numbers:

```python
import time
import statistics

latencies = []

def timed_request(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    latencies.append(time.perf_counter() - start)
    return result

# after a batch of calls:
p50 = statistics.median(latencies)
p99 = statistics.quantiles(latencies, n=100)[98]
throughput = len(latencies) / sum(latencies)  # rough requests/sec

print(f"p50: {p50*1000:.1f}ms  p99: {p99*1000:.1f}ms  throughput: {throughput:.1f} req/s")
```

Run this against a service under a batching change. You'll see it directly: throughput up, p99 up with it. Real numbers to decide whether the trade was worth it.

| | Optimize for Latency | Optimize for Throughput |
|---|---|---|
| Best for | User-facing, interactive requests | Batch jobs, background processing |
| What you measure | p50 / p95 / p99 | Requests or records per second |
| Common technique | Smaller batches, more parallelism, caching | Batching, queuing, connection pooling |
| Trade-off accepted | Lower total capacity | Slower individual requests |
| Where it breaks if ignored | Checkout flows, live APIs, anything real-time | Nightly jobs missing their window, pipeline backlog |

## What's next

Day 4: CAP theorem. Everyone's heard of it. Half can recite it. Fewer can apply it correctly under pressure.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
