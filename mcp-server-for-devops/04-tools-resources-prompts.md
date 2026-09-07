# MCP Deep Dive — Part 4 of 10
## Tools, Resources, Prompts: The Three Primitives (and Why Tool Design Is Everything)

> *Every MCP server exposes some combination of three primitives. Knowing which to reach for — and how to design them — is the difference between an AI assistant that surgically investigates incidents and one that "helpfully" restarts production. This is the most important design article in the series. Slow down for this one.*

---

## The Mental Model First

Think about how *you* interact with infrastructure:

- Sometimes you **do things**: restart a pod, scale a deployment, file a ticket.
- Sometimes you **read things**: logs, metrics, config files.
- Sometimes you **follow a procedure**: the failover runbook, the incident checklist.

MCP mirrors exactly that:

| Primitive | What it is | Side effects? | DevOps analogy |
|---|---|---|---|
| **Tool** | A function the AI can call | Possibly yes | Running a command |
| **Resource** | URI-addressable data the AI can read | Never | Tailing a log / reading a config |
| **Prompt** | A parameterized workflow template | No (it's instructions) | A runbook |

Most engineers build everything as tools and ignore the other two. That works — but you leave clarity, safety, and reusability on the table. Let's take each in turn.

---

## Primitive 1: Tools — Actions With Consequences

A tool is a function with a name, a description, and a JSON Schema for its inputs. Here's what the *model actually sees* when your server declares one:

```json
{
  "name": "restart_deployment",
  "description": "Perform a rollout restart on a Kubernetes deployment.\nOnly call after confirming the deployment is unhealthy via get_deployment_status.\nREQUIRES human approval for production namespaces.\nDO NOT call this speculatively.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "namespace":  { "type": "string", "enum": ["dev", "staging", "production"] },
      "deployment": { "type": "string" },
      "approval_token": { "type": "string", "description": "Required for production" }
    },
    "required": ["namespace", "deployment"]
  }
}
```

Sit with this fact: **the description field is executable.** The model reads it to decide *when* to call your tool, and reads the schema to decide *how*. Your docstring isn't documentation for humans anymore — it's a behavioral contract for a non-deterministic caller. Bad descriptions produce bad AI behavior as reliably as bad code produces bad output.

### The Golden Rules of Tool Design

**Rule 1 — Never build the God-tool.**

```python
# ❌ The most dangerous MCP tool ever written (and it gets written weekly)
@app.tool()
async def run_kubectl(raw_command: str) -> str:
    """Run any kubectl command."""
    ...
# The AI *will* eventually run: kubectl delete namespace production
```

```python
# ✅ Specific, bounded, read-only by construction
@app.tool()
async def get_deployment_status(namespace: str, deployment: str) -> dict:
    """Get rollout status for a deployment. READ-ONLY — modifies nothing."""
    ...
```

The God-tool feels efficient — one tool, infinite power! But you've just made your security boundary "whatever the model decides today." Constrain the *tool*, not the model's intentions.

**Rule 2 — Read before write, and keep them separate.** Read-only tools can be exposed broadly, called freely, retried blindly. Mutation tools get approval gates (Part 8), rate limits, audit logs. Mixing the two in one function makes both regimes impossible.

**Rule 3 — Enums over free strings.** `namespace: enum["dev","staging","production"]` cannot be typo'd or injected. Every free-form string parameter is a decision you're delegating to the model. Delegate as few as possible.

**Rule 4 — Descriptions state refusal conditions.** Notice the hardened example above says *when not* to call it ("DO NOT call speculatively"). Models respect negative space in descriptions remarkably well — but only if you write it.

**Rule 5 — Return shaped signal, not raw dumps.** This deserves its own section:

### Context Is the Currency

The model's context window is finite and expensive. A tool that returns 10,000 lines of `kubectl get pods -o json` hasn't helped the model — it's buried it.

```python
# ❌ Raw dump — burns context, buries signal
return result.stdout   # 10,000 lines of JSON

# ✅ Pre-processed signal — the AI reasons instantly
return {
    "service": "payment-api",
    "status": "degraded",
    "error_rate_5m": "12.3%",
    "p99_latency_ms": 2340,
    "affected_pods": ["payment-api-abc", "payment-api-xyz"],
    "anomaly_since": "2026-07-10T14:32:00Z",
    "suggested_investigation": [
        "Check payment-api-abc logs",
        "Review deploys to namespace 'payment' in the last hour",
    ],
}
```

Pre-processing isn't cheating; it's exactly what you'd do for any API consumer. The `suggested_investigation` field is a power move worth stealing: you're gently steering the agent's next step using your operational expertise, encoded once, applied on every call.

---

## Primitive 2: Resources — Windows Into Your Systems

Resources are **pure reads**, addressed by URI, guaranteed side-effect-free:

```
pod-logs://production/payment-api-abc123        # streaming logs
metrics://prometheus/http_request_rate/5m       # time-series data
config://helm/payment-api/production/values     # current Helm values
incident://pagerduty/INC-4821/timeline          # incident history

# Subscribable resources — live updates pushed to the client:
alerts://alertmanager/firing
events://kubernetes/production/default
```

"But couldn't I just make a `get_logs` tool?" You could, and often will. The reasons resources exist as a distinct primitive:

1. **The safety contract is structural.** A client knows a resource read can never mutate anything — it can offer them to the model freely, no approval machinery needed. With tools, that guarantee is only as good as your implementation.
2. **URIs compose.** `pod-logs://{namespace}/{pod}` is a template the client can enumerate and the model can construct — a whole family of reads from one declaration.
3. **Subscriptions.** Clients can subscribe to a resource and receive updates over the session — a live alert feed with zero polling. No tool semantics can express that.

The heuristic: **if it's a noun, make it a resource; if it's a verb, make it a tool.** "The payment-api logs" — noun, resource. "Search logs for a pattern" — verb, tool.

---

## Primitive 3: Prompts — Runbooks the AI Can Follow

Prompts are parameterized instruction templates served by your server. They encode *procedure*:

```json
{
  "name": "investigate_latency_spike",
  "description": "Standard SRE procedure for investigating service latency spikes.",
  "arguments": [
    { "name": "service",      "required": true },
    { "name": "start_time",   "required": true },
    { "name": "threshold_ms", "required": false }
  ]
}
```

When invoked, it expands into a structured plan the model follows:

```
1. Check {service} error rate for the last 30 minutes
2. Compare p50/p99 latency against {threshold_ms}ms baseline
3. Identify slowest traces in Jaeger for {service}
4. Check deploys to {service} since {start_time}
5. Correlate with infra events (node pressure, OOM kills)
```

Why this beats a wiki runbook: it lives **next to the tools that execute it**, it's versioned with the server, and it's identical every time. Your best on-call engineer's investigation sequence, encoded once, executed by every agent session thereafter. When people say "capture tribal knowledge," this is what capturing it actually looks like.

---

## Choosing: A Worked Example

You're building an observability server. Here's how the three primitives split a real feature set:

```
RESOURCES (nouns, pure reads):
  metrics://{service}/latency/{window}
  logs://{namespace}/{pod}
  alerts://firing

TOOLS (verbs, computed reads + gated actions):
  search_logs(query, service, last_minutes)        # verb: search
  correlate_signals(service, start, end)           # verb: correlate
  silence_alert(alert_id, duration, reason)        # mutation → gated (Part 8)

PROMPTS (procedures):
  investigate_latency_spike(service, start_time)
  post_incident_review(incident_id)
```

Notice `correlate_signals` — the highest-value tool in the whole set. It joins metrics, logs, and traces into one timestamp-aligned timeline. That's a *computation* over multiple sources, so it's a tool even though it mutates nothing. The noun/verb heuristic bends when real work is involved; that's fine — heuristics serve you, not the reverse.

---

## The Takeaway

Three primitives, three jobs: **tools act, resources inform, prompts guide.** And the deepest lesson of this article isn't the taxonomy — it's that in MCP, *design is the security model and the quality model at once*. A bounded schema prevents disasters; a precise description produces precise behavior; a shaped return value produces sharp reasoning. You don't get good agents by prompting harder. You get them by building better tools.

**Next up — Part 5: Your First MCP Server.** Theory's over. We build a complete, working Kubernetes intelligence server in Python — stdio transport, five well-designed tools, tested with the inspector and wired into a real client.

---

*Following along? Star the repo: [github.com/sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook)*
