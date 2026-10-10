# Scalability: Vertical vs. Horizontal

Every design conversation hits the same wall eventually. Works fine now. What happens when it doesn't?

That's scalability. Usually the first real decision in any system, long before sharding or consensus or the fancier topics ahead. Get it wrong, and you spend two years fighting the consequences.

Two ways to answer "we need more capacity." Bigger box. More boxes. Most engineers know the textbook definitions. What doesn't get discussed enough: when each actually makes sense, and how expensive it is to guess wrong.

## Fundamentals

### The bigger box

Vertical scaling. Same machine, more resources — CPU, RAM, faster disk. Architecture stays unchanged. Database is still one database, app is still one process. Code doesn't know anything happened except everything got faster.

Tempting for a reason: almost free in engineering effort. Resize an instance, schedule a restart, done. No new failure modes, no new code paths, no distributed systems headaches. For early-stage systems, this is often the right call. I'd argue it's underused. People reach for horizontal because it sounds sophisticated, when a bigger instance would've bought six months at a fraction of the complexity.

But there's a ceiling. Physical. AWS sells a biggest instance. The cost curve goes from linear to absurd past a certain point. And the quieter problem: one machine is one point of failure, no matter how big. Scale vertically forever and you've built something fast right up until it isn't there at all.

### More boxes

Horizontal scaling. More machines, load spread across them. This is where load balancers, service discovery, and a significant chunk of this series originates — because the moment you have two instances of something, you've inherited an entire category of problems that don't exist when there's only one.

```
Vertical scaling                    Horizontal scaling

   ┌─────────┐                      ┌───────┐  ┌───────┐  ┌───────┐
   │  Bigger │                      │Instance│  │Instance│  │Instance│
   │   Box   │        vs.           │   1   │  │   2   │  │   3   │
   │         │                      └───────┘  └───────┘  └───────┘
   └─────────┘                           │          │          │
                                          └────┬─────┴────┬─────┘
                                          Load Balancer / Router
```

The upside is real. No hard ceiling. No single point of failure — losing one instance out of ten is a rounding error, not an outage. The cost: your application has to be built for it. State that lived comfortably in one process — sessions, in-memory caches, anything assuming "there's only one of me" — needs to move somewhere shared, get replicated, or get redesigned out of existence.

Not a small ask. That's why "just make it stateless" appears constantly in this literature. Not a platitude. Actual precondition for horizontal scaling to work.

## Operations

### Where people actually get this wrong

The common mistake isn't picking the wrong one. It's picking horizontal too early. A team stands up Kubernetes with autoscaling and five replicas for a service doing a few hundred requests a minute, when a single reasonably-sized instance would've handled it without breaking a sweat — and without anyone thinking about session affinity or distributed rate limiting.

Reasonable order of operations:

1. Scale vertically first. Buys time cheaply, adds no complexity.
2. Scale vertically again if there's room. Second upgrade usually cheaper than redesign.
3. Go horizontal only after hitting an actual ceiling — real, not hypothetical — or when availability requirements mean you can't tolerate a single point of failure regardless of size.

That third point matters as much as the ceiling. Sometimes you go horizontal not because one big box can't handle the load, but because you can't accept downtime when that box restarts or dies. Availability and raw capacity are different reasons for the same architectural move. Worth knowing which one is driving your decision, because they lead to different designs. Capacity-driven horizontal scaling can tolerate slow instance spin-up. Availability-driven usually can't.

### The stateless requirement isn't optional

One lesson from this article: horizontal scaling doesn't work — not "works poorly," doesn't work — unless your application is genuinely stateless, or state lives somewhere all instances see equally.

Shows up constantly in incident reviews. Someone scales horizontally, forgets sessions are in local memory, and now half the users randomly log out depending on which instance gets their request. Fix isn't a scaling fix. Architecture fix. Move sessions to Redis, to a database, or sign a token the client carries.

Same for anything you're tempted to keep local. File uploads waiting for processing. In-memory caches saving database round trips. Background job queues only one process knows about. Every one needs a shared home before horizontal scaling is safe. Not after.

## Deep Dive: what this looks like on AWS

Vertical scaling on AWS: resize an EC2 instance type, bump an RDS instance class, increase CPU/memory limits on an ECS task. Config change and restart. For RDS specifically, Multi-AZ failover lets you do this with minimal downtime — standby gets resized, promoted, traffic cuts over in seconds rather than minutes.

Horizontal scaling: Auto Scaling Group behind an ALB for EC2, or ECS/EKS service with replica count driven by target tracking — CPU, memory, custom CloudWatch metric like queue depth. Part that gets skipped: testing scale-in, not just scale-out. Everyone tests "can we handle a spike." Few test "what happens when load drops and we terminate half our instances." Do in-flight requests drop? Does connection draining work? Does anything break during the shrink? That's where incidents hide.

Middle path worth knowing. Don't have to pick one forever. Plenty of production systems scale vertically within a horizontal fleet — three or four generously-sized instances instead of thirty small ones. Get horizontal's fault tolerance without infrastructure to support hundreds of ephemeral nodes.

| | Vertical Scaling | Horizontal Scaling |
|---|---|---|
| Complexity added | Minimal | Significant — statelessness, discovery, load balancing |
| Ceiling | Hard limit (biggest instance) | Effectively unbounded |
| Single point of failure | Yes, always | No, if done correctly |
| Cost curve | Linear, then steep | Linear, roughly |
| Good first move for | Early-stage systems, unclear future load | Systems with proven, sustained scale needs |
| AWS mechanism | Instance resize, RDS class change | ASG + ALB, ECS/EKS with target tracking |

## What's next

Day 3: latency vs. throughput. Two numbers that sound identical, get optimized as if they're identical, and are often in direct tension.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
