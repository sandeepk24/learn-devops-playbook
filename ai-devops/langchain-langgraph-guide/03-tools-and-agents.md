# LangChain and LangGraph for DevOps Architects — Part 3: Tools and Agents

> Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) AI-DevOps series.
>
> **Series map:**
> 1. Core architecture: Models, Prompts, LCEL, and where LangGraph comes in
> 2. LangGraph in depth: state, nodes, edges, and control loops
> 3. **Tools and agents: giving the model hands, safely** (this post)
> 4. Memory and retrieval: grounding the model in your own data
> 5. Running this in production: observability, evals, and cost control

---

## Recap, in one paragraph

Part 2 built a graph with real state, a real loop, and a checkpointer so a run can survive a restart. Every node in that example was code you wrote calling code you wrote — deterministic, in the sense that the same input always takes the same path through the graph. This post adds the piece that makes things non-deterministic on purpose: letting the model itself decide which function to call next, based on its own read of the situation. That's a tool, and a graph built around that decision is what most people mean when they say "agent."

---

## A tool is a function with a job description attached

Strip away the terminology and a LangChain tool is a Python function, plus a docstring the model reads to decide when it's relevant. Nothing about the function itself is special.

```python
from langchain_core.tools import tool

@tool
def get_deployment_status(service_name: str) -> str:
    """Get the current deployment status and last deploy time for a service."""
    return ci_client.get_status(service_name)

@tool
def rollback_deployment(service_name: str, target_version: str) -> str:
    """Roll a service back to a specific previous version. Destructive — use with care."""
    return ci_client.rollback(service_name, target_version)
```

The docstring is doing real work here — it's the only thing the model has to go on when deciding whether a tool applies to the question in front of it. Write it the way you'd write a commit message someone has to understand with zero other context, because that's exactly the situation the model is in.

You bind tools to a model like this:

```python
from langchain_openai import ChatOpenAI

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
model_with_tools = model.bind_tools([get_deployment_status, rollback_deployment])

response = model_with_tools.invoke("Is the checkout service deployment healthy?")
print(response.tool_calls)
# [{'name': 'get_deployment_status', 'args': {'service_name': 'checkout'}, 'id': '...'}]
```

Notice what didn't happen: the tool wasn't called. The model returned a **request** to call a tool — a name and a set of arguments — as structured output. Your code still has to look at `response.tool_calls`, actually run the matching function, and feed the result back. The model never touches your systems directly. It only ever produces a suggestion in a known shape, and everything downstream of that is code you wrote and control. This is the single most important fact in this entire post, so it's worth restating plainly: **the model cannot run anything on its own.** It can only ask. Whether the ask turns into an action is entirely up to the code standing between the model and your infrastructure.

---

## The agent loop: LangGraph doing the asking, over and over

An agent, in the LangGraph sense, is just the conditional-edge loop from Part 2, specialized for one purpose: keep calling the model, run whatever tool it asks for, feed the result back, and repeat until the model stops asking for tools and gives a final answer instead.

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, ToolMessage

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

tools_by_name = {"get_deployment_status": get_deployment_status,
                  "rollback_deployment": rollback_deployment}

def call_model(state: AgentState) -> dict:
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}

def call_tool(state: AgentState) -> dict:
    last_message = state["messages"][-1]
    outputs = []
    for call in last_message.tool_calls:
        result = tools_by_name[call["name"]].invoke(call["args"])
        outputs.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return {"messages": outputs}

def has_tool_calls(state: AgentState) -> str:
    last_message = state["messages"][-1]
    return "call_tool" if last_message.tool_calls else END

graph = StateGraph(AgentState)
graph.add_node("call_model", call_model)
graph.add_node("call_tool", call_tool)
graph.set_entry_point("call_model")
graph.add_conditional_edges("call_model", has_tool_calls, {"call_tool": "call_tool", END: END})
graph.add_edge("call_tool", "call_model")

app = graph.compile()

result = app.invoke({"messages": [HumanMessage("Is the checkout service healthy? "
                                                  "If not, roll it back to the last known good version.")]})
print(result["messages"][-1].content)
```

Trace the loop: `call_model` asks the model what to do. If the response includes a tool call, `has_tool_calls` routes to `call_tool`, which runs the real function and appends the result as a `ToolMessage`. That goes back to `call_model`, which now has the tool's output in front of it and decides what's next — maybe another tool call, maybe a final answer. When the model stops asking for tools, `has_tool_calls` routes to `END`.

This is exactly Part 2's control loop, just with the model instead of a fixed condition deciding when to keep going. Same shape, same risk of an unbounded loop if you don't cap it — add an attempt counter to `AgentState` and check it in `has_tool_calls`, same as the retrieval loop in Part 2.

---

## The part that actually matters: this is where you put guardrails

Look again at `rollback_deployment` in the tool list above. A model that can call `get_deployment_status` freely and `rollback_deployment` with the same freedom is a model that can decide, on its own reasoning, to roll back a production service. That might be exactly what you want in a fully automated remediation flow. It might also be the thing that makes your security team say no to shipping this at all. Either way, it's a decision you make explicitly, not something that falls out of the framework by default.

A few patterns, roughly in order of how much you'd trust the setup:

**1. Split tools by blast radius.** Read-only tools (status checks, log lookups) can be called freely. Anything that mutates state (rollbacks, scaling changes, deletions) goes through a separate, smaller set of tools with tighter argument validation — the same instinct behind separating a read-only IAM role from one that can write.

**2. Validate tool arguments before running them, every time.** Never trust the model's arguments blindly just because they came back in the right shape.

```python
def call_tool(state: AgentState) -> dict:
    outputs = []
    for call in state["messages"][-1].tool_calls:
        if call["name"] == "rollback_deployment":
            if call["args"]["service_name"] not in ALLOWED_SERVICES:
                outputs.append(ToolMessage(content="Denied: service not in allowlist.",
                                            tool_call_id=call["id"]))
                continue
        result = tools_by_name[call["name"]].invoke(call["args"])
        outputs.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return {"messages": outputs}
```

**3. Put a human in the loop before anything destructive runs.** This is where LangGraph's checkpointing from Part 2 earns its keep. You can interrupt a graph right before a specific node runs, save the state, and wait for a person to approve before continuing:

```python
app = graph.compile(checkpointer=checkpointer, interrupt_before=["call_tool"])

config = {"configurable": {"thread_id": "incident-4821"}}
app.invoke({"messages": [HumanMessage("Roll back checkout to v1.4.1")]}, config)
# graph pauses here, state is saved — nothing has executed yet

# ... a person reviews the pending tool call, approves via Slack, whatever ...

app.invoke(None, config)  # resume from exactly where it paused
```

This is the closest thing this stack has to a manual approval gate in a CI/CD pipeline — the step that says "deploy to prod" waits for a click, no matter how confident the pipeline is. Same idea: the graph pauses at a defined point, state is durable while it waits, and nothing destructive happens until a person says go.

**4. Log every tool call and its arguments, unconditionally**, the same way you'd log every call to a privileged API endpoint. When something goes wrong, the tool-call log is your audit trail, and it's the first thing you'll want when explaining to someone why the agent did what it did.

---

## Do / Don't for this layer

**Do** start by giving an agent read-only tools only, and add write/mutating tools one at a time, once you trust the read-only behavior in production. This is the same rollout discipline as granting permissions incrementally instead of handing out a broad role on day one.

**Don't** hand an agent a tool that can do something you wouldn't let a brand-new on-call engineer do unsupervised on their first night. If you wouldn't let them run it without a second pair of eyes, don't let the model run it without one either.

**Do** cap the number of tool-call iterations in every agent loop, and log when the cap gets hit. An agent that loops eight times because the model keeps second-guessing itself is a real failure mode, not a hypothetical one, and it's a billed API call every time.

**Don't** rely on the system prompt alone to prevent a destructive action ("please don't delete production"). A system prompt is guidance, not enforcement — the enforcement has to live in the code that decides whether to actually run the tool, exactly like the allowlist check above.

---

## What you should be able to do after this post

- Explain the difference between a model requesting a tool call and a tool call actually running, and why that gap is where all your safety logic lives.
- Build a basic tool-calling agent loop in LangGraph and know exactly which edge needs a hard iteration cap.
- List at least three concrete guardrail patterns (allowlisting, argument validation, human-in-the-loop interrupts) and know which one fits a given tool's blast radius.
- Explain why `interrupt_before` is the LangGraph equivalent of a manual approval gate in a pipeline.

Part 4 covers the other half of grounding an agent in reality: memory across turns, and retrieval-augmented generation for pulling your own runbooks and postmortems into the conversation instead of relying on whatever the model happened to learn during training.

---

*This is Part 3 of a 5-part series in [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook). Part 2: State, nodes, and edges. Part 4: Memory and retrieval.*
