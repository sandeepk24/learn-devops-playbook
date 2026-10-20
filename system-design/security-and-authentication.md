# Security and Authentication

Authentication answers one question: who is this? Authorization answers a different one: what are they allowed to do? The two are distinct problems, frequently conflated, and both need to be solved before any sensitive operation proceeds.

Getting authentication wrong is not primarily a code problem. It's a design problem. The wrong choice of token format, credential storage, or session model creates vulnerabilities that no amount of careful implementation can fix. Make the structural decisions correctly first.

## Fundamentals

### API keys

The simplest credential. A long random string. Client includes it in every request (`Authorization: Bearer <key>` or a custom header). Server validates it against a store.

Good for: machine-to-machine authentication where the client is a server you control or trust, internal service communication in controlled environments, simple public APIs with usage tracking needs.

Bad for: user-facing authentication (API keys don't have built-in expiry or rotation mechanisms without custom work), situations where the key needs to be embedded in a mobile app or browser (it will be extracted), anything requiring delegated access (there's no concept of "this key can only do X on behalf of user Y").

API keys have no cryptographic structure — the server must look them up in a store to validate them. At high request rates, this lookup becomes a bottleneck. Hash the key before storing; validate by hashing the incoming key and comparing. This prevents the stored value from being useful to an attacker who reads the database.

### JWTs

JSON Web Tokens. A signed (and optionally encrypted) JSON payload that carries claims about the subject. The server issues a JWT after authentication. The client presents the JWT on subsequent requests. The server validates the signature — no database lookup required.

Structure: `header.payload.signature`. The header specifies the signing algorithm. The payload carries claims: `sub` (subject — user ID), `iss` (issuer), `exp` (expiration), `iat` (issued at), and any custom claims the application needs. The signature is computed over the header and payload using the issuer's private key (RS256/ES256) or a shared secret (HS256).

The strength: stateless validation. Any service with the public key can validate the token without calling back to the issuer. Scales well. Enables decentralized authentication across microservices.

The weaknesses:
- **Revocation is hard.** A valid JWT remains valid until expiry. If a user logs out or a token is compromised, you can't invalidate it without maintaining a blocklist — which reintroduces the stateful lookup you were trying to avoid.
- **Short expiry is the mitigation.** Access tokens expire in 15–60 minutes. Refresh tokens (longer-lived, stored securely, used only to get new access tokens) extend the session without keeping long-lived access tokens in play.
- **Algorithm confusion attacks.** A poorly implemented validator that accepts `alg: none` or can be confused into using a symmetric algorithm with the public key as the secret is a well-known vulnerability class. Use a library. Don't implement JWT validation from scratch.

```
JWT flow:

Client ──► POST /auth (credentials) ──► Auth Server
                                          │
                                          └── issue JWT (signed with private key)
                                              └── { sub: "user123", exp: +15min }

Client ──► GET /api/resource
           Authorization: Bearer <jwt>
                │
                ▼
           Service validates signature with public key
           Checks exp claim
           No database call needed
```

### OAuth 2.0

A delegation protocol. Not an authentication protocol — OAuth tells the resource server that the client has been granted permission to act on behalf of a user, without the user giving the client their credentials.

Four grant types cover most use cases:

**Authorization code.** User is redirected to the authorization server, authenticates, grants consent, and is redirected back with an authorization code. The client exchanges the code for tokens. The user's credentials never touch the client. Standard for web applications. Use with PKCE (Proof Key for Code Exchange) to prevent authorization code interception — now required even for confidential clients.

**Client credentials.** No user involved. The client authenticates with its own credentials and gets a token. For machine-to-machine communication. Service A calls service B using a token obtained via client credentials.

**Device code.** For devices without a browser (CLIs, smart TVs). The device displays a code; the user enters it on another device. The device polls for token issuance.

**Implicit** and **resource owner password** grants are deprecated. Don't use them.

OpenID Connect (OIDC) is an identity layer on top of OAuth 2.0. OAuth handles authorization (access tokens). OIDC adds authentication (ID tokens that identify the user). Most "login with Google/GitHub" implementations use OIDC.

### mTLS

Mutual TLS. Standard TLS authenticates the server to the client. mTLS adds the reverse: the client presents a certificate, and the server validates it. Both sides are authenticated at the transport layer.

No tokens, no headers, no application-layer session management. Authentication happens during the TLS handshake. Appropriate for service-to-service communication where both parties are under your control and you can provision and rotate certificates.

The operational cost: certificate management. Each service needs a certificate, signed by a CA your infrastructure trusts. Certificates expire and need rotation. Revocation requires a CRL or OCSP. At scale this requires a certificate management system — cert-manager in Kubernetes, AWS Private CA, HashiCorp Vault PKI.

Worth the investment for zero-trust internal networks. Not worth it for simple internal communication where network controls (security groups, VPC boundaries) already provide sufficient isolation.

## Operations

### Token storage

Where a client stores tokens determines the attack surface.

**Browser applications:**
- Local storage: accessible to any JavaScript on the page. XSS vulnerability steals the token trivially. Don't store JWTs in local storage.
- Session cookies with `HttpOnly` and `Secure` flags: not accessible to JavaScript. Transmitted only over HTTPS. CSRF is the residual risk — mitigate with `SameSite=Strict` or `SameSite=Lax` cookie attribute and CSRF tokens for state-mutating requests.
- In-memory: lost on page refresh, but safe from XSS. Appropriate for access tokens with short expiry combined with a `HttpOnly` cookie holding the refresh token.

**Mobile applications:** OS-provided secure credential stores (Keychain on iOS, Keystore on Android). Not in plaintext in SharedPreferences or NSUserDefaults.

**Server-side / machine clients:** environment variables injected at runtime, not hardcoded in source code. Secrets managers (AWS Secrets Manager, Parameter Store) with rotation. Never in version control.

### Least privilege for service identities

Every service that calls an API or accesses a resource needs an identity and a set of permissions. The permissions should be the minimum required. This is easier to say than to maintain — permissions expand over time as features are added, and shrinking them requires knowing exactly what each service uses.

IAM roles for ECS tasks and EKS pods (via IRSA or Pod Identity) provide temporary, automatically-rotated credentials scoped to the instance. No long-lived keys to rotate manually. The role policy is the permission boundary.

Audit IAM permissions regularly. AWS IAM Access Analyzer generates findings for overly permissive policies. CloudTrail shows which API calls each role actually makes — if a role with S3 read/write permissions only ever makes read calls, remove the write permission.

### Token introspection and validation

For services receiving JWTs: validate the signature, validate the `exp` claim, validate the `iss` (issuer) claim, validate the `aud` (audience) claim. A JWT signed by a legitimate issuer but intended for a different service (`aud` mismatch) should be rejected.

Don't skip audience validation. An attacker who obtains a valid JWT for service A (perhaps through a less-secure endpoint) should not be able to use it against service B. Audience claims prevent token misuse across services.

Cache the public key used for validation rather than fetching it from the JWKS endpoint on every request. Keys rotate infrequently. Fetching on every request adds latency and creates a dependency on the auth server's availability for every API call. Cache with a TTL, refresh periodically or on signature validation failure.

## Deep Dive: authentication on AWS

**Amazon Cognito User Pools.** Managed user directory. Handles registration, login, MFA, password policies, account recovery. Issues JWTs (ID token, access token, refresh token) on successful authentication. Integrates with API Gateway and ALB for built-in JWT validation at the endpoint level — the auth logic doesn't need to be in the application code.

User Pool tokens use RS256. The JWKS endpoint is at `https://cognito-idp.<region>.amazonaws.com/<pool_id>/.well-known/jwks.json`. Cache these keys.

Cognito is opinionated and has limitations — limited custom attribute support, hosted UI customization is restricted, token claims are not freely configurable. For simple authentication needs it's a good default. For complex authorization requirements or heavily customized auth flows, consider a dedicated identity provider (Auth0, Okta) or self-hosted (Keycloak).

**API Gateway authorizers.** Two types:
- *Cognito authorizer:* validates User Pool JWTs automatically. Zero code.
- *Lambda authorizer:* custom Lambda validates any token format. Returns an IAM policy document indicating allowed/denied methods. Result is cached by API Gateway to reduce Lambda invocations — configure cache TTL based on token expiry to avoid serving stale allow/deny decisions.

**ALB authentication.** ALB can authenticate users via OIDC or Cognito before requests reach the target group. The authentication happens at the load balancer layer — the application never handles unauthenticated requests. On successful authentication, ALB adds headers (`X-Amzn-Oidc-Identity`, `X-Amzn-Oidc-Accesstoken`) to the forwarded request. Useful for protecting internal tools and dashboards without adding auth code to every application.

**AWS IAM for service-to-service.** Services calling AWS APIs authenticate via IAM roles with temporary credentials (STS). Services calling other internal services can use IAM authentication via Signature Version 4 request signing. API Gateway supports IAM authentication — the calling service signs the request with its role credentials; API Gateway validates the signature and checks IAM permissions. No JWT management, no token expiry to handle — the SDK handles credential rotation automatically.

**AWS Secrets Manager.** For credentials that can't use IAM (database passwords, third-party API keys, OAuth client secrets). Automatic rotation for RDS, Redshift, and DocumentDB credentials. Lambda function integration for custom rotation logic for other secret types. Applications retrieve secrets at startup rather than reading from environment variables — the secret is never in the environment, never in logs, never in a process listing.

| Credential type | Best for | Rotation | Revocation |
|---|---|---|---|
| API key | M2M, simple APIs | Manual | Delete from store |
| JWT (short-lived) | User sessions, service auth | Auto (expiry) | Blocklist or short TTL |
| OAuth access token | Delegated user auth | Auto (refresh) | Token introspection endpoint |
| mTLS certificate | Zero-trust service mesh | Certificate rotation | CRL/OCSP |
| IAM role (STS) | AWS service access | Automatic (15min–12hr TTL) | Revoke role session |

## What's next

Day 32: cost optimization — the architectural decisions that determine your AWS bill, the patterns that reduce cost without reducing reliability, and how to find where the money is actually going.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
