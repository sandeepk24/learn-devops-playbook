# Agent Memory, Context, and State
### Part 2 of the [Agentic AI series](./README.md)

> Builds on [file 01](./01-agentic-ai-fundamentals-for-devops.md). If you haven't read that one, the agent loop (observe → reason → act → observe) is the frame this whole file hangs off of.

---

## Why this is harder than "just keep the conversation history"

An LLM has no memory between calls by default — every call is stateless. What looks like an agent "remembering" earlier steps is really your system re-sending the entire relevant history back to the model on every single call. That has two consequences DevOps engineers should recognize immediately:

1. **It costs money and latency every time**, proportional to how much history you're carrying — the same trade-off as sending your full log history with every request to a log-analysis API instead of just what's new.
2. **It's bounded.** Every model has a maximum context window (measured in tokens), and a long-running agent that keeps appending every tool result to the conversation will eventually hit that ceiling — the model equivalent of a process slowly leaking memory until something OOMs.

So "agent memory" isn't one feature — it's a set of decisions about what to keep, what to summarize, what to drop, and what to persist outside the conversation entirely.

---

## Two kinds of memory, and they solve different problems

**Short-term (working) memory** — everything relevant to the *current run*: the goal, the steps taken so far, the tool results collected. This lives in the context window and disappears once the run ends, unless you explicitly persist it.

**Long-term memory** — information that needs to survive across runs and sessions: what happened in yesterday's incident, a user's stated preferences, facts about your infrastructure that don't change often. This has to be stored somewhere outside the model — a database, a vector store, a key-value store — and explicitly retrieved back into context when it's relevant.

| | Short-term | Long-term |
|---|---|---|
| Lives in | The context window, for this run | An external store (DB, vector store, cache) |
| Survives | Until the run ends | Across runs, sessions, restarts |
| Typical size | A few thousand to a few hundred thousand tokens | Effectively unbounded |
| Retrieval | Automatic — it's just "what's already in the conversation" | Explicit — you query for it, then inject it |
| DevOps analogy | A process's in-memory state | A database, or your metrics backend |

---

## Managing the context window (short-term memory)

The naive approach — append every tool result to the conversation forever — works fine for a 3-step agent and falls over for a 30-step one. A few patterns that actually scale:

**Truncation / sliding window.** Keep only the last N steps in full detail, and drop or compress anything older. Simple, and fine when older steps genuinely stop mattering (a health-check agent rarely needs the full detail of a check from 20 steps ago).

**Summarization.** Periodically compress older steps into a short summary instead of dropping them outright — "steps 1–5: checked recent deploys, found none in the last hour; checked connection pool, found it at 40% capacity, ruled out." This trades some detail for keeping the gist available across a long run, which matters when an early observation is still relevant much later.

**Selective retrieval instead of full history.** Rather than replaying every raw tool result, store them somewhere addressable (a scratchpad object, a small database) and let the agent explicitly fetch only what it needs for the current step — closer to how you'd query a log aggregator for the specific window you care about instead of tailing the entire history.

```python
from dataclasses import dataclass, field

@dataclass
class AgentScratchpad:
    """Tracks state for a single agent run — a lightweight version of what
    frameworks like LangGraph call 'agent state.'"""
    goal: str
    steps_taken: list[dict] = field(default_factory=list)
    summary_of_older_steps: str = ""

    def add_step(self, tool_name: str, arguments: dict, result: str):
        self.steps_taken.append({
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
        })
        if len(self.steps_taken) > 10:
            self._compress_oldest_steps()

    def _compress_oldest_steps(self):
        oldest = self.steps_taken[:5]
        self.summary_of_older_steps += f" Then: {[s['tool'] for s in oldest]} were run."
        self.steps_taken = self.steps_taken[5:]
```

If this reminds you of the [Pydantic guide](../python/python_pydantic_devops_guide.md), that's not an accident — in real agent code, this scratchpad is almost always a Pydantic model, not a plain dataclass, specifically so malformed tool results get caught at the boundary instead of silently corrupting the agent's state mid-run.

---

## Long-term memory patterns

**Vector store retrieval** is the pattern behind most "the agent remembers past conversations" or "the agent knows our internal docs" features. Past interactions or documents get embedded and stored; at the start of a run (or at a specific step), the agent's current goal is embedded too, and the most similar stored items are pulled back into context. This repo already covers the mechanics in depth — see the [embedding models series](../aws/embedding-models-part-1-concepts.md) and the [RAG knowledge base guide](../ai-devops/rag-knowledge-base-devops-runbooks.md) for the retrieval side; this file is just naming where it plugs into the agent loop.

**Key-value / structured state** is simpler and underused: if what you need to remember is a small number of structured facts ("last successful deploy hash," "current on-call engineer," "known-flaky test list"), a plain database row or a Redis key is a better fit than a vector store. Not everything that needs to persist needs semantic search — most operational facts are looked up by exact key, not by similarity.

**Session state in a real database** is what you want for anything resembling "resume this agent run later" or "this conversation continues tomorrow" — store the scratchpad, the goal, and the step history as a row, keyed by a session ID, exactly like you'd persist a workflow's state in a durable execution engine.

---

## Treat agent state like a reconciliation loop

This is the framing that should feel most natural to a DevOps engineer: an agent's state, at any point mid-run, is just **observed state** — what's true so far, as far as the agent knows. The goal is **desired state** — what "done" looks like. The loop's job, on every iteration, is to compare the two and decide the smallest next action that closes the gap.

This is precisely the model behind a Kubernetes controller: read current state, compare to desired state, take one action, re-read, repeat. Making that comparison explicit in your agent's design — instead of leaving "have I made progress toward the goal" as an implicit judgment buried in a prompt — is one of the more effective ways to keep a long-running agent from wandering.

---

## Where this goes wrong

**Unbounded memory growth.** An agent that appends every tool result forever, with no truncation or summarization, will either blow the context window or (if you've built naive truncation that just cuts off the *oldest* messages) silently drop the system prompt or the original goal off the front of the conversation. Always cap growth deliberately, and know which end of the history you're trimming from.

**The "goldfish" agent.** Overcorrect the other direction — too aggressive truncation — and the agent forgets a critical fact from three steps ago and repeats work or contradicts itself. If you're seeing an agent re-run a check it already ran, that's usually a memory management bug, not a reasoning bug.

**Context that never resets.** For a long-lived agent (a chat session, a monitoring loop), carrying every past session's full detail forward means every new run starts more expensive and more likely to hit the ceiling than the last. Decide explicitly what carries over between sessions and what starts fresh.

**Leaking secrets into memory.** If a tool result contains a credential, a token, or PII, and that result gets logged, summarized, or stored in long-term memory without scrubbing, you've just given that secret a much longer lifespan and a much wider blast radius than it had sitting in a single API response. Treat anything that goes into persisted agent memory with the same care you'd apply to anything going into a log aggregator — because functionally, that's what it is.

---

## Cheatsheet

```
Short-term memory  → lives in the context window, for one run, disappears after
Long-term memory   → lives outside the model, persisted, explicitly retrieved

Context window management:
  - truncation / sliding window   (drop the oldest, simplest)
  - summarization                  (compress instead of drop)
  - selective retrieval             (store externally, fetch only what's needed)

Long-term storage:
  - vector store    → semantic recall (past docs, past conversations)
  - key-value / DB  → exact-match facts (last deploy hash, on-call engineer)
  - session table    → resumable agent runs

Mental model: agent state = observed state, goal = desired state,
each loop iteration closes the gap — same shape as a k8s controller.

Watch for: unbounded growth, over-truncation, stale cross-session context,
secrets leaking into persisted memory.
```

---

**Next:** [`03-multi-agent-orchestration-patterns.md`](./03-multi-agent-orchestration-patterns.md) — when one agent isn't enough, and the patterns for coordinating more than one.
