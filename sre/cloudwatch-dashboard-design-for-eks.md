# Designing a Production-Grade CloudWatch Dashboard for AWS EKS Clusters

> A Senior AWS Engineer's guide to building observable, actionable, and scalable monitoring dashboards for Amazon Elastic Kubernetes Service.

---

## 1. Why a Dedicated EKS Dashboard Matters

Running Kubernetes on AWS EKS means metrics come from several layers at once: the AWS control plane, the EC2 or Fargate data plane, the Kubernetes object model, and the application containers themselves. Without one dashboard that pulls all of that together, on-call engineers waste time during incidents jumping between consoles.

A well-designed CloudWatch dashboard eliminates that friction. It answers three questions at a glance: Is the cluster healthy? Are workloads performing? Where is the bottleneck?

---

## 2. Prerequisite: Instrumenting EKS for CloudWatch

Before building widgets, you must ensure metric pipelines are flowing.

### 2.1 Enable the CloudWatch Observability Add-On

The modern approach is the **Amazon CloudWatch Observability EKS Add-On**, which replaces the older Fluent Bit and CW Agent sidecar pattern with a single, managed installation.

```bash
aws eks create-addon \
  --cluster-name production-cluster \
  --addon-name amazon-cloudwatch-observability \
  --addon-version v2.3.0-eksbuild.1 \
  --service-account-role-arn arn:aws:iam::ACCOUNT_ID:role/CWObservabilityRole \
  --configuration-values '{
    "containerLogs": { "enabled": true },
    "containerInsights": { "enhanced": true }
  }'
```

This deploys the CloudWatch Agent and Fluent Bit as a DaemonSet and enables **Container Insights with Enhanced Observability**, which pushes performance metrics into the `ContainerInsights` namespace.

### 2.2 Confirm Metric Flow

Verify metrics are landing in CloudWatch:

```bash
aws cloudwatch list-metrics \
  --namespace ContainerInsights \
  --dimensions Name=ClusterName,Value=production-cluster \
  --query 'Metrics[].MetricName' --output table
```

You should see metrics like `node_cpu_utilization`, `pod_memory_utilization`, `node_filesystem_utilization`, and many others.

### 2.3 Enable Control Plane Logging

Control plane logs (API server, audit, authenticator, controller manager, scheduler) are separate from Container Insights:

```bash
aws eks update-cluster-config \
  --name production-cluster \
  --logging '{
    "clusterLogging": [
      {
        "types": ["api", "audit", "authenticator", "controllerManager", "scheduler"],
        "enabled": true
      }
    ]
  }'
```

These logs stream to CloudWatch Logs under `/aws/eks/production-cluster/cluster`.

---

## 3. Dashboard Architecture: The Four-Tier Model

Organize the dashboard into four horizontal tiers, each answering a progressively deeper question.

```
┌──────────────────────────────────────────────────────────────────┐
│  TIER 1 — CLUSTER HEALTH SUMMARY                                │
│  (Single-value widgets: node count, pod status, API latency)    │
├──────────────────────────────────────────────────────────────────┤
│  TIER 2 — NODE-LEVEL RESOURCE UTILIZATION                       │
│  (CPU, memory, disk, network per node / node group)             │
├──────────────────────────────────────────────────────────────────┤
│  TIER 3 — WORKLOAD & POD PERFORMANCE                            │
│  (Namespace-level CPU/memory, pod restarts, OOMKill events)     │
├──────────────────────────────────────────────────────────────────┤
│  TIER 4 — NETWORKING & STORAGE                                  │
│  (CNI errors, DNS latency, EBS volume IOPS, PVC utilization)    │
└──────────────────────────────────────────────────────────────────┘
```

This top-down layout mirrors how an incident responder thinks: start broad, then drill in.

---

## 4. Tier 1: Cluster Health Summary

This tier uses **single-value (number) widgets** and a single time-series graph. The goal is a five-second assessment.

### 4.1 Widgets

| Widget | Metric Source | Type | Description |
|--------|---------------|------|-------------|
| Active Node Count | `ContainerInsights / node_status_condition_ready` | Number | Nodes in Ready state |
| Running Pods | `ContainerInsights / pod_number_of_running_pods` | Number | Cluster-wide running pod count |
| Pending Pods | `ContainerInsights / pod_status_pending` | Number | Non-zero = scheduling problem |
| API Server Latency (p99) | Control Plane Logs (Metric Filter) | Number | p99 request latency in ms |
| API Server 5xx Rate | Control Plane Logs (Metric Filter) | Number | 5xx errors/minute from API server |

### 4.2 API Server Latency Metric Filter

Since API server latency isn't a native Container Insights metric, create a CloudWatch Logs Metric Filter on the API server audit log:

```json
{
  "filterPattern": "{ $.responseStatus.code >= 500 }",
  "metricTransformations": [
    {
      "metricName": "ApiServer5xxCount",
      "metricNamespace": "EKS/ControlPlane",
      "metricValue": "1",
      "defaultValue": 0
    }
  ]
}
```

### 4.3 Dashboard JSON Fragment — Tier 1

```json
{
  "type": "metric",
  "properties": {
    "metrics": [
      [
        "ContainerInsights", "node_number_of_running_pods",
        "ClusterName", "production-cluster",
        { "stat": "Maximum", "label": "Running Pods" }
      ]
    ],
    "view": "singleValue",
    "region": "us-east-1",
    "period": 60,
    "title": "Running Pods"
  }
}
```

---

## 5. Tier 2: Node-Level Resource Utilization

This tier answers: Are we running out of compute capacity?

### 5.1 Key Metrics

| Metric Name | Statistic | Alarm Threshold | Rationale |
|-------------|-----------|-----------------|-----------|
| `node_cpu_utilization` | Average | > 80% sustained 5m | Leaves headroom for burst |
| `node_memory_utilization` | Average | > 85% sustained 5m | OOMKiller triggers above ~95% |
| `node_filesystem_utilization` | Average | > 75% | Ephemeral storage exhaustion causes pod eviction |
| `node_network_total_bytes` | Sum | Anomaly band | Detects DDoS or misconfigured services |

### 5.2 Recommended Widget Layout

```
┌──────────────────────┬──────────────────────┐
│ Node CPU Utilization │ Node Memory Util.    │
│ (line, per NodeGroup)│ (line, per NodeGroup)│
├──────────────────────┼──────────────────────┤
│ Disk Utilization     │ Network I/O          │
│ (line, per Node)     │ (stacked area, Rx/Tx)│
└──────────────────────┴──────────────────────┘
```

### 5.3 CloudWatch Metric Math: Cluster-Wide CPU Headroom

Use metric math to show remaining allocatable CPU across the cluster:

```
m1 = ContainerInsights.node_cpu_limit (Sum across cluster)
m2 = ContainerInsights.node_cpu_usage_total (Sum across cluster)

Expression: headroom_pct = ((m1 - m2) / m1) * 100
Label: "CPU Headroom %"
```

This is more actionable than raw utilization because it accounts for heterogeneous node groups (e.g., mixing `m6i.xlarge` and `c6i.2xlarge`).

### 5.4 Alarms to Attach

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name eks-node-cpu-high \
  --namespace ContainerInsights \
  --metric-name node_cpu_utilization \
  --dimensions Name=ClusterName,Value=production-cluster \
  --statistic Average \
  --period 300 \
  --evaluation-periods 3 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:ACCOUNT_ID:eks-alerts \
  --treat-missing-data notBreaching
```

---

## 6. Tier 3: Workload & Pod Performance

This tier answers: Which namespace or deployment is misbehaving?

### 6.1 Key Metrics

| Metric | Dimensions | Why It Matters |
|--------|-----------|----------------|
| `pod_cpu_utilization` | Namespace, PodName | Identifies runaway containers |
| `pod_memory_utilization` | Namespace, PodName | Predicts OOMKill before it happens |
| `pod_number_of_container_restarts` | Namespace, PodName | CrashLoopBackOff detection |
| `pod_status_failed` | Namespace | Broad failure signal |
| `pod_memory_utilization_over_pod_limit` | Namespace, PodName | Shows how close to the memory limit a pod is |

### 6.2 CloudWatch Logs Insights: OOMKill Detection

Create a dashboard widget backed by a Logs Insights query against the Container Insights performance logs:

```sql
fields @timestamp, kubernetes.namespace_name, kubernetes.pod_name, @message
| filter @message like /OOMKilled/
| stats count(*) as oomkill_count by kubernetes.namespace_name, kubernetes.pod_name
| sort oomkill_count desc
| limit 10
```

### 6.3 Restart Heatmap

A table widget showing restart counts per namespace over the last hour helps spot CrashLoopBackOff patterns without digging into `kubectl`:

```json
{
  "type": "log",
  "properties": {
    "query": "SOURCE '/aws/containerinsights/production-cluster/performance'\n| fields kubernetes.namespace_name as ns, kubernetes.pod_name as pod\n| filter Type = \"Pod\"\n| stats max(pod_number_of_container_restarts) as restarts by ns, pod\n| filter restarts > 0\n| sort restarts desc\n| limit 20",
    "region": "us-east-1",
    "title": "Pod Restarts (Last 1h)",
    "view": "table"
  }
}
```

### 6.4 Namespace Resource Quota Usage

If you enforce `ResourceQuota` objects, track consumed vs. allocated resources per namespace:

```sql
fields @timestamp, kubernetes.namespace_name as ns
| filter Type = "Namespace"
| stats
    latest(namespace_cpu_usage_total) as cpu_used,
    latest(namespace_cpu_limit) as cpu_limit,
    latest(namespace_memory_usage) as mem_used,
    latest(namespace_memory_limit) as mem_limit
  by ns
```

---

## 7. Tier 4: Networking & Storage

This tier covers the infrastructure plumbing that can silently degrade workloads.

### 7.1 Networking Metrics

| Metric | Source | Purpose |
|--------|--------|---------|
| `pod_network_rx_bytes` / `pod_network_tx_bytes` | ContainerInsights | Per-pod network throughput |
| `node_network_total_bytes` | ContainerInsights | Node-level saturation |
| CoreDNS latency | Prometheus (forwarded) or Logs Insights | DNS is the #1 silent killer in EKS |
| VPC CNI `ipamd` errors | `/aws/eks/cluster/cluster` logs | IP exhaustion in the VPC subnet |

### 7.2 CoreDNS Latency Widget

If you're forwarding CoreDNS Prometheus metrics to CloudWatch via the CW Agent's Prometheus scraper:

```json
{
  "type": "metric",
  "properties": {
    "metrics": [
      [
        "ContainerInsights/Prometheus", "coredns_dns_request_duration_seconds",
        "ClusterName", "production-cluster",
        { "stat": "p99", "label": "CoreDNS p99 Latency" }
      ]
    ],
    "view": "timeSeries",
    "period": 60,
    "title": "CoreDNS p99 Request Latency"
  }
}
```

### 7.3 EBS/EFS Storage Metrics

For workloads using Persistent Volumes:

| Metric | Namespace | Alarm Condition |
|--------|-----------|-----------------|
| `VolumeReadOps` / `VolumeWriteOps` | `AWS/EBS` | Sustained IOPS near provisioned limit |
| `VolumeQueueLength` | `AWS/EBS` | > 1 = I/O bottleneck |
| `BurstBalance` | `AWS/EBS` | < 20% on gp2/gp3 volumes |

---

## 8. The Complete Dashboard Template (CloudFormation)

Deploy the entire dashboard as infrastructure-as-code:

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Description: CloudWatch Dashboard for EKS Cluster Monitoring

Parameters:
  ClusterName:
    Type: String
    Default: production-cluster
  Region:
    Type: String
    Default: us-east-1

Resources:
  EKSDashboard:
    Type: AWS::CloudWatch::Dashboard
    Properties:
      DashboardName: !Sub "${ClusterName}-monitoring"
      DashboardBody: !Sub |
        {
          "widgets": [
            {
              "type": "text",
              "x": 0, "y": 0, "width": 24, "height": 1,
              "properties": {
                "markdown": "# ${ClusterName} — EKS Cluster Dashboard"
              }
            },
            {
              "type": "metric",
              "x": 0, "y": 1, "width": 6, "height": 4,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "cluster_node_count",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Maximum" }]
                ],
                "view": "singleValue",
                "region": "${Region}",
                "period": 60,
                "title": "Node Count"
              }
            },
            {
              "type": "metric",
              "x": 6, "y": 1, "width": 6, "height": 4,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "pod_number_of_running_pods",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Maximum" }]
                ],
                "view": "singleValue",
                "region": "${Region}",
                "period": 60,
                "title": "Running Pods"
              }
            },
            {
              "type": "metric",
              "x": 12, "y": 1, "width": 6, "height": 4,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "cluster_failed_node_count",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Maximum" }]
                ],
                "view": "singleValue",
                "region": "${Region}",
                "period": 60,
                "title": "Failed Nodes"
              }
            },
            {
              "type": "metric",
              "x": 18, "y": 1, "width": 6, "height": 4,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "pod_number_of_container_restarts",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Sum" }]
                ],
                "view": "singleValue",
                "region": "${Region}",
                "period": 300,
                "title": "Container Restarts (5m)"
              }
            },
            {
              "type": "text",
              "x": 0, "y": 5, "width": 24, "height": 1,
              "properties": {
                "markdown": "## Node Resource Utilization"
              }
            },
            {
              "type": "metric",
              "x": 0, "y": 6, "width": 12, "height": 6,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "node_cpu_utilization",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Average" }]
                ],
                "view": "timeSeries",
                "region": "${Region}",
                "period": 60,
                "yAxis": { "left": { "min": 0, "max": 100 } },
                "title": "Node CPU Utilization (%)",
                "annotations": {
                  "horizontal": [
                    { "label": "Alarm", "value": 80, "color": "#d62728" }
                  ]
                }
              }
            },
            {
              "type": "metric",
              "x": 12, "y": 6, "width": 12, "height": 6,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "node_memory_utilization",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Average" }]
                ],
                "view": "timeSeries",
                "region": "${Region}",
                "period": 60,
                "yAxis": { "left": { "min": 0, "max": 100 } },
                "title": "Node Memory Utilization (%)",
                "annotations": {
                  "horizontal": [
                    { "label": "Alarm", "value": 85, "color": "#d62728" }
                  ]
                }
              }
            },
            {
              "type": "metric",
              "x": 0, "y": 12, "width": 12, "height": 6,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "node_filesystem_utilization",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Average" }]
                ],
                "view": "timeSeries",
                "region": "${Region}",
                "period": 60,
                "title": "Node Disk Utilization (%)"
              }
            },
            {
              "type": "metric",
              "x": 12, "y": 12, "width": 12, "height": 6,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "node_network_total_bytes",
                   "ClusterName", "${ClusterName}",
                   { "stat": "Sum" }]
                ],
                "view": "timeSeries",
                "stacked": true,
                "region": "${Region}",
                "period": 60,
                "title": "Node Network I/O (bytes)"
              }
            },
            {
              "type": "text",
              "x": 0, "y": 18, "width": 24, "height": 1,
              "properties": {
                "markdown": "## Workload & Pod Performance"
              }
            },
            {
              "type": "metric",
              "x": 0, "y": 19, "width": 12, "height": 6,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "pod_cpu_utilization",
                   "ClusterName", "${ClusterName}",
                   "Namespace", "default",
                   { "stat": "Average" }]
                ],
                "view": "timeSeries",
                "region": "${Region}",
                "period": 60,
                "title": "Pod CPU Utilization by Namespace"
              }
            },
            {
              "type": "metric",
              "x": 12, "y": 19, "width": 12, "height": 6,
              "properties": {
                "metrics": [
                  ["ContainerInsights", "pod_memory_utilization",
                   "ClusterName", "${ClusterName}",
                   "Namespace", "default",
                   { "stat": "Average" }]
                ],
                "view": "timeSeries",
                "region": "${Region}",
                "period": 60,
                "title": "Pod Memory Utilization by Namespace"
              }
            },
            {
              "type": "log",
              "x": 0, "y": 25, "width": 24, "height": 6,
              "properties": {
                "query": "SOURCE '/aws/containerinsights/${ClusterName}/performance'\n| fields kubernetes.namespace_name as ns, kubernetes.pod_name as pod\n| filter Type = \"Pod\"\n| stats max(pod_number_of_container_restarts) as restarts by ns, pod\n| filter restarts > 0\n| sort restarts desc\n| limit 20",
                "region": "${Region}",
                "title": "Top 20 — Pod Restarts",
                "view": "table"
              }
            }
          ]
        }
```

Deploy with:

```bash
aws cloudformation deploy \
  --template-file eks-dashboard.yaml \
  --stack-name eks-dashboard \
  --parameter-overrides ClusterName=production-cluster Region=us-east-1
```

---

## 9. Alarm Strategy: What to Alert On

Not every metric deserves a PagerDuty notification. Follow a tiered severity model.

### Critical (Page Immediately)

These indicate active user impact or imminent cluster failure:

- `cluster_failed_node_count > 0` for 2 consecutive periods (5m each)
- `pod_number_of_running_pods` drops > 20% in 5 minutes (anomaly detection)
- API server 5xx rate > 5/min sustained for 3 minutes
- `node_memory_utilization > 95%` for 5 minutes (OOMKill imminent)

### Warning (Slack Notification)

These require investigation within the hour:

- `node_cpu_utilization > 80%` sustained 15 minutes
- `node_filesystem_utilization > 75%`
- `pod_number_of_container_restarts` Sum > 10 in 5 minutes
- EBS `BurstBalance < 20%`

### Informational (Dashboard Only)

Track on the dashboard for trend analysis but don't alert:

- Per-namespace CPU/memory trends
- Network throughput baselines
- CoreDNS query volume

---

## 10. Advanced Patterns

### 10.1 Cross-Account / Cross-Cluster Dashboards

For organizations running multiple EKS clusters across accounts, use **CloudWatch Cross-Account Observability**:

```bash
# In the monitoring account
aws cloudwatch put-metric-data \
  --namespace "ContainerInsights" \
  --metric-data ...

# Link source accounts
aws oam create-link \
  --label-template "\$AccountName" \
  --resource-types "AWS::CloudWatch::Metric" "AWS::Logs::LogGroup" \
  --sink-identifier arn:aws:oam:us-east-1:MONITORING_ACCT:sink/sink-id
```

Then build a single dashboard that queries metrics across all linked accounts.

### 10.2 Anomaly Detection Bands

For metrics without a clean static threshold (like network traffic or pod count), use CloudWatch Anomaly Detection:

```bash
aws cloudwatch put-anomaly-detector \
  --namespace ContainerInsights \
  --metric-name node_network_total_bytes \
  --dimensions Name=ClusterName,Value=production-cluster \
  --stat Average
```

Reference the anomaly band in your dashboard widget to visualize expected vs. actual ranges.

### 10.3 Composite Alarms

Reduce alert noise by combining related alarms into a composite that only fires when multiple conditions are true:

```bash
aws cloudwatch put-composite-alarm \
  --alarm-name eks-cluster-degraded \
  --alarm-rule 'ALARM("eks-node-cpu-high") AND ALARM("eks-pod-restarts-high")' \
  --alarm-actions arn:aws:sns:us-east-1:ACCOUNT_ID:critical-alerts
```

This prevents paging when a single metric spikes briefly during a deployment.

---

## 11. Cost Optimization

CloudWatch costs scale with metric count and query volume. Keep costs predictable:

- **Metric period**: Use 60-second periods for Tier 1 widgets, 300 seconds for Tier 3/4 where sub-minute resolution isn't needed.
- **Log retention**: Set `/aws/containerinsights/` log groups to 14-30 day retention unless compliance requires more.
- **Dashboard auto-refresh**: Set to 5 minutes instead of 10 seconds to reduce `GetMetricData` API calls.
- **Metric filters vs. Logs Insights**: Prefer metric filters for persistent queries (cheaper at scale) and Logs Insights for ad-hoc investigation.
- **Selective namespace instrumentation**: If running 50+ namespaces, configure the CW Agent to only collect metrics from namespaces you care about using the `metrics_collected.kubernetes.enhanced_container_insights.namespace_include` setting.

---

## 12. Maintenance Checklist

Run monthly to keep the dashboard relevant:

- Review alarm thresholds against actual utilization trends — a cluster that consistently runs at 70% CPU should have its threshold adjusted, not ignored.
- Remove widgets for decommissioned namespaces or node groups.
- Validate that the CloudWatch Observability Add-On is up to date (`aws eks describe-addon`).
- Verify control plane logs are still enabled after any Terraform/CDK re-apply (some IaC patterns reset logging config).
- Audit cross-account links if clusters have been added or removed.

---

## 13. Summary

A production CloudWatch dashboard for EKS follows a clear hierarchy: cluster health at the top, node resources in the middle, workload metrics below, and infrastructure plumbing at the bottom. Pair the dashboard with a disciplined alarm strategy that separates critical pages from informational trends, and deploy everything as CloudFormation so the dashboard evolves alongside the cluster. The goal is never to build the most comprehensive dashboard — it's to build the one your on-call engineer actually trusts at 3 AM.
