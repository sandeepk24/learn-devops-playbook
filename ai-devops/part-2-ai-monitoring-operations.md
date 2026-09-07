# Monitoring AI Agents — Part 2: Operations 🛠️

> **Part 2 of 3 — The Hands-On Build**
>
> Part 1 covered *why* AI monitoring is different. Now we build it:
> traces, metrics, evals, prompt versioning, and alerts — with code you
> can adapt today.
>
> - **Part 1:** Why AI monitoring is different + what to measure
> - **Part 2 (this one):** Traces, metrics, evals, and alerts with real code
> - **Part 3:** Deep dives — hallucinations, cost guardrails, drift, incident response

---

## 📋 What You'll Build

1. [Tracing — See What Your Agent Actually Did](#1-tracing)
2. [Deploy Langfuse on EKS](#2-deploy-langfuse-on-eks)
3. [LLM Metrics in Prometheus](#3-llm-metrics-in-prometheus)
4. [The Grafana Dashboard That Matters](#4-the-grafana-dashboard)
5. [Evals — Unit Tests for AI Behavior](#5-evals)
6. [Prompt Versioning — Your Biggest Blind Spot](#6-prompt-versioning)
7. [Alert Rules — What Pages You at 3AM](#7-alert-rules)

---

## 1. Tracing — See What Your Agent Actually Did

A traditional trace shows you middleware → DB query → response. An AI trace needs to show you the agent's *reasoning*:

```
TRADITIONAL TRACE:                AI AGENT TRACE:
GET /api/orders                   POST /agent/research-task
├── Auth: 2ms                     ├── [Step 1] Plan the task        650ms
├── DB query: 45ms                │     tokens: 2,081 | model: gpt-4o
└── Serialize: 3ms                ├── [Step 2] Tool: web_search   2,100ms
Total: 50ms                       │     input: "AI regulation 2024"
                                  ├── [Step 3] Tool: web_search   1,900ms
                                  └── [Step 4] Write final answer 1,200ms
                                        tokens: 6,126
                                  Total: 5.8s | 8,207 tokens | $0.25
```

Three things you must capture on **every span** that traditional tracing doesn't have:
1. **Token counts** (your new "memory usage")
2. **Cost in USD** (your new billing meter)
3. **Which prompt version and model version** served the request (your new "deploy SHA")

### The instrumented agent (simplified)

```python
# ai_tracing.py — OpenTelemetry + Langfuse instrumentation

from opentelemetry import trace
from langfuse.decorators import observe, langfuse_context
import time

tracer = trace.get_tracer("ai-agent")

@observe(name="agent-run")          # Langfuse: full trace appears in the UI
async def run_agent(user_query: str, session_id: str) -> dict:
    with tracer.start_as_current_span("agent-run") as span:
        # Truncate user input — don't dump PII into your traces
        span.set_attribute("user.query", user_query[:200])
        span.set_attribute("session.id", session_id)

        start = time.time()
        total_tokens = 0

        try:
            plan, tokens = await plan_task(user_query)
            total_tokens += tokens

            tool_results = [await run_tool(tc) for tc in plan.tool_calls]

            response, tokens = await synthesize(user_query, plan, tool_results)
            total_tokens += tokens

            # The three attributes that matter most:
            span.set_attribute("agent.total_tokens", total_tokens)
            span.set_attribute("agent.cost_usd", estimate_cost(total_tokens, "gpt-4o"))
            span.set_attribute("agent.duration_seconds", time.time() - start)

            langfuse_context.score_current_trace(name="task-completed", value=1.0)
            return {"response": response}

        except Exception as e:
            span.record_exception(e)
            langfuse_context.score_current_trace(name="task-completed", value=0.0)
            raise


def estimate_cost(tokens: int, model: str) -> float:
    """Rough cost estimate. Update rates regularly — they change!"""
    rates = {  # USD per token, (input, output)
        "gpt-4o":            (0.000005,   0.000015),
        "claude-3-5-sonnet": (0.000003,   0.000015),
        "claude-3-haiku":    (0.00000025, 0.00000125),
    }
    inp, out = rates.get(model, (0.000005, 0.000015))
    return tokens * 0.7 * inp + tokens * 0.3 * out  # assume 70/30 split
```

**What changed vs. normal instrumentation?** Almost nothing — that's the point. It's the same OpenTelemetry you already use. You're just recording tokens and dollars instead of only milliseconds.

---

## 2. Deploy Langfuse on EKS

Langfuse is just a stateless Node.js app plus PostgreSQL. Treat it like any other workload: Deployment + Service, RDS behind it, secrets from a Secret.

```yaml
# langfuse-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: langfuse
  namespace: ai-platform
spec:
  replicas: 2
  selector:
    matchLabels: { app: langfuse }
  template:
    metadata:
      labels: { app: langfuse }
    spec:
      containers:
        - name: langfuse
          image: langfuse/langfuse:latest
          ports: [{ containerPort: 3000 }]
          env:
            - name: DATABASE_URL          # Point at RDS PostgreSQL in prod
              valueFrom:
                secretKeyRef: { name: langfuse-secrets, key: database-url }
            - name: NEXTAUTH_SECRET
              valueFrom:
                secretKeyRef: { name: langfuse-secrets, key: nextauth-secret }
            - name: NEXTAUTH_URL
              value: "https://langfuse.internal.mycompany.com"
          resources:
            requests: { memory: "512Mi", cpu: "250m" }
            limits:   { memory: "1Gi",   cpu: "1000m" }
          livenessProbe:
            httpGet: { path: /api/public/health, port: 3000 }
            initialDelaySeconds: 30
          readinessProbe:
            httpGet: { path: /api/public/health, port: 3000 }
            initialDelaySeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: langfuse
  namespace: ai-platform
spec:
  selector: { app: langfuse }
  ports: [{ port: 3000, targetPort: 3000 }]
```

Nothing exotic here. If you can run Grafana on EKS, you can run Langfuse.

---

## 3. LLM Metrics in Prometheus

You only need **six metrics** to start. Everything else is refinement:

| Metric | Type | Answers |
|---|---|---|
| `llm_tokens_total` | Counter | How many tokens are we burning? |
| `llm_cost_usd_total` | Counter | What is this costing us? |
| `llm_request_duration_seconds` | Histogram | How slow is the LLM? |
| `agent_task_total{outcome=...}` | Counter | Are tasks succeeding? |
| `agent_quality_score` | Histogram | Are the answers *good*? |
| `agent_tool_calls_total{success=...}` | Counter | Are tools working? |

```python
# metrics.py — the starter six

from prometheus_client import Counter, Histogram
import time

tokens_total = Counter(
    "llm_tokens_total", "Tokens consumed",
    ["model", "type", "feature"]        # type: input|output
)
cost_total = Counter(
    "llm_cost_usd_total", "USD spent on LLM calls",
    ["model", "feature"]
)
llm_duration = Histogram(
    "llm_request_duration_seconds", "LLM response time",
    ["model", "feature"],
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60]   # AI-appropriate buckets — note the 60!
)
task_total = Counter(
    "agent_task_total", "Agent task attempts",
    ["agent_type", "outcome"]            # outcome: success|failure|timeout|loop_detected
)
quality_score = Histogram(
    "agent_quality_score", "LLM-as-judge score 0-10",
    ["agent_type"],
    buckets=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
)
tool_calls = Counter(
    "agent_tool_calls_total", "Tool invocations",
    ["tool_name", "success"]
)


class InstrumentedLLMClient:
    """Wrap your LLM client once — every call gets metrics for free."""

    def __init__(self, client, model: str, feature: str):
        self.client, self.model, self.feature = client, model, feature

    async def complete(self, messages: list, **kwargs):
        start = time.time()
        response = await self.client.chat.completions.create(
            model=self.model, messages=messages, **kwargs
        )
        llm_duration.labels(self.model, self.feature).observe(time.time() - start)

        usage = response.usage
        tokens_total.labels(self.model, "input", self.feature).inc(usage.prompt_tokens)
        tokens_total.labels(self.model, "output", self.feature).inc(usage.completion_tokens)
        cost_total.labels(self.model, self.feature).inc(
            estimate_cost(usage.total_tokens, self.model)
        )
        return response
```

**Gotcha:** default Prometheus histogram buckets top out around 10s. LLM calls routinely take 20–60s. If you keep default buckets, your P99 becomes a lie. Note the explicit `buckets=` above.

---

## 4. The Grafana Dashboard

Four stat panels across the top — your AI system's vital signs:

| Panel | PromQL | Green / Yellow / Red |
|---|---|---|
| **Task success rate** | `sum(rate(agent_task_total{outcome="success"}[1h])) / sum(rate(agent_task_total[1h])) * 100` | >95% / 90–95% / <90% |
| **P99 latency** | `histogram_quantile(0.99, rate(agent_run_duration_seconds_bucket[5m]))` | <15s / 15–30s / >30s |
| **Cost per hour** | `increase(llm_cost_usd_total[1h])` | <$50 / $50–200 / >$200 |
| **Median quality score** | `histogram_quantile(0.5, rate(agent_quality_score_bucket[1h]))` | >7 / 6–7 / <6 |

Below that, add: token usage by model (pie), cost by feature over 24h (bar), TTFT percentiles (timeseries), and tool success rate by tool (table). That's a complete v1 dashboard.

---

## 5. Evals — Unit Tests for AI Behavior

This is the pillar most teams skip, and it's the one that catches the "wrong city" failures from Part 1.

**Three tiers, by cost:**

```
TIER 1: DETERMINISTIC  → free, <1ms  → run on 100% of requests
        Valid JSON? Required fields? Right length? No PII leaked?

TIER 2: LLM-AS-JUDGE   → ~$0.001-0.01 each → run on 10-20% sample
        A cheap model (Haiku, gpt-4o-mini) grades the answer 1-10.
        "Is this faithful to the source docs? Is it safe?"

TIER 3: HUMAN REVIEW   → expensive → gold standard
        Thumbs up/down from users, expert review of samples.
        Use to calibrate whether your Tier 2 judge can be trusted.
```

### Tier 1: deterministic checks (run on everything)

```python
# evals_deterministic.py
import json, re
from dataclasses import dataclass

@dataclass
class EvalResult:
    eval_name: str
    passed: bool
    score: float
    reason: str

def check_json_valid(response: str, required_keys: list) -> EvalResult:
    try:
        data = json.loads(response)
        missing = [k for k in required_keys if k not in data]
        if missing:
            return EvalResult("json_structure", False, 0, f"Missing keys: {missing}")
        return EvalResult("json_structure", True, 10, "OK")
    except json.JSONDecodeError as e:
        return EvalResult("json_structure", False, 0, f"Invalid JSON: {e}")

def check_no_pii(response: str) -> EvalResult:
    patterns = {
        "ssn":   r"\b\d{3}-\d{2}-\d{4}\b",
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "phone": r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    }
    found = [name for name, p in patterns.items() if re.search(p, response)]
    return EvalResult("pii_detection", not found, 0 if found else 10,
                      f"PII found: {found}" if found else "Clean")
```

### Tier 2: LLM-as-judge (run on a sample)

The trick: use a **cheap, fast model** to grade your expensive model's homework.

```python
# evals_judge.py
import anthropic, json

client = anthropic.Anthropic()
JUDGE_MODEL = "claude-haiku-4-5-20251001"   # fast + cheap = good judge

async def judge_faithfulness(question: str, response: str, sources: list[str]) -> EvalResult:
    """RAGAS-style faithfulness: does the answer stick to the sources?"""
    sources_text = "\n\n".join(f"Source {i+1}: {d}" for i, d in enumerate(sources))

    prompt = f"""You are evaluating whether an AI response is faithful to its sources.

QUESTION: {question}

SOURCES:
{sources_text}

AI RESPONSE: {response}

Does the response only contain claims supported by the sources?
Respond ONLY with JSON:
{{"score": <1-10>, "passed": <true if score >= 7>, "reason": "<one sentence>"}}"""

    judged = client.messages.create(
        model=JUDGE_MODEL, max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    try:
        r = json.loads(judged.content[0].text)
        return EvalResult("faithfulness", r["passed"], r["score"], r["reason"])
    except json.JSONDecodeError:
        return EvalResult("faithfulness", False, 0, "Judge returned invalid JSON")
```

### Wire it into production

```python
# eval_pipeline.py
import random

class EvalPipeline:
    def __init__(self, sample_rate: float = 0.15):
        self.sample_rate = sample_rate    # LLM judging 15% of traffic

    async def evaluate(self, question, response, context) -> list[EvalResult]:
        results = [
            check_no_pii(response),                       # always — free
        ]
        if random.random() < self.sample_rate:            # sampled — costs money
            if context.get("source_documents"):
                results.append(await judge_faithfulness(
                    question, response, context["source_documents"]
                ))
        # Push every result to Prometheus (quality_score histogram from §3)
        for r in results:
            if r.score is not None:
                quality_score.labels(agent_type="research").observe(r.score)
        return results
```

**Rule of thumb:** deterministic evals on 100% of traffic, LLM-judge on 10–20%, and a golden dataset of ~50–100 curated test cases run in CI before every deploy (more on that in Part 3).

---

## 6. Prompt Versioning — Your Biggest Blind Spot

Here's a story that has happened at every company running AI in production:

> A PM tweaks the system prompt at 2PM Friday. By 5PM the agent is giving
> wrong answers. **No deploy happened. Nothing is in git. No alert fired.**
> The on-call spends the weekend looking for an infrastructure problem
> that doesn't exist.

**A prompt change is a code change.** Treat it like one:

```python
# prompt_registry.py — every request logs which prompt version served it

import hashlib

class PromptRegistry:
    def __init__(self, langfuse_client):
        self.langfuse = langfuse_client

    def get_prompt(self, name: str, label: str = "production") -> dict:
        prompt = self.langfuse.get_prompt(name=name, label=label)
        return {
            "content": prompt.prompt,
            "version": prompt.version,
            "hash": hashlib.sha256(prompt.prompt.encode()).hexdigest()[:8],
        }

# In your agent — stamp every trace:
p = registry.get_prompt("research-agent-system")
span.set_attribute("prompt.version", p["version"])
span.set_attribute("prompt.hash", p["hash"])
```

Now when quality drops at 5PM Friday, one Langfuse query tells you: *prompt v14 → v15 at 2:03PM*. Incident solved in minutes instead of days.

Same discipline applies to the **model version** — providers update models silently. Log it on every span.

---

## 7. Alert Rules — What Pages You at 3AM

Alert on **quality and cost**, not just errors. The starter set:

```yaml
# prometheus-ai-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ai-agent-alerts
  namespace: monitoring
spec:
  groups:
    - name: ai-agent-quality
      rules:
        # CRITICAL — more than 10% of tasks failing
        - alert: AgentTaskFailureRateHigh
          expr: |
            sum(rate(agent_task_total{outcome!="success"}[10m])) /
            sum(rate(agent_task_total[10m])) > 0.10
          for: 5m
          labels: { severity: critical }
          annotations:
            summary: "Agent failure rate {{ $value | humanizePercentage }}"
            description: "Check: agent logs, LLM API status, tool availability."

        # CRITICAL — spending too fast
        - alert: LLMCostExplosion
          expr: increase(llm_cost_usd_total[1h]) > 200
          for: 5m
          labels: { severity: critical }
          annotations:
            summary: "LLM spend > $200/hour"
            description: "Check for: agent loops, oversized prompts, bot traffic."

        # WARNING — answers getting worse
        - alert: AgentQualityScoreDegraded
          expr: |
            histogram_quantile(0.5, rate(agent_quality_score_bucket[1h])) < 6
          for: 30m
          labels: { severity: warning }
          annotations:
            summary: "Median quality score below 6/10 — check for drift or prompt changes"

        # WARNING — too slow
        - alert: AgentLatencyHigh
          expr: |
            histogram_quantile(0.99, rate(agent_run_duration_seconds_bucket[10m])) > 60
          for: 10m
          labels: { severity: warning }
          annotations:
            summary: "Agent P99 > 60s — check LLM rate limits, tool timeouts, loops"
```

**Notice what's alerting:** failure rate, cost, quality score, latency. Not a single one of these is a 5xx error — which is exactly the point of this whole series.

---

## ✅ Your Part 2 Checklist

- [ ] Agent instrumented with OpenTelemetry (tokens, cost, prompt version on every span)
- [ ] Langfuse running on EKS with RDS PostgreSQL
- [ ] The six starter Prometheus metrics emitting
- [ ] Grafana dashboard with the four vital-sign panels
- [ ] Tier 1 evals on 100% of traffic, Tier 2 judge on ~15%
- [ ] Prompts versioned and stamped onto traces
- [ ] The four starter alerts deployed

---

## 🚀 Next Up

**Part 3: Deep Dives** — hallucination detection layers, hard cost guardrails that stop runaway agents mid-flight, statistical drift detection, RAG and multi-agent monitoring, CI/CD eval gates, and incident response runbooks for AI systems.

---

*Found this useful? This is part of the **Learn DevOps Playbook** series — production-grade references for DevOps engineers. Star the repo and follow along: [github.com/sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook)* ⭐
