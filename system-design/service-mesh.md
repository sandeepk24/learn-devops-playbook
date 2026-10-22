# Service Mesh

A service mesh is a dedicated infrastructure layer for service-to-service communication. It handles the concerns that would otherwise be implemented redundantly in every service: mTLS, retries, circuit breaking, traffic routing, and distributed tracing. The mesh makes these cross-cutting concerns consistent without requiring each service team to implement them.

The value proposition is real. So is the operational cost. A service mesh adds a sidecar proxy to every pod, a control plane that must be kept healthy, and a new failure mode — the mesh itself. Before adopting one, be clear about which specific problems it solves for your system that aren't already solved more simply.

## Fundamentals

### What the mesh is actually doing

A service mesh intercepts all network traffic to and from each service by running a proxy sidecar alongside every workload instance. The sidecar — typically Envoy — handles the TCP connection. The application thinks it's talking to the other service directly. It's actually talking to its local sidecar, which handles the actual network communication.

This interception is the source of all mesh capabilities:

**mTLS.** The sidecar negotiates TLS with the destination sidecar. Both sides present certificates issued by the mesh's certificate authority. Application code doesn't manage TLS — it makes a plain TCP connection to the local sidecar. The mesh provides encryption and mutual authentication transparently.

**Traffic control.** The control plane can configure the sidecar to apply routing rules, traffic splits, and fault injection. Route 10% of requests for service B to the v2 deployment, 90% to v1 — without touching service A's code or deployment. Inject a 100ms delay on 5% of requests to service C — for chaos testing (Day 33), without modifying service C.

**Observability.** Every sidecar emits metrics (request rate, latency, error rate) and traces (span per connection through the proxy). No application-level instrumentation required for the infrastructure-layer signals. The service topology — which services call which — is automatically mapped from the mesh's telemetry.

**Retries and circuit breaking.** Configured in the mesh control plane, not in application code. A retry policy on the service's `VirtualService` (Istio) or route configuration (App Mesh) applies to all callers of that service without each caller implementing retry logic independently. Circuit breaking configuration declares how many consecutive failures before a backend is considered unhealthy.

```
Without mesh:                        With mesh:

Service A ──── TLS ────► Service B   Service A ──► Sidecar A
                                                       │ mTLS
(each service manages TLS,                         Sidecar B ──► Service B
 retries, circuit breaking)
                                     (control plane configures all sidecars;
                                      application code unchanged)
```

### Data plane vs control plane

**Data plane.** The sidecars. The Envoy proxies running next to each service instance. They handle actual traffic. The data plane is in the hot path for every request — its latency overhead matters.

**Control plane.** The mesh management layer. Distributes configuration to the sidecars. Manages certificate issuance and rotation. Does not handle production traffic directly. In Istio: `istiod`. In App Mesh: the AWS-managed control plane.

The control plane is critical infrastructure. If it's unavailable, sidecars continue operating on their last-known configuration — the data plane keeps working. But no configuration changes can be pushed, no new certificates issued, and new sidecar registrations fail. Control plane health is monitored differently from data plane health.

### Sidecar overhead

Every request traverses two additional proxy hops — the source sidecar and the destination sidecar. Envoy adds roughly 0.5–2ms of latency per hop under normal conditions. For services with p99 latency targets of 50ms, 2–4ms of mesh overhead is less than 10%. For services with p99 targets of 5ms, it's significant.

Memory overhead: each Envoy sidecar consumes roughly 50–100MB of memory depending on the number of upstream services it tracks. In a large cluster with hundreds of services, Envoy's xDS configuration (the list of all upstream endpoints) grows proportionally. Clusters with more than a few hundred services may see Envoy memory growing to several hundred MB per sidecar — a real cost at fleet scale.

CPU overhead is present but typically minor — 0.5–2% CPU per sidecar at moderate request rates.

## Operations

### When a service mesh is justified

The mesh adds operational complexity. It's justified when the problems it solves are more expensive than the complexity it adds. Specific signals:

**The team is already implementing retry/circuit breaking/mTLS in every service, inconsistently.** Each service team is solving the same problem in slightly different ways. Bugs in retry logic appear repeatedly. mTLS is implemented in some services and skipped in others. A mesh standardizes these consistently.

**You need traffic control for progressive delivery across many services.** Canary deployments (Day 26) for a single service are manageable with ALB weighted routing. Canary deployments for fifty services, with traffic shaping across all of them, are significantly easier with a mesh that handles the routing configuration uniformly.

**You need uniform observability across a polyglot service fleet.** Services in Go, Python, Java, and Node.js. Getting consistent distributed traces from all of them requires either per-language SDK integration or a mesh that captures the traces at the proxy layer regardless of language.

**Zero trust is a hard requirement.** mTLS between all services, with cryptographic identity verification rather than network-based trust. The mesh implements this consistently across the fleet.

Not justified: a small fleet of a few services. A single-language fleet where per-library instrumentation is consistent. A system where the latency overhead of 2–4ms per hop conflicts with latency SLOs.

### Debugging through the mesh

The mesh adds indirection. A request fails. Is the failure in the application or in the sidecar? Is the circuit breaker in the mesh configuration tripping, or is the downstream service actually broken?

The mesh provides the tooling to answer these questions:
- Envoy's admin interface (`localhost:15000`) on each pod exposes cluster health, upstream endpoints, circuit breaker state, and traffic statistics. `kubectl exec -it <pod> -c istio-proxy -- curl localhost:15000/stats` shows Envoy's view of every upstream.
- `istioctl proxy-config clusters <pod>` shows the clusters Envoy knows about and their health status.
- Control plane logs show configuration distribution failures — when the control plane can't push configuration to a sidecar.

The failure mode to know: configuration propagation lag. You apply a traffic shift. The control plane processes it. Envoy sidecars receive the update asynchronously. During the propagation window, different instances have different configurations. A canary rollout that looks correct from the control plane may have inconsistent behavior at the data plane while propagation completes.

### Certificate rotation and PKI

The mesh issues short-lived certificates (typically 24 hours) to each sidecar. Rotation is automatic. If the control plane is unavailable for longer than the certificate lifetime, sidecars start rejecting connections because their certificates have expired and no new ones can be issued.

This is the key operational risk of a mesh: the control plane's availability determines whether services can communicate after certificate expiry. Operate the control plane with the same care as a critical infrastructure component. Multi-replica control plane deployment, monitored, with alerts on certificate issuance failures.

## Deep Dive: service mesh on AWS

**AWS App Mesh.** AWS-managed control plane. Envoy sidecars on ECS tasks or EKS pods. Integration with AWS Certificate Manager Private CA for certificate issuance. CloudWatch and X-Ray for metrics and traces. The mesh configuration is defined as AWS resources (VirtualService, VirtualNode, VirtualRouter) — managed via Terraform or CloudFormation alongside the rest of the infrastructure.

App Mesh's managed control plane removes the operational burden of running `istiod`. The trade-off: less feature richness than Istio, less configurability. For teams that want mesh capabilities without the overhead of a self-managed control plane, App Mesh is the practical choice on AWS.

**AWS Cloud Map integration.** App Mesh uses Cloud Map for service discovery. VirtualNodes reference Cloud Map service names. When a task starts and registers with Cloud Map, App Mesh's control plane updates Envoy's endpoint configuration. The mesh tracks fleet membership automatically.

**Istio on EKS.** Full Istio feature set: traffic management, mTLS, circuit breaking, fault injection, traffic mirroring, JWT-based authorization policies. `istiod` runs as a Deployment in the cluster. Managed with Helm or the Istio operator. Higher operational burden than App Mesh — you're responsible for `istiod` availability, upgrades, and configuration.

Istio on EKS with AWS-managed add-ons: AWS contributes to the upstream Istio project and maintains compatibility. Use EKS managed node groups with adequate memory per node — each Envoy sidecar's memory consumption adds to the node's baseline. Underestimating this leads to OOM events on nodes as sidecar count grows.

**AWS Service Connect.** A lighter-weight alternative to a full service mesh, integrated into ECS. Services register with Service Connect and discover each other by name. Envoy proxies handle the traffic with built-in connection management, circuit breaking, and basic observability. No separate control plane to manage — Service Connect configuration is part of the ECS service definition. Appropriate for ECS workloads that want proxy-based reliability features without the full operational complexity of App Mesh or Istio.

| Feature | App Mesh | Istio on EKS | Service Connect |
|---|---|---|---|
| mTLS | Yes (ACM PCA) | Yes (built-in CA) | No |
| Traffic splitting | Yes | Yes | Limited |
| Circuit breaking | Yes | Yes | Yes |
| Fault injection | Limited | Yes | No |
| Control plane | AWS-managed | Self-managed (`istiod`) | ECS-integrated |
| Observability | CloudWatch + X-Ray | Prometheus + Jaeger/Zipkin | CloudWatch |
| Operational overhead | Low | High | Very low |
| Best for | AWS-native, managed simplicity | Full feature set, EKS | ECS workloads, simpler use cases |

## What's next

Day 39: infrastructure as code and GitOps — treating infrastructure definitions as code with the same review, version control, and deployment discipline as application code, and the operational patterns that keep infrastructure state from drifting.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
