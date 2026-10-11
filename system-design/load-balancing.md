# Load Balancing

Every engineer knows what a load balancer does. Request arrives, gets routed to one of several backends. Basic. The part that matters — the part that shows up in incidents — is what happens at the edges: routing logic, health detection lag, connection draining, and what becomes of in-flight requests when a backend disappears mid-stream.

## Fundamentals

### Routing algorithms

Not all algorithms are interchangeable. The choice affects latency distribution, hot spots, and how gracefully the system behaves when backends aren't identical.

**Round robin.** Requests cycle through backends in order. Simple. Works well when backends are homogeneous and requests are roughly equal cost. Falls apart when either assumption breaks — slow backends accumulate connections while fast ones sit idle.

**Least connections.** Routes to the backend with the fewest active connections. Better than round robin when request cost varies. Still imperfect: doesn't account for connection weight or backend capacity differences.

**Weighted.** Assign weights to backends. Send proportionally more traffic to heavier-weighted nodes. Useful during rollouts — gradually shift traffic from old to new — and for heterogeneous fleets where some nodes are larger than others.

**IP hash / sticky sessions.** Hash the source IP, always route to the same backend. Maintains session affinity without server-side session storage. Brittle. NAT and IPv6 break the hash distribution. Clients behind a proxy look like one IP. Use sparingly, and only when you genuinely can't move state out of the server.

**Least response time.** Routes to the backend with the lowest combination of active connections and response latency. Closest to "send to whoever's actually handling requests fastest right now." Requires the load balancer to track response time per backend, which not all implementations do.

### Layer 4 vs Layer 7

Two fundamentally different operating modes.

**Layer 4** operates at the transport layer. TCP/UDP. Sees IP addresses and ports. Routes without inspecting the payload. Fast. Low overhead. Can't make routing decisions based on HTTP headers, URL paths, or cookies. Good for raw throughput when you don't need content-aware routing.

**Layer 7** operates at the application layer. Reads HTTP headers, paths, host names. Can route `/api/*` to one target group and `/static/*` to another. Terminate TLS. Inspect cookies for sticky routing. Costs more — parsing application-layer content is more expensive than passing packets. Worth it for any system where routing decisions depend on what's inside the request.

```
Layer 4 (TCP)                      Layer 7 (HTTP)

Client ──► LB ──► Backend          Client ──► LB ──► /api/*   ──► API fleet
                                                 └──► /static/* ──► CDN origin
                                                 └──► /ws/*    ──► WebSocket fleet
(no content inspection)            (full HTTP inspection, path/host routing)
```

### Health checks

Load balancers route around failed backends — but only if health checks catch the failure. The gap between "backend is broken" and "health check marks it unhealthy" is where requests go to die.

Health check configuration matters more than people give it credit for. Check interval, unhealthy threshold, what counts as healthy. An HTTP health check hitting `/health` that returns 200 tells you the process is alive. Tells you nothing about whether the database connection it needs is working, whether it's caught in a GC pause, or whether it's saturated and responding slowly. A shallow health check gives you a false sense of detection coverage.

## Operations

### Connection draining

When you take a backend out of rotation — deployment, scale-in, maintenance — requests already in flight on that backend need to finish. Abruptly removing a node drops those connections. The user gets an error.

Connection draining (AWS calls it deregistration delay) lets the load balancer stop sending new requests to a deregistering target while existing connections complete. Default on ALB is 300 seconds. For most services that's too long. A backend handling API calls with p99 under 500ms doesn't need five minutes. Set it to the p99 of your longest expected request, add a small buffer, and move on.

Skipping this tuning means deployments are noisier than they need to be, and scale-in events produce user-visible errors that feel like bugs when they're actually configuration.

### Thundering herd

Backend disappears. Load balancer shifts its traffic share to remaining nodes. If those nodes were already near capacity, the shifted traffic pushes them over. They slow down or fail. More backends disappear. Load concentrates further.

This cascades. Fast.

Protection: keep backends running well below saturation during normal operation. Circuit breakers at the service level. Autoscaling that responds before the fleet is overwhelmed, not after. The load balancer itself can't save you from a cascade — it just distributes traffic. If the fleet is undersized or the autoscaling lag is too high, you're relying on the balancer to solve a problem it wasn't designed to solve.

### Sticky sessions under horizontal scale

Sticky sessions are often a symptom of state in the wrong place. The sticky routing is a workaround, not a fix. When sticky backends fail — and they will — every user pinned to that backend loses their session regardless of what's stored on the remaining nodes.

If you're using IP hash or cookie-based stickiness because sessions live in server memory, that's the thing to fix. Move sessions to Redis or a database, make the app stateless, and the stickiness requirement goes away. The load balancer can then route freely, the fleet is genuinely resilient, and you've removed a class of incident.

## Deep Dive: load balancing on AWS

Three load balancer types. Different use cases.

**ALB (Application Load Balancer).** Layer 7. HTTP/HTTPS/WebSocket. Path-based and host-based routing. Native integration with ECS, EKS, Lambda. Target groups. Use this for any HTTP workload. Default choice.

**NLB (Network Load Balancer).** Layer 4. TCP/UDP/TLS. Extreme throughput, ultra-low latency overhead. Preserves source IP. Use when you need raw TCP routing, need to preserve client IP at the backend, or when protocol isn't HTTP. gRPC, custom protocols, gaming traffic, IoT.

**GLB (Gateway Load Balancer).** Layer 3. For routing traffic through third-party network appliances — firewalls, IDS/IPS. Specific use case. Most teams don't need it.

ALB health check tuning worth knowing: the default unhealthy threshold is 2 consecutive failures at 30-second intervals. That's 60 seconds before an instance is pulled. For services where failure is obvious and recovery is fast, drop the interval to 5–10 seconds and the threshold to 2. Detection time drops to 10–20 seconds. Not nothing, but substantially better than a minute of bad requests.

Access logs on ALB are disabled by default. Turn them on. `target_processing_time` breaks down how long the request spent at each stage. When latency spikes, this is the first place to look — it tells you whether time is being spent at the load balancer or at the backend, which are different problems with different fixes.

| | ALB | NLB |
|---|---|---|
| Layer | 7 (HTTP) | 4 (TCP/UDP) |
| Routing | Path, host, header, query | IP + port only |
| TLS termination | Yes | Yes (passthrough also supported) |
| Source IP preservation | Via X-Forwarded-For header | Native |
| Use case | HTTP APIs, microservices, containers | High-throughput TCP, non-HTTP protocols |
| Health check depth | HTTP status codes, response body | TCP connection, HTTP optional |

## What's next

Day 6: caching. Where it helps, where it silently lies to you, and the invalidation problem that makes it harder than it looks.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
