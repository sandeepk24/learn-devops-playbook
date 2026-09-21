# LangChain and LangGraph for DevOps Architects — Part 2: State, Nodes, Edges, and Control Loops

> Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) AI-DevOps series.
>
> **Series map:**
> 1. Core architecture: Models, Prompts, LCEL, and where LangGraph comes in
> 2. **LangGraph in depth: state, nodes, edges, and control loops** (this post)
> 3. Tools and agents: giving the model hands, safely
> 4. Memory and retrieval: grounding the model in your own data
> 5. Running this in production: observability, evals, and cost control

---

## Recap, in one paragraph

Part 1 covered the three LangChain basics — a `ChatModel` for calling any provider the same way, a `ChatPromptTemplate` for building the request, and LCEL's `|` operator for wiring pieces into a straight-line chain. It also drew the line where a chain stops being enough: the moment you need branching, looping, or a step that can pause and pick back up later. That's the line LangGraph sits on. This post is about actually building on that side of the line.

---

## The four things a graph is made of

A LangGraph graph has exactly four moving parts. Once these click, everything else — agents, retries, human approval — is just a specific arrangement of these four things.

| Piece | What it is | Kubernetes analogy |
|---|---|---|
| **State** | A typed object (a `TypedDict` or a small class) that gets passed to every node and updated as the graph runs | The object you'd store in etcd — the source of truth for "where things stand right now" |
| **Node** | A plain Python function: takes the state, returns a dict of updates | A reconcile function inside a controller |
| **Edge** | The wiring between nodes — either fixed ("always go from A to B") or conditional ("check the state, then decide") | The watch/requeue logic that decides what gets reconciled next |
| **Checkpointer** | An optional component that saves the state after each node runs | The write to etcd that makes the object's status durable across a controller restart |

Let's take these one at a time with actual code, building up from Part 1's two-node example into something with a real loop.

---

## State: the object every node reads and writes

State in LangGraph isn't memory in the "chat history" sense (that's Part 4's topic). It's closer to a work order that gets passed from station to station, picking up more detail at each stop. You define its shape up front, the same way you'd define a CRD schema before writing a controller for it.

```python
from typing import TypedDict, Annotated
import operator

class IncidentState(TypedDict):
    ticket_id: str
    logs: str
    attempts: int
    context: Annotated[list[str], operator.add]  # append, don't overwrite
    answer: str
    needs_more_context: bool
```

That `Annotated[list[str], operator.add]` line is worth pausing on. By default, when a node returns `{"context": [...]}`, LangGraph **overwrites** the `context` field with whatever the node returned. Tagging a field with `operator.add` changes that to "append instead of overwrite" — so if node A returns one context chunk and node B returns another, you end up with both, not just the last one. This matters the same way it matters whether a Kubernetes status field is a single value that gets replaced or a list that accumulates conditions over time — get it wrong and you silently lose data every time a node runs.

---

## Nodes: plain functions, nothing magic

A node is a normal Python function. It takes the current state and returns a dict with only the fields it wants to change — you don't have to return the whole state back.

```python
def fetch_logs(state: IncidentState) -> dict:
    logs = log_client.get_recent(state["ticket_id"])
    return {"logs": logs}

def retrieve_context(state: IncidentState) -> dict:
    chunks = retriever.invoke(state["logs"])
    return {"context": chunks, "attempts": state["attempts"] + 1}

def draft_answer(state: IncidentState) -> dict:
    result = answer_chain.invoke({
        "logs": state["logs"],
        "context": "\n".join(state["context"])
    })
    return {"answer": result.content, "needs_more_context": "not enough context" in result.content.lower()}
```

Notice `draft_answer` calls `answer_chain.invoke(...)` — that's an LCEL chain from Part 1, called from inside a node. This is the point worth repeating: **a node is often just a chain you already built, wrapped in a function that reads from and writes to shared state.** LangGraph doesn't replace LCEL chains, it gives them somewhere to live when the workflow around them needs to branch or repeat.

---

## Edges: fixed vs. conditional

A fixed edge is what Part 1's example used — always go from A to B, no decision involved. A conditional edge is a function that looks at the current state and returns the name of whichever node should run next. This is the piece that turns a straight line into an actual loop.

```python
from langgraph.graph import StateGraph, END

def should_keep_retrieving(state: IncidentState) -> str:
    if state["needs_more_context"] and state["attempts"] < 3:
        return "retrieve_context"   # loop back
    return END                       # stop, we have enough (or we've tried enough)

graph = StateGraph(IncidentState)
graph.add_node("fetch_logs", fetch_logs)
graph.add_node("retrieve_context", retrieve_context)
graph.add_node("draft_answer", draft_answer)

graph.set_entry_point("fetch_logs")
graph.add_edge("fetch_logs", "retrieve_context")
graph.add_edge("retrieve_context", "draft_answer")

graph.add_conditional_edges(
    "draft_answer",
    should_keep_retrieving,
    {"retrieve_context": "retrieve_context", END: END}
)

app = graph.compile()

result = app.invoke({
    "ticket_id": "OPS-4821",
    "logs": "", "attempts": 0, "context": [], "answer": "", "needs_more_context": False
})
print(result["answer"])
```

Walk through what this actually does: fetch logs once, retrieve context, draft an answer, then check — if the answer says "I don't have enough context" and we haven't tried more than three times, go back and retrieve more context; otherwise stop. That's a loop with an exit condition, capped at a fixed number of attempts so it can't run forever.

Sound familiar? It's the same shape as a Kubernetes controller that keeps reconciling until a resource is `Ready`, except with a hard iteration cap standing in for the kind of backoff limit you'd put on a `CronJob` or a retrying HTTP client. You never want an unbounded retry loop in either world, for the same reason: a bug in the exit condition turns into an infinite loop. And every iteration here is a billed API call, not a free retry.

```
                 ┌──────────────┐
                 │  fetch_logs   │
                 └──────┬────────┘
                        ▼
              ┌──────────────────┐
        ┌────▶│ retrieve_context │
        │     └──────┬────────────┘
        │            ▼
        │     ┌──────────────┐
        │     │ draft_answer  │
        │     └──────┬────────┘
        │            ▼
        │     needs more context
        │     AND attempts < 3?
        │      /            \
        └─────yes            no
                               \
                                ▼
                               END
```

---

## Checkpointing: surviving a restart without starting over

Everything above runs `app.invoke(...)` once and returns a final result, all in one process, in memory. That's fine for a quick script. It's not fine for a long-running workflow where a node might call an external API that takes ten seconds, or where you want to pause after `draft_answer` and wait for a human to approve before continuing — a pattern we'll build fully in Part 3.

LangGraph's answer to this is a checkpointer: a plugin that saves the state after every node runs, keyed by a thread ID.

```python
from langgraph.checkpoint.memory import MemorySaver
# for real use: langgraph.checkpoint.postgres.PostgresSaver, or a Redis-backed one

checkpointer = MemorySaver()
app = graph.compile(checkpointer=checkpointer)

config = {"configurable": {"thread_id": "incident-OPS-4821"}}
result = app.invoke({"ticket_id": "OPS-4821", "logs": "", "attempts": 0,
                      "context": [], "answer": "", "needs_more_context": False}, config)

# Later — a new process, a new deploy, doesn't matter —
# resuming the same thread picks up from the last completed node,
# not from the start.
state = app.get_state(config)
print(state.next)  # which node would run next, if anything is still pending
```

This is directly equivalent to a controller reading current state from etcd after a restart instead of re-provisioning every resource from zero. The thread ID is your object's identity — the same role a resource name plays in a cluster. `MemorySaver` is fine for local dev; in production you'd point this at Postgres or Redis, the same way you wouldn't run a real controller against an in-memory store you lose on restart.

---

## Why this beats hand-rolled retry loops

You could write all of this yourself with a `while` loop and a database row tracking progress — plenty of teams do, and it works. What LangGraph buys you over that:

- **The state shape is explicit and typed**, so a new engineer reading the graph definition can see every field that gets passed around, instead of grepping through a service for every place a dict gets mutated.
- **The graph structure is inspectable.** `graph.get_graph().draw_mermaid()` gives you an actual diagram of your control flow — useful for a design review, and a lot faster than reading nested conditionals to reconstruct the same picture.
- **Checkpointing and resumption are built in**, instead of being a bespoke "save progress to a table" pattern you write once per project and maintain forever.
- **It composes with everything from Part 1.** A node can be an LCEL chain, a tool call, or a plain function — you're not locked into one shape.

**Do** start a graph with the smallest state object that solves the problem in front of you. Adding a field later is cheap; a bloated state object that nothing reads is just as much of a liability as an over-broad IAM role — something will eventually depend on it by accident.

**Don't** put anything in state that doesn't need to survive a checkpoint. Large blobs (full log files, entire documents) belong in a store you reference by ID, not inlined into the state object. Same reason you don't put a 50MB file into a Kubernetes ConfigMap.

---

## What you should be able to do after this post

- Define a `TypedDict` state shape for a workflow and know when a field needs `operator.add` instead of the default overwrite.
- Write a node function and know it's just a regular function, optionally wrapping a chain from Part 1.
- Write a conditional edge that creates an actual loop, with a hard cap so it can't run forever.
- Explain what a checkpointer buys you over an in-memory-only run, and why the thread ID matters.

Part 3 puts a graph like this to work with actual tools — giving the model the ability to call your APIs, and the guardrails that keep that from being a way to accidentally let an LLM run `kubectl delete` on production.

---

*This is Part 2 of a 5-part series in [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook). Part 1: Core architecture. Part 3: Tools and agents.*
