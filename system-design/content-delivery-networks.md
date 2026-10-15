# Content Delivery Networks

A CDN is a geographically distributed network of cache nodes. Request arrives at the nearest edge location instead of traveling to your origin. Faster for the user. Less load on your infrastructure. For anything static or semi-static, it's one of the highest-leverage performance improvements available.

What CDNs don't do: they're not magic. A cache miss still goes to origin. Personalized or authenticated content that can't be cached still hits your servers for every request. And a misconfigured CDN can cache the wrong things — private data served to the wrong user, stale content that never refreshes — in ways that are worse than not having a CDN at all.

## Fundamentals

### How edge caching works

User in Tokyo requests an asset. Without a CDN, that request travels to your us-east-1 origin — 150ms round trip, minimum, just for physics. With a CDN, the Tokyo edge node checks its cache. Hit: response in 5ms. Miss: edge fetches from origin, caches the response, returns it to the user. Every subsequent request from Tokyo for the same asset is served locally until the cache entry expires.

The cache key determines what counts as the same request. By default it's the URL. Two requests to the same URL are the same cache entry. This breaks down immediately for dynamic content — `/home` for user A and `/home` for user B are the same URL but should return different content. Caching based on URL alone would serve user A's data to user B.

**Cache key customization.** Include headers, cookies, or query parameters in the cache key to differentiate requests that share a URL but need different responses. Add the `Accept-Language` header to the key to serve localized content correctly. Add a session cookie to the key to prevent cross-user cache poisoning — though at that point you're caching per-user content, which means cache hit rates approach zero and you've lost most of the CDN's value for that content type.

### Cache-Control headers

The origin controls caching behavior through HTTP headers. The CDN respects them. If the headers are wrong, behavior is wrong — at the CDN layer and at every downstream cache, including the browser.

`Cache-Control: public, max-age=31536000, immutable` — cache for one year, mark as immutable. For versioned static assets (`main.8f3a2c.js`), this is correct. The content hash in the filename guarantees the URL changes when content changes. Stale content is never a risk.

`Cache-Control: no-store` — don't cache anywhere. For authenticated API responses, sensitive data, anything that must always come from origin.

`Cache-Control: no-cache` — cache is allowed but must revalidate with origin before serving. The CDN stores the response but checks with origin each time. If origin returns 304 Not Modified, the CDN serves from cache without re-downloading. Reduces bandwidth but doesn't reduce origin request count.

`Cache-Control: private` — can be cached by the browser but not by shared caches, including CDNs. For user-specific content that's safe to cache in the browser but shouldn't be in a shared edge cache.

```
Origin response headers → CDN behavior

Cache-Control: public, max-age=3600   → cache for 1 hour, serve without revalidation
Cache-Control: no-store               → never cache, always fetch from origin
Cache-Control: no-cache               → cache but revalidate every request
Cache-Control: private                → bypass CDN cache, go to origin
Vary: Accept-Encoding                 → cache separate versions per encoding
```

### Origin shield

Most CDN architectures have two tiers: edge nodes (PoPs) close to users, and a smaller set of regional mid-tier nodes between edge and origin. Origin shield is a designated regional cache that aggregates cache misses from multiple edge nodes before they reach origin.

Without origin shield: ten edge nodes all miss the cache simultaneously for the same object. Ten requests hit origin. With origin shield: those ten requests hit the regional node. One cache miss propagates to origin. Nine are served from the shield.

At high traffic volumes with low cache hit rates, origin shield can dramatically reduce origin load. At low traffic volumes, it adds a hop without much benefit. Worth enabling when origin is expensive, slow, or fragile under load.

## Operations

### Cache invalidation in production

Content changes. The CDN has the old version cached. Users see stale content until TTL expires.

Two approaches to invalidation:

**Explicit purge.** Send an invalidation request to the CDN to evict specific paths or patterns. Takes effect in seconds. Useful for urgent corrections — wrong price on a product page, broken content that needs immediate removal. Most CDNs charge per invalidation or rate-limit them. Don't design a system that depends on frequent programmatic purges; that's a sign the cache TTL is wrong.

**Cache-busting via versioned URLs.** The cleaner approach for static assets. Change the filename when content changes (`app.v2.js` or `app.8f3a2c.js` with a content hash). The old URL remains cached and valid — it's just not requested anymore because the HTML now references the new URL. No invalidation needed. No stale content risk. This is how every mature frontend build pipeline works.

For semi-dynamic content that can't use versioned URLs — a CMS page, a product listing — set a TTL that reflects how stale is acceptable. Ten-minute TTL means at worst ten minutes of stale content after a change. That's usually fine. Two-hour TTL for content that editors expect to update and see immediately is not fine — have that conversation explicitly.

### Bypassing the cache when needed

Some requests must always hit origin. Authentication flows. Payment processing. Any request that writes state. Most CDN configurations pass through POST, PUT, DELETE, and PATCH by default, caching only GET and HEAD responses. Verify this is actually the behavior for your CDN configuration and don't assume it.

For GET requests that must bypass the cache: use `Cache-Control: no-store` or `no-cache` on the origin response, or configure the CDN to forward specific headers that disable caching for matching requests.

Cache bypass based on a cookie is a common pattern: if a logged-in session cookie is present, bypass the CDN and hit origin. This correctly handles personalized content. The edge case to watch: a misconfigured rule that accidentally caches the first authenticated response and then serves it to unauthenticated users. Test this explicitly.

### Debugging cache behavior

`X-Cache` header in the response: `Hit` or `Miss`. Most CDNs include this. First thing to check when behavior seems wrong.

`Age` header: how many seconds the response has been in cache. `Age: 0` on a cache hit means it was just cached. `Age: 3590` on a 3600-second TTL means it's about to expire.

Check what URL the CDN is actually caching. Query parameters that should vary the response but aren't in the cache key will cause collisions. CloudFront's cache behavior configuration explicitly lists which query parameters to include in the key; parameters not listed are stripped before the cache key is computed, meaning `?user=a` and `?user=b` map to the same cache entry.

## Deep Dive: CloudFront on AWS

**Distributions and behaviors.** A CloudFront distribution is the top-level object. Behaviors are routing rules within it — path patterns matched against the request URL, each with its own cache policy and origin. `/static/*` goes to S3 with a year-long TTL. `/api/*` bypasses cache and forwards to an ALB. `/*` serves a default with a five-minute TTL. This per-path configuration is where most of the useful control lives.

**Cache policies vs origin request policies.** Two distinct concerns in CloudFront, separated as of 2020.

Cache policy: what goes into the cache key (URL path + selected headers + selected cookies + selected query strings). Controls what the CDN considers a unique cacheable object.

Origin request policy: what gets forwarded to origin on a miss (additional headers, cookies, query strings). The origin might need the `Authorization` header or a specific cookie for authentication, but you don't want those in the cache key because they'd effectively disable caching. Origin request policy sends them to origin without including them in the key.

**S3 as origin.** The canonical CloudFront setup. S3 serves static assets with public access disabled — all access goes through CloudFront using an Origin Access Control (OAC). No direct public bucket URL. Users get the CDN URL. S3 costs stay minimal because CloudFront serves cached content and only misses reach S3.

**Lambda@Edge and CloudFront Functions.** Code that runs at the edge, attached to CloudFront events. Lambda@Edge runs at regional edge locations, full Lambda execution environment, higher latency than functions. CloudFront Functions run at every PoP, sub-millisecond execution, V8 JavaScript only, restricted API.

Use cases: URL rewrites, A/B test header injection, auth token validation at the edge before requests reach origin, custom cache key manipulation. Both are event-driven against four hooks: viewer request, origin request, origin response, viewer response. Viewer request is the hook for authentication and routing. Origin request is for modifying what goes to origin. Don't run heavy logic on viewer response — it's on the critical path for every cached and uncached response.

**Real-time logs.** CloudFront can stream access logs to Kinesis Data Streams with sub-second latency. Standard access logs go to S3 with a 5–24 hour delay. For anything requiring near-real-time traffic visibility — security monitoring, DDoS detection, dynamic rate limiting at the edge — real-time logs are the right choice.

| Cache-Control directive | CDN behavior | Browser behavior |
|---|---|---|
| `public, max-age=N` | Cache for N seconds | Cache for N seconds |
| `private, max-age=N` | Bypass cache | Cache for N seconds |
| `no-cache` | Cache but revalidate | Cache but revalidate |
| `no-store` | Never cache | Never cache |
| `immutable` | Hint: won't change within max-age | Skip revalidation within max-age |
| `s-maxage=N` | Override max-age for shared caches | Ignored |

## What's next

Day 17: event-driven architecture — decoupling services through events, the difference between commands and events, and the consistency problems that emerge when your system is a web of async reactions.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
