# API Design and Versioning

An API is a contract. Once clients depend on it, changing it breaks them. The problem isn't the first version — that's just design. The problem is every version after it, when real clients are running in production and you can't coordinate a simultaneous upgrade across all of them.

Most API versioning problems aren't technical. They're a failure to treat the API as a product with a lifecycle from the start. Design it like you'll never change it. Version it like you will.

## Fundamentals

### What makes a breaking change

Not all changes break clients. Know the difference.

**Non-breaking (backward-compatible):**
- Adding a new optional field to a response
- Adding a new optional request parameter
- Adding a new endpoint
- Adding a new enum value (with caveats — clients that switch on enum values and have no default case will break)

**Breaking:**
- Removing a field from a response
- Renaming a field
- Changing a field's type (`string` → `integer`)
- Changing the semantics of an existing field
- Making a previously optional parameter required
- Removing an endpoint

The instinct to "just rename that field to something cleaner" is the most common source of breaking changes. Rename it in a new version. Keep the old name in the current one.

### Versioning strategies

**URL path versioning.** `/v1/users`, `/v2/users`. Explicit, visible, easy to route in a load balancer or API Gateway. Cache-friendly — different versions are different URLs. Breaks REST purity (a resource shouldn't have a version in its path) but the pragmatic choice for most teams. Clients know exactly what version they're calling. The version is visible in logs, metrics, and dashboards.

**Header versioning.** `Accept: application/vnd.api+json;version=2` or a custom `API-Version: 2` header. Cleaner URLs. Harder to test in a browser. Requires the routing layer to inspect headers. Less visible in access logs by default. Preferred by API purists. Operationally more painful.

**Query parameter versioning.** `/users?version=2`. Easy to add. Easy to miss. Not cache-friendly because the same URL with different query parameters may or may not be cached as different resources depending on the CDN configuration. Generally the worst of the three options for production APIs.

**No versioning.** Design the API to evolve without versions. Only add, never remove. Deprecate fields with documentation and sunset headers (`Sunset: Sat, 01 Jan 2027 00:00:00 GMT`). Works well for internal APIs where you control all consumers. Fragile for public APIs where consumers are outside your deployment boundary.

```
URL versioning                    Header versioning

GET /v1/users/123                 GET /users/123
GET /v2/users/123                 API-Version: 2

(different URLs, easy to route)   (same URL, routing on headers)
```

### Designing for change

The cheapest way to handle versioning is to not need it. A few patterns that extend the life of a version:

**Use envelopes consistently.** Wrap responses in an object rather than returning arrays or primitives at the top level. `{"data": [...], "meta": {...}}` is extensible. `[...]` is not — you can't add metadata without a breaking change.

**Treat all new fields as optional.** Clients must ignore fields they don't understand. Design server responses the same way — unknown request fields should be ignored, not rejected. This is Postel's Law applied to API design: be conservative in what you send, liberal in what you accept.

**Avoid exposing internal IDs and enums directly.** A database auto-increment ID in the API response means the client assumes integer IDs. Switch to UUIDs later and it's a breaking change. An internal status enum exposed as-is means adding a new status value is a potentially breaking change for any client that doesn't handle unknown values. Abstract these at the API layer.

## Operations

### Running multiple versions simultaneously

Every version you add is one more you have to run and maintain. Version proliferation is a real cost. Three active API versions means three code paths, three sets of tests, three things to consider when the database schema changes.

Deprecation is non-negotiable. Announce the deprecation date clearly, enforce it with `Sunset` headers in responses, monitor traffic to the deprecated version, and follow through. The failure mode: announce a deprecation, watch version traffic never drop to zero, quietly extend the deadline twice, and end up running five versions indefinitely.

Tracking per-version traffic in API Gateway or CloudWatch lets you make the deprecation conversation data-driven. "Version 1 still gets 12,000 requests per day from two clients" is a concrete conversation. "Version 1 usage is down 98% and the remaining traffic is from one integration test that hasn't been updated" is a different one.

### Versioning internal vs external APIs

Different rules.

**Internal APIs** — between services you own and deploy. You control both sides. No external consumers. Prefer evolutionary design over explicit versioning: keep changes backward-compatible, deprecate fields rather than removing them, coordinate upgrades across services in a single deployment window when a breaking change is unavoidable. Consumer-driven contract testing (Pact, for example) catches breaking changes before they reach production.

**External APIs** — consumed by third parties, mobile clients, or partners. You don't control when they upgrade. Explicit versioning is mandatory. Long deprecation windows (six months minimum for anything with significant usage). SLA on version support lifetime. Clear documentation on what changed and how to migrate.

The mistake: treating internal APIs with external-API discipline (over-engineered) or treating external APIs with internal-API casualness (breaking clients silently).

### Idempotency keys

Write operations need to be safe to retry. Networks are unreliable. A client sends a payment request, the network drops the response, the client doesn't know if the payment succeeded. It retries. Now the payment has run twice.

Idempotency keys solve this. Client generates a unique key, sends it with the request (`Idempotency-Key: <uuid>`). Server stores the key alongside the result. If the same key arrives again, the server returns the stored result instead of re-executing the operation. Client can retry freely without risk of duplication.

Store idempotency keys with a TTL. 24 hours is typical. After that window, a retry is treated as a new request. The key needs to be stored in a durable, shared store — not in-memory, since the retry might hit a different instance.

## Deep Dive: API versioning on AWS

**API Gateway.** Stages are the natural versioning unit — `dev`, `staging`, `v1`, `v2`. Each stage has its own URL: `https://api-id.execute-api.region.amazonaws.com/v1`. Stage variables can parameterize backend integrations, so `/v1` and `/v2` can point to different Lambda function aliases or different backend URLs without duplicating the API definition.

Custom domain names with base path mappings decouple the friendly URL from the stage. `api.example.com/v1` maps to the `v1` stage. `api.example.com/v2` maps to the `v2` stage. When you're ready to retire a version, remove the mapping. The URL returns 403, which is better than silently routing old requests to a new API version they're not compatible with.

**Lambda function aliases and versions.** Pair with API Gateway stage variables for clean version management. Lambda function alias `v1` points to a specific published version. API Gateway stage `v1` uses the `v1` alias. Deploying new logic publishes a new Lambda version, updates the `v2` alias to point to it, but the `v1` stage and alias remain unchanged. Rollback is an alias pointer update — seconds, no redeployment.

**Usage plans.** Rate limits and quotas per API key. Use these to differentiate service tiers — free tier clients get 1,000 requests per day, paid clients get unlimited. Also useful during a version migration: apply a tighter usage plan to deprecated version endpoints to create economic pressure to migrate, rather than just hoping clients move on their own.

Logging setup worth doing on every API: enable access logging to CloudWatch with a JSON format that includes `$context.httpMethod`, `$context.path`, `$context.requestId`, `$context.status`, `$context.responseLatency`, and `$context.identity.apiKey`. That combination gives you per-endpoint latency, error rates by status code, and per-client usage — everything you need to operate the API and manage the version lifecycle with real data.

| Strategy | Visibility | Cache-friendly | Routing simplicity | Best for |
|---|---|---|---|---|
| URL path (`/v2/`) | High | Yes | Simple | Most public APIs |
| Header | Low | No | Requires header inspection | REST purists, internal APIs |
| Query param | Medium | No | Simple | Prototyping, avoid in production |
| Evolutionary (no version) | N/A | N/A | N/A | Internal APIs with controlled consumers |

## What's next

Day 16: content delivery networks — how CDNs work at the edge, cache hierarchy, origin offload, and where CDNs fail you if you don't understand what they're actually caching.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
