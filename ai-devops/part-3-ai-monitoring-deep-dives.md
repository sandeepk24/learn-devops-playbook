# Monitoring AI Agents — Part 3: Deep Dives 🔬

> **Part 3 of 3 — Advanced Patterns for Production Scale**
>
> Parts 1 and 2 got your foundation running. This part covers what
> separates a working AI system from a *trustworthy* one: catching
> hallucinations, hard-stopping runaway costs, detecting silent drift,
> and responding to AI incidents.
>
> - **Part 1:** Why AI monitoring is different + what to measure
> - **Part 2:** Traces, metrics, evals, and alerts with real code
> - **Part 3 (this one):** Hallucinations, cost guardrails, drift, RAG, multi-agent, CI/CD, incident response

---

## 📋 What's Covered

1. [Hallucination Detection — Defense in Layers](#1-hallucination-detection)
2. [Cost Guardrails — Hard Limits, Not Hopes](#2-cost-guardrails)
3. [Drift Detection — When Your Agent Quietly Gets Worse](#3-drift-detection)
4. [RAG Pipeline Monitoring](#4-rag-pipeline-monitoring)
5. [Multi-Agent Tracing](#5-multi-agent-tracing)
6. [CI/CD for AI — The Eval Gate](#6-cicd-for-ai)
7. [Incident Response for AI Systems](#7-incident-response)
8. [The AI DevOps Career Roadmap](#8-career-roadmap)
9. [Daily Checklist + SLO Cheat Sheet](#9-cheat-sheet)

---

## 1. Hallucination Detection

You can't catch every hallucination, but you can catch most of them with **layered defense** — cheap checks on everything, expensive checks on the suspicious cases:

```
LAYER 1: STRUCTURAL SIGNALS      free, every request
         Red flag = high confidence + very specific facts + no sources
                          │
                          ▼ (suspicious? escalate)
LAYER 2: LLM-AS-JUDGE            ~$0.001, flagged + 10% sample
         Cheap model checks claims against the source context
                          │
                          ▼ (confirmed? count it)
LAYER 3: METRICS + ALERTS        hallucination_rate > 5% = page
```

### Layer 1: structural signals (free)

The counterintuitive insight: **hedging is healthy**. A model saying "approximately" or "I'm not certain" knows its limits. A model saying "definitely" and "100%" while citing specific dates and numbers *without any sources* is your highest-risk output.

```python
# hallucination_detector.py — Layer 1

import re

HIGH_CONFIDENCE = ["definitely", "certainly", "absolutely", "always",
                   "never", "guaranteed", "100%", "the fact is"]
HEDGING = ["I think", "I believe", "approximately", "roughly",
           "it's possible", "you may want to verify"]

def confidence_risk(response: str) -> int:
    """Positive score = overconfident. Negative = appropriately hedged."""
    text = response.lower()
    confident = sum(1 for p in HIGH_CONFIDENCE if p in text)
    hedged = sum(1 for p in HEDGING if p.lower() in text)
    return confident - hedged

def has_specific_facts(response: str) -> bool:
    """Dates, percentages, big numbers — specific facts without sources = risk."""
    patterns = [
        r"\b(?:19|20)\d{2}\b",            # years
        r"\b\d+(?:\.\d+)?%",              # percentages
        r"\b\d{1,3}(?:,\d{3})+\b",        # large numbers
    ]
    return sum(1 for p in patterns if re.search(p, response)) >= 2

def quick_flag(response: str, has_context: bool) -> bool:
    """The red-flag combo: confident + specific + no grounding."""
    return confidence_risk(response) > 2 and has_specific_facts(response) and not has_context
```

### Layer 2: LLM judge (escalated cases)

```python
import anthropic, json, random

client = anthropic.Anthropic()

async def judge_hallucination(question: str, response: str, context: str | None) -> dict:
    context_block = (f"SOURCE CONTEXT:\n{context}" if context
                     else "NOTE: No sources — judge general plausibility.")

    prompt = f"""You are a hallucination detector.

QUESTION: {question}
{context_block}
AI RESPONSE: {response}

Flag claims that are contradicted by the context, unverifiable specifics,
or stated with false confidence.

Respond ONLY with JSON:
{{"hallucination_detected": <bool>,
  "problematic_claims": [{{"claim": "...", "issue": "..."}}],
  "reliability_score": <1-10>}}"""

    result = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return json.loads(result.content[0].text)


async def evaluate(question, response, context=None) -> dict:
    flagged = quick_flag(response, has_context=context is not None)
    result = {"quick_flag": flagged, "llm_judge": None}

    # Escalate: all flagged cases + a 10% random sample as ground truth
    if flagged or random.random() < 0.10:
        result["llm_judge"] = await judge_hallucination(question, response, context)
        if result["llm_judge"].get("hallucination_detected"):
            hallucination_detected.labels(agent_type="research",
                                          detector="llm_judge").inc()
    return result
```

Feed the counter into the `HallucinationRateHigh` alert from Part 2 and the loop is closed: detect → measure → page.

---

## 2. Cost Guardrails

Alerts tell you money *was* spent. Guardrails stop it from *being* spent. You need both — because a looping agent can burn $500 between an alert firing and a human reading Slack.

**Layered limits, checked BEFORE each LLM call:**

| Level | Limit | Protects Against |
|---|---|---|
| Per request | $0.50 | One agent stuck in a reasoning loop |
| Per user per hour | $2.00 | One abusive or compromised user |
| Per feature per hour | $50 | One buggy feature deploy |
| Global per hour | $200 | Traffic spike / bot swarm |
| Global per day | $2,000 | **Hard stop.** Pages on-call. |

```python
# cost_guardrails.py — Redis-backed distributed limits

from datetime import datetime

class CostGuardrail:
    LIMITS = {
        "per_user_per_hour": 2.00,
        "global_hour": 200.00,
        "global_day": 2000.00,
    }

    def __init__(self, redis_client):
        self.redis = redis_client

    async def check_pre_request(self, user_id: str, estimated_tokens: int = 2000) -> dict:
        """Call this BEFORE the agent runs. Deny if any limit would breach."""
        est_cost = estimated_tokens * 0.000010  # conservative
        now = datetime.now()
        checks = [
            (f"spend:user:{user_id}:hour:{now:%Y%m%dT%H}", "per_user_per_hour"),
            (f"spend:hour:{now:%Y%m%dT%H}",                "global_hour"),
            (f"spend:day:{now:%Y%m%d}",                    "global_day"),
        ]
        for key, limit_name in checks:
            current = float(await self.redis.get(key) or 0)
            if current + est_cost > self.LIMITS[limit_name]:
                if limit_name == "global_day":
                    await self.page_oncall(current)   # hard stop = human wakes up
                return {"allowed": False, "reason": limit_name,
                        "current": current, "limit": self.LIMITS[limit_name]}
        return {"allowed": True}

    async def record(self, user_id: str, cost: float):
        """Call AFTER each LLM call. Increment all windows atomically."""
        now = datetime.now()
        pipe = self.redis.pipeline()
        for key, ttl in [
            (f"spend:user:{user_id}:hour:{now:%Y%m%dT%H}", 3600),
            (f"spend:hour:{now:%Y%m%dT%H}", 3600),
            (f"spend:day:{now:%Y%m%d}", 86400),
        ]:
            pipe.incrbyfloat(key, cost)
            pipe.expire(key, ttl)
        await pipe.execute()
```

**Why Redis and not in-memory counters?** Your agent runs 3+ replicas on EKS. Each pod tracking its own spend means your $200/hour limit is silently a $600/hour limit. Distributed limits need distributed state.

---

## 3. Drift Detection

Three ways your agent gets worse with **zero deploys**:

```
1. MODEL DRIFT    Provider silently updates gpt-4o. Your evals were
                  tuned for the old behavior. Users complain in 2 weeks.

2. DATA DRIFT     RAG knowledge base goes stale. Agent answers
                  confidently from 6-month-old information.

3. DISTRIBUTION   User query patterns shift. Prompts optimized for
   DRIFT          old query types fumble the new ones.
```

The fix is statistical: continuously compare your recent metric distribution against a historical baseline using a **Kolmogorov–Smirnov test** (fancy name, one scipy call — it asks "do these two samples come from the same distribution?").

```python
# drift_detector.py

import numpy as np
from scipy import stats
from collections import deque

class MetricDriftDetector:
    def __init__(self, window_size=1000, baseline_size=5000):
        self.window_size = window_size
        self.metrics = {
            name: deque(maxlen=baseline_size)
            for name in ["quality_score", "response_length", "latency"]
        }

    def add(self, metric: str, value: float):
        self.metrics[metric].append(value)

    def detect(self, metric: str) -> dict:
        values = list(self.metrics[metric])
        if len(values) < self.window_size + 100:
            return {"drift_detected": False, "reason": "insufficient_data"}

        baseline = values[:len(values) // 2]       # older half
        recent = values[-self.window_size:]        # newest window

        ks_stat, p_value = stats.ks_2samp(baseline, recent)
        b_mean, r_mean = np.mean(baseline), np.mean(recent)
        shift_pct = abs(r_mean - b_mean) / (b_mean + 1e-9) * 100

        return {
            "metric": metric,
            # Both conditions: statistically significant AND practically meaningful
            "drift_detected": p_value < 0.05 and shift_pct > 10,
            "baseline_mean": round(b_mean, 3),
            "recent_mean": round(r_mean, 3),
            "shift_pct": round(shift_pct, 1),
            "direction": "degraded" if r_mean < b_mean else "improved",
        }
```

Run it hourly via a scheduled task; alert to Slack when shift > 10%, page when > 20% degraded. When drift fires, your first three questions are always: **did the model version change? did a prompt change? did the data change?** (You're logging all three on every span since Part 2 — this is why.)

---

## 4. RAG Pipeline Monitoring

RAG failures are quality failures at the *retrieval* step, before the LLM ever runs:

```
QUERY → [EMBED] → [VECTOR SEARCH] → [RETRIEVE DOCS] → [GENERATE]
            ↑            ↑                 ↑               ↑
        embedding     search           retrieval          LLM
        quality       latency          relevance          quality
```

The four RAG metrics that matter:

```python
# rag_monitoring.py
from prometheus_client import Histogram, Counter, Gauge

retrieval_latency = Histogram(
    "rag_retrieval_duration_seconds", "Vector store retrieval time",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0]
)
retrieval_score = Histogram(
    "rag_retrieval_relevance_score", "Top-doc similarity to query",
    buckets=[0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
)
retrieval_empty = Counter(
    "rag_empty_retrieval_total", "Retrievals with no results above threshold"
)
index_staleness_days = Gauge(
    "rag_index_staleness_days", "Days since index update", ["index_name"]
)
```

The two alerts worth having:

- **Empty retrieval rate > 20%** → your index is stale, corrupted, or your queries drifted away from your documents. The agent will now answer *without grounding* — hallucination risk spikes.
- **Index staleness > 7 days** → the agent is confidently serving old information. Set this gauge from your ingestion pipeline's last-success timestamp.

**The connection to make:** a rising empty-retrieval rate is often the *leading indicator* of a hallucination-rate spike 30 minutes later. Watch them as a pair.

---

## 5. Multi-Agent Tracing

One orchestrator fanning out to research, analysis, and writer agents is a distributed system — so use the distributed-tracing tool you already know: **W3C trace context propagation** via OpenTelemetry.

```python
# multi_agent_tracing.py
from opentelemetry import trace
from opentelemetry.propagate import inject
import httpx

tracer = trace.get_tracer("multi-agent")

class AgentOrchestrator:
    async def run_pipeline(self, task: str) -> dict:
        with tracer.start_as_current_span("orchestrator-pipeline") as root:
            root.set_attribute("task.description", task[:200])

            headers = {}
            inject(headers)   # adds traceparent — downstream spans join this trace

            research = await self.call_agent("research-agent", {"task": task}, headers)
            analysis = await self.call_agent("analysis-agent",
                                             {"task": task, "research": research}, headers)
            return {"research": research, "analysis": analysis}

    async def call_agent(self, name: str, payload: dict, headers: dict) -> dict:
        with tracer.start_as_current_span(f"call-{name}") as span:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"http://{name}.ai-platform.svc.cluster.local/run",
                    json=payload, headers=headers, timeout=60.0
                )
                resp.raise_for_status()
                result = resp.json()
                # Roll costs UP the trace — total pipeline cost lives on the root
                span.set_attribute("agent.tokens_used", result.get("tokens", 0))
                span.set_attribute("agent.cost_usd", result.get("cost", 0))
                return result
```

Two multi-agent-specific rules:

1. **Cost multiplies.** A 4-agent pipeline is 4x the tokens per user request. Set your Part 2 guardrails at the *pipeline* level, not per agent.
2. **Failures cascade.** If the research agent hallucinates, the writer agent confidently writes fiction. Run evals at the *handoff points* between agents, not just on the final output.

---

## 6. CI/CD for AI — The Eval Gate

The core idea: **no deploy ships if quality regressed** — even if every traditional test passes. You maintain a *golden dataset* (50–100 curated question/expected-answer pairs) and grade every build against it.

```yaml
# .github/workflows/ai-agent-deploy.yml (the parts unique to AI)

jobs:
  eval-gate:                        # ← blocks everything downstream
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deterministic evals
        run: pytest evals/deterministic/ -v

      - name: LLM-judge evals on golden dataset
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python evals/run_golden_set.py \
            --dataset evals/golden_set.jsonl \
            --min-score 7.5

      - name: Block on regression vs baseline
        run: |
          python evals/check_regression.py \
            --current eval-results.json \
            --baseline evals/baseline_scores.json \
            --max-regression-pct 5      # >5% quality drop = build fails

  prompt-review:                    # prompts are code — extra scrutiny
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 2 }
      - name: Flag prompt changes for human review
        run: |
          if git diff HEAD~1 HEAD --name-only | grep -q 'prompts/'; then
            echo "⚠️ Prompt files changed — requires explicit review"
          fi

  deploy-canary:                    # rollout gated on QUALITY, not just 5xx
    needs: [eval-gate]
    steps:
      - name: Deploy 5% canary
        run: |
          kubectl annotate ingress ai-agent-canary \
            nginx.ingress.kubernetes.io/canary-weight="5" --overwrite -n ai-platform
      - name: Watch canary quality for 30 min
        run: |
          python scripts/monitor_canary_evals.py \
            --duration 1800 \
            --min-quality-score 7.0 \
            --max-hallucination-rate 0.03 \
            --rollback-on-breach
```

The difference from your normal canary: the rollback trigger is **quality score and hallucination rate**, not HTTP errors. A canary that serves confident nonsense at 0% error rate must still roll back.

---

## 7. Incident Response

### The AI incident decision tree

```
Alert: AgentTaskFailureRateHigh
     │
     ├─ Hallucination spike?
     │    YES → Check prompt changes + model version in last 24h
     │          Action: roll back prompt / pin model version
     │
     ├─ LLM API erroring?
     │    YES → Check provider status page
     │          Action: flip to fallback provider in the LLM gateway
     │
     ├─ Tools failing?
     │    YES → Check tool service health, expired API keys
     │          Action: disable failing tool, degrade gracefully
     │
     ├─ Cost explosion?
     │    YES → Check for loops, oversized prompts, bot traffic
     │          Action: tighten guardrails, rate limit
     │
     └─ None of the above → escalate to AI platform team
```

### First-response commands

```bash
# ai-incident-runbook.sh

echo "=== HALLUCINATION RATE (30m) ==="
kubectl exec -n monitoring prometheus-0 -- \
  curl -s 'http://localhost:9090/api/v1/query?query=rate(agent_hallucination_total[30m])/rate(agent_task_total[30m])*100' \
  | jq '.data.result[].value[1]'

echo "=== COST THIS HOUR ==="
kubectl exec -n monitoring prometheus-0 -- \
  curl -s 'http://localhost:9090/api/v1/query?query=increase(llm_cost_usd_total[1h])' \
  | jq '.data.result[].value[1]'

echo "=== RECENT AGENT ERRORS ==="
kubectl logs -n ai-platform deployment/agent --since=10m | grep -iE "error|exception|failed"

# EMERGENCY: kill switch (cost explosion or safety incident)
kubectl scale deployment/agent --replicas=0 -n ai-platform

# Switch to fallback model (primary provider down)
kubectl set env deployment/agent \
  LLM_PROVIDER=anthropic LLM_MODEL=claude-3-haiku-20240307 -n ai-platform
```

**The mindset shift:** for AI incidents, "roll back" usually means rolling back a *prompt* or pinning a *model version* — not redeploying a container. The container never changed.

---

## 8. Career Roadmap

Where this skillset takes you:

```
LEVEL 1: Traditional DevOps (you're here)
  K8s/EKS, CI/CD, Prometheus/Grafana, Docker, AWS core services

LEVEL 2: AI Infrastructure (this series gets you here)
  LLM APIs (OpenAI/Anthropic/Bedrock) · vector DBs (pgvector, Weaviate)
  LLM observability (Langfuse) · OTel for AI · cost guardrails
  GPU nodes on EKS

LEVEL 3: AI Platform Engineering
  Eval pipelines + golden datasets · prompt registries · drift detection
  LLM gateway (multi-model routing/fallback) · vLLM/TGI model serving
  Fine-tuning infrastructure

LEVEL 4: Principal AI DevOps
  Org-wide AI observability standards · internal AI platform
  FinOps for AI · AI security (prompt injection defense)
  Compliance (EU AI Act, SOC2 for AI)

SALARY RANGES (US, 2024-2025):
  Level 2: $160K–200K   Level 3: $200K–260K   Level 4: $250K–350K+

LEARN NEXT: vLLM · Langfuse · LangGraph · OpenTelemetry ·
            Argo Workflows · NVIDIA DCGM
```

The gap between Level 1 and Level 2 is smaller than it looks — this three-part series *is* the bridge.

---

## 9. Cheat Sheet

### Daily checklist (5 minutes)

```
MORNING:
□ Grafana AI dashboard — quality score above threshold?
□ Cost spend this hour — within budget?
□ Any overnight hallucination alerts?
□ LLM provider status pages green?
□ RAG index freshness — updated recently?

BEFORE EVERY AI DEPLOY:
□ Eval gate passed (golden set ≥ baseline)?
□ Prompt changes explicitly reviewed?
□ Cost guardrails set for new features?
□ Rollback plan covers QUALITY failure, not just 5xx?

WEEKLY:
□ Quality score trend — drifting?
□ Top failure cases — new patterns?
□ Cost by feature — surprises?
□ Add this week's edge cases to the golden dataset
```

### SLO targets

| Metric | SLO | Alert At |
|---|---|---|
| Task completion rate | > 95% | < 90% |
| Quality score (P50) | > 7/10 | < 6/10 |
| Hallucination rate | < 2% | > 5% |
| P99 agent latency | < 30s | > 60s |
| LLM API error rate | < 1% | > 5% |
| Cost per 1000 requests | < $5 | > $10 |
| RAG retrieval relevance | > 0.75 | < 0.60 |
| Index staleness | < 3 days | > 7 days |

---

## 🏁 Series Wrap-Up

The whole series in three sentences:

1. **AI agents fail with HTTP 200** — so monitor quality and cost, not just availability. *(Part 1)*
2. **Your existing tools carry 80% of the load** — add tokens, cost, and prompt versions to traces; add evals as your new unit tests. *(Part 2)*
3. **Trust comes from layers** — hallucination detection, hard cost stops, drift statistics, and eval-gated deploys turn a working system into one you can bet the business on. *(Part 3)*

---

*Found this useful? This is part of the **Learn DevOps Playbook** series — production-grade references for DevOps engineers. Star the repo and follow along: [github.com/sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook)* ⭐
