# Agentic AI Fundamentals for DevOps Engineers
### Part 1 of the [Agentic AI series](./README.md)

> This series assumes you've already read [GenAI vs Agentic AI, part 1](../ai-devops/genai-vs-agentic-ai-part1.md). That article draws the conceptual line between "AI that helps you think" and "AI that acts on your behalf." This file picks up right at that line and gets into how the "acts on your behalf" part is actually built.

---

## Chatbot, workflow, or agent — pick the right word

These three get used interchangeably in job postings and vendor pitch decks, and they're not the same thing. Getting the distinction straight up front saves you from over-building or under-building later.

**A chatbot** answers questions in a single turn (or a conversation of turns) and doesn't take action. You ask, it answers, you decide what to do with the answer. This is generative AI, full stop.

**A workflow** is a fixed sequence of steps, some of which might call an LLM, but the *order* and *branching logic* are decided by your code, not by the model. "Call the LLM to summarize the ticket, then always create a Jira issue, then always post to Slack" — that's a workflow with an LLM step bolted on. It's deterministic and easy to reason about, which is exactly why you should prefer it when it's sufficient.

**An agent** is a system where the model itself decides, at each step, what to do next — which tool to call, whether it has enough information, whether the task is done — based on what it's observed so far. The control flow lives in the model's reasoning, not in your `if` statements. That's the defining feature, and it's also exactly what makes agents harder to test, debug, and secure than a workflow.

| | Chatbot | Workflow | Agent |
|---|---|---|---|
| Who decides what happens next | The user, after reading the response | Your code | The model, at each step |
| Number of steps | Usually one exchange | Fixed, known in advance | Variable, decided at runtime |
| Predictability | High | High | Lower — same input can take a different path |
| Where the risk lives | What it says | What your code does | What the model decides to do |

If a fixed sequence of steps solves your problem, build the workflow. It'll be cheaper, faster, easier to debug, and easier to get through a security review. Reach for an agent only when the *path* genuinely can't be known ahead of time — the number of steps, or which tool is needed, depends on what earlier steps turned up.

---

## The agent loop

Every agent, regardless of framework, is some variation of the same loop. This pattern has a name — **ReAct** (Reason + Act) — and it's worth knowing the name because you'll see it in framework docs and papers.

```
┌─────────────────────────────────────────────────────────┐
│                                                           │
│   1. OBSERVE  — read the current state: the original     │
│      goal, prior tool results, conversation so far        │
│                                                           │
│   2. REASON   — the model decides: do I have enough       │
│      info to finish? if not, what's the next action?      │
│                                                           │
│   3. ACT       — call a tool (query an API, run a          │
│      command, search a knowledge base)                    │
│                                                           │
│   4. OBSERVE the result of that action  ──────────────────┘
│      (loop back to step 2, or stop if the goal is met)
│
└── stop condition: goal reached, max steps hit, or a
    guardrail intervenes
```

Walk it through a concrete example — an agent asked to "find out why checkout-api's error rate spiked":

1. **Observe:** goal = diagnose the error rate spike. No tool results yet.
2. **Reason:** "I should check recent deploys first."
3. **Act:** calls a `get_recent_deploys(service="checkout-api")` tool.
4. **Observe:** a deploy went out 12 minutes ago.
5. **Reason:** "That timing matches. Let me check the diff."
6. **Act:** calls `get_deploy_diff(deploy_id=...)`.
7. **Observe:** the diff lowered a connection pool size.
8. **Reason:** "That's almost certainly the cause. I have enough to answer."
9. **Stop:** returns a summary and a suggested rollback.

Nothing here is magic — it's a `while` loop where the "what do I do next" decision is made by a model call instead of your own code. That's the whole trick, and also the whole risk surface: your code no longer controls which branch gets taken.

---

## The building blocks every agent has

| Component | What it does | DevOps equivalent you already know |
|---|---|---|
| **Model** | Does the reasoning at each step | The "brain" — not much of an analogy needed |
| **Tools** | Functions the model can choose to call | An API surface — see [file 04](./04-tool-use-and-function-calling-design.md) |
| **Memory / state** | Tracks what's happened so far in the run | Application state, or a reconciliation loop's "observed state" — see [file 02](./02-agent-memory-context-and-state.md) |
| **Loop controller** | Decides when to stop: goal met, max steps, error | A circuit breaker or a retry-with-max-attempts guard |
| **Guardrails** | Constraints the loop controller can't override | IAM policy, network egress rules, admission controllers |

If you've built a Kubernetes controller, an autoscaler, or anything with a reconcile loop, this shape should feel familiar: observe current state, decide the next action, take it, observe again. The difference is that a controller's "decide" step is deterministic code you wrote; an agent's "decide" step is a probabilistic model call. Same loop shape, very different reliability guarantees — which is exactly why guardrails matter so much more here than in a controller you wrote yourself.

---

## A minimal loop, in plain Python

Stripped of any specific framework, this is roughly what's happening under the hood of every agent SDK:

```python
def run_agent(goal: str, tools: dict, max_steps: int = 10) -> str:
    messages = [{"role": "user", "content": goal}]

    for step in range(max_steps):
        response = call_model(messages, available_tools=tools)

        if response.is_final_answer:
            return response.content

        # The model chose a tool and provided arguments for it
        tool_name = response.tool_call.name
        tool_args = response.tool_call.arguments

        if tool_name not in tools:
            messages.append({"role": "tool_error", "content": f"Unknown tool: {tool_name}"})
            continue

        result = tools[tool_name](**tool_args)
        messages.append({"role": "tool_result", "content": result})

    return "Stopped: max steps reached without a final answer"
```

Every framework — LangGraph, CrewAI, the Anthropic and OpenAI SDKs, AWS Strands — is a more capable, more ergonomic version of this same shape: a loop, a model call that can request a tool, a tool execution step, and a stop condition. Once this loop is clear in your head, reading any framework's docs gets a lot faster — you're mapping their vocabulary onto a shape you already understand instead of learning the shape from scratch.

---

## When not to build an agent

This repo's whole ethos is "understand, don't memorize," and understanding an agent loop includes understanding when it's the wrong tool.

**Skip the agent if:**
- The steps and their order are always the same — write a workflow, it'll be faster and far easier to test.
- The task doesn't need real-time information or tool access — a single LLM call (generative AI, no loop) is enough.
- You can't tolerate variable latency or variable cost — an agent might take 2 steps or 12 depending on the input, and your bill and your p99 will reflect that.
- You can't afford the failure modes — an agent that loops, calls the wrong tool, or takes 12 steps to answer a question a script would answer in one deterministic call is a real cost and reliability trade-off, not a hypothetical one.

**Reach for an agent when:**
- The number and order of steps genuinely depends on what earlier steps discover (diagnosing an unknown incident, for example, where the second command you'd run depends on what the first one returned).
- The tasks are open-ended enough that hardcoding every branch would mean re-implementing a large chunk of your team's judgment as `if` statements.

A good rule of thumb from teams who've shipped this in production: try the deterministic workflow first. Reach for an agent only once you can point at the specific decision point where a fixed script keeps breaking because the right next step actually varies.

---

## Failure modes to keep in the back of your mind

This is a preview — each gets real coverage later in the series:

- **Runaway loops** — the model keeps calling tools without converging on an answer. Always set a `max_steps` (as in the example above) as a hard stop, not a suggestion.
- **Wrong tool, confidently** — the model calls a plausible-looking tool that isn't actually right for the situation. Tool descriptions matter more than people expect — see [file 04](./04-tool-use-and-function-calling-design.md).
- **Cost blowups** — every step is a model call, and model calls cost tokens. A 15-step run on an expensive model adds up fast, especially under load.
- **Excessive agency** — the agent has more tool access than the task actually needs, so a mistake (its own or an attacker's) has a bigger blast radius than it should. See [file 05](./05-agentic-ai-security-threat-model.md).

---

## Cheatsheet

```
Chatbot   → one answer, no action, human decides what happens next
Workflow  → fixed steps, your code decides the order, LLM is just a step
Agent     → the model decides the next action, at each step, until it stops

The loop: observe → reason → act → observe → ... → stop

Building blocks: model, tools, memory/state, loop controller, guardrails

Default to a workflow. Reach for an agent only when the path
genuinely can't be known ahead of time.
```

---

**Next:** [`02-agent-memory-context-and-state.md`](./02-agent-memory-context-and-state.md) — what an agent actually remembers between steps, and why that's a harder problem than it sounds.
