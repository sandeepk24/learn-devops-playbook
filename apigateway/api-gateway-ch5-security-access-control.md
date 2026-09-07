# AWS API Gateway for DevOps Engineers, Part 5: Security and Access Control

*Part 5 of a 7-part series. Parts 1–3 covered core concepts, Part 4 covered building and deploying. This chapter covers everything related to locking the API down. Part 6 covers traffic management and custom domains, and Part 7 covers observability and troubleshooting.*

Every example in Parts 1 and 2 quietly used `authorizationType="NONE"`, which was deliberate — you can't reasonably learn resource creation and authorization in the same breath. But shipping that to production is how you end up explaining a security incident to people who don't normally ask you technical questions. This chapter fixes that, and goes further into everything else that determines who can reach your API and what they're allowed to do once they're there.

---

## The Four Ways to Authorize a Request

| Method | How it works | Best for |
|---|---|---|
| **AWS_IAM** | SigV4-signed requests, verified against IAM policies | Service-to-service calls within your own AWS account or trusted accounts |
| **COGNITO_USER_POOLS** | Cognito issues a JWT after sign-in; API Gateway validates it against the pool | End-user-facing apps with their own sign-up/sign-in flows |
| **Lambda authorizer (TOKEN or REQUEST)** | Your own code validates the request and returns an IAM policy | Custom logic — third-party IdP tokens, API keys checked against a database, per-tenant rate limits |
| **NONE** | No authorization at all | Public, unauthenticated endpoints only — and even then, consider a resource policy or WAF rule |

### IAM authorization

This is the right choice when both sides of the call are AWS resources you control — a Lambda calling another service's API, an EC2 instance hitting an internal endpoint. The caller signs the request with SigV4 using their IAM credentials, and API Gateway checks that identity against an IAM policy attached to the method.

```python
client.put_method(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="GET",
    authorizationType="AWS_IAM",
)
```

The caller then needs an IAM policy granting `execute-api:Invoke` on the specific method ARN:

```python
policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": "execute-api:Invoke",
        "Resource": f"arn:aws:execute-api:{region}:{account_id}:{api_id}/prod/GET/orders",
    }],
}
```

The advantage here is you're not managing a separate credential system at all — you're reusing IAM, which your team already understands and already audits.

### Cognito User Pools

If your API serves an end-user-facing application, Cognito hands you sign-up, sign-in, MFA, and password reset for free, and API Gateway validates the resulting JWT natively without any custom code:

```python
client.put_method(
    restApiId=api_id,
    resourceId=orders_resource["id"],
    httpMethod="GET",
    authorizationType="COGNITO_USER_POOLS",
    authorizerId=cognito_authorizer_id,
)
```

The client sends the JWT in the `Authorization` header, and API Gateway checks its signature and expiry against the configured user pool before the request ever reaches your integration. Your handler can trust `event["requestContext"]["authorizer"]["claims"]` without re-validating anything.

### Lambda authorizers: full control, full responsibility

When neither IAM nor Cognito fits — you're validating a token from a third-party identity provider, checking an API key against your own database, or implementing per-tenant logic — a Lambda authorizer is the escape hatch. It just needs to return an IAM policy document:

```python
def lambda_handler(event, context):
    token = event.get("authorizationToken", "")

    if not is_valid_token(token):
        raise Exception("Unauthorized")  # API Gateway returns 401 for this

    principal_id = get_principal_from_token(token)

    return {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{
                "Action": "execute-api:Invoke",
                "Effect": "Allow",
                "Resource": event["methodArn"],
            }],
        },
        "context": {
            "tenantId": get_tenant_from_token(token),  # passed through to your integration
        },
    }
```

One detail that catches people off guard: API Gateway caches the authorizer's response by default (usually 300 seconds), keyed on the identity source you configure. If you're debugging "why isn't my token revocation taking effect immediately," check the authorizer cache TTL before you assume the code is broken. You can set the TTL to 0 to disable caching entirely, but that means every single request pays for a full authorizer invocation — a real latency and cost tradeoff, not a free safety knob.

There are two flavors: **TOKEN** authorizers, which just receive a bearer token, and **REQUEST** authorizers, which receive the full request (headers, query params, path params, source IP) — use REQUEST when your authorization logic needs more than just a token, like checking a header combination or the caller's IP range.

---

## Resource Policies: Authorization at the API Level, Not the Method Level

A resource policy is a JSON IAM-style policy attached to the whole API, evaluated *before* any method-level authorizer runs. This is where you'd restrict an entire API to a specific VPC endpoint (for private APIs), a specific IP range, or a specific set of AWS accounts.

```python
resource_policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Deny",
        "Principal": "*",
        "Action": "execute-api:Invoke",
        "Resource": "arn:aws:execute-api:*:*:*",
        "Condition": {
            "NotIpAddress": {"aws:SourceIp": ["203.0.113.0/24"]}
        },
    }],
}
```

This stacks with, rather than replaces, method-level authorization — a request has to pass both the resource policy and whatever authorizer is on the specific method it's hitting. It's the right layer for coarse-grained restrictions ("only this office IP range" or "only this VPC endpoint") that shouldn't have to be re-implemented in every Lambda authorizer.

---

## Private APIs and VPC Endpoints

For internal services that should never touch the public internet, a private API paired with an interface VPC endpoint means the API isn't reachable from outside your VPC at all — not "blocked by a security group," but genuinely unroutable from the internet.

```python
api = client.create_rest_api(
    name="internal-inventory-api",
    endpointConfiguration={
        "types": ["PRIVATE"],
        "vpcEndpointIds": ["vpce-0123456789abcdef0"],
    },
)
```

You still need a resource policy that explicitly allows the VPC endpoint — without it, the default is deny-all, which is a common "why can't anything reach my private API" support ticket:

```python
resource_policy = {
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": "*",
        "Action": "execute-api:Invoke",
        "Resource": "arn:aws:execute-api:*:*:*",
        "Condition": {
            "StringEquals": {"aws:SourceVpce": "vpce-0123456789abcdef0"}
        },
    }],
}
```

---

## API Keys: Identification, Not Authentication

This is a distinction worth being precise about, because the naming ("API key") suggests security it doesn't actually provide. An API key identifies which client is calling — it's what usage plans and quotas key off of — but it is **not** an authentication mechanism on its own. Anyone with the key string can use it; there's no cryptographic proof of identity involved.

```python
key = client.create_api_key(name="partner-acme-corp", enabled=True)
```

Pair API keys with a real authorizer (IAM, Cognito, or Lambda) if you need actual authentication. Use them alone only for internal, low-stakes rate limiting where identifying the caller — not proving who they are — is the whole point.

---

## Mutual TLS: Verifying the Client's Certificate

For B2B integrations where you need cryptographic proof of client identity beyond a bearer token — common in financial services and healthcare integrations — API Gateway supports mutual TLS on custom domain names. You upload a truststore (a PEM file of trusted CA certificates) to S3, and API Gateway rejects any client that doesn't present a certificate signed by one of them, before the request even reaches your authorizer.

```python
client.create_domain_name(
    domainName="partners-api.yourcompany.com",
    mutualTlsAuthentication={
        "truststoreUri": "s3://your-truststore-bucket/truststore.pem",
    },
    # ... certificate ARN and endpoint config
)
```

This is more operational overhead than it's worth for most internal or consumer-facing APIs, but it's the right tool when a partner contract or compliance requirement specifically calls for client certificate verification.

---

## CORS: A Security Topic, Not Just a Browser Annoyance

CORS gets treated as a debugging nuisance, but it exists to protect your users — it's the browser preventing a malicious site from making authenticated requests to your API on a logged-in user's behalf. Getting it right matters as much as getting authorization right.

The checklist, in order:

1. Does the resource have an `OPTIONS` method configured, with a `MOCK` integration returning the right headers?
2. Do your actual `GET`/`POST`/etc. integration responses *also* include `Access-Control-Allow-Origin`? This is the one people miss — CORS headers need to be on every response, not just the preflight.
3. Did you redeploy the stage after changing any of the above?

If you're using a Lambda proxy integration, the CORS headers have to come from your Lambda's return value, not from API Gateway's method response config — proxy integrations bypass that layer entirely. And resist the temptation to set `Access-Control-Allow-Origin: *` on an authenticated endpoint just to make a browser error go away — a wildcard origin combined with credentialed requests is exactly the hole CORS exists to close.

---

## Do This, Not That

| Instead of... | Do this |
|---|---|
| Shipping `authorizationType="NONE"` past the prototype stage | Wire up an authorizer — even a minimal Lambda one — before the first real deployment |
| Treating an API key as authentication | Use it for client identification and rate limiting; pair with IAM, Cognito, or a Lambda authorizer for real auth |
| Setting a Lambda authorizer's cache TTL to 0 by default "to be safe" | Keep the default cache and design revocation flows around it, unless per-request freshness is a genuine requirement |
| Locking down a private API with security groups alone | Use a private endpoint type plus an explicit resource policy scoped to the VPC endpoint |
| Setting `Access-Control-Allow-Origin: *` to silence a CORS error on an authenticated route | Scope it to the specific origins that should be allowed, and never combine a wildcard with credentialed requests |

---

## What's Next

Part 6 covers traffic management — throttling at the account, stage, and usage-plan level, response caching, canary deployments, and custom domain names with base path mapping.

More DevOps and cloud infrastructure write-ups like this live at [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — issues and PRs from fellow practitioners are always welcome.
