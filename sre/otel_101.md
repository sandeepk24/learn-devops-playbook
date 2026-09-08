# OpenTelemetry 101: The Beginner's Guide to Modern Observability


---

## What Problem Are We Actually Solving?

Let me paint you a picture. It's 2 AM. Your phone is screaming. The checkout page is down, customers are angry, and you're staring at three different dashboards — one for metrics, one for logs, one for traces — each from a different vendor, each speaking a different language. You can see *something* is wrong, but connecting the dots between "CPU spike on server X" and "timeout error in the payment service" and "that weird log line from the API gateway" feels like solving a murder mystery with clues written in three different alphabets.

This is the problem OpenTelemetry was born to fix.

## So What Is OpenTelemetry, Really?

OpenTelemetry (often shortened to "OTel") is an open-source framework that gives you one consistent way to collect, process, and export telemetry data — that means your **metrics**, **logs**, and **traces** — from your applications and infrastructure.

Think of it like this: before OpenTelemetry, every monitoring tool had its own way of collecting data. Using Datadog? Install the Datadog agent and use their SDK. Switching to Splunk? Rip all that out and start over. Want to send data to two places? Good luck.

OpenTelemetry said: "What if we all agreed on *one* way to instrument code and collect data, and then you could send that data anywhere you want?"

That's exactly what it does. You instrument once, and export to whatever backend you choose — Grafana, Prometheus, Jaeger, AWS CloudWatch, Datadog, or even your own homegrown system.

### The Origin Story (It Matters)

OpenTelemetry didn't appear out of thin air. Two earlier projects — **OpenTracing** (focused on distributed tracing) and **OpenCensus** (focused on metrics and tracing) — were both trying to solve similar problems but splitting the community. In 2019 at KubeCon, they merged into OpenTelemetry under the Cloud Native Computing Foundation (CNCF). It graduated as a CNCF project and today has over 10,000 contributors from more than 1,200 companies. As of early 2026, nearly half of all organizations are using it, with another quarter planning to adopt it.

In March 2026, OpenTelemetry officially deprecated its OpenTracing compatibility requirements — a clear sign that the migration is complete and everyone's moved on.

## The Three Pillars (Plus a New One)

When people talk about observability, they usually mean three types of telemetry data. OpenTelemetry handles all of them, and recently added a fourth.

### 1. Traces — Following the Breadcrumbs

A trace tells the story of a single request as it travels through your system. Imagine a customer clicks "Buy Now" on your website. That request might hit your API gateway, then your order service, then your payment service, then your inventory service, then your notification service. A trace captures all of that, start to finish.

Each stop along the way is called a **span**. A span records when the work started, when it finished, whether it succeeded, and any relevant details (called **attributes**). Spans are nested — the parent span is the whole request, and child spans are each individual operation.

Here's a quick Python example to make this concrete:

```python
from opentelemetry import trace

tracer = trace.get_tracer("checkout-service")

# This creates a span that tracks the checkout process
with tracer.start_as_current_span("process_checkout") as span:
    span.set_attribute("user.id", "user_12345")
    span.set_attribute("cart.item_count", 3)
    
    # A child span for the payment step
    with tracer.start_as_current_span("charge_payment") as payment_span:
        payment_span.set_attribute("payment.method", "credit_card")
        payment_span.set_attribute("payment.amount", 59.99)
        # ... actual payment logic here
```

Why traces matter: when something goes wrong in a distributed system, traces let you see exactly *where* in the chain the problem occurred and *how long* each step took.

### 2. Metrics — The Vital Signs

Metrics are numerical measurements collected over time. Think of them like the vital signs monitor in a hospital — heart rate, blood pressure, temperature. For your systems, that's things like CPU usage, request count, error rate, response latency, and queue depth.

OpenTelemetry supports several metric types:

- **Counters** — values that only go up (total requests served, total bytes sent)
- **Gauges** — values that go up and down (current memory usage, active connections)
- **Histograms** — distributions of values (request duration broken into buckets)
- **Up-Down Counters** — like counters but they can decrease (active tasks in a queue)

```python
from opentelemetry import metrics

meter = metrics.get_meter("checkout-service")

# Count every checkout attempt
checkout_counter = meter.create_counter(
    name="checkout.attempts",
    description="Number of checkout attempts",
    unit="1"
)

# Track how long checkouts take
checkout_duration = meter.create_histogram(
    name="checkout.duration",
    description="Time taken to process checkout",
    unit="ms"
)

# In your code
checkout_counter.add(1, {"payment.method": "credit_card", "status": "success"})
checkout_duration.record(234.5, {"payment.method": "credit_card"})
```

### 3. Logs — The Story in Words

Logs are timestamped text records of events. They're the oldest form of telemetry — we've been writing `print("something happened")` since the dawn of programming. What OpenTelemetry brings to logs isn't necessarily a new way to write them, but a way to **correlate** them with your traces and metrics.

The magic happens when a log line carries a trace ID. Instead of searching through millions of log lines hoping to find the relevant ones, you can jump straight from a slow trace to the exact logs that were generated during that request.

```python
import logging
from opentelemetry import trace

logger = logging.getLogger("checkout-service")

# When OTel is configured, your logs automatically get trace context
def process_payment(order_id, amount):
    logger.info(f"Processing payment for order {order_id}, amount: ${amount}")
    # The log now carries the trace_id and span_id automatically
    # so you can find it when looking at the trace
```

### 4. Profiles — The New Kid on the Block

In March 2026, OpenTelemetry announced that **Profiles** entered public alpha. Profiles capture what your code is actually doing at the CPU level — which functions are consuming time, where memory is being allocated, where threads are blocking. This is the fourth signal type, joining traces, metrics, and logs to give you the complete picture.

Think of it this way: traces tell you *that* a function was slow, but profiles tell you *why* — maybe it's stuck in a garbage collection loop, or maybe it's doing an expensive string concatenation in a tight loop.

## The Architecture: How It All Fits Together

Here's the mental model you need. OpenTelemetry has four main building blocks:

### APIs — The Contract

The API is a set of interfaces that define *how* you instrument your code. When you write `tracer.start_as_current_span("do_work")`, you're using the API. The API itself doesn't do anything — it's a contract. This means library authors can instrument their code against the API without forcing any specific implementation on their users.

### SDKs — The Engine

The SDK is the actual implementation. It's what takes your API calls and turns them into real telemetry data. The SDK handles things like sampling (deciding which traces to keep), batching (grouping data before sending), and resource detection (figuring out what environment you're running in).

### Exporters — The Delivery Trucks

Exporters take the data the SDK produces and send it somewhere. There are exporters for just about every observability backend you can think of: OTLP (the native OpenTelemetry protocol), Prometheus, Jaeger, Zipkin, AWS CloudWatch, and dozens more. This is where the "vendor neutral" promise comes to life — swap an exporter, and your data goes to a different backend. No re-instrumentation needed.

### The Collector — The Traffic Controller

The OTel Collector is a standalone process that sits between your applications and your backends. Your apps send telemetry to the Collector, and the Collector processes it (filtering, transforming, batching, enriching) and forwards it to one or more destinations.

```
┌─────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│  Your App    │────>│    OTel Collector         │────>│  Grafana     │
│  (with SDK)  │     │                          │────>│  CloudWatch  │
└─────────────┘     │  Receivers → Processors  │────>│  Datadog     │
┌─────────────┐     │  → Exporters             │     └──────────────┘
│  Another App │────>│                          │
└─────────────┘     └──────────────────────────┘
```

Why use a Collector instead of exporting directly from your app? A few reasons: it offloads processing work from your application, it gives you a single place to manage your telemetry pipeline, it lets you retry failed exports without your app knowing, and it makes it trivial to add or change backends.

## Semantic Conventions — Speaking the Same Language

This might be the most underappreciated part of OpenTelemetry. Semantic conventions are agreed-upon names and formats for common telemetry attributes. Instead of one team calling it `http.status` and another calling it `response_code` and a third calling it `http_status_code`, everyone uses `http.response.status_code`.

This matters enormously when you're building dashboards and alerts across dozens of services written by different teams. If everyone follows the conventions, your dashboards just work — no translation layer needed.

In early 2026, the Kubernetes semantic conventions were stabilized, and new GenAI semantic conventions were introduced for standardizing how we monitor LLM-based applications. This shows the project isn't just maintaining existing standards — it's actively keeping up with how the industry builds software.

## Getting Started: Your First Five Minutes

If you want to see this working in Python right now, here's the minimum viable setup:

```bash
pip install opentelemetry-api \
            opentelemetry-sdk \
            opentelemetry-exporter-otlp-proto-grpc \
            opentelemetry-instrumentation-requests \
            opentelemetry-instrumentation-flask
```

```python
# app.py — a Flask app with auto-instrumentation
from flask import Flask
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

# Set up tracing
trace_provider = TracerProvider()
trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(trace_provider)

# Set up metrics
metric_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))

app = Flask(__name__)

# These two lines auto-instrument Flask and the requests library
FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

@app.route("/")
def hello():
    return "Hello, OTel!"
```

That's it. Your Flask app now generates traces for every incoming request and every outgoing HTTP call, without you writing any tracing code manually.

## Where Does OpenTelemetry Fit in Your DevOps World?

As a DevOps architect, here's how to think about OTel's place in your stack:

**OpenTelemetry IS**: a standard for instrumentation and data collection, a vendor-neutral pipeline, an API and SDK, a data collector/processor.

**OpenTelemetry IS NOT**: a storage backend (it doesn't store your data), a visualization tool (it doesn't make dashboards), an alerting system (it doesn't page you at 2 AM). Those are the jobs of your backend — Grafana, CloudWatch, Datadog, or whatever you choose.

Think of OpenTelemetry as the plumbing. It's the pipes that carry your telemetry data. You still need faucets (dashboards) and a water treatment plant (your backend), but the pipes are standardized.

## Key Takeaways

1. **OpenTelemetry gives you vendor freedom.** Instrument once, send data anywhere.
2. **Four signal types** — traces, metrics, logs, and now profiles — cover the full observability picture.
3. **The Collector is your friend.** Use it as a central pipeline for processing and routing telemetry.
4. **Semantic conventions matter.** They're what make cross-service, cross-team observability actually work.
5. **The community is massive.** With 10,000+ contributors and adoption nearing 50% of organizations, this isn't a fad — it's the industry standard.

---

