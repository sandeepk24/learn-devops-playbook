# AWS API Gateway for DevOps Engineers, Part 6: Traffic Management and Custom Domains

*Part 6 of a 7-part series. Parts 1–3 covered core concepts, Part 4 covered building and deploying, Part 5 covered security. This chapter covers what happens once real traffic — and real clients you don't fully trust to behave — starts hitting your API. Part 7 closes the series with observability and troubleshooting.*

Everything up to this point assumes one well-behaved client making reasonable requests. Production doesn't work that way. One client integrates a retry loop with no backoff, another starts a batch job that hammers your endpoint at 2 AM, and suddenly your "it works on my machine" API is the reason a downstream team's dashboard is red. This chapter is about controlling that before it controls you.

---

## Throttling: Three Layers, Not One

There isn't a single throttle — there are three, stacked, and understanding which one fired is half the debugging work when you see a `429`.

```
Account-level throttle (whole account, all APIs)
        │
        ▼
Stage-level throttle (this API, this stage)
        │
        ▼
Method-level throttle (this specific method, if overridden)
        │
        ▼
Usage plan throttle (this specific API key, if using usage plans)
```

**Account-level** is a hard ceiling AWS sets per account per region (commonly 10,000 requests/second burst, 5,000 steady-state — always verify current limits for your account, AWS adjusts these over time and they can be raised via support ticket). This is the limit that, left unmanaged, means one runaway client can throttle every other client sharing the account.

**Stage-level and method-level** throttles are ones you set yourself, and they default to inheriting the account limit unless overridden:

```python
client.update_stage(
    restApiId=api_id,
    stageName="prod",
    patchOperations=[
        {"op": "replace", "path": "/throttle/burstLimit", "value": "200"},
        {"op": "replace", "path": "/throttle/rateLimit", "value": "100"},
    ],
)
```

**Usage-plan throttles** are per-client, tied to an API key, and this is the mechanism you want in place *before* a noisy client shows up, not after:

```python
plan = client.create_usage_plan(
    name="partner-tier-standard",
    throttle={"burstLimit": 50, "rateLimit": 20},
    quota={"limit": 100000, "period": "MONTH"},
    apiStages=[{"apiId": api_id, "stage": "prod"}],
)

key = client.create_api_key(name="partner-acme-corp", enabled=True)

client.create_usage_plan_key(
    usagePlanId=plan["id"],
    keyId=key["id"],
    keyType="API_KEY",
)
```

Burst versus rate is worth being precise about: **rate limit** is the sustained steady-state requests-per-second allowed, while **burst limit** is the size of the token bucket that absorbs short spikes above that rate. A client sending 15 requests in a single second against a `rateLimit=10, burstLimit=20` plan gets through fine — they're within the burst allowance — but the same client sustaining 15 req/s for a minute starts getting throttled once the bucket drains, because that's above the steady-state rate.

---

## Caching: Trading Freshness for Latency and Backend Load

API Gateway can cache responses at the stage level, keyed by request parameters you specify, without any change to your backend at all.

```python
client.update_stage(
    restApiId=api_id,
    stageName="prod",
    patchOperations=[
        {"op": "replace", "path": "/cacheClusterEnabled", "value": "true"},
        {"op": "replace", "path": "/cacheClusterSize", "value": "0.5"},
    ],
)

client.update_method(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="GET",
    patchOperations=[
        {"op": "replace", "path": "/caching/enabled", "value": "true"},
        {"op": "replace", "path": "/caching/ttlInSeconds", "value": "300"},
    ],
)
```

This is genuinely useful for read-heavy, slowly-changing data — a product catalog, a config endpoint — where shaving backend load matters more than sub-5-minute freshness. It's the wrong tool the moment your response depends on per-user state or changes frequently, because a misconfigured cache key means one user's response gets served to another — worth testing explicitly, not just assuming the default cache key (method request parameters) does what you expect.

The cache cluster itself costs money continuously, independent of request volume — it's provisioned capacity, not pay-per-use — so this is a deliberate cost tradeoff against reduced backend load, not a free performance win.

---

## Canary Deployments: Shipping to a Slice of Traffic

Instead of a deployment going 100% live instantly, a canary release routes a configurable percentage of traffic to the new deployment while the rest continues hitting the previous one — the same pattern you'd recognize from ECS or Lambda alias traffic shifting, applied at the Gateway layer.

```python
client.update_stage(
    restApiId=api_id,
    stageName="prod",
    patchOperations=[
        {"op": "replace", "path": "/canarySettings/percentTraffic", "value": "10"},
        {"op": "replace", "path": "/canarySettings/deploymentId", "value": new_deployment_id},
    ],
)
```

Watch your error-rate and latency metrics (Part 7 covers exactly which ones) on the canary before promoting it to 100%. Promotion itself is a separate, deliberate call — nothing shifts automatically just because the canary looks healthy for a few minutes, which is the right default: you decide when the evidence is enough.

---

## Custom Domain Names: Getting Off `execute-api`

Nobody wants to hand a partner a URL like `a1b2c3d4e5.execute-api.us-east-1.amazonaws.com/prod`. Custom domains map a real hostname to your API, and base path mapping lets one domain serve multiple APIs under different path prefixes.

```python
domain = client.create_domain_name(
    domainName="api.yourcompany.com",
    regionalCertificateArn=f"arn:aws:acm:{region}:{account_id}:certificate/your-cert-id",
    endpointConfiguration={"types": ["REGIONAL"]},
)

client.create_base_path_mapping(
    domainName="api.yourcompany.com",
    basePath="orders",
    restApiId=api_id,
    stage="prod",
)
```

That gives you `api.yourcompany.com/orders` routing to this API's `prod` stage. A second API could map `api.yourcompany.com/inventory` to a completely different API — one domain, multiple backend APIs, invisible to the client.

Two things worth knowing before you hit them as surprises:

- The ACM certificate for a **regional** endpoint must be in the **same region** as the API. For an **edge-optimized** endpoint, the certificate must be in **us-east-1**, regardless of where your API actually lives — a CloudFront requirement that trips people up constantly, because it's not obvious from the API Gateway console alone.
- After creating the domain name, you still need a Route 53 (or your DNS provider's) record pointing at the `regionalDomainName` (or `distributionDomainName` for edge-optimized) that AWS gives you back — the custom domain name resource alone doesn't make DNS resolve.

---

## Binary Media Types and Payload Compression

Two smaller settings that matter more than their size in the console suggests.

**Binary media types** control whether API Gateway treats a response as text (base64-safe passthrough) or binary (actual bytes) — this matters the moment you're serving images, PDFs, or any non-JSON payload through a Lambda proxy integration. Without configuring this, a Lambda returning an image ends up corrupted on the client side because it was double-encoded.

```python
client.update_rest_api(
    restApiId=api_id,
    patchOperations=[
        {"op": "add", "path": "/binaryMediaTypes/image~1png", "value": ""},
    ],
)
```

(Note the `~1` — that's the JSON Patch escape for a literal `/` in the path, since `image/png` contains one.)

**Payload compression** reduces response size over the wire for clients that send `Accept-Encoding: gzip`, at the cost of a small amount of CPU time on API Gateway's side (which you don't pay for directly, but which does add negligible latency):

```python
client.update_rest_api(
    restApiId=api_id,
    patchOperations=[
        {"op": "replace", "path": "/minimumCompressionSize", "value": "1024"},
    ],
)
```

Worth enabling for any API returning JSON payloads over a few KB — it's close to free and meaningfully cuts transfer time for clients on slower connections.

---

## Do This, Not That

| Instead of... | Do this |
|---|---|
| Sharing one usage plan across every client "for now" | Set per-client throttles the same week you onboard a second client |
| Assuming a canary deployment shifts traffic automatically once it looks healthy | Treat promotion as a deliberate, separate action gated on your own review of metrics |
| Enabling caching on an endpoint with per-user response data without checking the cache key | Verify the cache key includes whatever distinguishes one user's valid response from another's before flipping caching on |
| Discovering the us-east-1 certificate requirement for edge-optimized domains during an incident | Confirm certificate region against endpoint type before you're mid-deployment |
| Serving binary content through a Lambda proxy integration without configuring binary media types | Register the content type explicitly, or expect corrupted responses on the client |

---

## What's Next

Part 7, the final chapter, covers observability and troubleshooting — the CloudWatch metrics that actually matter, structured access logging, X-Ray tracing, the specific failure signatures (502 vs 504 vs 429, CORS, cold starts) you'll see in production, and cost optimization.

More DevOps and cloud infrastructure write-ups like this live at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — issues and PRs from fellow practitioners are always welcome.
