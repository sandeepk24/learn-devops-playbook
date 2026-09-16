# LangChain and LangGraph for DevOps Architects — Part 1: Core Architecture

> Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) AI-DevOps series.
>
> This is Part 1 of a 5-part series aimed at senior DevOps and platform architects who already know how to build and run production systems, and just need a straight answer on how LangChain and LangGraph actually fit together.
>
> **Series map:**
> 1. **Core architecture: Models, Prompts, LCEL, and where LangGraph comes in** (this post)
> 2. LangGraph in depth: state, nodes, edges, and control loops
> 3. Tools and agents: giving the model hands, safely
> 4. Memory and retrieval: grounding the model in your own data
> 5. Running this in production: observability, evals, and cost control

---

## Who this is for, and what it skips

You've already run a Kubernetes cluster, written a CI/CD pipeline from scratch, and debugged a distributed system at 2 AM. You don't need someone to explain what a control loop is, or why idempotency matters. What you need is a mapping from things you already understand to this new stack, so you can tell in five minutes whether a design is sound or whether someone bolted an LLM onto a cron job and called it an "agent."

This series skips the "what is AI" preamble entirely. Instead, we'll map each LangChain and LangGraph concept to something you already run: a Kubernetes reconciliation loop, a CI/CD pipeline stage, a message queue. By the end of Part 1 you'll have enough to read someone else's LangChain code and know what it's actually doing, plus a small working pipeline of your own.

---

## The one-sentence version

LangChain gives you three building blocks — a standard way to call a model, a standard way to build the prompt you send it, and a standard way to wire those calls together (LCEL). LangGraph sits on top of that and gives you a runtime loop, so a workflow can branch, retry, and hold state across multiple steps instead of running once and stopping.

That's the whole architecture. Everything else in the ecosystem (tools, memory, retrieval, agents) is built out of those two layers. If you understand this post, the rest of the series is just "here's how to use that loop for real work."

---

## Piece 1: Models — a standard socket, not a vendor

Every model provider (OpenAI, Anthropic, Bedrock, a local Ollama model) has its own SDK, its own request shape, its own way of streaming tokens back. If you wrote directly against each one, swapping providers means rewriting call sites. LangChain's `ChatModel` class is the adapter that hides that: same `.invoke()`, same message format, same streaming interface, no matter which provider is underneath.

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
response = model.invoke("In one sentence, what does ImagePullBackOff mean?")
print(response.content)
```

Swap the provider, keep the calling code:

```python
from langchain_aws import ChatBedrock

model = ChatBedrock(model_id="anthropic.claude-3-5-sonnet-20241022-v2:0")
# same .invoke(), same response shape as above
```

**The DevOps parallel:** this is the same job a load balancer's health-check config or a `kubectl` provider abstraction does for you — one interface, swappable backend. You don't rewrite your deployment scripts because you moved from one cloud provider's managed database to another; you change a connection string. Same idea here: you change a class name and a model ID, not your prompt logic, your parsing logic, or your tool definitions.

One thing worth internalizing early: **the model itself has no state and no memory.** Every call is a fresh request-response, exactly like a stateless HTTP call to an API. If a workflow needs to remember what happened three steps ago, that memory has to live outside the model, in your code. We'll come back to this — it's the entire reason LangGraph exists.

---

## Piece 2: Prompts — config, not a string you type once

The word "prompt" makes people think of typing a question into a chat window. In a production system, a prompt is a template with variables, the same way a Terraform file has variables or a Helm chart has values. You write it once, parameterize it, and fill in the blanks per request.

```python
from langchain_core.prompts import ChatPromptTemplate

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a DevOps assistant. Answer using only the provided context. "
               "If the context doesn't cover the question, say so instead of guessing."),
    ("human", "Context:\n{context}\n\nQuestion: {question}")
])

filled = prompt.invoke({
    "context": "Deployment failed: ImagePullBackOff on pod api-server-7d9f",
    "question": "What's the likely cause?"
})
```

Two things matter here, and both map to habits you already have:

- **Treat prompts like config, not like inline strings.** Put them in version control, review changes in a pull request, and write a test that checks the output didn't silently get worse when someone edited the wording. A prompt change is a behavior change, same as a config change to a rate limiter or a retry policy — it deserves the same review bar.
- **The system message is your policy, not a suggestion.** It's the closest thing this stack has to an RBAC rule or a pod security policy: it sets the boundaries the model is supposed to operate inside. It won't enforce anything on its own (more on that in Part 3, when we talk about tools and guardrails), but it's the first line of defense and it's cheap to get right.

---

## Piece 3: LCEL — the pipe operator, not a new idea

LCEL stands for LangChain Expression Language. Don't let the name make it sound bigger than it is: it's the `|` operator, the same symbol you already use to chain shell commands, applied to LangChain components.

```python
chain = prompt | model | parser
```

Read that exactly like a shell pipeline: output of the left side becomes input to the right side. `prompt` builds the message, `model` sends it and gets a response, `parser` cleans that response into whatever shape you want back (a plain string, a JSON object, whatever). Nothing about this is clever — it's function composition with a readable syntax, the same reason you like `grep | sort | uniq -c` more than one script that does all three things in a row with no clear seams.

Here's a complete, runnable example — the smallest realistic LangChain pipeline:

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import StrOutputParser

# 1. The template
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a DevOps assistant. Answer using only the provided context. "
               "If the context doesn't cover the question, say so instead of guessing."),
    ("human", "Context:\n{context}\n\nQuestion: {question}")
])

# 2. The model
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# 3. The output parser (just pulls the plain text out of the response)
parser = StrOutputParser()

# 4. Wire them together
chain = prompt | model | parser

# 5. Run it
answer = chain.invoke({
    "context": "Deployment failed: ImagePullBackOff on pod api-server-7d9f. "
               "Image tag in the manifest is api-server:1.4.2-rc but the "
               "registry only has tags up to 1.4.1.",
    "question": "What's the likely cause, in one line?"
})

print(answer)
# Something like: "The manifest references image tag 1.4.2-rc, which
# doesn't exist in the registry — the last available tag is 1.4.1."
```

Every piece in that chain is a `Runnable`. That's the actual base class underneath prompts, models, and parsers, and it's why they all snap together with the same `|` syntax and all support `.invoke()`, `.stream()`, and `.batch()` without you writing that plumbing yourself. If you remember one term from this post, make it `Runnable` — it's the interface everything else in LangChain implements.

**The CI/CD parallel:** this chain is a pipeline with three fixed stages, no different in shape from a Bamboo or GitHub Actions job with three steps that pass artifacts forward. `prompt` is your "build the request" stage, `model` is your "call the external service" stage, `parser` is your "process the response" stage. If any stage throws, the chain fails, exactly like a pipeline stage failing — same retry and error-handling instincts apply.

---

## Where a straight pipeline stops being enough

A chain like the one above runs once, start to finish, in a straight line. That's fine for "take this input, produce this output." It falls apart the moment you need any of the following, all of which are completely normal asks in a real system:

- **Branching:** "if the retrieved context doesn't actually answer the question, do a web search instead of just answering anyway."
- **Looping:** "let the model try calling a tool, look at the result, and decide whether it needs to call another tool before answering."
- **Persistent state across steps:** "remember what was already tried in this session so we don't call the same API twice."
- **Human approval in the middle:** "pause here and wait for someone to click approve before running the actual remediation."

A plain LCEL chain is a straight line. None of the four things above are a straight line — they're a loop with a condition, which is a graph, not a pipe. Bolting branching logic onto a linear chain with nested `if` statements is exactly the trap: it works for the demo and turns into unreadable spaghetti the moment there are three tools and two retry paths. This is the actual gap LangGraph was built to close.

---

## Enter LangGraph: a control loop, not a bigger chain

Here's the mental model that will save you time: **stop thinking of LangGraph as "LangChain but fancier."** Think of it as a small state machine runtime, closer in spirit to a Kubernetes controller than to a pipeline tool.

A Kubernetes controller does one thing, over and over: look at the current state of the world, compare it to the desired state, do something to close the gap, and check again. It doesn't run once and exit — it keeps looping until the actual state matches the desired state, and it keeps a record of where things stand the whole time.

LangGraph runs the same loop, just with an LLM call (or a tool call) as the "do something" step instead of a pod restart:

```
Kubernetes controller loop:              LangGraph agent loop:
┌──────────────────┐                     ┌──────────────────┐
│ Read current      │                     │ Read current      │
│ state (etcd)       │                     │ state (messages,  │
│                    │                     │ tool results)      │
└─────────┬──────────┘                     └─────────┬──────────┘
          ▼                                           ▼
┌──────────────────┐                     ┌──────────────────┐
│ Compare to        │                     │ Ask the model:    │
│ desired state      │                     │ "given this state,│
│                    │                     │ what's next?"      │
└─────────┬──────────┘                     └─────────┬──────────┘
          ▼                                           ▼
┌──────────────────┐                     ┌──────────────────┐
│ Take an action     │                     │ Take an action:    │
│ (create/delete a   │                     │ call a tool, or     │
│ resource)           │                     │ produce a final     │
│                    │                     │ answer               │
└─────────┬──────────┘                     └─────────┬──────────┘
          ▼                                           ▼
   loop again, unless                          loop again, unless
   state == desired state                       model says "done"
```

The concepts line up directly:

| Kubernetes controller | LangGraph |
|---|---|
| Object stored in etcd | **State** — a typed object (usually a dict or a small class) that gets passed between steps and updated as the graph runs |
| Reconcile function | **Node** — a plain Python function that takes the current state and returns updates to it |
| Watch + requeue | **Edge** — the wiring that decides which node runs next, including edges that loop back |
| A `Ready` condition that stops reconciliation | **Conditional edge** — a function that inspects the state and decides "loop again" or "stop, we're done" |
| Controller restart resuming from last known state | **Checkpointing** — LangGraph can persist state after each step so a run can resume exactly where it left off, instead of starting over |

That last row matters more than it looks. A plain LCEL chain has no concept of "resume from where I crashed" — if step 2 of 3 fails, you re-run the whole chain from the top. A LangGraph graph with checkpointing enabled can pick back up at the node it was on, with the state it had, the same way a controller doesn't re-provision every resource in the cluster just because it got restarted — it reads current state and carries on.

We'll build a real multi-node graph with branching and looping in Part 2. For this post, here's the smallest possible LangGraph example, just to see the shape of the API — a two-node graph that always runs node A then node B, no branching yet:

```python
from typing import TypedDict
from langgraph.graph import StateGraph, END

# The state every node reads from and writes to — think of this
# as the object a controller reconciles against.
class PipelineState(TypedDict):
    ticket_id: str
    status: str
    summary: str

def fetch_status(state: PipelineState) -> dict:
    # in real life: call your Jira/Bitbucket/CI client here
    return {"status": "build_failed"}

def summarize(state: PipelineState) -> dict:
    # in real life: call an LLM chain here, passing in state["status"]
    return {"summary": f"Ticket {state['ticket_id']} is blocked: {state['status']}"}

graph = StateGraph(PipelineState)
graph.add_node("fetch_status", fetch_status)
graph.add_node("summarize", summarize)

graph.set_entry_point("fetch_status")
graph.add_edge("fetch_status", "summarize")
graph.add_edge("summarize", END)

app = graph.compile()

result = app.invoke({"ticket_id": "OPS-4821", "status": "", "summary": ""})
print(result["summary"])
# "Ticket OPS-4821 is blocked: build_failed"
```

Notice this graph doesn't branch or loop yet — it's a straight line, same as the LCEL chain earlier, just expressed as a graph instead of a pipe. That's intentional. The point of this example is the shape of the API (state in, node functions, edges, `compile()`, `invoke()`), not the power of graphs. Part 2 adds the conditional edge that makes this actually loop — the part a plain chain can't do.

---

## Do / Don't for this layer

**Do** reach for a plain LCEL chain first. If your workflow is "take input, run it through N fixed steps, return output," a chain is simpler to write, simpler to test, and simpler to explain to the next engineer than a graph with one node per step and no branches.

**Don't** reach for LangGraph just because it's the newer tool. If there's no branching, no loop, and no need to pause and resume, a graph gives you nothing a chain doesn't, plus more code to read.

**Do** reach for LangGraph the moment you have a loop, a condition, or a step that needs to survive a crash and pick back up. That's the actual line: chains for straight-line work, graphs for anything with a decision point.

**Don't** assume "agent" means "LangGraph" and "chain" means "LangChain" as some kind of version boundary. LangGraph is built using LangChain's Runnable interface underneath — a node in a graph is often just a chain you already wrote. They're not competing tools; one is the pipe, the other is the loop that calls the pipe repeatedly.

---

## What you should be able to do after this post

- Explain to a teammate, in plain terms, what a `Runnable` is and why the `|` operator works on prompts, models, and parsers alike.
- Look at a chain like `prompt | model | parser` and know exactly what runs, in what order, and where you'd add a step.
- Know the actual trigger for reaching for LangGraph instead of a chain: branching, looping, or needing to resume after a crash.
- Read the state/node/edge table above and map it back to a reconciliation loop without having to re-read it.

Part 2 picks up right here: we'll build a graph with a real conditional edge and a real loop — an incident-triage flow that keeps pulling more context until it has enough to answer, the same way a controller keeps reconciling until the object is actually `Ready` — and we'll look at how LangGraph's checkpointing actually gets stored so a run can survive a process restart.

---

*This is Part 1 of a 5-part series in [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook). Part 2: LangGraph state, nodes, edges, and control loops.*
