# Tool Use and Function-Calling Design
### Part 4 of the [Agentic AI series](./README.md)

> This is the "how do I design a tool well" companion to the [MCP series](../mcp-server-for-devops/01-why-ai-needs-doors.md)'s "how do I build the server that hosts it." Read that series for the protocol mechanics; read this one for the design judgment.

---

## What a "tool" actually is, mechanically

A tool is not code the model runs. The model never executes anything. A tool is a **schema** — a name, a description, and a set of typed parameters — that you hand to the model alongside the conversation. When the model decides a tool is the right next step, it doesn't run it; it outputs a structured request ("call `get_pod_status` with `namespace=production, pod_name=checkout-api-7f9`"). Your code — the agent runtime — is the thing that actually receives that request, executes the real function, and hands the result back into the conversation.

```
Model: "I'll call get_pod_status(namespace='production', pod_name='checkout-api-7f9')"
              │
              ▼
Your code: receives the request, validates it, actually runs the function
              │
              ▼
Your code: returns the result back into the conversation
              │
              ▼
Model: reasons about the result, decides the next step
```

This matters because it means **every safety property you want has to be enforced in your code, not requested of the model.** The model choosing to call a tool is a suggestion your runtime is free to reject, rate-limit, sandbox, or require approval for. Treat the model's tool-call request the same way you'd treat a request from an untrusted client hitting your API — validate it, don't just trust that it's well-formed or safe because it came from a capable model.

---

## Anatomy of a well-designed tool

```python
from pydantic import BaseModel, Field

class GetPodStatusInput(BaseModel):
    """Arguments for the get_pod_status tool."""
    namespace: str = Field(..., description="Kubernetes namespace, e.g. 'production'")
    pod_name: str = Field(..., min_length=1, max_length=253, description="Exact pod name")

def get_pod_status(input: GetPodStatusInput) -> dict:
    """
    Returns the current status of a single named pod.

    Read-only. Does not modify cluster state. Safe to call repeatedly.
    """
    # ... actual kubectl / API call here, with a timeout ...
    return {"pod": input.pod_name, "phase": "Running", "restarts": 2}
```

The tool description you hand to the model is doing more work than it looks like — it's the only thing the model has to decide *whether* and *when* to call this tool over another one. A vague description ("gets info about pods") invites the model to reach for it at the wrong moment or misunderstand what it returns. A specific one ("returns the current status of a single named pod; read-only, safe to call repeatedly") gives the model exactly the signal it needs to use it correctly — the same discipline you'd apply to naming and documenting a public API endpoint, because functionally, that's what this is.

### Design principles, in order of how often people skip them

**1. Narrow scope, one clear job.** A tool called `manage_deployment` that can create, scale, delete, and roll back based on a `action` string parameter is doing four things behind one door — and now the model has to get the `action` argument exactly right, with no schema-level guardrail stopping it from passing `"delete"` when it meant `"describe"`. Four separate, narrowly-scoped tools (`get_deployment`, `scale_deployment`, `delete_deployment`, `rollback_deployment`) let you apply different guardrails per action (read-only tools need no approval; `delete_deployment` might always require one) and let the model's tool *choice itself* — not a string argument buried inside one big tool — be the signal you audit and gate.

**2. Strict, typed parameters — not a free-text blob.** Passing `command: str` and letting the model write `"scale checkout-api to 5"` as a raw string means you're now parsing natural language inside your tool executor, with all the ambiguity that implies. Passing `service_name: str, replicas: int = Field(ge=1, le=50)` means bad input gets rejected at the schema boundary, before your code ever runs — this is the exact same reasoning behind everything in the [Pydantic guide](../python/python_pydantic_devops_guide.md), just applied to tool inputs instead of API request bodies.

**3. Idempotency wherever the operation allows it.** An agent loop can call a tool more than once for the same logical step — a retry after a timeout, a model reconsidering and calling it again "to be sure." A `scale_deployment(service, replicas=5)` call is safe to run five times in a row; a `create_deployment` without a check for "does this already exist" is not. This is the exact same discipline covered in [idempotent scripting](../linux/idempotent-scripting-automation.md) — an agent's tool calls need it even more than a cron job does, because you don't fully control how many times the model decides to call something.

**4. Fail loud, with structured errors — not a stack trace.** If a tool call fails, the model needs *usable* information to decide what to do next: retry, try a different tool, or give up and tell the user. A raw exception dumped into the conversation wastes tokens and gives the model nothing actionable. A structured error does:

```python
# Bad — a raw exception message, unhelpful to the model
"Traceback (most recent call last): ... ConnectionResetError: [Errno 104] ..."

# Good — structured, tells the model what happened and what it can do
{
    "error": "timeout",
    "message": "Could not reach the Kubernetes API within 5 seconds.",
    "retryable": True,
}
```

**5. Timeouts, always.** Same reasoning as file 06 of the Python roadmap's `requests` section — a tool call that can hang forever can hang your whole agent loop forever. Every tool implementation should have its own timeout, independent of whatever timeout the agent framework applies at the loop level.

**6. Least privilege, scoped per tool.** A tool's credentials should be scoped to exactly what that tool needs — a `get_pod_status` tool needs read access to one namespace, not cluster-admin. This is IAM least-privilege thinking applied one layer up, and it's the single most effective mitigation against the security failure modes covered in [file 05](./05-agentic-ai-security-threat-model.md): if a tool physically can't do something destructive, no amount of clever prompting — yours or an attacker's — can make it happen through that tool.

---

## Side by side: the same tool, designed badly and well

```python
# Badly designed
def infra_action(action: str, target: str, params: str = ""):
    """Do something to infrastructure."""
    if action == "restart":
        subprocess.run(f"kubectl rollout restart deployment/{target}", shell=True)
    elif action == "scale":
        replicas = params  # unvalidated, comes straight from the model
        subprocess.run(f"kubectl scale deployment/{target} --replicas={replicas}", shell=True)
    elif action == "delete":
        subprocess.run(f"kubectl delete deployment/{target}", shell=True)
    # ... more actions, more ambiguity, no per-action guardrails possible

# Well designed
class ScaleDeploymentInput(BaseModel):
    deployment_name: str = Field(..., pattern=r'^[a-z0-9-]+$', max_length=63)
    namespace: str = Field(default="default")
    replicas: int = Field(..., ge=0, le=50)

def scale_deployment(input: ScaleDeploymentInput) -> dict:
    """
    Scales a Kubernetes deployment to the given replica count.
    Idempotent. Read the current replica count first with get_deployment
    if you need to know the value before changing it.
    """
    subprocess.run(
        ["kubectl", "scale", f"deployment/{input.deployment_name}",
         "-n", input.namespace, f"--replicas={input.replicas}"],
        check=True, timeout=15,
    )
    return {"deployment": input.deployment_name, "replicas": input.replicas, "status": "scaled"}
```

The first version has one door with four rooms behind it and a `shell=True` command-injection risk baked in via unvalidated string interpolation. The second has one door, one room, a locked schema at the threshold, and no shell string ever gets built from model-supplied text.

---

## Managing tool result size

A tool that returns 500 lines of raw pod logs back into the conversation eats a large chunk of your context budget on one step, for information the model probably doesn't need in full. Summarize, paginate, or filter before returning:

```python
def get_pod_logs(input: GetPodLogsInput) -> dict:
    raw_logs = fetch_logs(input.pod_name, tail_lines=1000)
    error_lines = [line for line in raw_logs.splitlines() if "ERROR" in line]
    return {
        "total_lines_fetched": len(raw_logs.splitlines()),
        "error_line_count": len(error_lines),
        "error_lines": error_lines[:20],   # cap it — don't dump everything
        "note": "showing first 20 error lines; call again with a filter for more",
    }
```

This is the same instinct behind paginating an API response instead of returning your entire table in one call — it exists here for the same reason, plus a second one specific to agents: every token in a tool result is a token you're paying for and a token that competes for space with everything else the agent needs to remember.

---

## Cheatsheet

```
A tool = a schema (name, description, typed parameters), not code the model runs.
Your runtime executes it and can reject, rate-limit, or gate any call.

Design checklist for every tool:
  [ ] One narrow job — not a multi-action dispatcher
  [ ] Strict typed parameters (Pydantic), not free-text
  [ ] Idempotent wherever the operation allows it
  [ ] Structured, actionable errors — not raw stack traces
  [ ] A timeout, independent of the agent loop's own timeout
  [ ] Least-privilege credentials scoped to exactly this tool
  [ ] Result size capped/summarized — don't dump raw dumps into context
```

---

**Next:** [`05-agentic-ai-security-threat-model.md`](./05-agentic-ai-security-threat-model.md) — what happens when the tools are well designed but someone still finds a way to misuse them.
