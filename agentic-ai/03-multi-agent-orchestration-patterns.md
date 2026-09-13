# Multi-Agent Orchestration Patterns
### Part 3 of the [Agentic AI series](./README.md)

> Builds on [file 01](./01-agentic-ai-fundamentals-for-devops.md) (the agent loop) and [file 02](./02-agent-memory-context-and-state.md) (memory). This file is about what happens once one agent isn't enough and you're coordinating more than one.

---

## Why split into multiple agents at all

The reasoning is the same reasoning behind splitting a monolith into microservices, and it comes with the same trade-offs. A single agent with 40 tools and a sprawling system prompt trying to do "incident response, deployment, and cost analysis" is harder to test, harder to reason about, and more likely to pick the wrong tool than three focused agents that each do one of those things well. You're trading simplicity of a single process for clearer boundaries, specialization, and (sometimes) parallelism — and you're taking on the same coordination overhead and cross-service debugging pain that comes with any distributed system.

Don't reach for multiple agents by default. Start with one agent with a tight, well-scoped tool set (see [file 04](./04-tool-use-and-function-calling-design.md)). Split only once you can point at a specific problem a single agent is genuinely struggling with — usually too many unrelated tools confusing its tool choice, or a task that's naturally parallelizable and a single sequential loop is too slow.

---

## The patterns

### 1. Single agent, many tools

Not "multi-agent" at all, but it's the baseline everything else gets compared against. One agent, one loop, a focused set of tools. Simplest to build, test, and debug. The right choice for most tasks — most agent projects that reach for multi-agent architectures on day one would have shipped faster and more reliably as this.

### 2. Orchestrator–worker (hierarchical)

One "manager" agent breaks the task into subtasks and delegates each to a specialized worker agent, then combines their results. The manager doesn't do the detailed work itself — it decides *who* should, the same way an engineering lead breaks a project into tickets and assigns them rather than writing every line of code personally.

```
                ┌──────────────────┐
                │  Orchestrator     │
                │  agent            │
                └─────────┬─────────┘
             ┌─────────────┼─────────────┐
             ▼              ▼              ▼
      ┌────────────┐ ┌────────────┐ ┌────────────┐
      │ Worker:     │ │ Worker:     │ │ Worker:     │
      │ logs        │ │ metrics     │ │ deploy      │
      │ analysis    │ │ analysis    │ │ history     │
      └────────────┘ └────────────┘ └────────────┘
```

**Good for:** tasks that decompose cleanly into independent, specialized sub-problems — an incident-response agent that delegates "check logs," "check metrics," and "check recent deploys" to three focused sub-agents and synthesizes their findings. **Watch for:** the orchestrator itself becoming a bottleneck or a single point of failure, and errors from a worker getting misread or silently swallowed on the way back up — same failure shape as a flaky downstream service whose errors an API gateway masks instead of surfacing.

### 3. Pipeline / sequential handoff

Agent A finishes its work and hands a clean, structured result to Agent B, which hands off to Agent C. No back-and-forth — strictly linear, like stages in a CI/CD pipeline.

```
Agent A (triage) → Agent B (root cause analysis) → Agent C (draft the fix / runbook)
```

**Good for:** workflows where each stage genuinely depends on the previous one finishing, and each stage benefits from a different focused prompt/tool set. **Watch for:** treating this as fundamentally different from a plain workflow with LLM steps — often it isn't. If each stage is deterministic about *when* it runs (always triage, then always root-cause, then always draft), you may not need "agents" here at all — a workflow with an LLM call per stage is simpler and gets you the same result.

### 4. Peer-to-peer / swarm

Multiple agents communicate directly with each other, with no fixed hierarchy, negotiating who does what as they go. This is the pattern with the most flexibility and, honestly, the most operational risk — coordination is emergent rather than designed, which makes behavior harder to predict and harder to debug when something goes wrong.

**Good for:** genuinely exploratory, open-ended collaboration where the "who should do what" decision itself benefits from negotiation. **Reality check:** this is the least common pattern in production DevOps use cases specifically. Most real infrastructure and ops tasks have enough natural structure that orchestrator-worker or a pipeline fits better and is dramatically easier to observe and debug.

---

## Comparing them like you'd compare service architectures

| Pattern | Coordination style | DevOps analogy | Debugging difficulty |
|---|---|---|---|
| Single agent | N/A | A single well-scoped service | Low |
| Orchestrator–worker | Centralized delegation | API gateway + backend services | Medium |
| Pipeline | Linear handoff | CI/CD pipeline stages | Medium |
| Peer-to-peer swarm | Decentralized, emergent | Event-driven choreography, no central coordinator | High |

If you've ever had the "orchestration vs. choreography" debate for microservices, you've already had this debate. The same conclusion tends to hold: centralized coordination is easier to reason about and debug; decentralized coordination scales better in theory and is a lot harder to keep observable in practice. Most teams are better served starting centralized.

---

## The framework landscape, briefly and without picking a favorite

This moves fast enough that specifics age quickly — treat this as a map of categories, not a ranking.

| Framework | Rough shape | Where it fits in this repo |
|---|---|---|
| **LangGraph** | Graph-based orchestration — you define nodes (agents/steps) and edges (transitions) explicitly | General-purpose, framework-agnostic patterns like this series map onto it directly |
| **CrewAI** | "Crew" of role-based agents (a manager, specialists) with built-in delegation | Closest fit to the orchestrator–worker pattern above, out of the box |
| **AutoGen / AG2** | Conversational multi-agent framework — agents "talk" to solve a task | Leans toward the peer-to-peer pattern |
| **AWS Strands Agents** | Model-driven agent loop with native AWS tool integration | Covered in depth in [`strands-agents-bedrock-guide.md`](../ai-devops/strands-agents-bedrock-guide.md) |
| **Bedrock AgentCore** | Managed runtime for deploying agents, not a design framework itself | Covered in the [AgentCore series](../learning-amazon-bedrock-agentcore/README.md) — that's the "where does this run," this file is the "how is it shaped" |

Pick based on what your team can operate and debug, not on which one has the most GitHub stars this quarter. A framework that logs and traces every step clearly beats one with more features and a black-box execution model, every time you're the one on call for it.

---

## MCP vs. A2A — a distinction people mix up constantly

Both are protocols that exist so people stop building bespoke integrations for the tenth time, and they solve two different halves of the same problem:

**MCP (Model Context Protocol)** standardizes how an **agent talks to a tool** — a database, an API, a file system. It's the protocol between a model and the *systems* it acts on. Covered in full in the [MCP series](../mcp-server-for-devops/01-why-ai-needs-doors.md).

**A2A (Agent-to-Agent protocol)** standardizes how **one agent talks to another agent** — potentially built by a different team, on a different framework, hosted somewhere else entirely. It's the protocol between two *reasoning systems*, not between a reasoner and a plain tool.

```
   Agent  ──MCP──►  Tool / API / Database   (agent-to-system)
   Agent  ──A2A──►  Another Agent            (agent-to-agent)
```

Put concretely: your incident-response agent uses MCP to query Prometheus and CloudWatch (those are tools). If it needs to hand part of the investigation to a separate deployment-history agent that another team built and maintains on a different stack entirely, that handoff is the kind of problem A2A is meant to solve — a standard way for two independently-built agents to exchange a task and a result without one having to know the other's internals. See the [Bedrock agentic AI production guide](../aws/aws-bedrock-advanced-agentic-ai.md) for where A2A shows up concretely on AWS.

---

## Failure modes specific to multi-agent systems

**Coordination overhead.** Every hop between agents costs latency and, usually, a summarization or translation step — the same tax you pay for every network hop between microservices, except the "network call" here is a model call that also costs tokens.

**Error amplification.** A wrong or incomplete result from one agent gets passed to the next, which builds on it without necessarily catching the error — the multi-agent version of a bad value silently propagating through a data pipeline instead of failing where it started.

**Cost multiplication.** Three agents each doing a few reasoning steps is a lot more model calls than one agent doing the same total work. Multi-agent systems are almost never cheaper per task than a well-scoped single agent — the win, when there is one, is in quality, specialization, or parallel latency, not in cost.

**Debugging complexity.** When something goes wrong, you now need to trace it across multiple agents' individual reasoning steps, not just one — this is exactly the distributed tracing problem, and the fix is the same one you already know: structured, correlated logging/tracing across every agent in the system, with a shared run/trace ID. See the [OpenTelemetry series](../observability/opentelemetry-101-modern-observability.md) for the underlying tooling, and [monitoring AI agents in production](../ai-devops/how-to-monitor-ai-agents-in-production.md) for the AI-specific version of that same discipline.

---

## Cheatsheet

```
Single agent           → default choice; simplest to build and debug
Orchestrator–worker     → manager delegates to specialists, combines results
Pipeline                 → strictly linear handoff, stage to stage
Peer-to-peer swarm       → decentralized, most flexible, hardest to debug

MCP  = agent  ↔ tool/system      (the "hands")
A2A  = agent  ↔ another agent    (the "handshake" between reasoners)

Start with one agent. Split only when you can name the specific
problem a single agent can't solve.
```

---

**Next:** [`04-tool-use-and-function-calling-design.md`](./04-tool-use-and-function-calling-design.md) — what a "tool" actually is to a model, and how to design one that doesn't invite disaster.
