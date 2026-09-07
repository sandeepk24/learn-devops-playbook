# AWS API Gateway for DevOps Engineers, Part 3: Integration Types Deep Dive

*Part 3 of a 7-part series. Part 1 covered fundamentals and the request lifecycle, Part 2 covered endpoint types and resource design. This chapter is the last of the core-concepts foundation before the series turns hands-on. Part 4 covers building and deploying with boto3, Part 5 covers security, Part 6 covers traffic management, and Part 7 closes with observability and troubleshooting.*

Everything in Parts 1 and 2 was about the shape of your API from the outside — how requests arrive, how the resource tree is structured. This chapter is about what happens on the inside: the six integration types, what each one actually does to a request and response, and — more importantly than memorizing the list — how to reason about which one is right for a given endpoint instead of defaulting to whatever the last tutorial used.

---

## The Real Axis: Proxy vs. Non-Proxy

Before the six types, there's one distinction that matters more than any individual type: **proxy** integrations pass the request through mostly unmodified and expect the backend to handle the full request/response shape itself. **Non-proxy** (custom) integrations let API Gateway transform the request and response using mapping templates, decoupling your backend from HTTP semantics entirely.

This is a genuine architectural tradeoff, not just a config toggle:

| | Proxy | Non-proxy (custom) |
|---|---|---|
| Where request/response logic lives | In your handler code | In VTL mapping templates, declared in API Gateway |
| Backend coupling | Backend receives raw HTTP-shaped event, must return HTTP-shaped response | Backend can receive/return whatever shape the mapping template produces — fully decoupled from HTTP |
| Iteration speed | Fast — change code, redeploy the function | Slower — mapping template changes require a new API Gateway deployment too |
| Reusability of the backend | Lower — a Lambda coupled to API Gateway's event shape is awkward to trigger from SQS or EventBridge without an adapter | Higher — backend can be shape-agnostic if the mapping template does the translation |
| Where errors are debugged | Almost always in the backend's logs | Could be the mapping template, the backend, or the response mapping — three places to check instead of one |

Most teams should default to proxy integrations, for the same reason most teams should default to HTTP API — less moving parts, faster iteration, and the added flexibility of non-proxy integrations goes unused more often than it gets exercised. Reach for non-proxy specifically when you want to decouple a backend from HTTP entirely (calling an AWS service directly with no compute layer at all) or when many different clients need different response shapes from the same underlying data without touching backend code for each variation.

---

## The Six Integration Types

| Integration type | What it does | Typical use |
|---|---|---|
| **Lambda proxy (AWS_PROXY)** | Passes the entire request to Lambda as an event object; your handler returns the entire response shape | The default for Lambda-backed APIs — least config, most control lives in code |
| **Lambda custom (AWS)** | You define mapping templates to transform the request before it reaches Lambda, and the response before it reaches the client | When you need the Gateway to reshape payloads without touching handler code, or want the handler decoupled from HTTP semantics entirely |
| **HTTP proxy (HTTP_PROXY)** | Forwards the request as-is to an HTTP endpoint | Fronting an existing HTTP service (ALB, on-prem via VPC Link, third-party API) with minimal transformation |
| **HTTP custom (HTTP)** | Like HTTP proxy, but with mapping templates for request/response transformation | Same as HTTP proxy, but you need to reshape the payload in transit |
| **AWS service** | Calls an AWS service API directly (S3, DynamoDB, SNS, Step Functions, etc.) without a Lambda in between | Simple CRUD against DynamoDB, direct S3 uploads, triggering Step Functions — skips a Lambda invocation entirely |
| **Mock** | Returns a response without calling any backend | CORS preflight (`OPTIONS`) handling, or stubbing an endpoint before the real backend exists |

### Lambda proxy: the default for a reason

Your handler receives the entire request — headers, path parameters, query strings, body, and request context (including anything an authorizer attached) — as a single event dictionary, and is responsible for returning `{statusCode, headers, body}`. There's essentially no API Gateway-side configuration beyond wiring the integration; everything meaningful lives in your code, in a language you already know, tested however you already test your Lambdas.

The coupling cost is real but often overstated: yes, a Lambda written against the API Gateway proxy event shape needs an adapter to also work behind SQS or EventBridge, but that adapter is usually a few lines, and the alternative (maintaining VTL mapping templates for the same flexibility) is more code to maintain, not less, for most teams.

### Lambda custom: when you want the Gateway doing the shaping

Here, API Gateway transforms the incoming request using a VTL mapping template before it ever reaches your Lambda, and transforms the Lambda's response before it reaches the client. Your handler can be written against a clean, purpose-built input/output shape that has nothing to do with HTTP — useful if the same Lambda is also invoked directly by other services and you don't want it coupled to API Gateway's event format at all.

A minimal request mapping template, reshaping an HTTP POST body into whatever your handler actually expects:

```velocity
{
  "action": "createOrder",
  "payload": {
    "customerId": "$input.path('$.customerId')",
    "items": $input.json('$.items')
  },
  "requestId": "$context.requestId"
}
```

The tradeoff shows up during debugging: a malformed request can now fail in the mapping template (a VTL error, often an unhelpful one) before your Lambda's own error handling ever gets a chance to run, which means your usual application logs won't show anything — you have to go to API Gateway's execution logs instead. That's a real cost, and it's the main reason most teams don't reach for this type unless they have a specific decoupling requirement.

### HTTP proxy and HTTP custom: fronting existing services

These follow the same proxy/non-proxy logic as the Lambda types, but the backend is any HTTP(S) endpoint — an Application Load Balancer, an on-prem service reachable via VPC Link, or a third-party API you want to front with your own auth and throttling layer. HTTP proxy forwards the request essentially unmodified; HTTP custom lets you reshape it with mapping templates, same as Lambda custom.

This is the integration type behind a common and underused pattern: putting API Gateway in front of an ALB-fronted ECS service purely to get managed auth, throttling, usage plans, and a custom domain, without changing anything about how the ECS service itself works. The service doesn't need to know API Gateway exists.

### AWS service integration: skipping compute entirely

This calls an AWS service's API directly — DynamoDB, S3, SNS, Step Functions, and others — using IAM credentials that API Gateway assumes, with no Lambda in the middle at all. For simple, high-volume, low-logic operations (write a record, publish a message, start a state machine execution), this cuts out an entire compute layer: no cold start, no Lambda cost, no Lambda to patch or monitor.

The cost is that all your logic has to live in a VTL mapping template, and VTL is not a language anyone particularly enjoys writing or debugging. It's the right tool for endpoints that are genuinely thin — a health-check-style write, a straightforward `PutItem` — and the wrong tool the moment there's real business logic (validation beyond what a request model can express, conditional branching, calling multiple downstream services) that would be trivial in Python and painful in VTL.

### Mock: no backend, on purpose

A Mock integration returns a canned response defined entirely in API Gateway configuration, without invoking anything. The two legitimate uses: handling `OPTIONS` preflight requests for CORS (the response is always the same set of headers, so there's no reason to pay for a Lambda invocation to generate it), and stubbing an endpoint's shape during early development before the real backend exists, so frontend or integration work can proceed against a stable contract.

---

## Choosing: A Decision Path, Not a Checklist

Rather than memorizing the table, it's more durable to reason through a few questions in order:

1. **Is there real logic involved, or is this a thin pass-through to one AWS service?** Thin pass-through → consider AWS service integration. Real logic → you need compute, so Lambda or HTTP.
2. **If compute — does the backend already exist as an HTTP service (ECS, EC2, on-prem), or does it need to be written?** Existing HTTP service → HTTP proxy/custom. Needs writing → Lambda.
3. **If Lambda — does this function need to be shape-agnostic (also triggered by SQS, EventBridge, or called directly by other services)?** Yes → Lambda custom, with a mapping template producing a clean shape. No, it's API Gateway-only → Lambda proxy, and keep the logic in code.
4. **Does the response need to differ by client without touching backend code, or does the request/response need reshaping that's cheaper to declare than to code?** → non-proxy (custom), for either Lambda or HTTP. Otherwise → proxy, and take the simplicity.

Most endpoints, for most teams, land on Lambda proxy. That's not a failure of imagination — it's usually correct. The other five types exist for the specific situations where proxy's simplicity stops being a win, and knowing which situation you're in is the actual skill, more than knowing the six types exist.

---

## Do This, Not That

| Instead of... | Do this |
|---|---|
| Reaching for Lambda custom "for flexibility" without a concrete decoupling need | Default to Lambda proxy and keep transformation logic in code, where it's easier to test and debug |
| Routing every DynamoDB write through a Lambda "for consistency" | Consider a direct AWS service integration for genuinely thin, low-logic endpoints |
| Writing real business logic (multi-step validation, conditional branching) in a VTL mapping template | Move that logic into a Lambda — VTL is the wrong tool for anything beyond straightforward reshaping |
| Standing up a Lambda purely to return static CORS preflight headers | Use a Mock integration for `OPTIONS` — no invocation needed |
| Assuming an HTTP-backed service needs to be rewritten to sit behind API Gateway | Use an HTTP proxy integration to front it as-is and layer auth/throttling/custom domain on top |

---

## What's Next

That's the core-concepts foundation — the request lifecycle, endpoint types and resource design, and integration types. Part 4 turns hands-on: creating resources, methods, and integrations with boto3, writing request validation models, working with mapping templates in practice, and understanding exactly when a deployment is required versus when it isn't.

More DevOps and cloud infrastructure write-ups like this live at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — issues and PRs from fellow practitioners are always welcome.
