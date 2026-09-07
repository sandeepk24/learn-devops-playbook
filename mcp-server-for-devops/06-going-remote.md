# MCP Deep Dive — Part 6 of 10
## Going Remote: Transports, Deployment, and Running MCP Like a Real Service

> *The server from Part 5 runs as a subprocess on your laptop. That's perfect for development — and a dead end for a team. This article is the graduation: from stdio to HTTP, from a script to a container, from "works on my machine" to a shared piece of infrastructure with a URL, TLS, and a health check. In other words: the part of MCP that's actually your day job.*

---

## The Two Worlds of MCP Transport

| Transport | Where it lives | Latency | Security model | Use it for |
|---|---|---|---|---|
| **stdio** | Subprocess on the same machine | Sub-ms | OS process isolation | Local dev tools, personal agents, CLI wrappers |
| **Streamable HTTP** | A network service | Network | TLS + real AuthN/AuthZ | Shared infra servers, multiple agents, production |

stdio's security model is beautifully simple: the server runs *as you*, with *your* kubeconfig, and only a process on your machine can talk to it. The moment a second engineer — or a fleet of agents — needs the same server, you need a network transport.

A note on naming, because the ecosystem's history causes confusion: early MCP used **HTTP+SSE** as its remote transport (one endpoint for requests, a separate Server-Sent Events stream for responses). The spec has since converged on **Streamable HTTP** — a single endpoint that handles plain request/response and can upgrade to streaming when needed. You'll still see SSE in older servers and tutorials; new builds should target Streamable HTTP. The SDK makes this nearly invisible, which brings us to the best part:

## The Same Server, One Line Different

This is the payoff of MCP being transport-agnostic (Part 3). Take the Part 5 server and change *only* the last line:

```python
if __name__ == "__main__":
    # was: mcp.run()                     # stdio — local subprocess
    mcp.run(transport="streamable-http") # HTTP — network service on :8000
```

All five tools, all schemas, all behavior — identical. This enables the hybrid workflow you should adopt as standard practice:

```
DEV:   stdio     → fast iteration, inspector, personal kubeconfig
PROD:  HTTP      → containerized, TLS-terminated, service-account creds
                    same code, different config
```

## Containerizing It

An MCP server is a Python service. Treat it like one:

```dockerfile
FROM python:3.12-slim

# The server shells out to kubectl — bake in a pinned version
ARG KUBECTL_VERSION=v1.30.3
RUN apt-get update && apt-get install -y --no-install-recommends curl \
 && curl -fsSLo /usr/local/bin/kubectl \
    "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" \
 && chmod +x /usr/local/bin/kubectl \
 && apt-get purge -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .

RUN useradd -m mcp
USER mcp

EXPOSE 8000
CMD ["python", "server.py"]
```

And the identity question changes completely. On your laptop, the server used *your* kubeconfig — your permissions, your accountability. In the cluster, it must run as a **dedicated ServiceAccount with exactly the RBAC its tools need**:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: mcp-kubectl-intel-readonly
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "events", "nodes"]
    verbs: ["get", "list"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list"]
```

Read that manifest again, because it's the deepest idea in this article: **your Part 5 tool design just became enforceable at the platform layer.** The tools are read-only *and* the ServiceAccount physically cannot mutate anything. Even if a tool were buggy, even if a prompt injection convinced the model to try something destructive — the API server says no. Defense in depth starts with RBAC, not with prompts. (Part 8 stacks more layers on top.)

Deploy it like anything else — Deployment, Service, resource limits, liveness probe on the health endpoint — and it's a URL your whole platform can use.

## Authentication: The Part stdio Let You Ignore

An HTTP MCP server with no auth is `kubectl` access for anyone who can reach the port. Non-negotiable minimums:

1. **TLS everywhere** — terminate at your ingress/mesh as usual.
2. **Authenticate every request.** The MCP spec's answer for remote servers is **OAuth 2.1 with PKCE** — the server acts as a resource server validating bearer tokens. If you're behind a corporate gateway, letting the gateway enforce OIDC and forwarding identity to the server is a pragmatic, spec-friendly pattern.
3. **Identity must reach the tool layer.** This is the subtle one. It's not enough to know *a* valid client connected — Part 8's authorization gates ("is *this* caller allowed to touch *this* namespace?") need to know **who**. Extract the principal from the token and attach it to the request context now, even if you only log it today. Retrofitting identity plumbing later is miserable.

```python
# Sketch: identity middleware ahead of the MCP endpoint
async def auth_middleware(request, call_next):
    token = (request.headers.get("Authorization") or "").removeprefix("Bearer ")
    claims = await validate_jwt(token)          # signature, expiry, audience
    if not claims:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    request.state.principal = claims["sub"]     # ← flows into tool context
    return await call_next(request)
```

## Operating It: MCP Servers Are Just Services

Once remote, every operational instinct you have applies verbatim:

| Concern | Same answer as any microservice |
|---|---|
| Health checks | Liveness/readiness endpoints; probe them |
| Scaling | Stateless server → HPA works. Keep tools stateless (they should be anyway — the AI calls them in any order, from any replica) |
| Versioning | Bump `serverInfo` version on tool signature changes; clients feature-flag on it (Part 3) |
| Rollouts | Standard Deployment rollout. Sessions reconnect; agents retry (which is why Part 9's idempotency matters) |
| Timeouts | Ingress timeout > your longest tool timeout, or the client sees mystery disconnects |

That statelessness point deserves a beat: the moment you run **two replicas** behind a Service, any in-memory state (caches, "current investigation" objects, naive rate-limit counters) silently breaks — calls land on different pods. Push shared state to Redis or design it away. We build the rate limiter properly in Part 9.

## The Decision Framework

```
Is the server for one engineer's machine?           → stdio. Done.
Do multiple people/agents need it?                  → Streamable HTTP.
Does it hold privileged creds (cloud, cluster)?     → HTTP in a controlled
                                                      environment with a scoped
                                                      ServiceAccount — even for
                                                      one user. Don't scatter
                                                      prod creds across laptops.
```

That last row is a rule I'd underline twice: **credentials centralize better than they distribute.** One audited server with one scoped identity beats twenty laptops with god-mode kubeconfigs.

## The Takeaway

Remote MCP isn't a new discipline — it's your existing discipline pointed at a new kind of service. The transport switch is one line; everything that matters is what surrounds it: containerization, least-privilege ServiceAccounts, token auth with identity plumbed to the tool layer, and stateless design that scales. Your MCP server is now infrastructure. Which means it's now an attack surface, too.

**Next up — Part 7: Advanced Patterns.** Sampling (your server asking the AI for help mid-execution), roots, rich content types, and the hub-and-spoke architecture for federating many servers behind one endpoint.

---

*Following along? Star the repo: [github.com/sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook)*
