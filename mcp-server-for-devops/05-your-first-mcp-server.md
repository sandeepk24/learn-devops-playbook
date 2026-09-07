# MCP Deep Dive — Part 5 of 10
## Your First MCP Server: A Kubernetes Intelligence Server, End to End

> *Four articles of foundations. Now we build. By the end of this one you'll have a working MCP server that lets an AI inspect a real Kubernetes cluster — pods, events, logs, rollout status — tested with the official inspector and connected to a live client. Read-only by design, because that's how every MCP journey should start.*

---

## What We're Building

A **Kubernetes Intelligence Server**: five read-only tools that turn cluster state into AI-consumable signal.

```
kubectl-intel-server (stdio)
  ├── get_pod_health(namespace, label_selector)      → pod status summary
  ├── get_recent_events(namespace, warnings_only)    → filtered K8s events
  ├── get_pod_logs(namespace, pod, tail_lines)       → shaped log excerpt
  ├── get_deployment_rollout(namespace, deployment)  → rollout health
  └── get_node_pressure()                            → CPU/mem/disk by node
```

Why this as a first server? Because it answers the question every DevOps engineer asks an AI first — *"why is my service unhealthy?"* — and because read-only means the blast radius of every mistake you make while learning is zero.

## Setup

```bash
mkdir kubectl-intel && cd kubectl-intel
python -m venv .venv && source .venv/bin/activate
pip install "mcp[cli]"
```

The modern Python SDK ships `FastMCP` — a decorator-driven API that turns type hints and docstrings into the JSON schemas and descriptions we dissected in Part 4. What you write in Python becomes, automatically, what the model sees.

## The Server

```python
# server.py — Kubernetes Intelligence MCP Server (read-only)
import asyncio
import json
import sys
import logging
from mcp.server.fastmcp import FastMCP

# Part 3 lesson: stdio server => stderr logging. stdout is the wire.
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("kubectl-intel")

mcp = FastMCP("kubectl-intel")


async def run_kubectl(*args: str, timeout: float = 30.0) -> dict:
    """Shared async kubectl runner. Never blocks the event loop (Part 2)."""
    proc = await asyncio.create_subprocess_exec(
        "kubectl", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": "timeout",
                "hint": "kubectl did not respond in 30s. Try get_node_pressure() "
                        "to check whether the API server itself is degraded."}
    if proc.returncode != 0:
        return {"error": "kubectl_failed", "detail": stderr.decode()[:500],
                "is_retryable": True}
    return {"data": stdout.decode()}


@mcp.tool()
async def get_pod_health(namespace: str, label_selector: str = "") -> str:
    """Summarize pod health in a namespace: phase, readiness, restart counts.
    READ-ONLY. Use label_selector (e.g. 'app=payment-api') to narrow scope.
    Call this FIRST when investigating any service issue."""
    args = ["get", "pods", "-n", namespace, "-o", "json"]
    if label_selector:
        args += ["-l", label_selector]
    result = await run_kubectl(*args)
    if "error" in result:
        return json.dumps(result)

    pods, summary = json.loads(result["data"]).get("items", []), []
    for pod in pods:
        statuses = pod["status"].get("containerStatuses", [])
        summary.append({
            "name": pod["metadata"]["name"],
            "phase": pod["status"].get("phase", "Unknown"),
            "ready": all(c.get("ready") for c in statuses) if statuses else False,
            "restarts": sum(c.get("restartCount", 0) for c in statuses),
        })
    # Part 4 lesson: shaped signal, not raw dumps. Surface the anomalies.
    unhealthy = [p for p in summary if not p["ready"] or p["restarts"] > 3]
    return json.dumps({
        "namespace": namespace,
        "total_pods": len(summary),
        "unhealthy_count": len(unhealthy),
        "unhealthy_pods": unhealthy,
        "suggested_next": (
            [f"get_pod_logs('{namespace}', '{unhealthy[0]['name']}')",
             f"get_recent_events('{namespace}')"] if unhealthy
            else ["Pods look healthy — check get_deployment_rollout or metrics."]
        ),
    }, indent=2)


@mcp.tool()
async def get_recent_events(namespace: str, warnings_only: bool = True,
                            limit: int = 20) -> str:
    """Fetch recent Kubernetes events, newest last. warnings_only=True filters
    to Warning-type events (OOMKilled, FailedScheduling, probe failures).
    READ-ONLY."""
    result = await run_kubectl("get", "events", "-n", namespace,
                               "--sort-by=.metadata.creationTimestamp", "-o", "json")
    if "error" in result:
        return json.dumps(result)
    items = json.loads(result["data"]).get("items", [])
    if warnings_only:
        items = [e for e in items if e.get("type") == "Warning"]
    events = [{
        "reason": e.get("reason"),
        "object": e.get("involvedObject", {}).get("name"),
        "message": (e.get("message") or "")[:200],
        "count": e.get("count", 1),
    } for e in items[-limit:]]
    return json.dumps({"namespace": namespace, "warning_events": events}, indent=2)


@mcp.tool()
async def get_pod_logs(namespace: str, pod: str, tail_lines: int = 100,
                       previous: bool = False) -> str:
    """Fetch recent logs from a pod, error lines surfaced first.
    Set previous=True to read logs from the *last crashed* container —
    essential for CrashLoopBackOff investigation. READ-ONLY."""
    args = ["logs", pod, "-n", namespace, f"--tail={min(tail_lines, 500)}"]
    if previous:
        args.append("--previous")
    result = await run_kubectl(*args)
    if "error" in result:
        return json.dumps(result)
    lines = result["data"].splitlines()
    errors = [l for l in lines if any(k in l.upper()
              for k in ("ERROR", "FATAL", "EXCEPTION", "PANIC"))]
    return json.dumps({
        "pod": pod, "lines_fetched": len(lines),
        "error_line_count": len(errors),
        "error_lines": errors[:30],
        "tail_sample": lines[-15:],
    }, indent=2)


@mcp.tool()
async def get_deployment_rollout(namespace: str, deployment: str) -> str:
    """Get rollout health for a deployment: desired vs ready replicas and
    conditions. Use to check whether a deploy is stuck or progressing. READ-ONLY."""
    result = await run_kubectl("get", f"deployment/{deployment}",
                               "-n", namespace, "-o", "json")
    if "error" in result:
        return json.dumps(result)
    d = json.loads(result["data"])
    status = d.get("status", {})
    return json.dumps({
        "deployment": deployment,
        "desired": d.get("spec", {}).get("replicas"),
        "ready": status.get("readyReplicas", 0),
        "updated": status.get("updatedReplicas", 0),
        "conditions": [{"type": c["type"], "status": c["status"],
                        "reason": c.get("reason")}
                       for c in status.get("conditions", [])],
    }, indent=2)


@mcp.tool()
async def get_node_pressure() -> str:
    """Check node conditions cluster-wide: MemoryPressure, DiskPressure,
    PIDPressure, Ready. First stop when *multiple* services degrade at once.
    READ-ONLY."""
    result = await run_kubectl("get", "nodes", "-o", "json")
    if "error" in result:
        return json.dumps(result)
    nodes = []
    for n in json.loads(result["data"]).get("items", []):
        conditions = {c["type"]: c["status"]
                      for c in n["status"].get("conditions", [])}
        nodes.append({"name": n["metadata"]["name"], "conditions": conditions,
                      "healthy": conditions.get("Ready") == "True"})
    return json.dumps({"nodes": nodes,
                       "unhealthy": [n["name"] for n in nodes if not n["healthy"]]},
                      indent=2)


if __name__ == "__main__":
    mcp.run()   # stdio transport by default
```

About 150 lines, and notice how much of the previous four articles is load-bearing in it: async subprocess with timeouts (Part 2), stderr logging (Part 3), descriptions with usage guidance and shaped returns with `suggested_next` (Part 4). Nothing here is decoration.

## Test It: The Inspector First, Always

Before wiring any AI to this, exercise it directly:

```bash
npx @modelcontextprotocol/inspector python server.py
```

The inspector opens a UI showing your five tools with their generated schemas. Call `get_pod_health` with a real namespace and read the output *as if you were the model*: Is it compact? Does it surface anomalies? Does it suggest a next step? If it reads like noise to you, it reads like noise to the AI. Fix it here, not after an agent misbehaves.

## Connect It to a Real Client

For Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "kubectl-intel": {
      "command": "/path/to/kubectl-intel/.venv/bin/python",
      "args": ["/path/to/kubectl-intel/server.py"],
      "env": { "KUBECONFIG": "/home/you/.kube/config" }
    }
  }
}
```

Two hard-won notes: use the **absolute path to the venv's python** (the client won't inherit your shell's activation), and pass `KUBECONFIG` explicitly (the client won't inherit your shell's environment either). Restart the client, then ask:

> *"Something's off with the payment service in the prod namespace. Can you investigate?"*

Watch what happens. The model calls `get_pod_health`, sees a CrashLoopBackOff pod, follows your `suggested_next` breadcrumb into `get_pod_logs` with `previous=True`, finds the OOM kill, checks `get_recent_events` to confirm — and hands you a hypothesis. You watched an investigation you'd normally do half-asleep at 3 AM run itself in seconds, over tools you wrote in an afternoon.

## Exercises Before Part 6

1. Add `get_hpa_status(namespace)` — autoscaler state is gold during load incidents.
2. Add `compare_replica_sets(namespace, deployment)` — old vs new RS during a rollout is a poor man's canary analysis.
3. Break it on purpose: point `KUBECONFIG` at a dead cluster and check that every tool returns your structured timeout error, not a stack trace.

## The Takeaway

Your first server is deliberately boring: read-only, five tools, one transport. That's the point — boring is what you can trust, and trust is what earns the right to add mutations later (with the gates from Part 8). You've also now closed the full loop once: design → implement → inspect → connect → watch it think. Every server after this is that loop with more ambition.

**Next up — Part 6: Going Remote.** stdio works for your laptop. Production means HTTP transports, containerizing the server, and running MCP like the microservice it is.

---

*Following along? Star the repo: [github.com/sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook)*
