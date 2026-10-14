# DNS and Service Discovery

Services need to find each other. In a static environment with fixed IPs, this is a configuration problem. In a dynamic fleet where instances come and go, containers scale up and down, and deployments replace endpoints constantly, it becomes an infrastructure problem. That infrastructure is service discovery, and in most systems DNS is at the center of it.

Problems that look like application failures often trace back to DNS. Wrong IP cached past its TTL. Service registered as healthy after a deployment hasn't started listening yet. Pod IP recycled by Kubernetes before old entries expired. DNS is quiet infrastructure that only gets noticed when it breaks — and it breaks in ways that are genuinely hard to diagnose if you don't know to check it.

## Fundamentals

### What service discovery solves

Static configuration breaks the moment anything changes. IP address of a database node changes — every service that had that IP hardcoded is now broken. New backend instance added to the pool — traffic won't reach it until someone updates the config. Deployment replaces ten containers with ten new ones at new IPs — nothing routes to them until the change propagates.

Service discovery replaces static configuration with a registry. Services register themselves when they start, deregister when they stop. Clients look up the current set of healthy endpoints at runtime rather than reading from a config file written at deploy time.

Two broad models:

**Client-side discovery.** Client queries the registry directly, gets a list of healthy instances, picks one using its own load balancing logic. More control. More code in the client. Every language and framework needs its own implementation.

**Server-side discovery.** Client queries a load balancer or proxy. The load balancer queries the registry and routes the request. Client is decoupled from the registry entirely. This is the model ALB uses with ECS or EKS target groups.

### DNS as a service discovery mechanism

DNS is the oldest and most ubiquitous service discovery layer. A service name resolves to one or more IP addresses. Change the IP, update the record, propagation follows TTL.

**A records.** Name to IP. Can return multiple IPs for basic load distribution. Clients typically use the first one returned, sometimes cycling through on retry.

**SRV records.** Name to host plus port plus priority plus weight. Designed for service discovery — encodes the port alongside the address, supports weighted routing. Used by Kubernetes headless services, etcd clusters, and various service mesh implementations.

**DNS-based health.** Route 53 health checks can remove unhealthy endpoints from a record automatically. An A record backed by three IP addresses drops to two when one fails its health check. Clients re-resolve after TTL and get only healthy IPs.

The TTL problem: DNS caches at every layer — resolver, OS, application. A record update propagates only after every cache in the chain has expired. Aggressive short TTLs (30 seconds or less) make propagation fast but increase DNS query volume. Long TTLs mean faster resolution but slower failover. In dynamic environments, short TTLs are almost always the right call.

### Health checks and registration lifecycle

Service discovery is only useful if the registry reflects reality. A service registered as healthy that's actually failing is worse than no discovery at all — it actively routes traffic to a broken endpoint.

Registration on start is the easy part. The harder question: when does a service get marked healthy? Immediately on process start? After passing a health check? After being ready to serve traffic? These are different moments. A container that starts immediately registers but might take ten seconds to initialize its database connection pool and warm its caches. Registering before ready means traffic arrives before the service can handle it.

Deregistration is equally important. A process that crashes deregisters on SIGTERM — if it handles it cleanly. A process that gets OOM-killed or loses network connectivity might not deregister at all. Health check TTLs handle this: if a service stops sending heartbeats within a window, the registry marks it unhealthy and removes it from the pool.

## Operations

### TTL and cache poisoning in practice

The failure mode: service A has an old IP for service B cached. Service B moved. Service A's requests go to the old IP. Depending on what's listening at the old IP, the result is a connection refused (fast failure, easy to diagnose) or a timeout (slow failure, much harder).

In Kubernetes, Pod IPs are recycled. A pod terminates, its IP returns to the pool, another pod starts with that IP later. If a client has that IP cached with a long TTL from a previous DNS lookup, it might accidentally reach the new pod when it intended to reach the old one. This is usually harmless when the new pod runs the same service, but it's the exact mechanism behind some bizarre routing bugs in misconfigured clusters.

Check TTLs. Use `dig` or `nslookup` to see what TTL a record is returning. In Route 53, default TTLs are 300 seconds. For records tied to auto-scaling groups or container fleets, 30–60 seconds is more appropriate. For records backed by Route 53 health checks, the effective failover time is approximately: health check interval × failure threshold + TTL. Configure with that math in mind.

### Split-horizon DNS

Internal services shouldn't be reachable from the public internet, and internal DNS records shouldn't resolve outside the VPC. Split-horizon DNS serves different answers based on where the query originates. A name resolves to a private IP inside the VPC and a public IP or nothing at all outside it.

AWS Route 53 Private Hosted Zones do this. The same domain can have a public hosted zone (for external clients) and a private hosted zone (for internal services). The private zone overrides the public zone for queries originating inside the associated VPC. Services use the same hostnames regardless of environment; the DNS layer handles the routing difference.

### Debugging DNS problems

The sequence when a service-to-service call is failing and you suspect DNS:

1. `dig <hostname>` from inside the failing service's network namespace. Does it resolve? What does it resolve to?
2. Check the TTL on the response. Is a stale entry cached somewhere?
3. Verify the returned IP is actually listening on the expected port: `curl -v` or `telnet`.
4. Check the service registry (Consul, Cloud Map, ECS service discovery) for the registered endpoints and their health status.
5. Compare what's registered to what's running. Mismatches usually indicate a registration or deregistration timing problem.

`nslookup` and `dig` are often not installed in minimal container images. `getent hosts <hostname>` uses the system resolver and is almost always available. It also respects `/etc/resolv.conf` and `/etc/nsswitch.conf`, so it shows what the application actually sees — not just what an external DNS query returns.

## Deep Dive: service discovery on AWS

**Route 53 + Health Checks.** The standard for service-to-service routing in non-container workloads. A record backed by health checks. Unhealthy endpoints are automatically removed from responses. Works across regions with latency-based, weighted, and failover routing policies. Failover routing specifically: a primary record serves traffic when healthy; if health checks fail, Route 53 returns the secondary record automatically.

**AWS Cloud Map.** Managed service registry. Services register instances with attributes (IP, port, metadata). Route 53 DNS records are created automatically for registered services. Health checks are integrated. Works with ECS, EKS, and arbitrary compute. ECS can integrate with Cloud Map directly — tasks register on start, deregister on stop, health checks managed by the ALB or a custom health check.

**ECS Service Discovery.** Built on Cloud Map. Enabled at service creation. Each task gets a DNS record in a private hosted zone: `<service>.<namespace>`. Other ECS services resolve the name and get the IPs of all healthy tasks. No load balancer required for service-to-service calls inside the cluster — DNS returns all task IPs, client round-robins. Useful for gRPC and other non-HTTP protocols that ALB doesn't support well.

**CoreDNS in Kubernetes.** The cluster DNS server. Every service gets a DNS name: `<service>.<namespace>.svc.cluster.local`. Pods resolve service names; CoreDNS returns the ClusterIP of the matching Service. The Service then load-balances to healthy pod IPs via kube-proxy or eBPF. For headless services (`clusterIP: None`), CoreDNS returns the individual pod IPs directly, enabling client-side load balancing or direct pod addressing.

CoreDNS configuration is a ConfigMap. Default caching TTL is 30 seconds. If you're seeing stale DNS in Kubernetes and it's causing issues, the CoreDNS cache is the first place to check. `ndots` setting in pod DNS config affects how many dots a name needs before it's treated as a fully qualified domain name — misconfigured `ndots` causes every external DNS lookup to generate several failed internal queries first, adding latency.

| Mechanism | Best for | Limitation |
|---|---|---|
| Route 53 A + health checks | EC2/Lambda service endpoints | TTL-bounded failover speed |
| Route 53 Private Hosted Zones | Internal service naming | Requires VPC association |
| AWS Cloud Map | Container and arbitrary workloads | Adds registration logic to deployment |
| ECS Service Discovery | ECS service-to-service (non-HTTP) | DNS round-robin only, no weighted routing |
| CoreDNS (Kubernetes) | Pod-to-service resolution in EKS | `ndots` misconfiguration is a common tax |

## What's next

Day 15: API design and versioning — how to change an API without breaking the clients that depend on it, and the versioning strategies that fail more gracefully than others.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
