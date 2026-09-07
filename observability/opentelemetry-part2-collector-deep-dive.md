# OpenTelemetry Collector Deep Dive: Receivers, Processors, Exporters, and Pipelines

> **Series**: Observability Engineering | **Part 2 of 4**
> **Stack**: OTel Collector 0.105+ · ADOT · AWS CloudWatch · Prometheus · Grafana
> **Prereq**: [Part 1 — OTel 101](./opentelemetry-101-modern-observability.md)

---

## The Problem the Collector Solves

In Part 1, your Python app exported spans directly to a backend using an `OTLPSpanExporter`. That works fine on your laptop. In production, it creates three problems:

**Problem 1 — Tight coupling.** Your app knows where telemetry goes. Change the backend, redeploy every service.

**Problem 2 — No buffer.** Backend goes down for 60 seconds? Your app drops spans. There's nowhere to queue.

**Problem 3 — No processing.** Want to drop health-check traces? Redact a PII field? Add a `cluster.name` attribute to every span? You're writing that logic in every service, in every language.

The Collector solves all three. It sits between your apps and your backends. Apps send OTLP to `localhost:4317`, the Collector does the rest.

```
WITHOUT Collector:                    WITH Collector:
──────────────────                    ──────────────
service-A → CloudWatch                service-A ─┐
service-B → CloudWatch                service-B ─┤→ Collector → CloudWatch
service-C → CloudWatch                service-C ─┘          └→ Grafana
(3 services, 3 backend configs)       (3 services, 1 config to change)
```

---

## Collector Architecture in 90 Seconds

The Collector is a single binary with three internal stages chained into **pipelines**:

```
┌─────────────────────────────────────────────────────────────┐
│                      OTel Collector                          │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐   │
│  │  Receivers   │──▶│  Processors  │──▶│   Exporters   │   │
│  │              │   │              │   │               │   │
│  │ OTLP         │   │ batch        │   │ OTLP          │   │
│  │ Prometheus   │   │ filter       │   │ CloudWatch    │   │
│  │ Jaeger       │   │ resource     │   │ Prometheus    │   │
│  │ StatsD       │   │ transform    │   │ Jaeger        │   │
│  │ filelog      │   │ tail_sample  │   │ debug         │   │
│  └──────────────┘   └──────────────┘   └───────────────┘   │
│                                                             │
│  Extensions: health_check · pprof · zpages · memory_ballast │
└─────────────────────────────────────────────────────────────┘
```

A **pipeline** declares which receiver feeds which processors in which order, and which exporters receive the result. You can run multiple pipelines — one for traces, one for metrics, one for logs — with different components in each.

---

## The Config File Structure

Everything is driven by a single YAML config. The top-level keys map exactly to the architecture above:

```yaml
# collector-config.yaml

receivers:    # where data comes IN
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:   # what you DO to data in flight
  batch: {}
  memory_limiter:
    limit_mib: 512

exporters:    # where data goes OUT
  debug:
    verbosity: detailed

extensions:   # supporting capabilities (health checks, etc.)
  health_check:
    endpoint: 0.0.0.0:13133

service:
  extensions: [health_check]
  pipelines:
    traces:         # one pipeline per signal type
      receivers:  [otlp]
      processors: [memory_limiter, batch]
      exporters:  [debug]
    metrics:
      receivers:  [otlp]
      processors: [memory_limiter, batch]
      exporters:  [debug]
    logs:
      receivers:  [otlp]
      processors: [memory_limiter, batch]
      exporters:  [debug]
```

Two rules that catch people off guard:

1. **Processor order matters.** `memory_limiter` must come first — before `batch`. If you batch first, a memory spike has already happened before the limiter can act.
2. **A component defined but not wired into `service.pipelines` does nothing.** You'll see no error. Data just won't flow through it.

---

## Receivers — Where Data Enters

### OTLP Receiver (the one you'll use most)

Accepts telemetry from any OTel SDK over gRPC or HTTP.

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
        # optional TLS
        # tls:
        #   cert_file: /certs/server.crt
        #   key_file:  /certs/server.key
      http:
        endpoint: 0.0.0.0:4318
        cors:
          allowed_origins: ["https://your-ui.example.com"]
```

**gRPC vs HTTP/OTLP:** gRPC is the default for server-to-server (Python SDK → Collector). HTTP is useful for browser clients and Windows .NET Framework apps that don't support gRPC cleanly.

### Prometheus Receiver (scraping existing metrics endpoints)

Useful when you have services exposing `/metrics` that you can't re-instrument — legacy apps, third-party exporters, RabbitMQ, Redis, etc.

```yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: 'api-gateway'
          scrape_interval: 30s
          static_configs:
            - targets: ['api-gateway:9090']
          metric_relabel_configs:
            # drop metrics you don't need to control cost
            - source_labels: [__name__]
              regex: 'go_gc_.*'
              action: drop
```

### Filelog Receiver (reading log files)

For services that write to files or stdout rather than emitting OTLP logs.

```yaml
receivers:
  filelog:
    include:
      - /var/log/app/*.log
    start_at: beginning
    operators:
      - type: json_parser        # parse JSON log lines
        timestamp:
          parse_from: attributes.timestamp
          layout: '%Y-%m-%dT%H:%M:%S.%fZ'
      - type: move
        from: attributes.level
        to: severity_text
```

### Do/Don't: Receiver Configuration

| | Do | Don't |
|---|---|---|
| **Endpoint binding** | Bind to `0.0.0.0` in containers | Bind to `localhost` — nothing can reach it |
| **Prometheus scraping** | Use `metric_relabel_configs` to drop unused metrics | Scrape everything and filter later at the exporter |
| **gRPC vs HTTP** | Default to gRPC for SDK-to-Collector | Use HTTP only when gRPC isn't supported |

---

## Processors — Shaping Data in Flight

This is where the real power lives. Processors run in the order declared in the pipeline.

### `memory_limiter` — Always First

Prevents the Collector from OOMing under traffic spikes. Configured with a hard limit and a spike limit.

```yaml
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 512        # hard limit — starts dropping when exceeded
    spike_limit_mib: 128  # headroom for bursts above steady state
```

When memory exceeds `limit_mib`, the Collector starts refusing new data and returns backpressure to senders. Set this lower than your container's memory limit — leave room for the Go runtime itself (at least 20%).

### `batch` — Always Second

Groups spans/metrics/logs before exporting. Without it, every span triggers a separate export call — expensive on the network and on your backend.

```yaml
processors:
  batch:
    send_batch_size: 1024     # export when this many items accumulate
    timeout: 5s               # or when this much time passes, whichever first
    send_batch_max_size: 2048 # hard cap — prevents oversized payloads
```

### `resource` — Enriching Telemetry with Context

Add, update, or delete resource attributes. Critical for tagging all telemetry with environment, cluster, and region when your apps don't set them.

```yaml
processors:
  resource:
    attributes:
      - action: insert      # add if not already present
        key: deployment.environment
        value: production
      - action: insert
        key: cloud.region
        value: us-east-1
      - action: insert
        key: k8s.cluster.name
        value: prod-eks-cluster
      - action: delete      # strip internal keys before export
        key: internal.debug.flag
```

**`insert` vs `upsert`:** Use `insert` in a centralized Collector. `upsert` overwrites values the app already set — in a multi-account gateway, that means every service's `ClusterName` becomes the gateway's own cluster name, erasing the true origin.

### `filter` — Dropping Unwanted Telemetry

Drop health-check traces, internal probes, noisy low-value spans before they hit your backend (and your bill).

```yaml
processors:
  filter:
    error_mode: ignore   # don't fail the pipeline on filter errors
    traces:
      span:
        # drop any span where the URL matches these patterns
        - 'attributes["http.route"] == "/health"'
        - 'attributes["http.route"] == "/readyz"'
        - 'attributes["http.route"] == "/metrics"'
    metrics:
      metric:
        # drop Go runtime metrics — verbose, rarely actionable
        - 'name == "go_goroutines"'
        - 'IsMatch(name, "go_gc_.*")'
```

### `transform` — Mutating Attributes

Rename attributes, compute new values, restructure data. Uses the OpenTelemetry Transformation Language (OTTL).

```yaml
processors:
  transform:
    error_mode: ignore
    trace_statements:
      - context: span
        statements:
          # rename to match semantic conventions
          - set(attributes["http.response.status_code"],
                attributes["http.status_code"])
          - delete_key(attributes, "http.status_code")
          # redact PII — mask anything that looks like an email
          - replace_pattern(attributes["user.email"],
                            "^(.{2}).*(@.*)$", "$$1***$$2")
    metric_statements:
      - context: datapoint
        statements:
          # normalize environment labels
          - set(attributes["env"], "prod")
            where attributes["environment"] == "production"
```

### `probabilistic_sampler` — Head-Based Sampling

Keep only a percentage of traces. Simple but blind — it doesn't know if a trace is interesting before deciding.

```yaml
processors:
  probabilistic_sampler:
    sampling_percentage: 20   # keep 20% of traces
    hash_seed: 42             # consistent sampling across Collector replicas
```

### Processor Order in Production

```yaml
service:
  pipelines:
    traces:
      receivers:  [otlp]
      processors:
        - memory_limiter    # 1. protect the process first
        - filter            # 2. drop unwanted data early (before batching)
        - resource          # 3. enrich what remains
        - transform         # 4. reshape attributes
        - batch             # 5. group for efficient export — always last
      exporters:  [otlp/grafana, awsxray]
```

---

## Exporters — Where Data Goes

### Debug Exporter (essential for local dev)

Prints telemetry to stdout. Use `verbosity: detailed` locally, remove or set `basic` in production.

```yaml
exporters:
  debug:
    verbosity: detailed  # detailed | normal | basic
```

### OTLP Exporter (sending to another Collector or OTLP-native backend)

```yaml
exporters:
  otlp/grafana:             # suffix after / is an alias — lets you define multiple
    endpoint: "grafana-agent:4317"
    tls:
      insecure: false
      ca_file: /certs/ca.crt
    retry_on_failure:
      enabled: true
      initial_interval: 5s
      max_interval: 30s
      max_elapsed_time: 300s
    sending_queue:
      enabled: true
      num_consumers: 10
      queue_size: 1000

  otlp/secondary:           # a second OTLP destination — same data, different endpoint
    endpoint: "backup-collector:4317"
    tls:
      insecure: true
```

### Prometheus Exporter (exposing metrics for scraping)

Instead of pushing metrics, expose them on an HTTP endpoint for Prometheus to scrape.

```yaml
exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"   # Prometheus scrapes this
    namespace: myapp
    resource_to_telemetry_conversion:
      enabled: true  # promote resource attributes to metric labels
```

### AWS CloudWatch EMF Exporter (ADOT-specific)

Converts OTLP metrics to CloudWatch Embedded Metric Format and sends them as structured log entries. This is how ADOT gets metrics into CloudWatch without native OTLP support.

```yaml
exporters:
  awsemf:
    region: us-east-1
    namespace: MyApp/Metrics
    log_group_name: /aws/ecs/myapp
    dimension_rollup_option: NoDimensionRollup
    metric_declarations:
      # only these dimension combinations get published
      # controls cardinality and cost
      - dimensions:
          - [service.name, deployment.environment]
          - [service.name]   # fallback if environment not set
        metric_name_selectors:
          - "checkout\\..*"  # only checkout.* metrics
          - "http\\..*"
```

### AWS X-Ray Exporter (ADOT-specific)

```yaml
exporters:
  awsxray:
    region: us-east-1
    indexed_attributes:
      - "user.id"
      - "order.id"
    # indexed_attributes become X-Ray annotations (searchable)
    # non-indexed attributes become X-Ray metadata (not searchable)
```

### Sending to Multiple Backends

List multiple exporters in the pipeline — the Collector fans out to all of them:

```yaml
service:
  pipelines:
    traces:
      receivers:  [otlp]
      processors: [memory_limiter, batch]
      exporters:  [awsxray, otlp/grafana]  # both get the same traces
    metrics:
      receivers:  [otlp, prometheus]        # two sources, one pipeline
      processors: [memory_limiter, batch]
      exporters:  [awsemf, prometheus]
    logs:
      receivers:  [otlp, filelog]
      processors: [memory_limiter, resource, batch]
      exporters:  [awscloudwatchlogs]
```

---

## Extensions — Supporting Capabilities

Extensions run alongside pipelines but don't process telemetry. They handle operational concerns.

```yaml
extensions:
  health_check:
    endpoint: 0.0.0.0:13133   # GET /health returns 200 when ready
                               # this is what your NLB/ALB targets

  pprof:
    endpoint: 0.0.0.0:1777    # Go profiling endpoint — disable in prod

  zpages:
    endpoint: 0.0.0.0:55679   # debug UI — /debug/tracez, /debug/pipelinez

  memory_ballast:
    size_mib: 256              # pre-allocates memory to reduce GC pressure
                               # set to ~40% of container memory limit

service:
  extensions: [health_check, memory_ballast]  # zpages and pprof: local only
```

**The NLB health-check gotcha:** Your load balancer (ALB, NLB, ECS health check) should target `health_check` on port 13133. Don't use a `curl`-based container health check — the ADOT collector image ships no `curl` binary. A check that always fails will cycle healthy tasks endlessly.

---

## Production Config: Full Working Example

This config reflects a realistic ECS/EKS production setup — OTLP in, traces to X-Ray, metrics to CloudWatch via EMF, logs to CloudWatch Logs, with filtering and enrichment.

```yaml
# production-collector.yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
  prometheus:
    config:
      scrape_configs:
        - job_name: 'internal-exporters'
          scrape_interval: 60s
          static_configs:
            - targets: ['redis-exporter:9121']

processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 400
    spike_limit_mib: 80

  filter:
    error_mode: ignore
    traces:
      span:
        - 'attributes["http.route"] == "/health"'
        - 'attributes["http.route"] == "/readyz"'
        - 'attributes["http.route"] == "/livez"'

  resource:
    attributes:
      - action: insert
        key: deployment.environment
        value: ${DEPLOYMENT_ENV}       # read from env var at runtime
      - action: insert
        key: cloud.region
        value: ${AWS_REGION}
      - action: insert
        key: cloud.account.id
        value: ${AWS_ACCOUNT_ID}

  batch:
    send_batch_size: 1024
    timeout: 5s
    send_batch_max_size: 2048

exporters:
  awsxray:
    region: ${AWS_REGION}
    indexed_attributes: ["user.id", "order.id", "service.name"]

  awsemf:
    region: ${AWS_REGION}
    namespace: Production/Metrics
    log_group_name: /otel/metrics
    dimension_rollup_option: NoDimensionRollup
    metric_declarations:
      - dimensions:
          - [service.name, deployment.environment, cloud.account.id]
          - [service.name, deployment.environment]   # fallback
        metric_name_selectors: [".*"]

  awscloudwatchlogs:
    region: ${AWS_REGION}
    log_group_name: /otel/application-logs
    log_stream_name: otlp
    log_retention: 90

  debug:
    verbosity: basic   # errors and summaries only in production

extensions:
  health_check:
    endpoint: 0.0.0.0:13133
  memory_ballast:
    size_mib: 160

service:
  extensions: [health_check, memory_ballast]
  pipelines:
    traces:
      receivers:  [otlp]
      processors: [memory_limiter, filter, resource, batch]
      exporters:  [awsxray, debug]
    metrics:
      receivers:  [otlp, prometheus]
      processors: [memory_limiter, resource, batch]
      exporters:  [awsemf, debug]
    logs:
      receivers:  [otlp]
      processors: [memory_limiter, resource, batch]
      exporters:  [awscloudwatchlogs, debug]
```

---

## Running It Locally

```bash
# Pull the official contrib image (includes all community components)
docker run \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 13133:13133 \
  -v $(pwd)/collector-config.yaml:/etc/otelcol-contrib/config.yaml \
  otel/opentelemetry-collector-contrib:latest

# Or with ADOT (AWS-specific components: X-Ray, EMF, ECS metadata)
docker run \
  -p 4317:4317 \
  -p 4318:4318 \
  -p 13133:13133 \
  -v $(pwd)/collector-config.yaml:/etc/ecs/ecs-default-config.yaml \
  public.ecr.aws/aws-observability/aws-otel-collector:latest
```

Point your Python app at it:

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

exporter = OTLPSpanExporter(endpoint="http://localhost:4317")
tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
```

Check the Collector is receiving by hitting `zpages` at `http://localhost:55679/debug/tracez`.

---

## Troubleshooting: The Five Most Common Issues

| Symptom | Likely Cause | Fix |
|---|---|---|
| Spans sent but nothing arrives | Component defined but not in `service.pipelines` | Wire it into the pipeline |
| `memory_limiter` dropping data constantly | `limit_mib` too low for your volume | Increase limit or reduce batch size |
| Health check failing on NLB | Container doesn't have `curl`; or port mismatch | Use TCP health check on port 13133 |
| All resource attributes show gateway values | `resource` processor uses `upsert` | Change to `action: insert` |
| Metrics not appearing in CloudWatch | EMF dimensions include attribute not set by all services | Add a fallback dimension set without that attribute |

---

## Key Takeaways

| Concept | The Point |
|---|---|
| **Pipeline order** | `memory_limiter` → `filter` → `resource` → `transform` → `batch`. Never batch before limiting. |
| **`insert` not `upsert`** | In shared/central Collectors, `upsert` overwrites source identity. |
| **Filter early** | Drop health checks and noise before batching, not after. |
| **Health check port** | Always 13133. Don't use curl-based checks with ADOT images. |
| **Multiple exporters** | List them both in the pipeline — Collector fans out automatically. |
| **Env vars in config** | Use `${VAR_NAME}` syntax — the Collector resolves them at startup. |

---

## What's Next

- **Part 3**: [Deploying OTel on EKS — DaemonSet, ADOT, and CloudWatch Integration](#)
- **Part 4**: [Tail-Based Sampling and OTel in Production — Cost Control Without Losing Signal](#)
- **ECS Series**: [OTel on ECS Fargate — Sidecar Pattern with ADOT](./opentelemetry-ecs-part1-sidecar.md)

---

*Found this useful? Star [sandeepk24/learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) on GitHub.*
