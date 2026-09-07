# AWS API Gateway for DevOps Engineers, Part 2: Endpoint Types and Resource Design

*Part 2 of a 7-part series. Part 1 covered fundamentals and the request lifecycle. This chapter goes deep on where your API physically lives and how to structure its resource tree. Part 3 covers integration types, Part 4 covers building and deploying, Part 5 covers security, Part 6 covers traffic management, and Part 7 closes with observability and troubleshooting.*

Two decisions get made early in an API's life and then almost never revisited: where the API's endpoint lives (edge-optimized, regional, or private), and how its resource tree is shaped. Both are cheap to get right at the start and genuinely annoying to change later — an endpoint type change means a new domain and a client migration, and a resource tree redesign means breaking every existing consumer's URLs. This chapter is about making both calls deliberately instead of by default.

---

## Endpoint Types: Where Your API Actually Lives

This is a decision people make once at creation time and then forget exists, until latency from a specific region becomes a support ticket.

| Endpoint type | How it routes | When to use it |
|---|---|---|
| **Edge-optimized** | Requests hit the nearest CloudFront edge location first, then route to your API's region | Public APIs with geographically distributed clients |
| **Regional** | Requests go straight to the API's region, no CloudFront hop | Clients concentrated in one region, or when you want to front the API with your own CloudFront distribution for more control |
| **Private** | Only reachable from within your VPC, via an interface VPC endpoint | Internal APIs that should never touch the public internet |

### Edge-optimized, in more detail

Edge-optimized APIs are automatically fronted by a CloudFront distribution that AWS manages on your behalf — you don't see it in your CloudFront console, and you can't customize its caching behavior, only API Gateway's own stage-level caching (covered in Part 6). Requests from a client in Tokyo hit a nearby edge location first, then get routed over AWS's backbone to wherever your API's region actually is, which is usually faster than that client making a direct TLS handshake all the way to, say, `us-east-1`.

The tradeoff is control. Because AWS manages that CloudFront distribution for you, you can't attach your own WAF rules to it, can't customize cache behaviors beyond what API Gateway exposes, and can't put a single CloudFront distribution in front of both this API and, say, a static frontend hosted on S3. If any of that matters, regional plus your own CloudFront distribution gives you the same latency benefit with full control.

### Regional, in more detail

A regional endpoint skips the managed CloudFront layer entirely — the client talks directly to API Gateway in whatever region you deployed to. This has become the more common default, for two reasons that aren't obvious from the console alone: it removes a layer you don't control, and it composes better with modern architectures where you're already running your own CloudFront distribution in front of a broader application (static assets, multiple APIs, custom cache behaviors per path) and want the API to be just one more origin behind it.

If your clients are genuinely concentrated in one region — an internal tool used only by a team in one office, a backend-to-backend call within the same region — the CloudFront hop of an edge-optimized endpoint adds a layer without adding a benefit.

### Private, in more detail

For internal services that should never touch the public internet, a private endpoint paired with an interface VPC endpoint means the API isn't reachable from outside your VPC at all — not "blocked by a security group," but genuinely unroutable from the internet. This solves a real architectural problem: internal services that need HTTP semantics (path routing, request validation, auth) but should never be internet-reachable, without having to reimplement network-level access control in every consuming service.

Two things about private APIs that aren't obvious until you've built one: the DNS resolution for a private API's default domain only works from *within* the VPC the endpoint is attached to (or a peered/connected VPC with the right DNS configuration) — trying to resolve it from your laptop over a VPN without the right setup just fails, which looks like a network problem but is actually expected behavior. And private APIs default to deny-all on their resource policy — you have to explicitly allow the VPC endpoint, or nothing gets through, which is covered in depth in Part 5.

---

## Designing the Resource Tree

A resource tree is easy to sketch badly and annoying to fix once clients depend on it. A few principles that hold up across most APIs:

### Nouns, not verbs, in the path

`/orders` and `/orders/{orderId}` with `GET`, `POST`, `PUT`, `DELETE` methods on them is the REST convention for a reason — the HTTP verb carries the action, so the path doesn't need to. `/getOrder` and `/createOrder` as separate resources works, but it fights the grain of everything else in the AWS ecosystem (IAM policies, API documentation tooling, client SDK generators) that assumes verb-in-method, noun-in-path.

### Path parameters vs. query strings

This is a real design decision, not just a style preference. Path parameters (`/orders/{orderId}`) identify a specific resource — the URL is meaningless without that value. Query strings (`/orders?status=shipped&limit=20`) filter or modify a collection request — the URL is still meaningful (if broader) without them. Mixing these up shows up as awkward APIs: `/orders/status/shipped` (should be a query string) or `/orders?id=abc123` (should be a path parameter) both work technically, but they make caching, logging, and client code less intuitive than they need to be. API Gateway's stage caching, for instance, is keyed off exactly this distinction — you configure which path parameters and query strings participate in the cache key, and getting the modeling right upstream makes that configuration make sense.

### The `{proxy+}` greedy path

Sometimes you don't want to model every resource explicitly — you're proxying an entire existing application behind API Gateway and want every path to fall through to the same backend. A greedy path variable, written `{proxy+}`, matches any remaining path segments:

```python
proxy_resource = client.create_resource(
    restApiId=api_id,
    parentId=root_id,
    pathPart="{proxy+}",
)

client.put_method(
    restApiId=api_id,
    resourceId=proxy_resource["id"],
    httpMethod="ANY",
    authorizationType="NONE",
)
```

Combined with the `ANY` method (matching every HTTP verb instead of registering `GET`, `POST`, `PUT`, `DELETE` separately), this is the fastest way to put API Gateway in front of an existing application with minimal per-route configuration — common when you're using API Gateway purely for TLS termination, custom domains, and a shared auth layer in front of an app that already does its own routing. The cost is that you lose per-route request validation, per-route throttling, and per-route caching, because as far as API Gateway is concerned there's only one route. It's a legitimate choice for a lift-and-shift or a thin proxy layer, and the wrong choice the moment you want fine-grained control over individual endpoints.

### How deep is too deep

There's no hard limit that matters in practice, but resource trees more than three or four levels deep (`/accounts/{accountId}/orders/{orderId}/items/{itemId}/notes`) usually signal that a nested resource should be its own top-level collection with a query parameter instead (`/notes?itemId={itemId}`). It's not wrong to nest deeply — REST purists will argue for it — but every level of nesting is another path parameter every client has to thread through, and another dimension in your request validation and IAM policy conditions. Flatten where the resource genuinely doesn't need its parent's context to be addressed.

---

## Method-Level Concepts Worth Knowing Early

A few settings live at the method level that are easy to skip past in the console but matter for how you'll build in Part 4:

- **`ANY` vs explicit verbs** – `ANY` is convenient for proxy integrations where your backend does its own verb-based routing, but it means API Gateway can't apply verb-specific request validation or throttling. Explicit verbs (`GET`, `POST`, etc.) are almost always the better choice once you're not just proxying wholesale.
- **`API_KEY_REQUIRED`** – a boolean on the method, independent of `authorizationType`, that determines whether a request needs a valid API key (checked against usage plans, covered in Part 6) in addition to whatever authorizer is configured. It's easy to set this and forget it's a separate axis from authorization entirely.
- **Method-level request parameters** – you can declare specific query strings or headers as required or optional at the method level, and API Gateway will reject requests missing a required one before your integration is ever invoked, similar in spirit to request body validation but for parameters instead of the body.

---

## Do This, Not That

| Instead of... | Do this |
|---|---|
| Modeling actions as path segments (`/getOrder`, `/createOrder`) | Use nouns in the path and let the HTTP verb carry the action (`GET /orders`, `POST /orders`) |
| Using a path parameter for something that filters a collection | Use a query string for filters, reserve path parameters for identifying a specific resource |
| Reaching for `{proxy+}` and `ANY` by default because it's less config | Model resources and verbs explicitly unless you're deliberately building a thin proxy in front of an app that does its own routing |
| Nesting resources four or five levels deep because the data model is nested | Flatten resources that don't strictly need their parent's context to be addressed |
| Choosing edge-optimized by habit | Choose regional unless your clients are genuinely geographically distributed and you don't want to manage your own CloudFront |
| Assuming a private API's default domain resolves from anywhere with VPN access | Verify DNS resolution is scoped correctly to the VPC (or peered VPCs) the endpoint is actually attached to |

---

## What's Next

Part 3 goes deep on the six integration types — Lambda proxy, Lambda custom, HTTP proxy, HTTP custom, AWS service, and Mock — including when a mapping template earns its complexity and when a proxy integration's simplicity is the better trade.

More DevOps and cloud infrastructure write-ups like this live at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — issues and PRs from fellow practitioners are always welcome.
