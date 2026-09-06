# Part 5 — Advanced API Architecture: When APIs Become Infrastructure

*Part 5 of 5 in the API Mastery Roadmap prerequisites series. This final part is for senior engineers, architects, and staff-level folks who've been building and running APIs for a few years and are ready to think about them at a different scale. We cover event-driven APIs, real-time patterns, composition and federation, backward compatibility strategy, API gateways as a platform, and what it actually means to treat an API as a product.*

---

There's a transition that happens somewhere around the three-to-five year mark in engineering, and it's hard to pinpoint when it occurs. You stop asking "how do I make this endpoint work?" and start asking "how do I design this system so that three teams can build against it independently, without me being a bottleneck, without breaking deployments they don't control, and without creating a single point of failure that takes everyone down at 2 AM?"

That's the shift from API user to API architect. This article is about the thinking that happens at that level.

---

## Event-Driven APIs: When Request-Response Isn't Enough

The REST request-response model assumes the client knows when it wants data. It asks, the server responds, done.

But what about: "Tell me when this payment completes." "Notify me when this long-running job finishes." "Stream me real-time prices." For these scenarios, the client shouldn't have to keep asking — the server should push.

You have four patterns available. Knowing when to use each one is a meaningful architectural decision.

### Polling (Request-Response Repeated)

The client checks repeatedly on a fixed interval:

```python
def wait_for_job_completion(job_id: str, interval_seconds: int = 5):
    while True:
        response = requests.get(f"/jobs/{job_id}")
        job = response.json()
        
        if job["status"] in ("completed", "failed"):
            return job
        
        time.sleep(interval_seconds)
```

**When it's right**: Simple cases, short wait times, when you control both client and server and the client population is small.

**When it hurts you**: At scale, polling is traffic you're generating for no business reason. 1,000 clients polling every 5 seconds is 200 requests per second of pure overhead, and they're all getting the same "not done yet" response most of the time.

### Webhooks (Server Pushes to Client)

You register a URL with the provider. When something happens, they POST to your URL.

```python
# Your server — the webhook receiver
from fastapi import FastAPI, Request, HTTPException
import hmac
import hashlib

app = FastAPI()

def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify the webhook came from who it claims to be from."""
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

@app.post("/webhooks/payments")
async def receive_payment_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("Stripe-Signature", "")
    
    if not verify_signature(payload, signature, STRIPE_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    event = await request.json()
    
    if event["type"] == "payment_intent.succeeded":
        payment_id = event["data"]["object"]["id"]
        # Process it asynchronously — return 200 immediately
        background_tasks.add_task(process_successful_payment, payment_id)
    
    # Return 200 fast. If you're slow, the provider will retry.
    return {"received": True}
```

**The signature verification is not optional.** Anyone who knows your webhook URL can POST to it and fake events. Always verify.

**Return 200 fast, process asynchronously.** Webhook providers have timeouts (Stripe's is 30 seconds). If you do heavy processing synchronously and time out, they'll retry — and you'll end up processing the same event multiple times.

**Idempotency is required.** Webhooks get delivered at-least-once, not exactly-once. Design your handlers to be safe when called multiple times for the same event:

```python
async def process_successful_payment(payment_id: str):
    # Check if we've already processed this
    if await db.payment_already_processed(payment_id):
        logger.info("duplicate_webhook_skipped", payment_id=payment_id)
        return
    
    # Process and mark as done atomically
    async with db.transaction():
        await fulfill_order(payment_id)
        await db.mark_payment_processed(payment_id)
```

**When webhooks are right**: Stripe-style integrations, GitHub events, any scenario where you're the consumer of another service's events and you control a publicly reachable URL.

**When they're hard**: Behind firewalls (your server needs to be reachable from the internet), at high volume (you need queueing infrastructure to handle bursts), when ordering matters (webhooks don't guarantee delivery order).

### Server-Sent Events (SSE)

A one-way stream from server to client, over a regular HTTP connection. The client opens a connection and keeps it open; the server sends events whenever it wants to.

```python
# FastAPI SSE endpoint
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import asyncio

app = FastAPI()

async def event_stream(user_id: str):
    """Yield SSE events as they happen."""
    while True:
        # Check for new events for this user
        events = await get_pending_events(user_id)
        
        for event in events:
            # SSE format: "data: <payload>\n\n"
            yield f"data: {event.to_json()}\n\n"
        
        await asyncio.sleep(1)

@app.get("/events/stream")
async def stream_events(user_id: str):
    return StreamingResponse(
        event_stream(user_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # Disable nginx buffering
        }
    )
```

**When SSE is right**: Live dashboards, notifications, activity feeds, progress updates for long-running operations. Works through HTTP load balancers with no special configuration. Automatic reconnection is built into browsers.

**When SSE isn't enough**: When the client also needs to push data to the server in real time — SSE is server-to-client only.

### WebSockets

A full-duplex, persistent TCP connection. Both sides can send at any time after the initial HTTP handshake upgrades to the WebSocket protocol.

```python
# FastAPI WebSocket endpoint
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import json

app = FastAPI()

class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
    
    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket
    
    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)
    
    async def send_to_user(self, user_id: str, message: dict):
        if websocket := self.active_connections.get(user_id):
            await websocket.send_text(json.dumps(message))
    
    async def broadcast(self, message: dict):
        for websocket in self.active_connections.values():
            await websocket.send_text(json.dumps(message))

manager = ConnectionManager()

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    await manager.connect(user_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle incoming messages from the client
            if message["type"] == "chat_message":
                await manager.broadcast({
                    "type": "chat_message",
                    "from": user_id,
                    "text": message["text"]
                })
    except WebSocketDisconnect:
        manager.disconnect(user_id)
```

**When WebSockets are right**: Chat, collaborative editing, multiplayer games, trading platforms, anything requiring sub-second bidirectional communication.

**The operational cost**: WebSockets are stateful connections. Your load balancer needs sticky sessions or a shared message broker (Redis pub/sub) so clients don't miss messages when their connection lands on a different server than the event source. This is complexity that SSE or webhooks avoid.

### The Decision Tree

```
Is the client the one initiating data retrieval?
├── Yes → REST (GET)
└── No (server needs to push)
    └── Does the client also push data in real-time?
        ├── Yes → WebSockets
        └── No (server-to-client only)
            └── Is this to another server (not a browser)?
                ├── Yes → Webhooks
                └── No (browser client)
                    └── Are you streaming continuous data?
                        ├── Yes → SSE
                        └── No (occasional notifications)
                            └── SSE or WebSockets (both work)
```

---

## API Composition and the BFF Pattern

In a microservices world, a single page in your application might need data from five different services. You have two choices:

**Option 1: Let the client call all five services directly.**

```
Browser
├── GET /users/{id}
├── GET /orders?user_id={id}
├── GET /notifications?user_id={id}
├── GET /recommendations?user_id={id}
└── GET /activity-feed?user_id={id}
```

This works at small scale. At production scale, it means:
- Five round trips from the client (adds latency, especially on mobile)
- The client knows about your internal service structure
- Auth token needs to work against five services
- Any change to any service can break the client

**Option 2: Build a Backend for Frontend (BFF)**

```
Browser
└── GET /dashboard/{userId}
        │
        ▼
    BFF Layer
    ├── GET /users/{id}
    ├── GET /orders?user_id={id}
    ├── GET /notifications?user_id={id}
    ├── GET /recommendations?user_id={id}
    └── GET /activity-feed?user_id={id}
    (executed in parallel)
        │
        ▼
    Single composed response
    {
      "user": {...},
      "recent_orders": [...],
      "unread_notifications": 3,
      "recommendations": [...],
      "activity_feed": [...]
    }
```

The BFF is an aggregation layer — it exists specifically to serve the needs of one client (the web app, or the mobile app, or the TV app). It makes the downstream service calls in parallel, handles partial failures gracefully, and returns a response shaped exactly for what the UI needs.

**The partial failure question** is important here. What happens if the recommendations service is down? Does the whole dashboard fail? Or do you return the dashboard with `"recommendations": null` and a note in the response metadata? Design for degradation, not just for success.

```python
import asyncio
import aiohttp

async def build_dashboard(user_id: str) -> dict:
    async with aiohttp.ClientSession() as session:
        # Run all requests in parallel
        tasks = {
            "user":             fetch_user(session, user_id),
            "orders":           fetch_recent_orders(session, user_id),
            "notifications":    fetch_notifications(session, user_id),
            "recommendations":  fetch_recommendations(session, user_id),
        }
        
        results = {}
        errors = {}
        
        for key, coro in tasks.items():
            try:
                # 2-second timeout per dependency
                results[key] = await asyncio.wait_for(coro, timeout=2.0)
            except asyncio.TimeoutError:
                results[key] = None
                errors[key] = "timeout"
            except Exception as e:
                results[key] = None
                errors[key] = str(e)
        
        return {
            "data": results,
            "partial_failures": errors if errors else None
        }
```

---

## Backward Compatibility: The Art of Not Breaking Your Consumers

The hardest constraint in API design at scale isn't technical — it's social. You have 50 teams consuming your API. You need to change something. You can't talk to all 50 teams before you ship.

### The Rules That Keep You Out of Trouble

**Additive changes are almost always safe:**
- Adding a new optional field to a response body
- Adding a new optional query parameter
- Adding a new endpoint
- Adding new values to an enum (only if consumers use a catch-all for unknown values)

**These are breaking changes, even if they look small:**
- Removing or renaming a field (consumers that depended on it will error or silently get `null`)
- Changing a field's type (`"count": "42"` → `"count": 42` breaks typed clients)
- Making an optional field required
- Changing the semantics of an existing field (same name, different meaning)
- Removing or renaming an endpoint
- Changing behavior behind an existing endpoint

### The Deprecation Lifecycle

When you need to make a breaking change, the responsible sequence is:

```
Month 1: Introduce v2 endpoint (or v2 field) alongside v1
Month 1: Add Deprecation response header to v1 endpoint
         "Deprecation: Sat, 01 Mar 2025 00:00:00 GMT"
         "Sunset: Sat, 01 Jun 2025 00:00:00 GMT"
         "Link: <https://api.example.com/v2/users>; rel=successor-version"

Month 1-3: Notify consumers, provide migration guide, answer questions

Month 3: Sunset date announced; v1 traffic dashboard shows who still uses it

Month 3+: Individual outreach to high-volume consumers still on v1

Month 6: v1 returns 410 Gone, with a migration note in the response body
```

The `Deprecation` and `Sunset` headers are actual proposed standards ([RFC 8594](https://www.rfc-editor.org/rfc/rfc8594)). Tools like [sdk generator](https://openapi-generator.tech) can warn consumers at build time when they're calling deprecated endpoints, which is genuinely helpful for adoption.

### Consumer-Driven Contract Evolution

The most mature teams track exactly who is consuming each field of each response. When you want to remove `old_field`, you check: is anyone still reading it? If yes, you contact them. If no, you remove it safely.

This requires that consumers report what they actually use — either through static analysis of their OpenAPI-generated SDKs, or through header-based field usage tracking. It's complex but eliminates guesswork for large organizations.

---

## GraphQL Federation: When One Schema Isn't Enough

At sufficient scale, a monolithic GraphQL schema becomes a bottleneck. Every team that wants to add a new type has to touch the same schema definition. Federation solves this by letting each service own its own schema, while a gateway composes them into one.

```
Client → GraphQL Gateway (Federation Router)
              │
    ┌─────────┼──────────┐
    │         │          │
    ▼         ▼          ▼
 User     Orders    Product
Service   Service   Service
(owns     (owns     (owns
 User      Order     Product
 type)     type)     type)
```

Each service extends the shared schema:

```graphql
# users-service schema
type User @key(fields: "id") {
  id: ID!
  name: String!
  email: String!
}
```

```graphql
# orders-service schema — extends User from another service
extend type User @key(fields: "id") {
  id: ID! @external
  orders: [Order!]!
}

type Order {
  id: ID!
  total: Float!
  status: OrderStatus!
}
```

A client can now query across service boundaries in a single request:

```graphql
query GetUserWithOrders {
  user(id: "u_4829") {
    name
    email
    orders {      # Resolved by orders-service, not users-service
      id
      total
      status
    }
  }
}
```

The federation router knows which service owns which type and composes the query across services transparently. Apollo Federation and the newer [Bramble](https://movio.github.io/bramble/) are the main implementations.

**When to consider federation**: When you have 10+ teams contributing to a GraphQL schema and the coordination overhead is measurable. Before that, it's engineering complexity you don't need yet.

---

## Service Meshes: APIs as Network Infrastructure

In a mature microservices architecture, the concerns we've talked about — mutual TLS between services, retry logic, circuit breaking, distributed tracing — start to feel like things that shouldn't live in application code. You'd have to implement them in every service, in every language, consistently.

A service mesh like [Istio](https://istio.io) or [Linkerd](https://linkerd.io) moves this logic into a sidecar proxy that runs alongside every service:

```
Service A Pod                    Service B Pod
┌─────────────────┐              ┌─────────────────┐
│ ┌─────────────┐ │              │ ┌─────────────┐ │
│ │  App Code   │ │              │ │  App Code   │ │
│ └──────┬──────┘ │              │ └──────┬──────┘ │
│        │        │              │        │        │
│ ┌──────▼──────┐ │  mTLS        │ ┌──────▼──────┐ │
│ │Envoy Proxy  ├─┼─────────────►│ │Envoy Proxy  │ │
│ │  (sidecar)  │ │              │ │  (sidecar)  │ │
│ └─────────────┘ │              │ └─────────────┘ │
└─────────────────┘              └─────────────────┘
         ▲                                ▲
         │          Control Plane         │
         └──────────────┬─────────────────┘
                        │
               Istio Control Plane
               (manages mTLS certs,
                routing rules,
                traffic policies)
```

With a service mesh, you get:
- **mTLS everywhere**: Service-to-service traffic is encrypted and mutually authenticated. No exceptions.
- **Traffic management**: Canary deployments, circuit breaking, and retry policies configured as Kubernetes resources, not application code.
- **Automatic distributed tracing**: The proxy injects trace headers without any application code changes.
- **Fine-grained authorization**: Service A is allowed to call `GET /orders` but not `DELETE /orders`, enforced at the network level.

The cost: significant operational complexity. A service mesh is a bet that standardization and centralized control are worth the overhead. It's not the right answer for a team of 10. It's potentially the right answer at 50+ microservices across multiple language runtimes.

---

## API as a Product: The Mindset Shift That Changes Everything

This is the one that's hardest to teach from first principles — it's the shift from thinking of an API as a technical artifact to thinking of it as a product with users who have needs, expectations, and alternatives.

The practical differences:

**A technical artifact**: "Here's the endpoint. RTFM."

**A product**: You have developer experience (DX) as a first-class concern. That means:

- **Documentation that actually runs.** Not static text — interactive examples with real sample data, runnable in the browser.
- **Versioning that respects consumers.** You give notice, you provide migration tooling, you reach out to high-usage consumers individually.
- **Changelogs written for humans.** Not "updated field validation" — "we now require `email` to be a valid format; previously this wasn't enforced and some integrations may need updating."
- **SDKs in the languages your consumers use.** Writing a client library is how you find out if your API is actually ergonomic.
- **A developer portal with your SLO public.** If you're asking other teams to build on your API, they deserve to know what reliability guarantees they're getting.
- **Office hours.** When your API is used by 20 teams internally, the highest-leverage thing you can do is a 30-minute open office hour each week where anyone can ask questions.

The organizational pattern that supports this is **platform engineering** — treating internal infrastructure and APIs as internal products with real customers (other engineering teams), with the same quality bar you'd apply to customer-facing software.

---

## The Staff Engineer's API Architecture Checklist

When I'm reviewing an architecture proposal for a new API or a significant change, these are the questions I ask:

**On design:**
- [ ] Is there an OpenAPI spec before there's any code?
- [ ] Does the design handle partial failure gracefully, not just the happy path?
- [ ] Is the event-driven pattern (if any) the right one for the latency and throughput requirements?
- [ ] Is there an explicit backward compatibility and deprecation strategy?

**On operations:**
- [ ] What does the runbook look like for the three most likely failure modes?
- [ ] What are the SLOs, and how are they measured?
- [ ] Is the gateway layer handling auth, rate limiting, and observability — or is that scattered across services?
- [ ] Has this been load tested at 2x expected peak?

**On security:**
- [ ] Is mTLS or a service mesh in scope for service-to-service calls?
- [ ] Where do credentials live? (The answer better not be "in the code.")
- [ ] Is there a WAF in front of any public-facing endpoints?

**On organization:**
- [ ] Which team owns this API? (A team, not "everyone")
- [ ] What's the process for consuming teams to report issues?
- [ ] Is there a changelog, and is it actually maintained?

If more than two of these are unanswered at the design stage, the conversation should happen before any code is written — not after the API is in production and 15 teams have built on top of a design that nobody thought through.

---

## Where This Leads

APIs have been the dominant architectural primitive of the last fifteen years. They're how the internet is built. They're how companies are built — Stripe is an API company, Twilio is an API company, the entire developer tools economy runs on APIs.

Understanding APIs deeply — not just how to call them, but how to design them, operate them, evolve them, and think about them as products — is one of the most transferable skills in software engineering. The specific technology changes; the principles stay.

The main series (AWS API Gateway for DevOps Engineers) picks up where this prerequisite track leaves off, going deep on one specific, widely-used implementation of these ideas. But the thinking from these five articles should apply whether you're working with AWS API Gateway, Kong, a custom nginx configuration, or whatever API gateway paradigm exists five years from now.

---

## Full Series Recap: The Five-Article Arc

| Part | Audience | Core Question |
|------|----------|--------------|
| **Part 1** | Absolute beginners | What is an API and why does it exist? |
| **Part 2** | Junior engineers | How do I actually use one in code? |
| **Part 3** | Software engineers | How do I design one that doesn't hurt people? |
| **Part 4** | DevOps engineers | How do I run one in production reliably and securely? |
| **Part 5** | Senior engineers | How do I build API systems that scale across teams and time? |

From here, the [AWS API Gateway Deep Dive series](../api-gateway-ch1-fundamentals-request-lifecycle.md) starts — seven chapters covering one production-grade API gateway from the inside out.

---

*This concludes the API Mastery Roadmap prerequisites track. The main series starts with [Chapter 1: Fundamentals and the Request Lifecycle](../api-gateway-ch1-fundamentals-request-lifecycle.md).*
