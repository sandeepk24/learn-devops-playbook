# Caching

Caching is storing a result so you don't compute or fetch it again. Concept is simple. Implementation is where systems quietly accumulate technical debt, stale reads, and incidents that are hard to diagnose because the cache makes everything look fine until it doesn't.

The cache hit rate tells you how often you're saving work. The harder question, the one fewer people ask: what happens on a miss, and what happens when the cached value is wrong?

## Fundamentals

### Cache placement

Where the cache sits determines what problems it solves and what problems it creates.

**Client-side caching.** Browser cache, mobile app cache, CDN. Closest to the user, lowest latency. Also the least control — you can't invalidate it reliably. HTTP cache headers give you hints. The client decides what to do with them.

**CDN caching.** Edge nodes serving static or semi-static content from the nearest geographic location. Eliminates origin requests for cacheable content. Effective for anything that doesn't change per user. Falls apart for personalized or frequently-updated content.

**Application-layer caching.** In-memory cache inside the application process, or a shared cache like Redis or Memcached. Most flexible. You control what's cached, for how long, and how invalidation works. Also where most cache-related bugs originate.

**Database query caching.** Built into some database engines. Caches query result sets. Invalidated automatically on writes to relevant tables. Can mask a slow query problem rather than fixing it — the query is still bad, it's just not running often enough to matter. Until it does.

```
Request flow with cache:

Client ──► App ──► Cache ──hit──► return value
                      │
                    miss
                      │
                      ▼
                  Database ──► store in cache ──► return value
```

### Cache invalidation

Phil Karlton's quote has been repeated enough that it's become a cliché. Still true. Naming is the other hard thing — cache invalidation is genuinely difficult because you're maintaining a copy of data that lives somewhere else, and you need to know when that somewhere else changes.

Three main strategies:

**TTL-based expiration.** Value lives in cache for a fixed duration, then gets evicted. Simple. No invalidation logic required. Trade-off: stale reads during the TTL window. Fine for data that can tolerate some lag — weather, exchange rates, leaderboards. Not fine for inventory counts or account balances.

**Write-through.** On every write, update both cache and database. Cache is always current. Cost: every write goes to two places, which adds latency and introduces a failure mode — what happens if the cache write succeeds but the database write fails? Or vice versa?

**Cache-aside (lazy loading).** Application checks cache on read. Miss triggers a database read and a cache write. Cache contains only data that's been requested at least once. Straightforward. Leaves a consistency window between when data changes and when the cache entry expires or gets explicitly invalidated.

No strategy is cleanly correct. The right one depends on whether your system can tolerate stale reads, how often data changes, and how much you want to spend on write latency.

### Cache eviction

Caches have finite space. When they fill up, something gets removed.

**LRU (Least Recently Used).** Evicts the entry that hasn't been accessed for the longest time. Works well for data with temporal locality — recently accessed things tend to be accessed again soon.

**LFU (Least Frequently Used).** Evicts the entry accessed least often. Better for data with stable hot spots. A one-time burst of reads won't protect a low-frequency item from eviction later.

**TTL expiration.** Eviction by age, not usage. Predictable. Doesn't adapt to access patterns.

Most production caches use LRU or a variant. Know what your cache does when it's full, because full caches under load start evicting things you didn't expect to evict, miss rates spike, and suddenly the database is getting hammered by traffic the cache used to absorb.

## Operations

### Cache stampede

Backend takes ten seconds to compute a value. You cache it. One thousand concurrent requests arrive while it's expired. All one thousand see a cache miss simultaneously. All one thousand kick off the expensive computation at the same moment. Database or backend gets hit with one thousand parallel requests for the same thing.

This is a cache stampede. Also called a thundering herd. The fix: probabilistic early expiration, or a lock/semaphore that lets one request refresh the cache while others wait. Simpler version: set slightly randomized TTLs so entries don't all expire together.

Easy to miss in development. Appears in production under load.

### Cache poisoning and inconsistency

Cache is a copy. Copies drift. Sources of drift:

- Direct database writes that bypass application code (migrations, scripts, manual fixes) don't update the cache
- Multi-region deployments where writes replicate with lag
- Application bugs that write incorrect values and cache them

When a cache entry is wrong and the TTL is long, users see wrong data for a long time. When a cache entry is wrong and you don't know it's wrong, you troubleshoot the database, the code, everything except the cache. Monitoring cache hit rate alone doesn't catch poisoning.

Operational habit: have a way to inspect cached values in production, and have a way to evict specific keys without flushing the entire cache. Both matter when debugging a data inconsistency.

### The cold start problem

Fresh deployment. New region. Cache is empty. Every request is a miss. All traffic hits the backend directly. If the backend was sized assuming a warm cache, this is when it falls over.

Seen most often after blue/green deployments that bring up a fresh environment, after cache cluster restarts, and after region failovers. Solutions: cache warming scripts that pre-populate high-value keys before traffic shifts, gradual traffic migration, or backends sized to handle full uncached load (expensive but safe).

## Deep Dive: caching on AWS

**ElastiCache for Redis.** Managed Redis. In-memory key-value store. Handles session storage, rate limiting counters, leaderboards, pub/sub, and general-purpose application caching. Cluster mode distributes data across shards for horizontal scale. Global Datastore replicates across regions.

**ElastiCache for Memcached.** Simpler. Multi-threaded. No persistence, no replication, no complex data structures. Pure cache. If you need something fast and straightforward with no operational overhead from replication, Memcached is a reasonable choice.

**DAX (DynamoDB Accelerator).** In-memory cache purpose-built for DynamoDB. Sits transparently in front of your tables. Microsecond reads for cache hits. Compatible with DynamoDB SDK — no application code changes. Useful when DynamoDB read costs or latency are a constraint. Worth evaluating before over-provisioning RCUs.

**CloudFront.** CDN. Cache at the edge, globally distributed. Works well for static assets, and increasingly for dynamic content with careful cache-control header configuration. Behaviors let you set per-path cache rules. Origin Shield adds a regional cache tier between edge and origin to reduce origin load.

One operational note on Redis specifically: `KEYS *` on a production cluster will block the event loop and cause latency spikes. Use `SCAN` instead. Obvious in retrospect, painful the first time you run it at 2 AM trying to debug something.

| Cache Layer | Best For | Watch Out For |
|---|---|---|
| CDN (CloudFront) | Static assets, semi-static pages | Personalized content, aggressive cache-control needed |
| Redis (ElastiCache) | Sessions, rate limiting, app-layer data | Stampedes, memory sizing, eviction policy |
| DAX | DynamoDB read acceleration | Write-through only, doesn't cache all operations |
| Memcached | Simple high-throughput key-value caching | No persistence, no replication, no complex types |
| In-process | Microsecond latency, no network hop | Per-instance state, not shared across fleet |

## What's next

Day 7: database replication and the consistency trade-offs that come with it — primary/replica lag, read replicas under load, and what "synchronous replication" actually costs.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
