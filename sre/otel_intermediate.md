# OpenTelemetry for Cloud Architects: AWS, Multi-Cloud Monitoring, and Production Patterns


---

## Moving Beyond the Basics

If you've read the 101 guide, you know what OpenTelemetry is and what problems it solves. Now let's get into the stuff that matters when you're actually building this out for a real organization — specifically, monitoring AWS services at scale, designing for multi-cloud from day one, and avoiding the mistakes I've seen teams make over and over again.

This article assumes you're a DevOps architect or platform engineer who needs to make decisions about observability infrastructure. We're going to talk about real architecture, real trade-offs, and real configurations.

## Where AWS Stands on OpenTelemetry in 2026

AWS has invested heavily in OpenTelemetry, and the tooling around it has matured a lot. Here's what you need to know.

### AWS Distro for OpenTelemetry (ADOT)

AWS doesn't just support OpenTelemetry — they maintain their own distribution of it called **ADOT** (AWS Distro for OpenTelemetry). Think of it like the difference between vanilla Kubernetes and Amazon EKS: same core technology, but AWS adds tested configurations, pre-built integrations, and official support.

ADOT extends the standard OTel Collector with AWS-specific components:

- **AWS X-Ray exporter** for distributed tracing
- **CloudWatch EMF exporter** for metrics (using Embedded Metric Format)
- **SigV4 authentication extension** for secure AWS API calls
- **Resource detection processor** that automatically discovers AWS metadata (EC2 instance IDs, ECS task definitions, EKS cluster names)
- **Application Signals processor** for CloudWatch Application Signals

The key decision here: **should you use ADOT or the community OTel Collector?**

If you're AWS-only and want official AWS support, ADOT is the safe choice. If you're multi-cloud or need contrib components that ADOT doesn't bundle, build a custom collector using the OTel Collector Builder (`ocb`). Many production teams actually run both — ADOT for their AWS-heavy workloads and a custom collector for everything else.

### CloudWatch Now Speaks OpenTelemetry Natively

A major development: Amazon CloudWatch now natively ingests OpenTelemetry metrics, logs, and traces through OTLP endpoints. This is a big deal because it means you no longer need to translate OTel data into CloudWatch's proprietary format — you send OTLP, CloudWatch understands it.

What makes this especially powerful for AWS-heavy shops:

- **PromQL support for CloudWatch metrics.** You can query OTel metrics in CloudWatch using PromQL — the same query language used by Prometheus and Grafana. This means your dashboards and alerts can use one query language regardless of where the data lives.
- **High-cardinality metric storage.** CloudWatch's new OTel-native store supports up to 150 labels per metric. That's a massive improvement over the old 30-dimension limit.
- **Automatic enrichment.** CloudWatch can automatically attach AWS resource tags to your OTel metrics, so your telemetry is automatically correlated with your infrastructure.

Here's what the Collector configuration looks like for sending metrics to CloudWatch via OTLP:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
    timeout: 10s
    send_batch_size: 1024
  
  resourcedetection:
    detectors: [ec2, ecs, eks]
    timeout: 5s

exporters:
  otlphttp/cloudwatch:
    compression: gzip
    metrics_endpoint: https://monitoring.us-east-1.amazonaws.com/v1/metrics
    logs_endpoint: https://logs.us-east-1.amazonaws.com/v1/logs
    traces_endpoint: https://xray.us-east-1.amazonaws.com/v1/traces
    auth:
      authenticator: sigv4auth

extensions:
  sigv4auth:
    region: us-east-1
    service: monitoring

service:
  extensions: [sigv4auth]
  pipelines:
    metrics:
      receivers: [otlp]
      processors: [resourcedetection, batch]
      exporters: [otlphttp/cloudwatch]
    traces:
      receivers: [otlp]
      processors: [resourcedetection, batch]
      exporters: [otlphttp/cloudwatch]
    logs:
      receivers: [otlp]
      processors: [resourcedetection, batch]
      exporters: [otlphttp/cloudwatch]
```

### Monitoring AWS Services with the CloudWatch Receiver

Here's where it gets practical for a DevOps architect. The **AWS CloudWatch Receiver** in the OTel Collector pulls metrics directly from CloudWatch's API and converts them into OTel format. This means you can pull metrics from any AWS service that publishes to CloudWatch — EC2, RDS, Lambda, DynamoDB, SQS, ALB, ECS, and over 70 others — and send them to any OTel-compatible backend.

```yaml
receivers:
  awscloudwatch:
    region: "us-east-1"
    collection_interval: 60s
    namespaces:
      - name: "AWS/EC2"
        metrics:
          - name: "CPUUtilization"
            statistic: "Average"
          - name: "NetworkIn"
            statistic: "Sum"
        dimensions:
          - name: "InstanceId"
            values:
              - "i-0abc123def456789"

      - name: "AWS/RDS"
        metrics:
          - name: "CPUUtilization"
            statistic: "Average"
          - name: "DatabaseConnections"
            statistic: "Average"
          - name: "FreeStorageSpace"
            statistic: "Average"
        dimensions:
          - name: "DBInstanceIdentifier"
            values:
              - "production-primary"
              - "production-replica"

      - name: "AWS/Lambda"
        metrics:
          - name: "Invocations"
            statistic: "Sum"
          - name: "Errors"
            statistic: "Sum"
          - name: "Duration"
            statistic: "Average"
          - name: "ConcurrentExecutions"
            statistic: "Maximum"

      - name: "AWS/SQS"
        metrics:
          - name: "ApproximateNumberOfMessagesVisible"
            statistic: "Average"
          - name: "ApproximateAgeOfOldestMessage"
            statistic: "Maximum"
```

**Cost warning**: Every CloudWatch API call costs money. Be deliberate about which namespaces and metrics you pull, how often you poll (don't go below 60 seconds unless you need to), and use dimension filtering aggressively. I've seen teams accidentally rack up thousands of dollars in CloudWatch API charges because they pulled every metric from every namespace with no filtering.

## Designing for Multi-Cloud From Day One

If you're thinking "I'm on AWS now, but Azure or GCP might be in our future," OpenTelemetry is your best friend. Here's the architectural pattern that works.

### The Fan-Out Collector Pattern

Instead of each application deciding where to send data, route everything through a Collector tier that handles fan-out:

```
┌─────────────────────────────────────────────────────────────┐
│                    Application Tier                          │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐      │
│  │ App A   │  │ App B   │  │ App C   │  │ App D   │      │
│  │ (OTel)  │  │ (OTel)  │  │ (OTel)  │  │ (OTel)  │      │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘      │
│       └─────┬──────┴──────┬─────┘            │             │
│             ▼             ▼                   ▼             │
│  ┌──────────────────────────────────────────────────┐      │
│  │           Gateway Collector (Load Balanced)       │      │
│  │  Receivers → Processors → Exporters              │      │
│  └────┬──────────────┬──────────────┬───────────────┘      │
│       │              │              │                       │
│       ▼              ▼              ▼                       │
│  CloudWatch     Grafana/Mimir    Future: Azure             │
│  (AWS)          (Multi-cloud)    Monitor                   │
└─────────────────────────────────────────────────────────────┘
```

The key insight: **your applications never need to know about your backends.** They send OTLP to the Collector. When you add Azure Monitor next year, you add an exporter to the Collector. No application changes required.

### The Two-Tier Collector Architecture

For production at scale, most teams run two tiers of collectors:

**Agent Collectors** run on every host (or as sidecars in Kubernetes). They collect local telemetry, do lightweight processing (adding host metadata, basic filtering), and forward to the gateway tier. Keep these lightweight — they share resources with your applications.

**Gateway Collectors** run as a dedicated, horizontally scaled service. They receive data from all agents, do the heavy processing (tail-based sampling, data enrichment, aggregation), and export to backends. This is where you put your complex pipeline logic.

```yaml
# Agent Collector (runs on every node)
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  resourcedetection:
    detectors: [ec2, ecs, eks]
  batch:
    timeout: 5s

exporters:
  otlp/gateway:
    endpoint: otel-gateway.internal:4317
    tls:
      insecure: false
      ca_file: /etc/ssl/certs/ca-certificates.crt

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [resourcedetection, batch]
      exporters: [otlp/gateway]
```

```yaml
# Gateway Collector (dedicated service, scaled horizontally)
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

processors:
  tail_sampling:
    decision_wait: 30s
    policies:
      - name: errors-always
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: slow-requests
        type: latency
        latency: {threshold_ms: 2000}
      - name: sample-rest
        type: probabilistic
        probabilistic: {sampling_percentage: 10}
  
  batch:
    timeout: 10s
    send_batch_size: 2048

exporters:
  otlphttp/cloudwatch:
    metrics_endpoint: https://monitoring.us-east-1.amazonaws.com/v1/metrics
    auth:
      authenticator: sigv4auth
  
  otlp/grafana:
    endpoint: grafana-mimir.internal:4317

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [tail_sampling, batch]
      exporters: [otlphttp/cloudwatch, otlp/grafana]
```

## Sampling Strategies: Don't Collect Everything

This is where I see the most costly mistakes. At any reasonable scale, you cannot afford to collect and store 100% of your traces. Sampling is not optional — it's an architectural decision.

### Head-Based Sampling

The decision to sample happens at the *start* of a trace, before you know anything about it. Simple, predictable, low overhead. The downside: you might drop interesting traces because you didn't know they'd be interesting yet.

```python
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

# Keep 10% of traces
sampler = TraceIdRatioBased(0.1)
```

### Tail-Based Sampling

The decision happens at the *end* of a trace, after all spans are collected. This means you can keep 100% of error traces, 100% of slow traces, and sample down the boring healthy ones. Much more powerful, but requires the Gateway Collector pattern — you need a place to buffer complete traces before making the decision.

This is what I recommend for most production environments. One company reported achieving 100% APM coverage while reducing costs by 72% by using intelligent tail-based sampling.

### The Practical Sampling Strategy

Here's what I recommend for most AWS environments:

1. **Keep all errors** — every trace with an ERROR status gets stored
2. **Keep all slow requests** — anything above your SLA threshold (say, 2 seconds)
3. **Keep all traces touching critical services** — your payment path, authentication flow
4. **Sample the rest** — 5-10% of normal, healthy traces is usually plenty

## Production Patterns and Gotchas

### Deploying on EKS

If you're running Kubernetes on AWS, here's the proven deployment pattern:

```yaml
# Deploy OTel Collector as a DaemonSet for infrastructure metrics
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: otel-agent
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: otel-agent
  template:
    spec:
      serviceAccountName: otel-collector
      containers:
        - name: otel-agent
          image: otel/opentelemetry-collector-contrib:latest
          ports:
            - containerPort: 4317  # gRPC
            - containerPort: 4318  # HTTP
          volumeMounts:
            - name: config
              mountPath: /etc/otelcol
          resources:
            requests:
              cpu: 200m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 512Mi
      volumes:
        - name: config
          configMap:
            name: otel-agent-config
```

**And a separate Deployment for the Gateway:**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: otel-gateway
  namespace: monitoring
spec:
  replicas: 3  # Scale based on throughput
  selector:
    matchLabels:
      app: otel-gateway
  template:
    spec:
      containers:
        - name: otel-gateway
          image: otel/opentelemetry-collector-contrib:latest
          resources:
            requests:
              cpu: "1"
              memory: 2Gi
            limits:
              cpu: "2"
              memory: 4Gi
```

### Instrumenting Lambda Functions

Lambda is a special case because the function spins up and down rapidly. You don't have a long-running Collector sidecar — instead, you use the OTel Lambda layer:

```python
# Lambda handler with OTel instrumentation
# Add the ADOT Lambda layer to your function configuration

import json
from opentelemetry import trace

tracer = trace.get_tracer("order-processor")

def handler(event, context):
    with tracer.start_as_current_span("process_order") as span:
        order_id = event.get("order_id")
        span.set_attribute("order.id", order_id)
        
        # Your business logic here
        result = process_the_order(order_id)
        
        span.set_attribute("order.status", result["status"])
        return {
            "statusCode": 200,
            "body": json.dumps(result)
        }
```

Environment variables for Lambda OTel configuration:

```
AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-handler
OTEL_SERVICE_NAME=order-processor
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector.internal:4317
```

### The Metrics You Should Actually Monitor

Here's a practical rundown of what to collect across your most common AWS services. Don't collect everything — focus on what drives action.

**EC2 / ECS / EKS Compute:**
CPU utilization, memory usage, network I/O, disk I/O, and for containers: pod restart count, OOM kills, and container CPU throttling.

**RDS / Aurora:**
CPU utilization, free storage space, database connections, read/write latency, replica lag, and deadlock count.

**Lambda:**
Invocations, errors, duration (p50, p95, p99), concurrent executions, throttle count, and cold start duration.

**ALB / NLB:**
Request count, 4xx/5xx error rates, target response time, healthy/unhealthy host count, and active connections.

**SQS:**
Queue depth (visible messages), message age (oldest message), messages sent/received/deleted, and dead letter queue depth.

**DynamoDB:**
Read/write capacity consumed vs. provisioned, throttled requests, system errors, and latency.

## Preparing for Multi-Cloud: Azure and GCP

The beauty of OpenTelemetry is that the application-side instrumentation is identical across clouds. What changes is the Collector configuration. When the time comes to add Azure or GCP, you'll add exporters:

**Azure Monitor:**

```yaml
exporters:
  azuremonitor:
    connection_string: "InstrumentationKey=your-key-here"
```

**Google Cloud:**

```yaml
exporters:
  googlecloud:
    project: your-gcp-project-id
```

Your applications don't change. Your processing pipeline doesn't change. You add an exporter and a pipeline to the Gateway Collector, and your multi-cloud observability is live.

## Dashboard Strategy

With OTel data flowing into your backend, organize your dashboards in layers:

1. **Executive / SLO Dashboard** — the "is everything OK?" view. Service availability, error budgets, SLO compliance. Green/red, no noise.
2. **Service Health Dashboard** — one per service or service group. Request rate, error rate, latency percentiles (the RED method). This is where on-call starts investigating.
3. **Infrastructure Dashboard** — compute, database, queue, and network metrics. Correlated with service-level data through OTel resource attributes.
4. **Deep-Dive / Debug Dashboard** — trace search, log exploration, span analysis. Used only during active incidents.

## Key Takeaways

1. **Use ADOT for AWS-heavy environments**, but plan for the community Collector if multi-cloud is in your future.
2. **Two-tier Collector architecture** (agent + gateway) is the production standard.
3. **Tail-based sampling** saves money without sacrificing visibility on errors and slow requests.
4. **CloudWatch now speaks OTLP natively** — use PromQL and the high-cardinality metrics store.
5. **Your application code stays the same** across clouds. The Collector is where cloud-specific logic lives.
6. **Budget for CloudWatch API costs** when using the CloudWatch receiver — filter aggressively.

---

