# AWS API Gateway for DevOps Engineers, Part 1: Fundamentals and the Request Lifecycle

*Part 1 of a 7-part series. This chapter and the two that follow it (Part 2: Endpoint Types and Resource Design, Part 3: Integration Types Deep Dive) are the core-concepts foundation the rest of the series builds on. Part 4 covers building and deploying with boto3, Part 5 covers security, Part 6 covers traffic management and custom domains, and Part 7 closes with observability and troubleshooting.*

If you've ever been paged because a client integration suddenly started throwing 504s and the only clue in the logs was "Endpoint request timed out," you already know why API Gateway deserves more respect than it usually gets. Most teams treat it as plumbing — something you click through once in the console and never think about again. Then six months later it's 3 AM, a downstream Lambda is cold-starting under load, and nobody on the call actually understands how the Gateway's integration timeout interacts with the Lambda's own timeout. This series exists so that call goes differently for you.

We're spending three full chapters on core concepts before touching a single line of boto3, and that's deliberate. Almost every confusing API Gateway bug traces back to a gap in the mental model, not a gap in AWS API knowledge — people who can write `put_integration` from memory still get tripped up by *why* a request behaved the way it did, because they never built a clear picture of what happens between "client sends HTTPS request" and "backend receives something." That picture is what these first three chapters give you.

---

## What Problem Is API Gateway Actually Solving?

Before Lambda and managed API layers existed, "exposing an API" meant standing up EC2 instances running nginx or an application server, putting a load balancer in front, handling TLS termination yourself, writing your own throttling logic, and building auth from scratch or bolting on OAuth libraries. All of that is undifferentiated heavy lifting — work that doesn't make your product better, it just has to exist.

API Gateway collapses that into a managed layer. It sits between the internet and whatever is actually doing the work — a Lambda function, an EC2-hosted service, a container in ECS, or even another AWS service directly — and handles routing, authentication, throttling, request/response transformation, and logging so your backend team can focus on business logic instead of plumbing.

---

## The Request Lifecycle, Step by Step

This is the single most important diagram in the entire series. Almost everything else — mapping templates, authorizers, throttling, caching — is a detail attached to one of these steps. If you understand this flow cold, the rest of API Gateway stops being a grab-bag of unrelated settings and starts looking like variations on one theme.

```
 Client
   │  HTTPS request
   ▼
┌─────────────────────────────────────────────────────────────────┐
│                         API Gateway                              │
│                                                                    │
│  1. TLS termination + custom domain / base path routing          │
│              │                                                    │
│              ▼                                                    │
│  2. Resource policy check (API-level allow/deny)                 │
│              │                                                    │
│              ▼                                                    │
│  3. Method request (path/query/header validation, request model  │
│     validation if configured)                                    │
│              │                                                    │
│              ▼                                                    │
│  4. Authorization (IAM / Cognito / Lambda authorizer / none)     │
│              │                                                    │
│              ▼                                                    │
│  5. Throttling check (usage plan → stage → account limits)       │
│              │                                                    │
│              ▼                                                    │
│  6. Integration request (mapping template transforms the         │
│     request, if this is a non-proxy integration)                 │
│              │                                                    │
│              ▼                                                    │
└──────────────┼─────────────────────────────────────────────────┘
               ▼
        Backend (Lambda / HTTP / AWS service / Mock)
               │
               ▼
┌──────────────┼─────────────────────────────────────────────────┐
│              ▼                                                    │
│  7. Integration response (mapping template transforms the        │
│     backend's response, if non-proxy)                            │
│              │                                                    │
│              ▼                                                    │
│  8. Method response (status code mapping, response headers,      │
│     CORS headers if not handled in code)                         │
│              │                                                    │
└──────────────┼─────────────────────────────────────────────────┘
               ▼
             Client
```

A few things worth calling out explicitly, because they're easy to miss on a first pass:

**The resource policy check happens before your method-level authorizer even runs.** If a request is denied at step 2, your Lambda authorizer never gets invoked at all — which matters when you're debugging "why isn't my authorizer being called," because the answer might be that the request never got that far.

**Throttling happens after authorization, not before.** An unauthenticated request that fails authorization at step 4 doesn't count against your usage plan quota at step 5 — it's rejected before it would be throttled. This is a meaningful distinction if you're trying to reason about whether a spike in `4XXError` is auth failures or throttle rejections; they're different steps, different metrics, different root causes.

**Steps 6 and 7 only exist in their full form for non-proxy integrations.** A Lambda proxy integration (the default most teams use) collapses steps 6 and 7 into "pass the whole request through, return the whole response as-is" — your handler receives the entire request context and is responsible for returning the entire response shape. That's simpler to reason about, but it also means request/response transformation logic that could live declaratively in a mapping template now has to live in your handler code instead. Neither choice is universally right; Part 3 goes deep on exactly this tradeoff.

**Method response headers and integration response headers are not the same thing**, and this distinction is the root cause of a large fraction of CORS confusion. For proxy integrations, the method response step barely matters because your Lambda's return value *is* the response — any CORS header has to come from your code. For non-proxy integrations, you configure headers at both the integration response and method response level, and mismatches between the two are a common source of "I set the header but the client doesn't see it."

---

## Three APIs, Not One

AWS bundles three genuinely different products under the "API Gateway" name, and picking the wrong one early is a common source of regret that's expensive to unwind later.

| Type | Best for | What you give up |
|---|---|---|
| **HTTP API** | Lambda/HTTP backends, low-latency proxying, cost-sensitive workloads | No request validation, limited transformation, historically fewer auth options (though Cognito/Lambda authorizers are now supported) |
| **REST API** | Fine-grained control — request validation, response mapping, usage plans, private APIs via VPC endpoints | More expensive, higher latency, more config surface to maintain |
| **WebSocket API** | Bidirectional, persistent connections — chat, live dashboards, trading feeds | Completely different mental model; connection state has to live somewhere (usually DynamoDB) |

### Feature parity, in more detail

The "just use HTTP API, it's cheaper" advice is directionally right but glosses over real gaps worth knowing before you commit:

| Capability | REST API | HTTP API |
|---|---|---|
| Request validation (JSON Schema models) | Yes | No |
| Usage plans and API keys | Yes | No |
| Private APIs (VPC endpoint only) | Yes | No |
| Response caching | Yes | No |
| Mapping templates / non-proxy integrations | Yes | Limited (parameter mapping only, no full VTL) |
| Canary deployments | Yes | No |
| Cognito authorizer | Yes | Yes |
| Lambda authorizer | Yes | Yes (simplified payload format) |
| JWT authorizer (native, no Lambda needed) | No | Yes |
| Per-request pricing | Higher | ~70% lower |
| Typical added latency | Slightly higher | Lower |

That last row on JWT authorizers is worth a specific callout — HTTP API added native JWT validation without requiring a Lambda authorizer at all, which is a genuine capability REST API doesn't have, not just a missing feature. If your entire auth model is "validate a JWT from an OIDC provider," HTTP API might actually give you *more* out of the box, not less.

The decision rule that holds up in practice: default to HTTP API. Move to REST API only when you hit a specific feature in the left column that you actually need — not because it's what the older tutorials use, and not "just in case" you need it later. Migrating later is possible but not trivial, so make the call deliberately rather than defaulting to the more complex option out of caution.

WebSocket API is its own animal entirely and deserves a separate deep dive outside this series — the moment you need `$connect`/`$disconnect`/`$default` routes and a connection table, you've left REST semantics behind completely.

---

## The Vocabulary You Need

A handful of terms show up constantly in AWS docs and in your own Terraform/CDK code, and it's worth being precise about them before going further, because REST API and HTTP API don't always use them identically.

- **Resource** – a URL path segment, like `/orders` or `/orders/{orderId}`. Path parameters in curly braces become variables your integration can read.
- **Method** – the HTTP verb attached to a resource (`GET`, `POST`, etc.). Each resource can have multiple methods, plus a special `ANY` method that matches every verb.
- **Integration** – what happens on the backend when the method is invoked. Part 3 goes deep on the six integration types — this is where most of the real complexity lives.
- **Stage** – a named, deployed snapshot of your API (`dev`, `staging`, `prod`). Each stage can have its own variables, throttling limits, logging config, and even point at different Lambda aliases.
- **Deployment** – the actual act of publishing your configuration to a stage. Changes to methods and integrations don't go live until you deploy.
- **Stage variable** – a key-value pair scoped to a stage, commonly used to parameterize which backend a stage points to (e.g., a different Lambda alias per stage) without duplicating the whole API definition.

That deployment/stage distinction trips up a surprising number of people the first time. You can edit a method in the console, hit save, curl your endpoint, and get the *old* behavior — because you forgot to deploy the change to the stage. It's not a bug. It's the whole point of having stages: it means you can stage a breaking change without it silently going to prod. Terraform and CDK both model this explicitly — if your IaC changes a method but doesn't trigger a new deployment resource, you've shipped a no-op, and that's a pattern worth testing for in CI rather than discovering in a postmortem.

---

## Do This, Not That

| Instead of... | Do this |
|---|---|
| Defaulting to REST API "because that's what the tutorials use" | Default to HTTP API unless you specifically need a feature only REST API has |
| Assuming your method changes are live after saving | Check that a new deployment was actually created and pushed to the stage you're testing against |
| Debugging "why isn't my authorizer firing" without checking the resource policy first | Confirm the request is even reaching step 4 of the lifecycle before assuming the authorizer itself is broken |
| Treating a `4XXError` spike as one undifferentiated problem | Distinguish auth failures (step 4) from throttle rejections (step 5) — they show up as different status codes and need different fixes |
| Choosing REST API "just in case" you need a feature later | Start with HTTP API and migrate deliberately if a specific, real requirement surfaces |

---

## What's Next

Part 2 goes deep on endpoint types — edge-optimized, regional, and private — and on how to design a resource hierarchy well, including proxy resources, path parameters, and the `ANY` method. Part 3 after that covers all six integration types in real depth, including when a mapping template is the right tool and when it's just friction.

More DevOps and cloud infrastructure write-ups like this live at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — issues and PRs from fellow practitioners are always welcome.
