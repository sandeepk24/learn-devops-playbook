# OpenTelemetry 101: The Practitioner's Guide to Modern Observability

> **Series**: Observability Engineering | **Part 1 of 4**
> **Stack**: Python 3.12 · OTel SDK 1.44.0 · OTel Collector · AWS CloudWatch · Grafana

---

## The 3 AM Problem

It's 3 AM. Your checkout service is down. You have three dashboards open:

- Metrics in Grafana showing a CPU spike on `api-node-07`
- Logs in Splunk showing a timeout in `payment-service`
- Traces in Jaeger showing something broke in the `order-flow`

Three tools. Three formats. Three vendor SDKs in your codebase. Connecting the dots feels like solving a murder mystery written in three different languages.

This is the problem OpenTelemetry was built to fix.

---

## What OpenTelemetry Actually Is

OpenTelemetry (OTel) is an open-source framework that gives you **one consistent way** to collect, process, and export telemetry data from your applications and infrastructure.

Before OTel, every monitoring vendor had its own agent and SDK. Using Datadog? Install their SDK. Switching to Splunk? Rip it out. Want to send data to two places? Good luck.

OTel's answer: **instrument once, export anywhere.**

```
Without OTel:                        With OTel:
─────────────                        ──────────
App  → Datadog SDK  → Datadog        App → OTel SDK → OTel Collector → Datadog
App  → Splunk SDK   → Splunk                                         → CloudWatch
App  → Jaeger SDK   → Jaeger                                         → Grafana
(3 SDKs, 3 agents, locked in)        (1 SDK, 1 pipeline, swap backends freely)
```

### Quick History

Two earlier projects were splitting the community:
- **OpenTracing** — focused on distributed tracing
- **OpenCensus** — focused on metrics and tracing

In 2019, they merged into OpenTelemetry under the CNCF. As of 2026, nearly **half of all organizations** are using it, with another quarter actively planning adoption. In March 2026, OTel officially deprecated OpenTracing compatibility — the migration is complete, everyone's moved on.

---

## The Four Signal Types

OTel handles three classic observability signals plus a new one added in 2026.

### 1. Traces — The Path a Request Takes

A trace follows a single request as it travels through your distributed system. Every hop — API gateway, order service, payment service, database — is a **span**. Spans are nested, share a `trace_id`, and record timing, status, and context.

```
trace_id: 0xc9ca78304fc969663a1f10d813a3a6eb
│
└── process_checkout (60.49 ms)          ← root span
    ├── validate_cart (10.13 ms)         ← child span
    └── charge_payment (50.16 ms)        ← child span
```

```python
from opentelemetry import trace

tracer = trace.get_tracer("checkout-service")

def process_checkout(user_id: str, items: list, amount: float):
    with tracer.start_as_current_span("process_checkout") as root_span:
        root_span.set_attribute("user.id", user_id)
        root_span.set_attribute("order.total_usd", amount)

        with tracer.start_as_current_span("validate_cart") as span:
            span.set_attribute("cart.item_count", len(items))
            # validation logic here

        with tracer.start_as_current_span("charge_payment") as span:
            span.set_attribute("payment.method", "credit_card")
            span.set_attribute("payment.amount_usd", amount)
            # payment logic here
```

**Why it matters:** When something breaks in a distributed system, traces show you exactly *where* in the chain the failure occurred and *how long* each step took. No more grepping through logs across five services.

---

### 2. Metrics — The Vital Signs

Metrics are numerical measurements over time. Think CPU utilization, request count, error rate, queue depth. OTel supports four metric types:

| Type | Behavior | Example Use |
|---|---|---|
| **Counter** | Only goes up | Total requests served, bytes sent |
| **Gauge** | Up and down | Active connections, memory usage |
| **Histogram** | Distributes values into buckets | Request latency, payload size |
| **UpDownCounter** | Counter that can decrease | Active tasks in a queue |

```python
from opentelemetry import metrics

meter = metrics.get_meter("checkout-service")

# Count every checkout attempt
checkout_counter = meter.create_counter(
    name="checkout.attempts",
    description="Total checkout attempts",
    unit="1"
)

# Track how long checkouts take (bucket distribution)
checkout_duration = meter.create_histogram(
    name="checkout.duration_ms",
    description="Checkout processing time",
    unit="ms"
)

# In your handler
def handle_checkout(request):
    start = time.time()
    result = process_order(request)
    elapsed_ms = (time.time() - start) * 1000

    checkout_counter.add(1, {
        "payment.method": request.payment_method,
        "status": "success" if result.ok else "error"
    })
    checkout_duration.record(elapsed_ms, {
        "payment.method": request.payment_method
    })
```

---

### 3. Logs — The Story in Words

Logs are what you've always written. OTel doesn't replace your logging — it **enriches it** by injecting `trace_id` and `span_id` automatically.

```python
import logging
from opentelemetry import trace

logger = logging.getLogger("checkout-service")

def process_payment(order_id: str, amount: float):
    current_span = trace.get_current_span()
    ctx = current_span.get_span_context()

    # When OTel is configured, trace_id is injected automatically
    # via logging bridge — no manual work needed
    logger.info(
        "Processing payment",
        extra={
            "order_id": order_id,
            "amount": amount,
            # OTel bridge adds: trace_id, span_id, trace_flags
        }
    )
```

**The payoff:** Instead of searching millions of log lines, you jump from a slow trace directly to the exact logs generated during that request — same `trace_id`, instant correlation.

---

### 4. Profiles — The New Signal (March 2026)

Profiles entered public alpha in March 2026. They capture what your code is doing at the CPU and memory level — which functions consume time, where memory is allocated, where threads block.

```
Traces tell you:   validate_cart() took 450ms  ← "that"
Profiles tell you: 390ms was GC pause caused   ← "why"
                   by string concat in a loop
```

This completes the observability picture. Traces show *what* is slow. Profiles show *why*.

---

## Architecture: How It All Fits Together

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            YOUR APPLICATION                             │
│                                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │    Traces    │  │   Metrics    │  │     Logs     │  │  Profiles  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
│         │                 │                  │                │        │
│  ┌──────▼─────────────────▼──────────────────▼────────────────▼──────┐ │
│  │                         OTel SDK                                   │ │
│  │          sampling · batching · resource detection                  │ │
│  └─────────────────────────────┬──────────────────────────────────────┘ │
└────────────────────────────────┼────────────────────────────────────────┘
                                 │ OTLP (gRPC or HTTP)
                    ┌────────────▼──────────────┐
                    │      OTel Collector        │
                    │                            │
                    │  Receivers                 │
                    │      ↓                     │
                    │  Processors                │
                    │  (filter, enrich, sample)  │
                    │      ↓                     │
                    │  Exporters                 │
                    └────┬──────┬──────┬─────────┘
                         │      │      │
              ┌──────────▼┐  ┌──▼────┐ ┌▼───────────────┐
              │  Grafana  │  │Jaeger │ │ AWS CloudWatch  │
              └───────────┘  └───────┘ └────────────────┘
```

### The Four Building Blocks

**OTel API** — the contract. Defines *how* you instrument code. Library authors instrument against the API without forcing any implementation on their users. `tracer.start_as_current_span()` is an API call — it defines the interface, nothing else.

**OTel SDK** — the engine. Implements the API. Handles sampling decisions (which traces to keep), batching (grouping data before export), and resource detection (figuring out it's running in EKS on `us-east-1`).

**Exporters** — the delivery mechanism. Takes SDK output and sends it somewhere. OTLP (native OTel protocol), Prometheus, Jaeger, Zipkin, CloudWatch, Datadog — swap an exporter, change your backend. Zero re-instrumentation.

**The Collector** — the traffic controller. A standalone process between your apps and backends. Apps ship to the Collector via OTLP; the Collector filters, transforms, batches, and fans out to multiple destinations.

### Do/Don't: Collector vs. Direct Export

| | Direct Export from App | Via Collector |
|---|---|---|
| **Retry on backend failure** | App handles it | Collector handles it |
| **Add/change backends** | Code change + redeploy | Config change only |
| **Telemetry processing** | In your app | Externalized |
| **Multi-destination** | Multiple exporters in app | One export from app |
| **Recommended for** | Local dev, prototyping | Production |

For EKS workloads: run the Collector as a **DaemonSet** (one per node) or a **sidecar** per pod. Apps export OTLP to `localhost:4317`, Collector fans it out.

---

## Semantic Conventions — The Underrated Part

Semantic conventions are agreed-upon attribute names that every OTel integration follows.

**Without them:**
```
team-A logs:  http_status = 200
team-B logs:  status_code = 200
team-C logs:  response.status = 200
```

**With semantic conventions:**
```
everyone:  http.response.status_code = 200
```

This is what makes cross-service, cross-team dashboards actually work. Build a dashboard once — it works across every service, regardless of which team wrote it.

**Key conventions stabilized or introduced in 2026:**

| Convention | Status | What It Covers |
|---|---|---|
| `http.*` | Stable | HTTP requests, responses, routes |
| `db.*` | Stable | Database calls, queries, systems |
| `k8s.*` | Stable (2026) | Kubernetes pods, nodes, deployments |
| `gen_ai.*` | New (2026) | LLM calls, tokens, model metadata |
| `aws.*` | Stable | AWS service calls, regions, resources |

---

## Getting Started: Minimum Viable Setup

### Install

```bash
pip install \
  opentelemetry-api \
  opentelemetry-sdk \
  opentelemetry-exporter-otlp-proto-grpc \
  opentelemetry-instrumentation-requests \
  opentelemetry-instrumentation-fastapi
```

As of August 2026, this installs **OTel SDK 1.44.0**.

### Verify Installation

```bash
pip show opentelemetry-sdk
# Name: opentelemetry-sdk
# Version: 1.44.0
```

### Working Demo: Traces + Metrics in Memory

The example below runs without any external backend. It captures real spans and metrics and prints them — useful for understanding what OTel actually produces before wiring up a Collector.

```python
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource
import time

# ── Resource: who is this service? ──────────────────────────────────────
resource = Resource.create({
    "service.name": "checkout-service",
    "service.version": "1.0.0",
    "deployment.environment": "staging"
})

# ── Trace setup ──────────────────────────────────────────────────────────
span_exporter = InMemorySpanExporter()
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
trace.set_tracer_provider(tracer_provider)
tracer = trace.get_tracer("checkout-service")

# ── Metrics setup ────────────────────────────────────────────────────────
metric_reader = InMemoryMetricReader()
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter("checkout-service")

checkout_counter = meter.create_counter("checkout.attempts", unit="1")
checkout_duration = meter.create_histogram("checkout.duration_ms", unit="ms")

# ── Simulate a checkout ──────────────────────────────────────────────────
def validate_cart(items):
    with tracer.start_as_current_span("validate_cart") as span:
        span.set_attribute("cart.item_count", len(items))
        time.sleep(0.01)
        span.set_attribute("cart.valid", True)
        return True

def charge_payment(amount, method):
    with tracer.start_as_current_span("charge_payment") as span:
        span.set_attribute("payment.method", method)
        span.set_attribute("payment.amount_usd", amount)
        time.sleep(0.05)
        return {"status": "approved", "transaction_id": "txn_abc123"}

def process_checkout(user_id, items, amount):
    start = time.time()
    with tracer.start_as_current_span("process_checkout") as root:
        root.set_attribute("user.id", user_id)
        root.set_attribute("order.total_usd", amount)
        validate_cart(items)
        result = charge_payment(amount, "credit_card")
        root.set_attribute("order.status", result["status"])

    elapsed_ms = (time.time() - start) * 1000
    checkout_counter.add(1, {"payment.method": "credit_card", "status": "success"})
    checkout_duration.record(elapsed_ms, {"payment.method": "credit_card"})
    return result

process_checkout("user_42", ["item_A", "item_B", "item_C"], 89.99)

# ── Inspect captured spans ───────────────────────────────────────────────
for span in span_exporter.get_finished_spans():
    ctx = span.context
    parent = hex(span.parent.span_id) if span.parent else "ROOT"
    duration_ms = (span.end_time - span.start_time) / 1_000_000
    print(f"\nSpan: {span.name}")
    print(f"  trace_id  : {hex(ctx.trace_id)}")
    print(f"  span_id   : {hex(ctx.span_id)}")
    print(f"  parent_id : {parent}")
    print(f"  duration  : {duration_ms:.2f} ms")
    for k, v in span.attributes.items():
        print(f"  {k} = {v}")
```

**Output:**

```
Span: validate_cart
  trace_id  : 0xc9ca78304fc969663a1f10d813a3a6eb
  span_id   : 0xce1298a069a3188
  parent_id : 0x82d25d93293991eb      ← child of process_checkout
  duration  : 10.13 ms
  cart.item_count = 3
  cart.valid = True

Span: charge_payment
  trace_id  : 0xc9ca78304fc969663a1f10d813a3a6eb
  span_id   : 0x2d431f4f20f2f851
  parent_id : 0x82d25d93293991eb      ← child of process_checkout
  duration  : 50.16 ms
  payment.method = credit_card
  payment.amount_usd = 89.99

Span: process_checkout
  trace_id  : 0xc9ca78304fc969663a1f10d813a3a6eb
  span_id   : 0x82d25d93293991eb
  parent_id : ROOT
  duration  : 60.49 ms
  user.id = user_42
  order.total_usd = 89.99
  order.status = approved
```

All three spans share the same `trace_id`. The parent/child relationship is encoded in `parent_id`. This is what a trace backend visualizes as the waterfall view.

---

### Wiring to a Real Collector

Replace the `InMemorySpanExporter` with an OTLP exporter pointing at your Collector:

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# BatchSpanProcessor: groups spans before sending — use this in production
# SimpleSpanProcessor: sends every span immediately — use this for debugging only
otlp_exporter = OTLPSpanExporter(endpoint="http://otel-collector:4317")
tracer_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
```

`BatchSpanProcessor` vs `SimpleSpanProcessor`:

| | Batch | Simple |
|---|---|---|
| Groups spans before export | Yes | No |
| Non-blocking | Yes | No |
| Production-safe | Yes | No |
| Good for debugging | No | Yes |

---

## What OTel Is and Isn't

```
OTel IS:                              OTel IS NOT:
────────                              ────────────
✓ Instrumentation standard            ✗ A storage backend (no DB)
✓ Vendor-neutral SDK                  ✗ A visualization tool (no dashboards)
✓ Telemetry pipeline (Collector)      ✗ An alerting system (no paging)
✓ Data format (OTLP)                  ✗ A replacement for Grafana/CloudWatch
✓ Semantic convention spec            ✗ An APM product
```

OTel is the plumbing. It collects and routes the water. Grafana, CloudWatch, and Datadog are the faucets and treatment plants. You need both.

---

## OTel in Your EKS Stack

For a production EKS deployment (like your seven-environment platform), the typical architecture looks like this:

```
┌────────────────────────────────────────────────────────┐
│                    EKS Cluster                          │
│                                                         │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐  │
│  │  Pod (app)  │   │  Pod (app)  │   │  Pod (app)  │  │
│  │  OTel SDK   │   │  OTel SDK   │   │  OTel SDK   │  │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘  │
│         │ OTLP             │ OTLP             │ OTLP    │
│  ┌──────▼──────────────────▼──────────────────▼──────┐  │
│  │          OTel Collector DaemonSet (per node)       │  │
│  └──────────────────────────┬─────────────────────────┘  │
└─────────────────────────────┼──────────────────────────┘
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                  │
     ┌──────▼──────┐  ┌───────▼──────┐  ┌───────▼──────┐
     │  CloudWatch │  │   Grafana    │  │    Jaeger    │
     │  (metrics)  │  │ (dashboards) │  │  (traces)    │
     └─────────────┘  └──────────────┘  └──────────────┘
```

The Collector DaemonSet receives from all pods on a node and batches the export — your pods don't each maintain their own connection to every backend. One Collector config change swaps or adds a destination for the entire cluster.

---

## Key Takeaways

| Concept | The Point |
|---|---|
| **Vendor neutrality** | Instrument once, export to any backend. Change backends without touching app code. |
| **Four signals** | Traces (journey), Metrics (numbers), Logs (words), Profiles (CPU/memory). Together they cover the full picture. |
| **The Collector** | Central pipeline. Decouples your apps from your backends. Required for production. |
| **Semantic conventions** | Agreed attribute names. The thing that makes dashboards work across teams. |
| **OTLP** | OTel's native wire protocol. gRPC or HTTP. What your SDK speaks to the Collector. |
| **BatchSpanProcessor** | Use in production. Groups spans before export. Non-blocking. |

---

## What's Next

- **Part 2**: [OTel Collector Deep Dive — Receivers, Processors, Exporters, and Pipelines](#)
- **Part 3**: [Deploying OTel on EKS — DaemonSet, ADOT, and CloudWatch Integration](#)
- **Part 4**: [Tail-Based Sampling and OTel in Production — Cost Control Without Losing Signal](#)

---

## References

- [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
- [OTel Python SDK](https://opentelemetry-python.readthedocs.io/)
- [Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/)
- [OTel Collector](https://opentelemetry.io/docs/collector/)
- [CNCF OTel Project](https://www.cncf.io/projects/opentelemetry/)

---

*Found this useful? Star [sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) on GitHub — more production-grade DevOps reference articles there.*
