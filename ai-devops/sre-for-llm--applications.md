# SRE for LLM Applications
### Notes from an engineer who got paged too many times before writing this down

I want to be upfront about something before you read further: most "LLM in production" content online is written by people who have never actually been on-call for one. It's written by developers who built a demo, maybe a beta, and then handed it off. This is not that.

This is the stuff I wish I'd had when I first got paged at 2am because our AI feature was "broken" — except the logs showed zero errors, the API was returning 200s, and users were getting confidently wrong answers. No alert fired. Nothing looked wrong from the outside. The model had just quietly decided to start making things up.

That moment is when you realize LLMs are a genuinely different animal. Everything you learned about keeping services reliable still applies, but you've also got a whole new category of failure that your existing tooling is completely blind to. This guide is about bridging that gap.

---

## Table of Contents

1. [Why LLMs Break Everything You Know About SRE](#1-why-llms-break-everything-you-know-about-sre)
2. [The LLM Application Stack — Know What You're Running](#2-the-llm-application-stack--know-what-youre-running)
3. [SLIs, SLOs, and SLAs for LLM Services](#3-slis-slos-and-slas-for-llm-services)
4. [Observability — What to Instrument and How](#4-observability--what-to-instrument-and-how)
5. [Performance Engineering for LLM Apps](#5-performance-engineering-for-llm-apps)
6. [Cost Engineering — The Hidden Ops Problem](#6-cost-engineering--the-hidden-ops-problem)
7. [Reliability Patterns for LLM Services](#7-reliability-patterns-for-llm-services)
8. [Incident Response for LLM Outages](#8-incident-response-for-llm-outages)
9. [Capacity Planning and Scaling](#9-capacity-planning-and-scaling)
10. [Security and Compliance in Production](#10-security-and-compliance-in-production)
11. [CI/CD for LLM Applications](#11-cicd-for-llm-applications)
12. [Self-Hosted vs Managed LLM Infrastructure](#12-self-hosted-vs-managed-llm-infrastructure)
13. [Runbooks and Operational Playbooks](#13-runbooks-and-operational-playbooks)
14. [SRE Maturity Model for LLM Teams](#14-sre-maturity-model-for-llm-teams)

---

## 1. Why LLMs Break Everything You Know About SRE

You've run services before. Databases, caches, queues, microservices — you know the drill. Something goes wrong, an alert fires, you look at the logs, you fix it. The mental model is solid: a request either works or it doesn't, and when it doesn't, something in your stack tells you.

LLMs don't respect that model at all.

The first thing that trips people up is latency. You're used to p99s in the hundreds of milliseconds. An LLM generating a detailed response can take 20, 30, sometimes 60 seconds — and that's completely normal. Your existing timeout configs will fire constantly if you don't adjust them. Your dashboards will look like the service is on fire when it's actually working fine.

The second thing is determinism. Send the same request twice to a traditional service and you get the same response. Send it to an LLM and you might get two different answers, both valid, neither "wrong" from the system's perspective. This makes regression testing genuinely hard and makes "is this working correctly" a much more interesting question than you're used to.

But the third thing — the one that really changes how you work — is what I'd call semantic failure. Your HTTP stack doesn't know if the answer the model gave was good. It just knows a response came back. This is the gap that kills LLM reliability in production:

```
Traditional failure:
  Request → Service → Error 500 → Alert fires → Engineer fixes

LLM failure (the one that actually hurts):
  Request → LLM → "Great question! Here's what you need to know..."
                   [model proceeds to confidently invent facts]
  → Zero errors in logs
  → No alert fires
  → HTTP 200, response time looks fine
  → Users get bad information for days or weeks
  → You find out from a customer support ticket
```

The cost dimension is different too. When traffic spikes on a web service, you pay more for compute — but it's roughly predictable and you can set autoscaling policies. When traffic spikes on an LLM application, you pay per token, and a single misbehaving request with a runaway context window can cost dollars instead of fractions of a cent. I've seen a misconfigured agent loop generate a $400 surprise on a single afternoon. You need cost alerting the same way you need error rate alerting.

Then there's the vendor dependency. With most services, you own the whole stack or at least have deep visibility into it. With LLMs, the model is a black box sitting behind someone else's API. When the provider pushes a model update — and they do this silently — your application's behavior can change overnight without a single line of your code changing. Most providers don't announce these changes with enough specificity to catch regressions automatically.

Here's a comparison to anchor the mental model shift:

| Traditional Service | LLM Service |
|---------------------|-------------|
| Response time: 50–500ms | Response time: 1–60+ seconds |
| Output is deterministic | Same input can produce different output |
| Failure is binary (200 or 500) | Failure is a spectrum — hallucination is a silent 200 |
| Scaling is horizontal CPU/memory | Scaling is rate limits and GPU availability |
| Cost is compute + storage | Cost is **per token** — spikes hit your invoice immediately |
| Retry is almost always safe | Retry doubles your cost and often doesn't help |
| You own and control the model | The model lives behind a vendor API you don't control |

None of this means LLMs are unrunnable in production. It means you need to expand your definition of what "reliable" means and build new instrumentation to measure it.

---

## 2. The LLM Application Stack — Know What You're Running

Before you can monitor something properly, you have to understand every layer of it. A lot of SREs get handed an "AI feature" to support without a clear picture of what's actually happening between the user's request and the response they see.

```
┌─────────────────────────────────────────────────────────┐
│                    CLIENT / USER                        │
└─────────────────────────┬───────────────────────────────┘
                          │ HTTP / WebSocket
┌─────────────────────────▼───────────────────────────────┐
│              API GATEWAY / LOAD BALANCER                │
│         (Kong, AWS API Gateway, Nginx)                  │
│   Rate limiting │ Auth │ Request routing                │
└─────────────────────────┬───────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────┐
│              APPLICATION LAYER (Your Code)              │
│   ┌─────────────────────────────────────────────┐       │
│   │           ORCHESTRATION FRAMEWORK           │       │
│   │   LangChain / LlamaIndex / custom Python    │       │
│   │   Prompt templates │ Chain logic │ Agents   │       │
│   └──────────┬───────────────────┬──────────────┘       │
│              │                   │                      │
│   ┌──────────▼──────┐  ┌─────────▼────────────┐        │
│   │  VECTOR STORE   │  │    CACHE LAYER        │        │
│   │ Pinecone/pgvector│  │  Redis / Semantic     │        │
│   │ (RAG retrieval) │  │  cache                │        │
│   └─────────────────┘  └──────────────────────┘        │
└─────────────────────────┬───────────────────────────────┘
                          │ API call (HTTPS)
┌─────────────────────────▼───────────────────────────────┐
│                  LLM PROVIDER LAYER                     │
│   ┌───────────┐  ┌──────────────┐  ┌────────────────┐  │
│   │  OpenAI   │  │  Anthropic   │  │  Self-hosted   │  │
│   │  GPT-4o   │  │  Claude      │  │  Llama / vLLM  │  │
│   └───────────┘  └──────────────┘  └────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

The thing that catches engineers off guard is how much of this stack is yours. The LLM call feels like the whole application, but it's really just one component — and often not the slowest one. Vector store retrieval can take 200ms. Your orchestration logic, if it's doing multiple LLM calls in a chain, can add up fast. Context assembly, reranking, output parsing — all of that is your code, your latency, your responsibility.

Being clear about ownership matters for incident response too:

```
YOU OWN:
├── API Gateway configuration and rate limits
├── Application code and orchestration logic
├── Prompt templates and prompt versioning
├── Vector store / database infrastructure
├── Cache layer
├── Request queuing and retry logic
├── Cost monitoring and budget alerts
└── Everything around the LLM call

VENDOR OWNS (but you must still watch):
├── Model availability and uptime
├── Inference latency
├── Model version changes (often silent)
├── Rate limits and quota enforcement
└── Output quality shifts after model updates
```

When something goes wrong, the first question in your triage should be: is this ours or theirs? Check your provider's status page before spending an hour debugging your own code. But also don't assume it's always the vendor — most incidents I've dealt with were in the application layer, not the model.

---

## 3. SLIs, SLOs, and SLAs for LLM Services

Most LLM teams I've talked to either have no SLOs at all, or they've copied their web service SLOs and applied them wholesale to their LLM endpoints. Neither works.

The no-SLO teams are flying blind — they don't know what "normal" looks like, so they can't tell when things get worse. The copy-paste teams set themselves up for constant SLO breaches because a 500ms latency target on an endpoint that normally takes 10 seconds is going to look like a disaster every day, even when everything is fine.

You need to define what good looks like for an LLM, and it's a different shape than a web service.

### Beyond latency and availability

For a traditional service, availability and latency cover most of your reliability story. For LLMs, you need two more dimensions that most teams skip entirely: **quality** and **cost efficiency**.

Quality is the answer to "is the model giving useful, correct responses?" You can't measure this from HTTP status codes. You need an evaluation layer. Cost efficiency is "how much is each successful response actually costing us?" Without tracking this per endpoint, you won't catch a poorly-optimized prompt quietly burning through your budget.

Here's how I'd define the full set of SLIs for a production LLM service:

```python
# SLI 1: Availability
# Plain old "did we get a non-error response" — still relevant
availability_sli = successful_responses / total_requests

# SLI 2: Time to First Token (TTFT)
# For streaming endpoints, this is what users actually perceive as "fast" or "slow"
# A spinner for 4 seconds before anything appears feels broken to most users
# Target: under 1 second for interactive use cases
ttft_sli = p95_time_to_first_token_ms

# SLI 3: Total Request Latency
# Full end-to-end — important for non-streaming or backend processing
latency_sli = p95_total_latency_seconds

# SLI 4: Generation Speed (Tokens per Second)
# > 30 tokens/sec feels natural, like reading pace
# < 10 tokens/sec feels like the model is struggling
generation_speed_sli = output_tokens / generation_time_seconds

# SLI 5: Hard Error Rate
# Context length exceeded, auth errors, network failures — unambiguous failures
error_rate_sli = error_responses / total_requests

# SLI 6: Quality Score — this one requires building an eval pipeline
# Covered in Section 4, but define it here so it's in your SLO framework
quality_sli = requests_meeting_quality_threshold / evaluated_requests

# SLI 7: Cache Hit Rate
# If you have semantic caching (you should), this is worth tracking
# A sudden drop can spike your costs significantly
cache_hit_sli = cache_hits / total_requests
```

### What realistic SLO targets look like

Don't copy these blindly — your use case matters. A customer-facing chat feature needs tighter TTFT targets than a backend summarization job. But these are reasonable starting points:

```yaml
service: llm-chat-api
slos:
  availability:
    target: 99.5%
    # Honest note: 99.9% is too aggressive for most LLM API-backed services.
    # Provider incidents, rate limiting, and model updates will eat your error budget
    # faster than you expect. Start at 99.5% and tighten once you know your baseline.
    window: 30d

  time_to_first_token:
    p50_target: 400ms
    p95_target: 1500ms    # Most users start feeling impatient around here
    p99_target: 5000ms
    window: 24h

  total_latency:
    p50_target: 3s
    p95_target: 15s       # For complex prompts generating long outputs, this is real
    p99_target: 45s
    window: 24h

  error_rate:
    target: < 1%
    window: 1h

  quality_score:
    target: > 85%         # % of sampled responses scoring above your threshold
    window: 24h
    evaluation_sample_rate: 5%

  cost_per_request:
    target: < $0.02
    window: 24h
    alert_threshold: $0.05   # Alert if average cost spikes 2.5x
```

### Add a new column to your error budget tracking

One thing worth doing that traditional services don't need: separate provider-caused incidents from self-caused ones. When your provider has an outage, that burns your error budget through no fault of your team. Track it separately so your postmortems are honest and so you have data if you ever want to negotiate SLA credits.

---

## 4. Observability — What to Instrument and How

Here's the uncomfortable truth about LLM observability: the standard three pillars (metrics, logs, traces) are necessary but not sufficient. You can have a beautiful Grafana dashboard showing green across all your technical metrics while your model is slowly degrading in quality and nobody notices for days.

There's a fourth pillar that most teams add only after their first quality incident: **evaluations**. Automated sampling and scoring of actual production responses. Without it, you're watching the plumbing and ignoring whether the water is clean.

### Metrics — emit these on every single LLM request

```python
# metrics.py
from prometheus_client import Counter, Histogram, Gauge

# Latency — use wide buckets, LLM responses are slow
llm_request_duration = Histogram(
    'llm_request_duration_seconds',
    'Total end-to-end LLM request duration',
    ['model', 'endpoint', 'status'],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 120]
)

llm_time_to_first_token = Histogram(
    'llm_time_to_first_token_seconds',
    'Time from request to first token received',
    ['model', 'endpoint'],
    buckets=[0.1, 0.25, 0.5, 1, 2, 5, 10]
)

# Token counts — these are your cost meter, treat them that way
llm_tokens_total = Counter(
    'llm_tokens_total',
    'Total tokens consumed',
    ['model', 'type', 'endpoint']   # type: 'input' or 'output'
)

llm_tokens_per_request = Histogram(
    'llm_tokens_per_request',
    'Token distribution per request',
    ['model', 'type'],
    buckets=[50, 100, 200, 500, 1000, 2000, 4000, 8000, 16000, 32000]
)

# Errors — track the type, not just the count
llm_errors_total = Counter(
    'llm_errors_total',
    'Total LLM errors by type',
    ['model', 'error_type']
    # error_type: rate_limit, timeout, context_length, api_error, quality_fail
)

# Quality — fed by your eval pipeline sampling production traffic
llm_quality_score = Histogram(
    'llm_quality_score',
    'Quality evaluation score (0-1)',
    ['model', 'use_case'],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)

llm_cache_hits = Counter(
    'llm_cache_hits_total',
    'Semantic cache hit/miss events',
    ['result']  # result: 'hit' or 'miss'
)

llm_active_requests = Gauge(
    'llm_active_requests',
    'Number of in-flight LLM requests',
    ['model']
)
```

### Structured logging — log what you'll actually need at 2am

The instinct is to log everything. Resist it — you'll end up with gigabytes of noise and still not find what you need during an incident. Log the things that answer: "what happened to request X, how long did it take, what did it cost, and did it succeed?"

One critical rule: **do not log raw prompt and response text in production without PII scrubbing.** Log token counts, not content. Log response length in characters, not the actual response. You'll thank yourself when a GDPR audit arrives.

```python
# logging_middleware.py
import json, time, logging

logger = logging.getLogger(__name__)

class LLMRequestLogger:

    def log_request(self, request_id, model, use_case, prompt_tokens,
                    user_id_hash, session_id):
        # Log token COUNT not prompt content — PII lives in prompts
        logger.info(json.dumps({
            "event": "llm_request_start",
            "request_id": request_id,
            "model": model,
            "use_case": use_case,
            "prompt_tokens": prompt_tokens,
            "user_id_hash": user_id_hash,   # Hash it — never raw user IDs
            "session_id": session_id,
            "timestamp": time.time(),
        }))

    def log_response(self, request_id, model, status, total_latency_ms,
                     ttft_ms, completion_tokens, finish_reason,
                     error_type, estimated_cost_usd, quality_score,
                     response_length_chars):
        logger.info(json.dumps({
            "event": "llm_request_complete",
            "request_id": request_id,
            "model": model,
            "status": status,               # success / error / timeout
            "latency_ms": total_latency_ms,
            "ttft_ms": ttft_ms,
            "completion_tokens": completion_tokens,
            "finish_reason": finish_reason, # stop / length / content_filter
            "error_type": error_type,
            "cost_usd": estimated_cost_usd,
            "quality_score": quality_score,
            "response_length_chars": response_length_chars,
            "timestamp": time.time(),
        }))

    def log_quality_failure(self, request_id, failure_reason, quality_score, evaluator):
        logger.warning(json.dumps({
            "event": "llm_quality_failure",
            "request_id": request_id,
            "failure_reason": failure_reason,  # hallucination / refusal / off_topic
            "quality_score": quality_score,
            "evaluator": evaluator,            # llm_judge / regex / human
            "timestamp": time.time(),
        }))
```

### Distributed tracing for chains

If your application does multi-step processing — retrieve context, rerank, generate, validate — you need traces that show each step individually. Otherwise when something is slow, you have no idea which step is the culprit. Is it the vector store? The LLM itself? The reranker? Without traces you're guessing.

```python
# tracing.py
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
import time

tracer = trace.get_tracer("llm-application")

def traced_rag_pipeline(user_query: str, user_id: str) -> str:
    with tracer.start_as_current_span("rag_pipeline") as pipeline_span:
        pipeline_span.set_attribute("user.id_hash", hash(user_id))
        pipeline_span.set_attribute("query.length", len(user_query))

        # Each step gets its own span — now you can see exactly where time goes
        with tracer.start_as_current_span("vector_retrieval") as retrieval_span:
            start = time.time()
            docs = vector_store.similarity_search(user_query, k=5)
            retrieval_span.set_attribute("retrieval.doc_count", len(docs))
            retrieval_span.set_attribute("retrieval.latency_ms",
                                         (time.time() - start) * 1000)

        with tracer.start_as_current_span("reranking") as rerank_span:
            reranked = reranker.rerank(user_query, docs)
            rerank_span.set_attribute("rerank.input_docs", len(docs))
            rerank_span.set_attribute("rerank.output_docs", len(reranked))

        with tracer.start_as_current_span("llm_generation") as llm_span:
            llm_span.set_attribute("llm.model", "claude-sonnet-4-6")
            llm_span.set_attribute("llm.context_docs", len(reranked))
            try:
                response = llm.generate(user_query, context=reranked)
                llm_span.set_attribute("llm.input_tokens", response.usage.input_tokens)
                llm_span.set_attribute("llm.output_tokens", response.usage.output_tokens)
                llm_span.set_attribute("llm.finish_reason", response.stop_reason)
                llm_span.set_status(Status(StatusCode.OK))
            except Exception as e:
                llm_span.set_status(Status(StatusCode.ERROR, str(e)))
                llm_span.record_exception(e)
                raise

        return response.content
```

### The eval pipeline — the part most teams skip and then regret

This is the one that matters most and gets implemented last. An automated evaluation pipeline samples a percentage of production traffic, scores each response against a quality rubric, and feeds those scores back into your metrics.

I've seen teams run without this for months, turn it on, and immediately discover their model had been degrading for three weeks. Hallucination rate had quietly crept up after a provider model update. Nobody knew because every HTTP request was a 200.

The implementation is simpler than it sounds — you're using a fast, cheap model to judge the outputs of your production model:

```python
# evaluator.py
import anthropic, json

class LLMQualityEvaluator:
    """
    Sample 5-10% of production responses and score them automatically.
    Use a small fast model for evaluation — you want this to be cheap.
    """

    def __init__(self):
        self.client = anthropic.Anthropic()

    def evaluate_response(self, user_query, llm_response, context_docs, use_case):

        judge_prompt = f"""You are evaluating the quality of an AI assistant's response.

User Query: {user_query}

Context Documents Used:
{chr(10).join(f'[{i+1}] {doc}' for i, doc in enumerate(context_docs))}

AI Response: {llm_response}

Evaluate on these dimensions. Return ONLY valid JSON, no preamble:
{{
    "factual_accuracy": <0.0-1.0>,
    "relevance": <0.0-1.0>,
    "hallucination_detected": <true/false>,
    "format_correct": <true/false>,
    "overall_score": <0.0-1.0>,
    "issues": ["list any specific problems"]
}}"""

        response = self.client.messages.create(
            model="claude-haiku-4-5-20251001",  # Cheap model for evaluation
            max_tokens=500,
            messages=[{"role": "user", "content": judge_prompt}]
        )

        try:
            return json.loads(response.content[0].text)
        except json.JSONDecodeError:
            return {"overall_score": 0.5, "issues": ["evaluation_parse_error"]}
```

### What your Grafana dashboard should actually show

A lot of LLM dashboards I've seen are web service dashboards with a few panels bolted on. Here's what I'd build from scratch, organized by how you actually triage an incident:

```
Row 1 — Are we healthy right now?
  [Stat] Availability last 24h          (big, green or red)
  [Stat] Error rate last 1h             (threshold: yellow >0.5%, red >2%)
  [Stat] p95 TTFT last 1h              (threshold: yellow >1s, red >3s)
  [Stat] Quality score last 24h         (threshold: yellow <0.85, red <0.75)
  [Stat] Estimated spend today          (threshold: yellow at 80% of daily budget)

Row 2 — Latency breakdown
  [Graph] TTFT p50/p95/p99 over 24h
  [Graph] Total latency p50/p95/p99
  [Heatmap] Latency distribution

Row 3 — Volume
  [Graph] Requests per minute
  [Graph] Tokens per minute by type (input vs output)
  [Graph] Active concurrent requests

Row 4 — Errors
  [Graph] Error rate broken down by error_type
  [Table] Top error messages in the last hour
  [Graph] Rate limit hits per minute — spikes here explain a lot of incidents

Row 5 — Cost
  [Graph] Estimated cost per hour broken out by model
  [Graph] Token efficiency ratio (output / input)
  [Stat] Projected monthly cost at current burn rate

Row 6 — Quality (the row that matters most and gets ignored most)
  [Graph] Quality score over time — watch for gradual drift, not just spikes
  [Graph] Hallucination detection rate
  [Table] Recent quality failures with request IDs for investigation
```

---

## 5. Performance Engineering for LLM Apps

The performance profile of an LLM application looks nothing like a web service, and that catches engineers off guard when they first start optimizing.

On a typical web service, slow responses mean something in your stack is doing too much work — a slow database query, a memory allocation issue, something you can profile and fix. On an LLM application, most of your latency is spent waiting for the model to generate tokens. You can't make the model faster. What you can do is reduce how often you need to call it, reduce how much work it has to do each time, and make the wait feel shorter through streaming.

Here's where time actually goes in a typical RAG application:

```
Breakdown of a 5-second response:

  Request routing & auth:         ~10ms    (yours)
  Prompt template construction:   ~5ms     (yours)
  Vector store retrieval:         ~50-200ms  ← can be optimized
  Context assembly:               ~10ms    (yours)
  LLM API call (TTFT):            ~300-1500ms  ← hard to control
  Token generation:               ~2-15s   ← hard to control, stream it
  Response parsing & return:      ~10ms    (yours)
```

The vector store retrieval is often the surprise. Teams focus on the LLM call and don't realize their Pinecone or pgvector query is occasionally spiking to 800ms. Get traces in place first so you know where your time actually goes before optimizing.

### Semantic caching — your highest-impact optimization

This one change can cut 30-60% of your LLM calls in many applications. The idea: if a new query is semantically similar enough to one you've already answered, return the cached answer instead of hitting the model again. Not exact-match caching — *semantic* caching that catches paraphrases and variants of the same question.

```python
# semantic_cache.py
import redis
import numpy as np
from sentence_transformers import SentenceTransformer
import json, hashlib

class SemanticCache:
    """
    Cache responses by embedding similarity, not exact string match.
    A 0.95 cosine similarity threshold catches most paraphrases while
    avoiding false positives on genuinely different questions.
    Tune this based on your use case — lower for precise factual queries.
    """

    def __init__(self, similarity_threshold: float = 0.95):
        self.redis = redis.Redis(host='redis', port=6379, decode_responses=True)
        self.encoder = SentenceTransformer('all-MiniLM-L6-v2')
        self.similarity_threshold = similarity_threshold
        self.ttl_seconds = 3600

    def get(self, query: str) -> tuple[str | None, float]:
        query_embedding = self.encoder.encode(query)
        cache_keys = self.redis.keys("cache:embed:*")

        for key in cache_keys:
            cached_data = json.loads(self.redis.get(key))
            cached_embedding = np.array(cached_data['embedding'])

            similarity = np.dot(query_embedding, cached_embedding) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(cached_embedding)
            )

            if similarity >= self.similarity_threshold:
                cache_id = key.split(":")[-1]
                response = self.redis.get(f"cache:response:{cache_id}")
                llm_cache_hits.labels(result='hit').inc()
                return response, float(similarity)

        llm_cache_hits.labels(result='miss').inc()
        return None, 0.0

    def set(self, query: str, response: str) -> None:
        cache_id = hashlib.md5(query.encode()).hexdigest()
        embedding = self.encoder.encode(query).tolist()

        self.redis.setex(
            f"cache:embed:{cache_id}",
            self.ttl_seconds,
            json.dumps({'embedding': embedding, 'query': query[:200]})
        )
        self.redis.setex(f"cache:response:{cache_id}", self.ttl_seconds, response)
```

### Request queuing — don't let traffic spikes hit the API raw

Without a queue, a traffic spike goes directly to your LLM provider. You hit rate limits, requests start failing or timing out, and users get errors. With a queue, requests wait in line instead of failing, and you control the rate at which they hit the provider.

The priority system matters here. You don't want a batch job your data team kicked off at noon to delay your paying users' interactive requests:

```python
# queue_processor.py
import asyncio
from collections import deque
from dataclasses import dataclass, field
import time

@dataclass
class LLMRequest:
    request_id: str
    prompt: str
    priority: int = 1        # 1=normal, 2=high (paid users), 3=critical (internal)
    enqueued_at: float = field(default_factory=time.time)
    future: asyncio.Future = None

class PriorityLLMQueue:

    def __init__(self, max_concurrent: int = 10, max_queue_size: int = 100):
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        self.active_count = 0
        self.queues = {3: deque(), 2: deque(), 1: deque()}

    async def enqueue(self, request: LLMRequest) -> str:
        total_queued = sum(len(q) for q in self.queues.values())

        if total_queued >= self.max_queue_size:
            raise QueueFullError(
                f"Request queue full at {self.max_queue_size}. Try again shortly."
            )

        request.future = asyncio.get_event_loop().create_future()
        self.queues[request.priority].append(request)
        return await request.future

    def get_next(self) -> LLMRequest | None:
        for priority in [3, 2, 1]:
            if self.queues[priority]:
                req = self.queues[priority].popleft()
                # Drop requests that sat too long — better to fail fast
                # than to eventually respond to something the user gave up on
                if time.time() - req.enqueued_at > 60:
                    req.future.set_exception(QueueTimeoutError("Request expired in queue"))
                    return self.get_next()
                return req
        return None
```

### Always stream — it's not optional for interactive features

A user staring at a spinner for 15 seconds will think your service is broken. The same user watching tokens appear one by one after half a second will feel like it's working. Same model, same total latency — completely different perception. Stream everything user-facing.

```python
# streaming_handler.py
import anthropic, asyncio, json, time
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()
client = anthropic.Anthropic()

@app.post("/chat")
async def chat_stream(request: ChatRequest):

    async def token_generator():
        ttft_recorded = False
        start_time = time.time()

        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": request.message}]
        ) as stream:

            for text_chunk in stream.text_stream:
                if not ttft_recorded:
                    ttft_ms = (time.time() - start_time) * 1000
                    llm_time_to_first_token.labels(
                        model="claude-sonnet-4-6", endpoint="/chat"
                    ).observe(ttft_ms / 1000)
                    ttft_recorded = True

                yield f"data: {json.dumps({'token': text_chunk})}\n\n"
                await asyncio.sleep(0)

            message = stream.get_final_message()
            yield f"data: {json.dumps({'done': True, 'usage': message.usage.__dict__})}\n\n"

    return StreamingResponse(
        token_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"   # Critical — without this Nginx buffers the whole response
        }
    )
```

---

## 6. Cost Engineering — The Hidden Ops Problem

I've seen teams treat LLM cost as a finance problem and ignore it operationally. That's a mistake. Cost is an operational signal just as much as latency or error rate. A sudden spike in tokens consumed per request often means something is wrong — a context window growing unbounded, a prompt injection generating huge outputs, an agent loop that's stuck calling the model in circles. If you're not watching costs in near-real-time, you'll find out about these problems on billing day.

### Know what you're paying for

LLM pricing is per token, and output tokens typically cost 3-5x more than input tokens. This matters when you're designing prompts — telling the model to "be concise" isn't just a quality preference, it's a cost optimization. Verbose prompts that encourage long responses cost significantly more.

```python
# cost_calculator.py
# Verify current pricing at your provider's docs — this changes

MODEL_PRICING = {
    "claude-opus-4-6": {
        "input": 15.00 / 1_000_000,
        "output": 75.00 / 1_000_000,
    },
    "claude-sonnet-4-6": {
        "input": 3.00 / 1_000_000,
        "output": 15.00 / 1_000_000,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80 / 1_000_000,
        "output": 4.00 / 1_000_000,
    },
}

def calculate_request_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, MODEL_PRICING["claude-sonnet-4-6"])
    return (input_tokens * pricing["input"]) + (output_tokens * pricing["output"])

def project_monthly_cost(requests_per_day, avg_input_tokens,
                          avg_output_tokens, model) -> float:
    daily = requests_per_day * calculate_request_cost(
        model, avg_input_tokens, avg_output_tokens
    )
    return daily * 30
```

### Alert on cost in real time

These alerts have caught real incidents — a misconfiguration generating huge outputs, a user hammering the API, a batch job running when it shouldn't:

```yaml
# alertmanager-rules.yaml

groups:
  - name: llm_cost_alerts
    rules:
      # Spend rate is 3x above the hourly baseline
      - alert: LLMCostSpike
        expr: |
          rate(llm_tokens_total{type="output"}[1h]) * 15.00 / 1000000 > 50
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "LLM spend spike — output cost exceeding $50/hour"

      # Individual responses are unusually large — could be a loop or injection
      - alert: LLMUnusuallyLargeResponse
        expr: |
          histogram_quantile(0.99, rate(llm_tokens_per_request_bucket{type="output"}[5m])) > 8000
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "p99 output tokens > 8000 — check for runaway generation"

      - alert: LLMDailyBudgetWarning
        expr: |
          sum(increase(llm_tokens_total[24h]) * on(model) group_left()
              llm_token_cost_per_unit) > 500
        labels:
          severity: critical
        annotations:
          summary: "Daily LLM spend approaching budget limit"
```

### Route requests to the right model

The single most impactful cost optimization is also the simplest: don't use your most expensive model for everything. A classification task that needs a yes/no answer costs 20x more than it should if you're routing it through your premium model. Build a router and actually enforce it:

```python
# model_router.py

class IntelligentModelRouter:
    """
    Route by complexity. In practice this cuts costs 60-80% with no
    quality impact on simpler tasks. The key is enforcing this in code
    rather than leaving each feature team to pick their own model.
    """

    def select_model(self, request: LLMRequest) -> str:
        # Extraction, classification, simple lookups — fast and cheap
        if request.use_case in ['classification', 'extraction', 'simple_qa']:
            return "claude-haiku-4-5-20251001"

        # Standard chat, RAG answers, summarization — the right default
        if request.use_case in ['chat', 'summarization', 'rag_qa']:
            return "claude-sonnet-4-6"

        # Complex reasoning, code, multi-step analysis — worth the premium
        if request.use_case in ['code_generation', 'complex_analysis', 'research']:
            return "claude-opus-4-6"

        return "claude-sonnet-4-6"
```

---

## 7. Reliability Patterns for LLM Services

The reliability patterns for LLM services are the same ones you'd use for any external API dependency — circuit breakers, retries, fallbacks. What's different is the tuning. LLMs are slow, expensive to retry, and have quirky failure modes around rate limits and context limits.

### Circuit breaker — fail fast when the provider is struggling

When your LLM provider starts having issues, you don't want to keep hammering it with requests that will time out after 30 seconds each. A circuit breaker detects the failure pattern and starts rejecting requests immediately with a clear error, preserving your users' experience and your queue from piling up.

```python
# circuit_breaker.py
import time
from enum import Enum
from threading import Lock

class CircuitState(Enum):
    CLOSED = "closed"       # Normal — requests go through
    OPEN = "open"           # Tripped — fail fast, don't call the provider
    HALF_OPEN = "half_open" # Recovery — let one request through to test

class LLMCircuitBreaker:

    def __init__(self, failure_threshold=5, timeout_seconds=60, success_threshold=2):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.success_threshold = success_threshold
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = None
        self._lock = Lock()

    def call(self, func, *args, **kwargs):
        with self._lock:
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time > self.timeout_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.success_count = 0
                else:
                    raise CircuitOpenError(
                        "LLM service temporarily unavailable. Retrying automatically."
                    )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except (RateLimitError, APITimeoutError, APIConnectionError):
            self._on_failure()
            raise

    def _on_success(self):
        with self._lock:
            self.failure_count = 0
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self.state = CircuitState.CLOSED

    def _on_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
```

### Fallback chain — degrade gracefully, don't just fail

Rather than having a single point of failure at the LLM call, build a chain of fallbacks. The goal isn't to always give a perfect answer — it's to always give *something* useful and never show users a hard error for something that has a degraded alternative.

```python
# fallback_chain.py

class LLMFallbackChain:
    """
    Primary:   Claude Sonnet  (best quality)
    Fallback1: Claude Haiku   (faster, cheaper — for when Sonnet is rate-limited)
    Fallback2: Stale cache    (yesterday's answer is better than an error)
    Fallback3: Static message (always works, tells user to try again)
    """

    async def generate(self, prompt: str, cache_key: str) -> LLMResponse:

        try:
            return await self._call_with_timeout(
                model="claude-sonnet-4-6", prompt=prompt, timeout=30
            )
        except (RateLimitError, APITimeoutError):
            llm_errors_total.labels(model='sonnet', error_type='primary_fail').inc()

        try:
            return await self._call_with_timeout(
                model="claude-haiku-4-5-20251001", prompt=prompt, timeout=15
            )
        except Exception:
            llm_errors_total.labels(model='haiku', error_type='fallback_fail').inc()

        # A stale cached answer is genuinely better than an error for most use cases
        stale = await self.cache.get_stale(cache_key, max_age_hours=24)
        if stale:
            return LLMResponse(content=stale, source='stale_cache', degraded=True)

        return LLMResponse(
            content="I'm having trouble responding right now. Please try again in a moment.",
            source='static_fallback',
            degraded=True
        )
```

### Retry strategy — trickier than you'd think

With a web service, retry-on-failure is almost always right. With LLMs you have to think about which errors are actually worth retrying. A rate limit error? Worth retrying after a delay. A context length exceeded error? Not worth retrying — the request is fundamentally too large and retrying will just fail again and waste money.

```python
# retry.py
import asyncio, random

async def retry_with_backoff(
    func,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    retryable_exceptions: tuple = (RateLimitError, APITimeoutError)
):
    for attempt in range(max_retries + 1):
        try:
            return await func()

        except retryable_exceptions as e:
            if attempt == max_retries:
                raise

            delay = min(base_delay * (2 ** attempt), max_delay)
            jitter = random.uniform(0, delay * 0.1)  # Prevent thundering herd

            # Honor the provider's Retry-After header if they sent one
            if hasattr(e, 'retry_after') and e.retry_after:
                delay = max(delay, e.retry_after)

            await asyncio.sleep(delay + jitter)

        except (ContextLengthExceededError, ContentFilterError):
            # These are not transient — retrying wastes money and time
            raise
```

---

## 8. Incident Response for LLM Outages

LLM incidents don't always look like traditional outages. Sometimes the "incident" is that quality has been quietly degrading for a week. Sometimes the model came back up fine but your prompts broke against the new version. Here's how I categorize them:

**Full provider outage** — The API is completely unreachable or returning 5xx across the board. This is the most obvious and, in some ways, the easiest to handle. Your circuit breaker trips, your fallback chain activates, you update your status page, and you wait. Check your provider's status page to confirm before spending time debugging your own stack.

**Quality regression** — The API is healthy, latency looks normal, error rate is fine, but your eval pipeline is lighting up with low quality scores. Almost always one of two things: you deployed a prompt change that broke something, or your provider silently updated the model. Either way, roll back to the last known-good state immediately.

**Rate limit exhaustion** — You've hit your quota and requests are being throttled. You'll see a spike in 429 errors and your queue depth growing. Short-term: shed non-critical load, route to a fallback model, queue everything else. Longer-term: talk to your provider about quota increases.

**Cost anomaly** — Spend has spiked 3-5x above baseline. Almost always a bug: a prompt template that's grown too large, an agent stuck in a loop, a user sending extremely long inputs. Find the offending endpoint or user and throttle it immediately. Don't wait to understand the root cause before stopping the bleeding.

### Provider outage runbook

```markdown
## Runbook: LLM Provider Outage

### First 5 minutes

Step 1: Confirm it's actually the provider, not us
  curl -H "x-api-key: $ANTHROPIC_API_KEY" \
    https://api.anthropic.com/v1/messages \
    -d '{"model":"claude-haiku-4-5-20251001","max_tokens":10,
         "messages":[{"role":"user","content":"hi"}]}'

  Also check: status.anthropic.com

Step 2: Is it all models or just one?
  If Sonnet is failing, try Haiku directly.
  If both fail, it's a broader provider incident.

Step 3: Are our fallbacks working?
  Check cache hit rate — should spike if fallbacks are active.
  Check static fallback rate in logs.

### Mitigation

Provider outage (nothing you can do about root cause):
  - Enable aggressive caching: raise TTL to 24h
  - Queue non-critical requests instead of failing them
  - Update status page: "AI features temporarily degraded"
  - Don't burn your on-call engineer debugging your own code

Rate limit exhaustion:
  - Find top token-consuming endpoints:
    SELECT endpoint, sum(tokens) FROM metrics GROUP BY endpoint ORDER BY sum DESC
  - Throttle or queue non-critical traffic
  - Temporarily route to Haiku
  - Contact provider for emergency quota increase

Quality regression:
  - Roll back to previous prompt version immediately
  - Raise eval sample rate to 100%
  - File a report with the provider if behavior is clearly worse

### User communication
"AI-powered features are temporarily degraded. Our team is investigating.
Core app features are unaffected. Updates every 30 minutes at [status page]."

### After the incident
- Provider-caused or self-caused? Track separately.
- Did our fallbacks actually work? Review fallback chain metrics.
- What test would have caught this earlier? Add it to the eval suite.
- Request SLA credits if the provider was at fault.
```

---

## 9. Capacity Planning and Scaling

Planning capacity for LLM applications is genuinely different from planning for web services, and the difference will surprise you if you're not prepared.

When you scale a web service, more instances means more throughput — roughly linear. When you "scale" an LLM application, you're mostly scaling the components *around* the model. The model's throughput is determined by your rate limits with the provider, and those don't automatically increase just because you're getting more traffic.

```python
# capacity_model.py

def calculate_capacity_requirements(
    peak_rps: float,
    avg_input_tokens: int,
    avg_output_tokens: int,
    avg_latency_seconds: float,
    headroom_factor: float = 1.5     # Build in 50% buffer
) -> dict:

    # Little's Law: active requests = arrival rate × average service time
    avg_active_requests = peak_rps * avg_latency_seconds
    required_concurrency = avg_active_requests * headroom_factor

    input_tokens_per_second = peak_rps * avg_input_tokens
    output_tokens_per_second = peak_rps * avg_output_tokens

    hourly_cost = (
        (input_tokens_per_second * 3600 * 3.00 / 1_000_000) +
        (output_tokens_per_second * 3600 * 15.00 / 1_000_000)
    )

    return {
        "required_concurrency": required_concurrency,
        "input_tokens_per_second": input_tokens_per_second,
        "output_tokens_per_second": output_tokens_per_second,
        "peak_cost_per_hour": hourly_cost,
        "monthly_cost_at_sustained_peak": hourly_cost * 24 * 30,
        "recommended_queue_size": int(required_concurrency * 10),
    }
```

One thing to remember when setting up autoscaling: your application pods are mostly idle CPU-wise during LLM calls — they're sitting in an async wait. Don't scale on CPU. Scale on active request count or queue depth:

```yaml
# kubernetes/hpa-llm-app.yaml

apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: llm-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: llm-api
  minReplicas: 2
  maxReplicas: 20
  metrics:
    # CPU will look low even under heavy load — don't use it as the scaling signal
    - type: External
      external:
        metric:
          name: llm_active_requests
        target:
          type: AverageValue
          averageValue: "5"

    - type: External
      external:
        metric:
          name: llm_queue_depth
        target:
          type: Value
          value: "20"
```

---

## 10. Security and Compliance in Production

LLM applications have the usual web security concerns, plus a new category that didn't exist before. The new stuff is weird if you're coming from traditional backend work.

**Prompt injection** is the LLM equivalent of SQL injection. A user crafts their input to override your system prompt or manipulate model behavior. Unlike SQL injection, there's no perfect sanitization — you can't just escape quotes and be safe. Defense is layered: input scanning, instruction hierarchy in your prompts, output validation.

**Indirect prompt injection** is sneakier. The attacker doesn't send malicious instructions directly — they embed them in content your LLM will process. A document someone uploads, a webpage your RAG system retrieves. The LLM then follows the attacker's instructions while processing a legitimate request. Particularly nasty for agent-based systems with tool access.

**Data exfiltration through tools** — if your LLM has database or API access, users might try to extract other users' data through the model. The model has no concept of access control — that's entirely on your application layer to enforce.

```python
# security_layer.py
import re

class LLMSecurityLayer:

    INJECTION_PATTERNS = [
        r"ignore (previous|all|prior|above) instructions",
        r"disregard (previous|all|prior) (instructions|context|prompt)",
        r"(you are|act as|pretend to be) (now|actually|really)",
        r"(reveal|show|print|output) (your|the) (system |)prompt",
        r"DAN mode",
        r"developer mode",
        r"jailbreak",
    ]

    def scan_input(self, user_input: str) -> SecurityScanResult:
        """
        Flag suspicious patterns. Don't necessarily block — log and apply
        extra scrutiny. Over-aggressive blocking creates false positives
        and frustrates legitimate users.
        """
        flags = []

        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, user_input, re.IGNORECASE):
                flags.append(f"injection_pattern: {pattern}")

        if len(user_input) > 10000:
            flags.append(f"excessive_length: {len(user_input)}")

        if self._has_suspicious_unicode(user_input):
            flags.append("suspicious_unicode")

        return SecurityScanResult(
            safe=len(flags) == 0,
            flags=flags,
            risk_level="high" if len(flags) > 2 else "medium" if flags else "low"
        )

    def scan_output(self, llm_output: str, expected_format: str) -> SecurityScanResult:
        flags = []

        if "system prompt" in llm_output.lower():
            flags.append("potential_system_prompt_leak")

        if self._contains_pii(llm_output):
            flags.append("pii_detected_in_output")

        if expected_format == "json":
            try:
                json.loads(llm_output)
            except json.JSONDecodeError:
                flags.append("invalid_json_output")

        return SecurityScanResult(safe=len(flags) == 0, flags=flags)
```

### PII scrubbing before it leaves your infrastructure

Non-negotiable for GDPR, HIPAA, and responsible operation generally. Don't send user PII to external model APIs without a specific agreement and legal basis:

```python
# pii_handler.py
import re

class PIIHandler:

    PII_PATTERNS = {
        'email': r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        'phone': r'\b(\+\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b',
        'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
        'credit_card': r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
        'ip_address': r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
    }

    def scrub(self, text: str) -> tuple[str, dict]:
        """Replace PII with placeholders. Return the mapping so you can
        restore values if needed (e.g., to put them back in the response)."""
        scrubbed = text
        mapping = {}
        counter = {}

        for pii_type, pattern in self.PII_PATTERNS.items():
            counter[pii_type] = 0
            for match in re.finditer(pattern, text):
                placeholder = f"[{pii_type.upper()}_{counter[pii_type]}]"
                mapping[placeholder] = match.group()
                scrubbed = scrubbed.replace(match.group(), placeholder, 1)
                counter[pii_type] += 1

        return scrubbed, mapping
```

---

## 11. CI/CD for LLM Applications

Testing LLM applications sounds straightforward until you sit down to do it and realize you have no idea how to write an assertion for a probabilistic output.

The answer is that you test different things at different levels. Your business logic — prompt formatting, context assembly, output parsing — can be unit tested with mocked LLM responses like any other code. Your integration with the actual model gets tested with real API calls against fixed inputs. And your output quality gets tested through an eval suite that scores responses on a rubric rather than checking for exact strings.

```
The LLM Testing Pyramid:

                    ┌─────────────┐
                    │  EVAL SUITE │  LLM-as-judge on golden dataset
                    │             │  Slow, costs money, high signal
                  ┌─┴─────────────┴─┐
                  │  INTEGRATION    │  Real API calls, fixed inputs
                  │    TESTS        │  Catches regressions and API changes
                ┌─┴─────────────────┴─┐
                │     UNIT TESTS      │  Mock the LLM, test everything around it
                │                     │  Fast and cheap
              ┌─┴─────────────────────┴─┐
              │   STATIC ANALYSIS       │  Prompt linting, token count checks,
              │                         │  security pattern scanning
              └─────────────────────────┘
```

```yaml
# .gitlab-ci.yml

stages:
  - static
  - unit-test
  - integration-test
  - eval
  - build
  - deploy-staging
  - eval-staging
  - deploy-production

prompt-lint:
  stage: static
  script:
    - python scripts/lint_prompts.py    # Check token counts, variable substitution

security-scan-prompts:
  stage: static
  script:
    - python scripts/scan_prompt_injections.py

unit-tests:
  stage: unit-test
  image: python:3.11-slim
  script:
    - pytest tests/unit/ -v --mock-llm  # No real API calls here
  coverage: '/TOTAL.*\s+(\d+%)$/'

integration-tests:
  stage: integration-test
  script:
    - pytest tests/integration/ -v --maxfail=3
  variables:
    ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY_TEST  # Separate key with spend limit
  rules:
    - if: '$CI_COMMIT_BRANCH =~ /^(main|develop)$/'

run-evals:
  stage: eval
  script:
    - python scripts/run_evals.py
        --dataset tests/eval/golden_dataset.json
        --threshold 0.85           # Pipeline fails if quality drops below 85%
        --output eval-results.json
  artifacts:
    paths: [eval-results.json]
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      changes:
        - "prompts/**"             # Only run expensive evals when prompts change
        - "app/chains/**"

build-docker:
  stage: build
  image: docker:24.0
  services: [docker:24.0-dind]
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy-staging:
  stage: deploy-staging
  script: [./scripts/deploy.sh staging $CI_COMMIT_SHORT_SHA]
  environment: {name: staging}

shadow-eval-staging:
  stage: eval-staging
  script:
    - python scripts/shadow_eval.py
        --env staging
        --sample-size 50
        --baseline-env production
        --max-regression 5%        # Fail if staging quality is 5% worse than prod
  needs: [deploy-staging]

deploy-production:
  stage: deploy-production
  script: [./scripts/deploy.sh production $CI_COMMIT_SHORT_SHA]
  environment: {name: production}
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
  when: manual
```

### Treat prompts like code — because they are

Your prompt templates should be in version control, reviewed in merge requests, and tested before deployment. A prompt change can and will break things in production just like a code change.

```
prompts/
├── chat/
│   ├── system_prompt_v1.txt
│   ├── system_prompt_v2.txt       ← Each version kept for rollback
│   └── system_prompt_current.txt  ← Points to current
├── rag/
│   └── rag_system_prompt_v3.txt
└── evaluators/
    └── quality_judge_prompt.txt
```

```python
# prompt_registry.py
class PromptRegistry:
    """
    Version-controlled prompt loading with caching.
    This abstraction means you can roll back a prompt in seconds
    without a full code deployment.
    """

    def __init__(self, prompts_dir: str = "prompts/"):
        self.prompts_dir = prompts_dir
        self._cache = {}

    def get(self, prompt_name: str, version: str = "current") -> str:
        cache_key = f"{prompt_name}:{version}"
        if cache_key not in self._cache:
            with open(f"{self.prompts_dir}/{prompt_name}_{version}.txt") as f:
                self._cache[cache_key] = f.read()
        return self._cache[cache_key]

    def get_ab_variant(self, prompt_name: str, user_id: str) -> tuple[str, str]:
        """A/B test prompts by routing users consistently to the same variant."""
        variant = "b" if hash(user_id) % 2 == 0 else "a"
        return self.get(prompt_name, version=f"v_ab_{variant}"), variant
```

---

## 12. Self-Hosted vs Managed LLM Infrastructure

At some point your team will have this conversation. Usually it's triggered by a compliance requirement, a cost analysis where the API bill is growing faster than the product, or an engineer who read about vLLM and wants to try it.

```
Use managed API when:
  → You're moving fast and don't have dedicated ML infra engineers
  → Traffic is unpredictable or bursty — you can't right-size GPU capacity
  → No hard data residency requirements
  → Your API cost is under roughly $20k/month — GPU infra doesn't break even below this
  → Frontier model capabilities matter to your use case

Self-host (vLLM, Ollama, TGI) when:
  → Data genuinely cannot leave your environment (HIPAA, defense, certain finance)
  → High, sustained, predictable volume and the math works out
  → You need a fine-tuned model
  → You need sub-100ms latency and are willing to manage GPU infra for it
  → You have the team to actually operate it — this is not a weekend project
```

The "the math works out" point is worth dwelling on. A g4dn.xlarge on EC2 (NVIDIA T4 GPU) runs about $0.53/hour, or ~$380/month. That sounds cheap compared to API costs at scale — but you need to factor in on-call burden, the ops time to keep it running, GPU driver updates, model updates, and the opportunity cost of your engineers' time. Most teams that self-host regret it until they genuinely need it.

```yaml
# terraform-ecs-gpu.tf excerpt

resource "aws_ecs_task_definition" "vllm" {
  family                   = "vllm-inference"
  requires_compatibilities = ["EC2"]    # GPU tasks can't run on Fargate
  network_mode             = "bridge"

  container_definitions = jsonencode([{
    name  = "vllm"
    image = "vllm/vllm-openai:latest"
    command = [
      "--model", "meta-llama/Llama-3.1-8B-Instruct",
      "--tensor-parallel-size", "1",
      "--max-model-len", "8192",
      "--gpu-memory-utilization", "0.90",
      "--host", "0.0.0.0",
      "--port", "8000"
    ]
    resourceRequirements = [{ type = "GPU", value = "1" }]
    portMappings = [{ containerPort = 8000, hostPort = 8000 }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group  = "/ecs/vllm"
        awslogs-region = var.aws_region
      }
    }
  }])
}
```

vLLM exposes Prometheus metrics natively. The ones that actually matter:

```yaml
# prometheus-scrape-config.yaml
scrape_configs:
  - job_name: 'vllm'
    static_configs:
      - targets: ['vllm-service:8000']
    metrics_path: /metrics

# vllm:gpu_cache_usage_perc          — KV cache fill level. Alert at > 90%.
#                                      When this fills up, generation slows hard.
# vllm:num_running_seqs              — How many requests are actively generating
# vllm:time_to_first_token_seconds   — Your TTFT histogram
# vllm:time_per_output_token_seconds — Generation speed per token
```

---

## 13. Runbooks and Operational Playbooks

These are the quick-reference decision trees to keep near your terminal when you're on-call. They don't replace investigation — they're the first five minutes before you know what you're dealing with.

```
ALERT: LLMHighErrorRate (error rate > 5%)
├── Check provider status page first — don't debug your code if it's them
├── Is error_type == rate_limit? → Enable queuing, reduce concurrent requests
├── Is error_type == timeout? → Check recent prompt changes for length increases
├── Is error_type == context_length? → Look for runaway context accumulation
└── Is it api_error with a specific message? → Look it up in provider docs

ALERT: LLMHighLatency (p95 > 30s)
├── Is it one endpoint or all? One endpoint = likely a prompt issue
├── Check cache hit rate — a sudden drop means more model calls than usual
├── Is rate limit hit rate also spiking? → Queuing is the cause, not the model
└── Compare to provider status page — if their TTFT is high, you're just waiting

ALERT: LLMCostSpike (spend > 3x baseline)
├── Find the expensive endpoint:
│   SELECT endpoint, sum(output_tokens) FROM metrics GROUP BY endpoint
├── Find expensive sessions — look for unusual request_id patterns
├── Is p99 output token count spiking? → Possible injection generating huge outputs
├── Throttle or block the offending endpoint/user immediately
└── Then investigate root cause — stop the bleeding first

ALERT: LLMQualityDrop (quality score < 80%)
├── Did we ship a prompt change today? → Roll it back, verify quality recovers
├── Did the provider update their model? → Check their changelog
├── Is input data quality degraded? → Check what's feeding your RAG pipeline
└── Raise eval sample rate to 100% so you can see the actual failures
```

---

## 14. SRE Maturity Model for LLM Teams

Honestly, most teams running LLMs in production are somewhere between Level 0 and Level 1 below, which means there's a lot of low-hanging fruit. You don't need to implement everything in this guide at once.

**Level 0 — Flying blind.** No LLM-specific metrics, no cost visibility, incidents discovered when users complain. The work here is basic instrumentation: get token counts, latency, and error rates into your observability stack. That alone will tell you things you didn't know about your service.

**Level 1 — Basic visibility.** You have metrics, basic alerting, and some cost tracking. You know when things break. What's missing: quality measurement, runbooks, fallback handling. The next priority is a runbook for a provider outage (because it will happen) and a circuit breaker.

**Level 2 — Operational confidence.** SLOs are defined and tracked. You have an eval pipeline sampling production traffic. Circuit breakers and fallbacks are in place. Cost alerts fire before the bill arrives. This is where most mature product teams land, and it's genuinely solid.

**Level 3 — Platform thinking.** You're building shared LLM infrastructure that other teams in your org use. Model routing by complexity, A/B testing for prompt changes, semantic caching with a meaningful hit rate, review apps with quality gating in CI. This is less about reliability and more about velocity — enabling your org to ship AI features confidently.

**Level 4 — Proactive reliability.** Chaos engineering for LLM components, automated capacity planning, game days simulating provider outages. If you're here, you're probably writing your own version of this guide.

### A realistic 30-day plan

If you're starting from scratch:

```
Week 1 — Know what's happening
  □ Add structured logging to every LLM call (request ID, token counts, latency, cost)
  □ Set up Prometheus metrics: latency, error rate, tokens consumed
  □ Define 3 SLOs: availability, p95 TTFT, error rate
  □ Start tracking cost — even a manual check of your provider dashboard counts

Week 2 — Stop flying blind
  □ Build the Grafana dashboard (availability, latency, cost, errors at minimum)
  □ Set up 2 alerts: error rate spike and cost spike
  □ Add a circuit breaker around your primary LLM call
  □ Write the provider outage runbook before you need it

Week 3 — Get ahead of quality
  □ Implement caching (exact-match at minimum, semantic if you can)
  □ Add a quality evaluation on 5% of production traffic
  □ Set up a fallback to a cheaper model for graceful degradation
  □ Audit your prompts for token waste

Week 4 — Build operational muscle
  □ Add a quality gate to CI (eval suite that must pass before deploy)
  □ Add request queuing with priority levels
  □ Build a golden dataset of 50-100 representative test cases
  □ Run a 30-minute game day: simulate a provider outage and watch your fallbacks work
```

---

LLMs in production are hard in new ways, not more ways. The fundamentals of SRE — define what good looks like, measure it continuously, fail gracefully, respond quickly — haven't changed. What changes is the vocabulary: tokens instead of CPU, quality scores instead of error codes, model versions instead of dependency versions, rate limits instead of instance capacity.

The teams that run LLMs well aren't the ones with the most sophisticated AI infrastructure. They're the ones that treated reliability as a first-class concern from the start, instrumented the right things early, and wrote runbooks before they needed them. That's achievable in 30 days. Everything after that is refinement.
