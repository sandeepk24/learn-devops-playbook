# What is System Design for DevOps Engineers?

Most system design content is written for software engineers. Interview prep. "Design Twitter." They sketch boxes, draw arrows, and the interviewer nods as long as it looks coherent.

That's not your job.

You get paged at 2 AM when someone else's clever design collapses under real traffic. You explain, six months post-launch, why a system that sailed through staging now craters every Friday at 5 PM. This series won't pretend DevOps system design is a coding interview with infrastructure vocabulary bolted on. It isn't. It needs its own framework, and that's what we're building — 75 days, one piece at a time, starting with the question beneath all the others: what does "system design" actually mean from where you sit?

## Fundamentals

### Two different jobs wearing the same name

Ask a backend engineer to design something. Success means features work, the API is clean. Ask you? Different game entirely. You're expected to handle the happy path. What matters is what happens when things break. Does it degrade gracefully or fall off a cliff? Can someone half-asleep diagnose it from dashboards, or do they need to call the person who built it?

That gap shows up everywhere:

| | SWE System Design | DevOps System Design |
|---|---|---|
| Primary question | How do components talk to each other? | How does the system fail, and how do I know? |
| Success metric | Feature correctness | Availability, recoverability, blast radius |
| Time horizon | Ship it | Operate it for three years |
| Interview framing | "Design X" | "Design X to survive Y failure mode" |
| Artifact you own | The service | The platform the service runs on |

Neither column is wrong. They answer different questions. Most confusion in studying system design comes from reading left-column material while preparing for right-column work.

### Three questions worth memorizing

Lots of theory ahead. CAP theorem, consensus algorithms, sharding strategies. The full catalog. But almost everything gets evaluated the same way, and it reduces to three questions. Memorize these:

1. **What happens when this component is slow, not down?** Dead is easy. Routes around it, alarms fire, obvious. Slow is dangerous. Requests pile up, threads block, retries multiply load, and failure spreads to healthy components before anyone notices the source.
2. **What's the blast radius if this fails?** One customer? One AZ? One region? Everyone? This question often goes unasked until after the incident, when it suddenly matters a great deal.
3. **How do I find out this is failing before a customer tells me?** No answer? Design isn't done. You've just finished the part that's fun to whiteboard.

Every deep dive in this series returns to these three. Load balancers, databases, queues, pipelines. The questions stay fixed. Only the answers change.

## Operations

### "It depends" isn't a cop-out, it's the actual job

Early career, people want rules. Always use eventual consistency. Always put a queue in front. Always shard by user ID. Problem is, every rule is wrong in some situation that will eventually land on your desk, and memorizing patterns won't help when the pattern doesn't fit.

What you're building — what this series is trying to build in you — is a fast, reliable way to weigh trade-offs on the spot. In a real design review, nobody waits while you look it up.

In practice, that reasoning runs something like this:

```
Requirement stated
      │
      ▼
Is this a hard constraint or a preference?
      │
      ├── Hard (compliance, physics, SLA) ──► Design around it, non-negotiable
      │
      └── Preference (cost, dev velocity) ──► Weigh it: what do we
                                                give up, what do we gain
      │
      ▼
Does this decision survive a component failure?
      │
      ├── No ──► Redesign it, or write down the risk you're accepting
      │
      └── Yes ──► Ship it, instrument it, and revisit once you're an
                       order of magnitude bigger
```

That last step gets skipped constantly. A system built for ten thousand requests a day and one built for ten million aren't the same design scaled up. They're different systems that happen to solve the same problem. We'll cover exactly why when we hit capacity planning.

### The 3 AM test

Run every design through this filter: could the on-call engineer figure out what's wrong and fix it at 3 AM, half-asleep, without calling the person who built it?

If the answer is no, the design isn't done. Doesn't matter how clean the architecture diagram looks. This is the gap between those two columns above. Software engineering system design optimizes for healthy-state behavior. Yours has to hold up when things aren't healthy — because that's the only time anyone actually needs you.

## Deep Dive: how this series is going to work

Every article follows the same shape:

- **Fundamentals** — the concept alone, before implementation complicates it. Good for interviews, good for intuition.
- **Operations** — how the concept behaves under scale, failure, multi-region traffic, and cost pressure.
- **Deep Dive** — a real build, usually on AWS, naming actual services and their trade-offs.

Tables and decision flows throughout. Meant for scanning mid-incident, not reading once and forgetting.

What this series won't cover:

| This series covers | This series doesn't cover |
|---|---|
| Trade-offs between architectural patterns | Step-by-step Terraform or CDK for any one pattern |
| Why a design breaks under specific conditions | Vendor console click-throughs |
| Interview framing for design questions | Certification exam content |

Implementation-level depth lives in the existing build guides — Kubernetes networking, EKS/IRSA, AWS ECS deep dive.

## What's next

Day 2: scalability. The common mistake of reaching for horizontal scaling before confirming vertical scaling has hit its ceiling.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time. Star the repo to follow along, and open an issue if there's a failure mode you'd like to see covered.*

