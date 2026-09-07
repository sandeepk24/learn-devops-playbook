# AWS API Gateway for DevOps Engineers, Part 7: Observability, Troubleshooting, and Production Operations

*Part 7 of a 7-part series. Parts 1–3 covered core concepts, Part 4 covered building and deploying, Part 5 covered security, and Part 6 covered traffic management and custom domains. This final chapter is the one worth bookmarking — it's what you'll actually reach for during an incident.*

Everything in the first four chapters was about building the thing correctly. This chapter is about knowing what's happening inside it once real traffic — and real failure modes — start showing up, and about not paying for capability you're not using.

---

## The CloudWatch Metrics That Actually Matter

API Gateway publishes metrics automatically, but most dashboards either show too many of them or the wrong ones. Here's the short list that earns a place on an on-call dashboard:

| Metric | What it tells you | Watch for |
|---|---|---|
| `Count` | Total requests | Sudden drops (something upstream is failing before requests even arrive) or spikes (traffic surge or retry storm) |
| `4XXError` | Client-side errors as a rate | A spike usually means a client-side bug shipped, or an auth token expired fleet-wide |
| `5XXError` | Server-side errors as a rate | Almost always worth an immediate look — this is your integration failing |
| `Latency` | End-to-end request time, including integration time | Rising p99 with flat p50 usually points at cold starts or a specific slow code path, not systemic load |
| `IntegrationLatency` | Time spent specifically in the backend integration | Separates "API Gateway is slow" from "your Lambda/backend is slow" — check this before blaming the Gateway |
| `ThrottleCount` (usage plans) / `CacheHitCount` / `CacheMissCount` | Whether throttling or caching is behaving as configured | A high `ThrottleCount` from one client means your usage plan limits are working as designed, not necessarily a problem |

The `Latency` vs `IntegrationLatency` distinction is the one that saves the most debugging time. If `Latency` is high but `IntegrationLatency` is normal, the time is being spent in API Gateway itself — often an authorizer with a slow cold path, or a mapping template doing more work than expected. If both are high together, the problem is downstream, and that's where you point your attention.

---

## Structured Access Logging

Execution logs (the ones enabled via stage settings, showing the full request lifecycle) are verbose and useful for debugging, but expensive to keep on permanently and not something you'd query at scale. Access logs are the leaner, structured alternative you actually want running in production continuously.

```python
client.update_stage(
    restApiId=api_id,
    stageName="prod",
    patchOperations=[
        {"op": "replace", "path": "/accessLogSettings/destinationArn",
         "value": f"arn:aws:logs:{region}:{account_id}:log-group:api-gateway-access-logs"},
        {"op": "replace", "path": "/accessLogSettings/format", "value": json.dumps({
            "requestId": "$context.requestId",
            "ip": "$context.identity.sourceIp",
            "requestTime": "$context.requestTime",
            "httpMethod": "$context.httpMethod",
            "resourcePath": "$context.resourcePath",
            "status": "$context.status",
            "responseLength": "$context.responseLength",
            "integrationLatency": "$context.integrationLatency",
            "userAgent": "$context.identity.userAgent",
        })},
    ],
)
```

The JSON format is the detail that matters here, not just enabling logging. Free-text log lines force you into regex when you're querying CloudWatch Logs Insights under pressure during an incident; a structured JSON format means `fields status, integrationLatency | filter status >= 500` just works, without anyone writing a parsing expression at 3 AM.

---

## X-Ray Tracing: Following a Request Across Services

Once your API is calling a Lambda that calls DynamoDB and publishes to SNS, "where did the 800ms go" becomes a real question that CloudWatch metrics alone can't answer — they tell you *that* something was slow, not *where* in the chain. X-Ray tracing, enabled at the stage level, threads a trace ID through the whole call graph:

```python
client.update_stage(
    restApiId=api_id,
    stageName="prod",
    patchOperations=[
        {"op": "replace", "path": "/tracingEnabled", "value": "true"},
    ],
)
```

Your Lambda needs the X-Ray SDK instrumented (or, more simply, X-Ray active tracing enabled on the function itself) for the trace to continue past the Gateway. The payoff is a service map and a waterfall view showing exactly which downstream call ate the latency — genuinely one of the fastest ways to root-cause a slow endpoint instead of guessing.

---

## Failure Signatures: What You'll Actually See in an Incident Channel

### 502 vs 504 vs 429 — they are not the same problem

| Status | What it usually means | Where to look |
|---|---|---|
| **502 Bad Gateway** | The integration responded, but the response was malformed — for Lambda proxy integrations, this is almost always a handler that didn't return the expected `{statusCode, headers, body}` shape | CloudWatch Logs for the Lambda function, specifically the return statement |
| **504 Gateway Timeout** | The integration didn't respond within the timeout window at all | Lambda duration metrics, or check if the function is cold-starting into a VPC with a slow ENI attachment |
| **429 Too Many Requests** | You hit a throttle — account-level, stage-level, or usage-plan-level | `ThrottleCount` metric, cross-referenced against usage plan quotas from Part 6 |

A 502 from a Lambda proxy integration is almost never an API Gateway problem, even though the error surfaces at the Gateway. Check the handler's return value first. A shockingly common cause: a try/except that swallows an exception and returns `None`, which isn't a valid proxy response.

### The 29-second wall

API Gateway has a hard integration timeout ceiling of 29 seconds, and it is not configurable upward — not through the console, not through the API, not through a support ticket. If your backend legitimately needs longer than that (a large report generation, a slow third-party call), API Gateway is the wrong front door for that specific endpoint. Options: make the call asynchronous (return 202, poll a status endpoint), move that endpoint behind Application Load Balancer instead, or restructure the work to fit the window. Don't spend an afternoon trying to configure your way past this — it's a hard limit for a reason, and no amount of console clicking changes it.

### CORS: it's not actually about API Gateway

Every CORS failure eventually becomes a five-minute fix and a thirty-minute detour, because the browser's error message ("No 'Access-Control-Allow-Origin' header") sends people straight to Google instead of to their own OPTIONS method config. The checklist from Part 5 is worth repeating here because it's the thing you'll actually reach for mid-incident: confirm the `OPTIONS` method exists and returns the right headers, confirm your real methods' responses *also* include `Access-Control-Allow-Origin` (not just the preflight), and confirm you redeployed after the last change.

### Cold starts hiding behind the integration timeout

If your Lambda is in a VPC and rarely invoked, ENI attachment on cold start can eat a meaningful chunk of your latency budget. Combine a cold VPC-attached Lambda with a tight downstream timeout, and you get intermittent 504s that vanish the moment you go looking, because by the time you're investigating, the function is warm again. Provisioned concurrency is the direct fix if the endpoint is latency-sensitive; it's not free, so reserve it for the paths that actually need it rather than applying it broadly.

---

## Cost Optimization: Where the Bill Actually Comes From

API Gateway pricing is per-request plus a few add-ons, and the add-ons are where teams get surprised:

- **Caching** bills for provisioned cache capacity continuously, regardless of hit rate — an idle 0.5 GB cache costs the same whether it's serving thousands of requests or nearly none. Size it to actual traffic, and turn it off on stages that don't need it (a `dev` stage rarely does).
- **Data transfer out** adds up on large response payloads — this is where the compression setting from Part 6 pays for itself on JSON-heavy APIs.
- **REST API vs HTTP API** pricing differs meaningfully — HTTP API is roughly 70% cheaper per request as of this writing. If an existing REST API isn't using anything REST-API-specific (request validation, usage plans, private endpoints), migrating it to HTTP API is a legitimate cost-reduction project, not just a preference.
- **Execution logs left on in production** don't cost API Gateway anything directly, but the CloudWatch Logs ingestion and storage cost for verbose execution logging at production volume is easy to underestimate — this is a good argument for access logs (lean, structured) as your always-on choice, with execution logs enabled temporarily during active debugging only.

---

## CI/CD for API Gateway

The pattern that holds up in practice: define the API in Terraform or CDK, never hand-edit via console in any environment past `dev`, and treat a `create_deployment` call as something your pipeline triggers explicitly after a plan/diff shows a real change — not something that happens implicitly on every `apply`. If your IaC tool's provider doesn't automatically create a new deployment resource when method or integration config changes (Terraform's `aws_api_gateway_deployment` needs a `triggers` block referencing a hash of the relevant resources, or it won't redeploy), you'll ship config changes that silently don't take effect, which is a worse failure mode than an error — nothing looks broken until someone notices the behavior didn't change.

---

## Do This, Not That

| Instead of... | Do this |
|---|---|
| Leaving execution logs on permanently in production "just in case" | Use structured access logs as the always-on default; enable execution logs temporarily during active debugging |
| Assuming API Gateway is slow when `Latency` is high | Check `IntegrationLatency` first to rule the Gateway itself in or out |
| Debugging a multi-service latency spike by guessing which call is slow | Enable X-Ray tracing and read the waterfall instead of guessing |
| Sizing a cache cluster once and forgetting it | Revisit cache cluster size against actual traffic periodically — it bills continuously regardless of usage |
| Treating deployment as implicit in every IaC apply | Make deployment an explicit, triggered step gated on a real config diff |

---

## Closing the Series

Seven chapters in, the throughline is the same one from Part 1: every piece of API Gateway — resources, integrations, authorizers, throttles, caching, logging — is a variation on the same request lifecycle. Once that lifecycle is second nature, the AWS console stops feeling like a maze of unrelated settings and starts looking like exactly what it is: a small number of decision points, repeated.

If this series was useful, more DevOps and cloud infrastructure write-ups like this live at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — issues and PRs from fellow practitioners are always welcome.
