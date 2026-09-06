# APIs for Humans: Part 3 — Designing APIs That Don't Embarrass You

*Part 3 of 5 in the API Mastery Roadmap prerequisites series. This one is for engineers who have consumed APIs and are now building them — backend engineers, full-stack developers, or anyone who's been handed a ticket that says "build an API endpoint for X." Parts 1 and 2 covered consuming APIs; this one covers producing them. Part 4 moves into the DevOps side.*

---

I want to tell you about an API I helped build early in my career that I deeply regret.

It was an internal service for managing user preferences. The endpoint to update a preference was `POST /updateUserPref` and it returned either `{"result": "ok"}` or `{"result": "error", "msg": "something broke"}` — always with a 200 status code. There was no versioning. The field names were inconsistent between endpoints (sometimes `userId`, sometimes `user_id`, once memorably `uid`). We used the same endpoint for creating and updating, and you could tell which one happened by a boolean field called `isNew` in the response.

Twelve other teams eventually integrated against that API. When we needed to change it, we couldn't. We broke people. We had three simultaneous "versions" that were just different undocumented parameter combinations. It was bad.

API design decisions compound over time — good ones and bad ones. Here's the thinking that goes into building something you won't regret.

---

## Resources, Not Actions: Getting the URL Structure Right

The most foundational REST design principle is so simple it seems obvious, but you will see it violated constantly:

**URLs identify resources (nouns). HTTP methods describe actions (verbs).**

```
❌ Bad — action-based URLs
POST /createUser
POST /updateUser
POST /deleteUser
POST /getUser
POST /getUserByEmail

✅ Good — resource-based URLs
POST   /users           → create a user
GET    /users           → list all users
GET    /users/{id}      → get a specific user
PUT    /users/{id}      → replace a user entirely
PATCH  /users/{id}      → partially update a user
DELETE /users/{id}      → delete a user
```

The good version has six behaviors mapped onto two URL patterns. The bad version has five URLs doing five things, and you haven't even handled listing yet.

### Nesting Resources

When one resource belongs to another, reflect that in the URL structure — but don't go more than two levels deep.

```
/users/{userId}/orders              ← all orders for a specific user
/users/{userId}/orders/{orderId}    ← a specific order for a specific user

# Don't do this:
/users/{userId}/orders/{orderId}/items/{itemId}/reviews/{reviewId}
# That URL is a maintenance nightmare and a red flag in a code review
```

If you need to access something deeply nested, create a top-level resource for it. A review is important enough to have `/reviews/{reviewId}` — you don't need to know whose order it belongs to just to look it up.

### Filtering vs. a New Resource

This is a judgment call that trips up a lot of people: when do you create a new endpoint vs. add a query parameter?

```
# Query parameters: filtering/sorting/searching the same collection
GET /orders?status=shipped&customer_id=42&sort=created_at&order=desc

# New endpoint: fundamentally different resource or behavior
POST /orders/{id}/cancel        ← an action that changes state
GET  /orders/export             ← different output format entirely
```

If you're slicing the same collection differently, use query params. If you're triggering a state transition or returning fundamentally different data, use a different path.

---

## Naming Conventions: Boring is Good

Pick a convention and apply it everywhere. The convention matters less than the consistency.

```json
{
  "userId": "u_4829",         ← camelCase
  "user_id": "u_4829",        ← snake_case
  "UserId": "u_4829"          ← PascalCase
}
```

Most REST APIs use `snake_case` for JSON field names. Most JavaScript-heavy APIs use `camelCase`. The GitHub API uses `snake_case`. The Stripe API uses `snake_case`. Pick one.

For boolean fields, name them as questions that have a yes/no answer:

```json
{
  "is_active": true,       ← better than "active" or "status"
  "has_verified_email": false,
  "can_publish": true
}
```

For timestamps, always use ISO 8601 with UTC timezone:

```json
{
  "created_at": "2024-03-15T14:32:07Z",
  "updated_at": "2024-03-15T14:32:07Z",
  "expires_at": null
}
```

Never, ever return Unix timestamps as integers in a public API. They're fine internally, but they're unreadable to humans and error-prone to handle — off-by-one errors between seconds and milliseconds have caused real production incidents.

---

## The Error Contract: This Is Where Most APIs Fail

Bad error design is the single fastest way to make other engineers hate your API. The two failure modes:

**Too little information:**
```json
{"error": "bad request"}
```
This tells me nothing. What field was wrong? What format did you expect?

**Too much information:**
```json
{"error": "NullPointerException at UserService.java:142: cannot access field email on null object"}
```
This leaks implementation details, helps attackers, and scares consumers.

Here's a good error response format. It's not the only valid one, but it has everything you need:

```json
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "One or more fields failed validation.",
    "details": [
      {
        "field": "email",
        "issue": "must be a valid email address",
        "received": "not-an-email"
      },
      {
        "field": "age",
        "issue": "must be a positive integer",
        "received": -5
      }
    ],
    "request_id": "req_8f2a9c1d4e7b"
  }
}
```

Notice:
- `code` is a machine-readable string the client can match on in code — not a human sentence, not an integer code.
- `message` is a human-readable summary.
- `details` is an array — you can report multiple validation failures at once. Making users fix errors one at a time is infuriating.
- `request_id` lets them contact you and say "I got this error" and you can find the actual trace in your logs.

Use the correct HTTP status codes to go with your errors:

| Situation | Status Code |
|-----------|-------------|
| Missing required field, invalid format | `400 Bad Request` |
| No auth token sent | `401 Unauthorized` |
| Auth token valid, but no permission | `403 Forbidden` |
| Resource doesn't exist | `404 Not Found` |
| Trying to create something that already exists | `409 Conflict` |
| Correct request, but violates business rule | `422 Unprocessable Entity` |
| Client is sending too many requests | `429 Too Many Requests` |
| Something unexpected broke on your side | `500 Internal Server Error` |
| You called a dependency that's down | `503 Service Unavailable` |

The `422 vs 400` distinction is worth knowing: `400` means the request is malformed (invalid JSON, missing required header, wrong content type). `422` means the request is valid JSON and parsed correctly, but the *content* fails business logic ("you can't schedule a meeting in the past").

---

## Versioning: The Decision You Can't Undo

Your API will change. The question is how you manage that change without breaking existing consumers.

### URL Versioning

```
https://api.example.com/v1/users
https://api.example.com/v2/users
```

This is the most common approach. It's explicit, easy to route, easy to cache, and easy to deprecate. The GitHub API, Stripe, Twilio — they all use URL versioning.

The downside: it's coarse. You're versioning everything together. If you change `/v1/users` to `/v2/users`, you're creating a new version even if `orders` didn't change at all.

### Header Versioning

```
GET /users
Api-Version: 2024-01-15
```

Stripe and GitHub both support this as an alternative. The version is a date-based string, and you're specifying "give me the behavior that was current as of this date." This is elegant but complex to implement.

### What to Actually Do

For an internal API that only a few teams use: URL versioning with `/v1/`, `/v2/`, etc. is fine and simple.

For a public API: Use URL versioning for major breaking changes. Be extremely conservative about breaking changes in the first place.

The golden rule of API versioning: **adding is safe, removing or renaming is a breaking change.**

Safe changes (adding):
- New optional fields in the response
- New optional request parameters
- New endpoints

Breaking changes (don't do without a version bump):
- Removing a field from the response
- Renaming a field
- Changing a field's type (string to integer)
- Changing the meaning of an existing status code
- Making an optional parameter required

---

## Idempotency: Building APIs That Survive Retries

Networks are unreliable. Clients retry. If your API isn't designed for retries, you'll end up with duplicate orders, double charges, and data corruption. 

**Idempotency** means: calling the same operation multiple times has the same effect as calling it once.

GET, PUT, and DELETE are naturally idempotent. POST is not (each POST call creates a new resource). Here's how to make POST idempotent when you need to:

**Idempotency keys:**

```bash
POST /payments
Idempotency-Key: 7f4e8a2b-3c1d-4f9e-8b7a-2c5d6e1f0a9b
Content-Type: application/json

{
  "amount": 4999,
  "currency": "usd",
  "customer_id": "cus_8f2a9c"
}
```

The server stores the `Idempotency-Key` and the response it returned. If the same key comes in again (because the client didn't receive the first response and retried), it returns the same stored response without executing the operation again.

Stripe pioneered this pattern. It's the right way to handle payment-style operations where "did it go through?" is an ambiguous question.

---

## Designing the Response Shape

Be deliberate about what you return and how it's structured.

### Envelope vs. Naked Response

```json
// Naked (simple, works fine for small APIs)
{
  "id": "u_4829",
  "name": "Jordan",
  "email": "jordan@example.com"
}

// Enveloped (better for APIs that will evolve)
{
  "data": {
    "id": "u_4829",
    "name": "Jordan",
    "email": "jordan@example.com"
  },
  "meta": {
    "request_id": "req_7f3a",
    "version": "2024-01-15"
  }
}
```

The naked response is simpler. The envelope gives you a stable place to add metadata later without breaking the existing field structure. If you're building a public API, use an envelope.

### List Responses

Always return list metadata alongside the data:

```json
{
  "data": [
    {"id": "ord_001", "status": "shipped"},
    {"id": "ord_002", "status": "pending"}
  ],
  "pagination": {
    "total": 2847,
    "page": 1,
    "per_page": 50,
    "next_cursor": "eyJpZCI6Im9yZF8wNTAifQ=="
  }
}
```

Consumers need to know how many total results exist, not just what's on the current page. Without `total`, clients can't show "Page 1 of 57" or determine whether to fetch more.

---

## OpenAPI: Document Your API Before You Build It

OpenAPI (formerly Swagger) is a standard format for describing REST APIs. Writing an OpenAPI spec before you implement anything forces you to think through your design, generates interactive documentation, and enables contract testing.

Here's a minimal OpenAPI spec for a users endpoint:

```yaml
openapi: "3.0.3"
info:
  title: User Service API
  version: "1.0"
  description: |
    Manages user accounts and preferences.
    All timestamps are ISO 8601 UTC.

paths:
  /users/{id}:
    get:
      summary: Get a user by ID
      operationId: getUser
      tags: [Users]
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
            example: u_4829
      responses:
        "200":
          description: User found
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/User"
        "404":
          description: User not found
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/Error"

components:
  schemas:
    User:
      type: object
      required: [id, name, email, created_at]
      properties:
        id:
          type: string
          example: u_4829
        name:
          type: string
          example: Jordan
        email:
          type: string
          format: email
        created_at:
          type: string
          format: date-time
    Error:
      type: object
      required: [error]
      properties:
        error:
          type: object
          required: [code, message, request_id]
          properties:
            code:
              type: string
              example: NOT_FOUND
            message:
              type: string
            request_id:
              type: string
```

Tools like [Swagger UI](https://swagger.io/tools/swagger-ui/) render this into interactive documentation. Tools like [Prism](https://stoplight.io/open-source/prism) can mock your API from this spec before you write a single line of implementation. This approach — design-first API development — catches a lot of issues before any code exists.

---

## REST vs. GraphQL vs. gRPC: A Practical Decision Framework

You'll face this choice at some point. Here's the honest comparison:

### Use REST When:
- Building a public API that external developers will consume
- Your team is medium-sized or mixed-experience
- Your API is relatively simple (CRUD operations on a handful of resources)
- Caching matters (REST responses are cacheable, GraphQL generally isn't)

### Use GraphQL When:
- You have multiple clients with significantly different data needs (mobile app needs 5 fields, web app needs 30)
- Over-fetching and under-fetching are causing real performance or bandwidth problems
- Your team has strong frontend engineers who will appreciate query flexibility

GraphQL's downside: it's significantly more complex to implement and operate. Rate limiting, caching, and authorization all need custom solutions. The tooling is good but the operational overhead is real.

### Use gRPC When:
- Service-to-service communication inside your own infrastructure
- You need high performance and low latency at scale
- Streaming (server-side or bidirectional) is a first-class requirement
- You can control both the client and server

gRPC requires both sides to use generated code from a `.proto` file. This is a non-starter for public APIs where you can't control how clients are built.

The practical advice: start with REST, move to GraphQL only if over/under-fetching is causing measurable problems, introduce gRPC at the service-mesh level when performance demands it.

---

## The Checklist: Before Your API Goes to Code Review

I keep this list open whenever I'm designing a new API surface:

- [ ] Resources are nouns, methods are verbs — no actions in URLs
- [ ] Field names are consistent (casing, format) across all endpoints
- [ ] Every endpoint has explicit error responses documented, not just the success case
- [ ] Timestamps are ISO 8601 UTC strings
- [ ] Auth is required on every non-public endpoint and the scheme is documented
- [ ] List endpoints support filtering, sorting, and pagination
- [ ] POST operations that need to be safe to retry have idempotency key support
- [ ] The versioning strategy is decided and applied
- [ ] An OpenAPI spec exists (even if incomplete)
- [ ] The error response shape is consistent — same structure across all endpoints

---

## Recap

- URLs are nouns, HTTP methods are verbs. Resource-based URLs scale better than action-based URLs.
- Name things consistently — `snake_case`, ISO 8601 timestamps, boolean fields as questions.
- Error responses need a machine-readable code, a human message, field-level details, and a request ID.
- Use correct HTTP status codes — 400 vs 422 vs 403 vs 409 all mean different things.
- Add is safe, remove is breaking — version your API when you need to break it.
- Idempotency keys let POST operations be safe to retry.
- Design-first with OpenAPI before you write implementation code.
- REST for public APIs, GraphQL for multi-client data flexibility, gRPC for internal high-performance services.

---

*Next up: [Part 4 — APIs in the DevOps World](./part-4-apis-devops-engineers.md). How APIs look from the infrastructure side: API gateways, observability, CI/CD pipelines for APIs, contract testing, and what changes when your API needs to be production-grade rather than just functional.*
