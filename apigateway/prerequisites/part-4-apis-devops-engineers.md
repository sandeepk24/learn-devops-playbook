# Part 4 — APIs in the DevOps World

*Part 4 of 5 in the API Mastery Roadmap prerequisites series. This one is for DevOps and platform engineers — the people who don't build the APIs themselves but are responsible for making sure they run, scale, stay secure, and don't take down the business at 3 AM. Parts 1–3 covered consuming and designing APIs; this one covers operating them. Part 5 closes with advanced architecture patterns.*

---

Here's the thing nobody tells you when you move from software engineering into DevOps: **you stop caring about what the API does and start caring about whether it runs.**

A developer worries about whether the endpoint returns the right data. A DevOps engineer worries about whether the endpoint is reachable, whether it's responding within SLA, whether the auth layer is going to get bypassed in production, whether the cert expires in three days, and whether anyone will notice before the monitoring does.

Different problems, different tools, different failure modes. This article is about APIs from that operational angle.

---

## The API Gateway: Why You Need One in Production

When developers talk about APIs, they usually mean the code running in a Lambda function or a container. When DevOps engineers talk about APIs, they often mean the *API Gateway* — the managed layer that sits between the internet and that code.

An API gateway does things your application code shouldn't have to do:

```
Internet
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                    API Gateway                       │
│                                                      │
│  ✓ TLS termination          ✓ Rate limiting          │
│  ✓ Authentication           ✓ Request transformation │
│  ✓ Authorization            ✓ Caching                │
│  ✓ DDoS protection          ✓ Observability          │
│  ✓ Routing                  ✓ Canary deployments     │
└──────────────────────────┬──────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
       Lambda #1     Container #2    EC2 Service #3
```

If you route traffic directly to your backend without a gateway, each backend service has to implement all of that itself. In a microservices architecture with 40 services, that means 40 implementations of rate limiting, 40 implementations of auth, 40 places where a misconfigured TLS cert can leak traffic. The gateway is where those cross-cutting concerns live once.

The major options you'll work with:

| Gateway | Where You'll See It |
|---------|---------------------|
| **AWS API Gateway** | AWS-native workloads (this repo's main series covers it in depth) |
| **Kong** | Self-hosted or hybrid; common in Kubernetes environments |
| **NGINX** | Legacy infrastructure, bare-metal, cost-sensitive setups |
| **Traefik** | Kubernetes-native; automatic service discovery |
| **Cloudflare** | Edge-first; DDoS protection + CDN + gateway in one |

The deep dive on AWS API Gateway specifically starts in the main series after this prerequisites track.

---

## Infrastructure as Code for APIs

If you're clicking through a console to configure your API gateway, routing rules, or auth settings — stop. Everything that changes a production system needs to be in version control.

For AWS API Gateway with Terraform:

```hcl
# api_gateway.tf

resource "aws_api_gateway_rest_api" "main" {
  name        = "user-service-api"
  description = "User service REST API"

  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_resource" "users" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "users"
}

resource "aws_api_gateway_method" "get_users" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.users.id
  http_method   = "GET"
  authorization = "COGNITO_USER_POOLS"
  authorizer_id = aws_api_gateway_authorizer.cognito.id
}

resource "aws_api_gateway_integration" "get_users_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.users.id
  http_method             = aws_api_gateway_method.get_users.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.user_service.invoke_arn
}

resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id

  # Force redeployment when config changes
  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.users.id,
      aws_api_gateway_method.get_users.id,
      aws_api_gateway_integration.get_users_lambda.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "prod" {
  deployment_id = aws_api_gateway_deployment.main.id
  rest_api_id   = aws_api_gateway_rest_api.main.id
  stage_name    = "prod"

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access_logs.arn
  }
}
```

Key practices here:
- The deployment has a `triggers` block that forces redeployment when any route or integration changes. Without this, Terraform might show "no changes" when AWS API Gateway hasn't actually picked up your updates.
- `create_before_destroy` prevents downtime during deployment by creating the new deployment before destroying the old one.
- Logging is configured from day one, not added later when something breaks.

---

## CI/CD for APIs: What Changes When You're Shipping an Interface

Shipping an API is not the same as shipping a web app. When an API breaks, it breaks every client that depends on it — mobile apps, internal services, third-party integrations. The CI/CD pipeline needs to account for that.

Here's a pipeline that actually works for API services:

```yaml
# .github/workflows/api-deploy.yml
name: API Deploy

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Validate OpenAPI spec
        uses: char0n/swagger-editor-validate@v1
        with:
          definition-file: openapi.yaml

      - name: Lint API spec for breaking changes
        uses: oasdiff/oasdiff-action/breaking@main
        with:
          base: origin/main
          revision: HEAD

  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run unit tests
        run: |
          pip install -r requirements.txt
          pytest tests/unit/ -v --cov=src --cov-report=xml

  contract-tests:
    runs-on: ubuntu-latest
    needs: unit-tests
    steps:
      - uses: actions/checkout@v4
      
      - name: Start mock server from OpenAPI spec
        run: |
          npx @stoplight/prism-cli mock openapi.yaml &
          sleep 3
      
      - name: Run contract tests against mock
        run: pytest tests/contract/ -v

  integration-tests:
    runs-on: ubuntu-latest
    needs: contract-tests
    if: github.ref == 'refs/heads/main'
    environment: staging
    steps:
      - name: Deploy to staging
        run: terraform apply -auto-approve -var="environment=staging"
      
      - name: Run integration tests against staging
        run: pytest tests/integration/ -v
        env:
          API_BASE_URL: ${{ vars.STAGING_API_URL }}
          API_TOKEN: ${{ secrets.STAGING_API_TOKEN }}

  deploy-prod:
    runs-on: ubuntu-latest
    needs: integration-tests
    if: github.ref == 'refs/heads/main'
    environment: production
    steps:
      - name: Deploy to production
        run: terraform apply -auto-approve -var="environment=prod"
      
      - name: Smoke test production
        run: |
          STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: Bearer ${{ secrets.PROD_HEALTH_TOKEN }}" \
            ${{ vars.PROD_API_URL }}/health)
          
          if [ "$STATUS" != "200" ]; then
            echo "Smoke test failed with status $STATUS"
            exit 1
          fi
```

The `oasdiff` step is the one most teams skip and then regret. It compares the OpenAPI spec on your branch against the spec on `main` and fails the build if it detects a breaking change — removed fields, changed types, new required parameters. This catches the thing that hurts: you change the API, the build passes, and three mobile app versions in production break silently.

---

## Contract Testing: The Guarantee That Services Actually Agree

Unit tests verify your code works. Integration tests verify two systems work together in a test environment. Contract tests verify that the *agreement* between producer and consumer is honored — and they do it without the two services needing to be deployed at the same time.

The tool for this in Python/Go/Node is [Pact](https://pact.io). Here's how it works:

**The consumer (the calling service) writes a test that defines what it expects:**

```python
# tests/contract/test_user_service_contract.py
from pact import Consumer, Provider

pact = Consumer("order-service").has_pact_with(Provider("user-service"))

def test_get_user_returns_expected_shape():
    expected_response = {
        "id": "u_4829",
        "name": Like("Jordan"),         # type check, not exact match
        "email": Like("any@email.com"),
        "is_active": Like(True),
    }
    
    (pact
     .given("user u_4829 exists")
     .upon_receiving("a request for user u_4829")
     .with_request("GET", "/users/u_4829",
                   headers={"Authorization": "Bearer token"})
     .will_respond_with(200, body=expected_response))
    
    with pact:
        # Your actual consumer code runs here, hitting the Pact mock
        user = UserServiceClient().get_user("u_4829")
        assert user["is_active"] is True
```

This generates a *pact file* — a JSON contract document. That file gets published to a Pact Broker (a shared registry). The provider (user-service) then runs its own test that *verifies* it actually satisfies every consumer's contract:

```python
# In the user-service repo
def test_satisfies_order_service_contract():
    verifier = Verifier(
        provider="user-service",
        provider_base_url="http://localhost:8000"
    )
    verifier.verify_with_broker(
        broker_url="https://pact-broker.internal.yourcompany.com",
        consumer_version_selectors=[{"mainBranch": True}]
    )
```

The value: the order-service and user-service never have to be deployed in the same place to verify they're compatible. You can change the user-service API and know immediately which consumers would break, before you ship anything.

---

## Observability: The Three Signals That Tell You Your API is Sick

When an API is struggling, three signals tell you the story — and you need all three, because each one has blind spots the others cover.

### 1. Metrics (What is happening at scale)

The core API metrics every service needs:

```
Request Rate       — how many requests per second
Error Rate         — what % are 4xx or 5xx
Latency (p50/p95/p99) — not average, percentiles
Saturation         — are you near any limits?
```

This is the RED method (Rate, Errors, Duration) — the standard framework for service monitoring. In CloudWatch for AWS API Gateway:

```bash
# Get p99 latency for the last 5 minutes
aws cloudwatch get-metric-statistics \
  --namespace AWS/ApiGateway \
  --metric-name IntegrationLatency \
  --dimensions Name=ApiName,Value=user-service-api \
  --start-time $(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 300 \
  --statistics p99
```

Metric alerts worth having from day one:
- Error rate > 1% for 5 minutes → page
- p99 latency > 2s for 5 minutes → page
- Request rate drops to near zero (traffic loss) → page immediately

### 2. Logs (What happened to a specific request)

Structured logs (JSON) are searchable. Plain text logs are archaeology.

```python
import structlog
import uuid

log = structlog.get_logger()

def handle_request(request):
    request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
    
    log = log.bind(
        request_id=request_id,
        method=request.method,
        path=request.path,
        user_id=request.user.id if request.user else None
    )
    
    try:
        result = process(request)
        log.info("request_completed",
                 status_code=200,
                 duration_ms=elapsed_ms())
        return result
    
    except ValidationError as e:
        log.warning("validation_failed",
                    status_code=400,
                    errors=e.errors)
        return error_response(400, e)
    
    except Exception as e:
        log.error("unexpected_error",
                  status_code=500,
                  exc_info=True)
        raise
```

The `request_id` threading through every log line is what lets you pull every log entry for a single request with a single query: `request_id = "req_8f2a9c"`.

### 3. Traces (How a request traveled through your systems)

Distributed tracing is how you answer "why was that specific request slow?" when the slowness is somewhere deep in a chain of service calls.

AWS X-Ray with Python Lambda:

```python
from aws_xray_sdk.core import xray_recorder, patch_all

# Auto-patch requests, boto3, and other common libraries
patch_all()

@xray_recorder.capture("process_order")
def process_order(order_id: str):
    # Everything in this function is tracked as a subsegment
    user = fetch_user(order_id)          # Traced
    inventory = check_inventory(order_id) # Traced
    result = charge_payment(order_id)    # Traced
    return result
```

A trace shows you a waterfall — each service call as a horizontal bar, with duration. When your p99 is 3 seconds and your p50 is 200ms, a trace for one of the slow requests will show you exactly where the 3 seconds went.

---

## Security: The DevOps Angle

Software engineers secure the code. DevOps engineers secure the infrastructure that runs it. For APIs, that means several things:

### TLS: Non-Negotiable, But Often Wrong in the Details

- Enforce TLS 1.2 minimum. TLS 1.0 and 1.1 are deprecated.
- Check your cipher suites. Tools like [testssl.sh](https://testssl.sh) or [SSL Labs](https://www.ssllabs.com/ssltest/) will tell you if you're using weak ones.
- Certificate expiry monitoring. A surprising number of outages are caused by expired certs. Set an alert for 30 days before expiry.

```bash
# Check when a cert expires
echo | openssl s_client -servername api.example.com \
  -connect api.example.com:443 2>/dev/null | \
  openssl x509 -noout -dates
```

### Secrets Management

Credentials should never live in environment variables on a running instance, in `.env` files committed to git, or hardcoded anywhere. They belong in a secrets manager:

```python
import boto3

def get_secret(secret_name: str) -> str:
    client = boto3.client("secretsmanager", region_name="us-east-1")
    response = client.get_secret_value(SecretId=secret_name)
    return response["SecretString"]

# Usage
DB_PASSWORD = get_secret("prod/user-service/db-password")
```

Rotate secrets regularly. If you discover one was exposed, rotate it within the hour.

### WAF: Your API's First Line of Defense

A Web Application Firewall sits in front of your API Gateway and blocks malformed or malicious traffic before it ever reaches your application. For AWS:

```hcl
resource "aws_wafv2_web_acl" "api" {
  name  = "api-gateway-waf"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # AWS Managed Rules — enable these immediately
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action { none {} }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # Rate limiting — 1000 requests per 5 minutes per IP
  rule {
    name     = "RateLimitRule"
    priority = 2

    action { block {} }

    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimit"
      sampled_requests_enabled   = true
    }
  }
}
```

Start in count mode (log but don't block) for one week before switching to block mode. This lets you see what the managed rules would have blocked and tune for false positives before you start breaking legitimate traffic.

---

## Health Checks and SLOs: Defining What "Working" Means

Without an explicit definition of healthy, your API is either "up" or "down" — and "down" is usually discovered by a user, not your monitoring.

### The Health Endpoint

Every API should have a `/health` endpoint. Don't just return 200 — return information:

```python
import time
import boto3
from fastapi import FastAPI

app = FastAPI()
start_time = time.time()

@app.get("/health")
async def health():
    # Check dependencies
    db_status = check_database()
    cache_status = check_cache()
    
    is_healthy = db_status["ok"] and cache_status["ok"]
    
    return {
        "status": "healthy" if is_healthy else "degraded",
        "uptime_seconds": int(time.time() - start_time),
        "version": "1.4.2",
        "checks": {
            "database": db_status,
            "cache": cache_status
        }
    }, 200 if is_healthy else 503
```

A load balancer or container orchestrator will hit this endpoint on an interval and pull traffic from instances that return non-200. The detail in the body helps when you're debugging *why* something went degraded.

### SLOs: The Promise You're Making

An SLO (Service Level Objective) is a measurable promise about API behavior:

```
Availability SLO:   99.9% of requests return non-5xx responses, measured monthly
Latency SLO:        95% of requests complete in < 500ms
Error Budget:       0.1% of monthly requests (≈ 43 minutes of total downtime)
```

The error budget is the key concept. If your SLO is 99.9%, you have 43 minutes of "budget" per month. When you're spending that budget, you slow down deployments and focus on reliability. When you have plenty of budget, you can move faster.

This is the foundation of SRE — quantifying the trade-off between reliability and velocity, rather than arguing about it in meetings.

---

## Load Testing: Find the Limit Before Your Users Do

Every API has a breaking point. Find yours in a load test, not in production.

Using [k6](https://k6.io) — the modern load testing tool:

```javascript
// load-test.js
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

const errorRate = new Rate('errors');

export const options = {
  stages: [
    { duration: '2m', target: 50 },   // Ramp up to 50 VUs
    { duration: '5m', target: 50 },   // Hold at 50 VUs
    { duration: '2m', target: 200 },  // Spike to 200 VUs
    { duration: '5m', target: 200 },  // Hold at 200 VUs
    { duration: '2m', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(99)<2000'],  // 99% under 2s
    errors: ['rate<0.01'],              // Error rate under 1%
  },
};

export default function () {
  const response = http.get(`${__ENV.API_URL}/users`, {
    headers: {
      'Authorization': `Bearer ${__ENV.API_TOKEN}`,
    },
  });

  check(response, {
    'status is 200': (r) => r.status === 200,
    'response time < 500ms': (r) => r.timings.duration < 500,
  });

  errorRate.add(response.status !== 200);
  sleep(1);
}
```

Run it:

```bash
k6 run -e API_URL=https://staging-api.example.com \
       -e API_TOKEN=$(cat .staging-token) \
       load-test.js
```

Never run load tests against production. Always against staging, with production-like data volumes.

What you're looking for:
- At what request rate does p99 latency start climbing?
- At what rate do errors appear?
- Does the service recover when load drops, or does it stay degraded?

---

## The Runbook: What to Do at 3 AM

Every production API should have a runbook — a step-by-step guide for diagnosing and resolving the most common failure modes. Here's a template:

```markdown
## API Gateway 5xx Spike Runbook

### Symptoms
- Error rate alert fires for > 5xx responses exceeding 1%
- CloudWatch dashboard shows IntegrationErrors climbing

### Step 1: Identify the scope
- Which endpoints are affected? (Check the 5xx breakdown by resource in CloudWatch)
- Is it all traffic or specific clients/IPs? (Check WAF logs)
- When did it start? (Correlate with recent deployments)

### Step 2: Check the integration
- Is Lambda/ECS healthy? Check function errors, container health checks
- Is the database accepting connections? Check RDS metrics
- Is there a dependency that's down? Check service health dashboard

### Step 3: Quick mitigations
- If a bad deployment caused it: `terraform apply` with previous version pinned
- If Lambda is throttled: request limit increase or enable provisioned concurrency
- If downstream dependency is down: enable the API Gateway cache to serve stale data

### Escalation
- If not resolved in 30 minutes: escalate to [on-call SRE]
- If customer-visible > 15 minutes: trigger customer comms process
```

A runbook that lives in the repo, next to the code, gets updated when things change. A runbook in Confluence from 2022 is a historical artifact.

---

## Recap

- API gateways centralize cross-cutting concerns — TLS, auth, rate limiting, routing — so your backend code doesn't have to.
- Everything that configures a production API (gateway rules, auth, certs) belongs in Terraform or CDK, not clicked through a console.
- Your CI/CD pipeline needs breaking-change detection on the OpenAPI spec, not just unit tests.
- Contract testing with Pact lets two services verify compatibility without being co-deployed.
- Observability means metrics (RED), structured logs with request IDs threaded through, and distributed traces.
- WAF, TLS hygiene, and secrets management are the non-negotiable security baseline.
- Load test in staging before you find the limit in production.
- SLOs define what "working" means numerically — without them, reliability is just vibes.

---

*Next up: [Part 5 — Advanced API Architecture: When APIs Become Infrastructure](./part-5-advanced-api-architecture.md). Event-driven APIs, webhooks vs. WebSockets vs. SSE, API composition patterns, service meshes, backward compatibility at scale, and what "API as a product" actually means.*
