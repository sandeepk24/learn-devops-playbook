"""
04_langgraph_agent.py - Full LangGraph agent with proper state management

LangGraph takes the manual agent loop from the earlier examples and gives it:
- Explicit state management (TypedDict with annotations)
- Graph-based control flow (nodes and edges)
- Built-in persistence (checkpointing)
- Interrupt/resume capabilities

This is what you'd use for production agents that need reliability.

Think of it as: the manual agent loop, but with the rigor of a Kubernetes controller.

Run: python 04_langgraph_agent.py
"""

import os
from typing import TypedDict, Annotated, Literal
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

# LangGraph imports
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------

SERVICES = {
    "checkout": {"status": "healthy", "version": "v2.3.1", "replicas": 3},
    "payment": {"status": "degraded", "version": "v1.8.0", "replicas": 2},
    "inventory": {"status": "healthy", "version": "v3.0.2", "replicas": 5},
}

@tool
def get_service_status(service_name: str) -> str:
    """Get current status, version, and replica count for a service."""
    if service_name not in SERVICES:
        return f"Unknown service: {service_name}. Available: {list(SERVICES.keys())}"
    s = SERVICES[service_name]
    return f"{service_name}: {s['status']} (version {s['version']}, {s['replicas']} replicas)"


@tool
def scale_service(service_name: str, replicas: int) -> str:
    """Scale a service to a target number of replicas (1-10)."""
    if service_name not in SERVICES:
        return f"Unknown service: {service_name}"
    if not 1 <= replicas <= 10:
        return "Error: replicas must be between 1 and 10"
    old = SERVICES[service_name]["replicas"]
    SERVICES[service_name]["replicas"] = replicas
    return f"Scaled {service_name}: {old} -> {replicas} replicas"


@tool
def restart_service(service_name: str) -> str:
    """Restart all pods for a service. Use when a service is unhealthy."""
    if service_name not in SERVICES:
        return f"Unknown service: {service_name}"
    SERVICES[service_name]["status"] = "healthy"  # Simulated restart fixes issues
    return f"Restarted {service_name}. Status is now healthy."


# -----------------------------------------------------------------------------
# State Definition
# -----------------------------------------------------------------------------

class AgentState(TypedDict):
    """
    The state that flows through the graph.
    
    `messages` uses Annotated with add_messages, which means:
    - New messages are appended, not replaced
    - This is the standard pattern for conversation state
    
    You can add more fields for your use case:
    - `iteration_count: int` for loop limiting
    - `approved: bool` for human-in-the-loop
    - `context: dict` for additional data
    """
    messages: Annotated[list, add_messages]


# -----------------------------------------------------------------------------
# Graph Nodes
# -----------------------------------------------------------------------------

# Model setup
model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
tools = [get_service_status, scale_service, restart_service]
model_with_tools = model.bind_tools(tools)
tools_by_name = {t.name: t for t in tools}


def call_model(state: AgentState) -> dict:
    """
    Node that invokes the LLM with current state.
    
    Returns a dict with the keys to update in state.
    Because `messages` has `add_messages` annotation, the returned
    message will be appended, not replace the list.
    """
    print("  [call_model] Invoking LLM...")
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def call_tools(state: AgentState) -> dict:
    """
    Node that executes any tool calls from the last message.
    """
    last_message = state["messages"][-1]
    outputs = []
    
    for tool_call in last_message.tool_calls:
        print(f"  [call_tools] Executing: {tool_call['name']}({tool_call['args']})")
        result = tools_by_name[tool_call["name"]].invoke(tool_call["args"])
        print(f"  [call_tools] Result: {result}")
        outputs.append(
            ToolMessage(content=str(result), tool_call_id=tool_call["id"])
        )
    
    return {"messages": outputs}


# -----------------------------------------------------------------------------
# Conditional Edge
# -----------------------------------------------------------------------------

def should_continue(state: AgentState) -> Literal["call_tools", "end"]:
    """
    Decides whether to continue to tools or end the graph.
    
    This is the routing logic - the equivalent of a conditional edge
    in a workflow. The model decides implicitly by whether it returns
    tool_calls or not.
    """
    last_message = state["messages"][-1]
    
    if last_message.tool_calls:
        return "call_tools"
    else:
        return "end"


# -----------------------------------------------------------------------------
# Build the Graph
# -----------------------------------------------------------------------------

def build_agent_graph():
    """
    Construct the LangGraph agent.
    
    The graph structure:
    
        ┌─────────────┐
        │   START     │
        └──────┬──────┘
               │
               ▼
        ┌─────────────┐
        │ call_model  │◄─────────────┐
        └──────┬──────┘              │
               │                     │
               ▼                     │
        ┌─────────────┐              │
        │ should_     │──(tools)───►┌┴────────────┐
        │ continue?   │             │ call_tools  │
        └──────┬──────┘             └─────────────┘
               │
               (end)
               │
               ▼
        ┌─────────────┐
        │    END      │
        └─────────────┘
    """
    
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("call_model", call_model)
    graph.add_node("call_tools", call_tools)
    
    # Set entry point
    graph.set_entry_point("call_model")
    
    # Add conditional edge from call_model
    graph.add_conditional_edges(
        "call_model",
        should_continue,
        {
            "call_tools": "call_tools",
            "end": END,
        }
    )
    
    # After tools, always go back to model
    graph.add_edge("call_tools", "call_model")
    
    return graph


# -----------------------------------------------------------------------------
# Running the Agent
# -----------------------------------------------------------------------------

def run_simple():
    """Run the agent without persistence."""
    
    print("=" * 70)
    print("SIMPLE LANGGRAPH AGENT (no persistence)")
    print("=" * 70)
    
    graph = build_agent_graph()
    app = graph.compile()
    
    # Run a query
    result = app.invoke({
        "messages": [
            SystemMessage(content="You are a helpful DevOps assistant. Be concise."),
            HumanMessage(content="What's the status of the payment service? If it's not healthy, please restart it."),
        ]
    })
    
    print("\nFinal response:")
    print(result["messages"][-1].content)


def run_with_persistence():
    """
    Run the agent with checkpointing - state survives across calls.
    
    This is critical for:
    - Resuming after interruption
    - Human-in-the-loop workflows
    - Multi-turn conversations with persistence
    """
    
    print("\n" + "=" * 70)
    print("LANGGRAPH AGENT WITH PERSISTENCE")
    print("=" * 70)
    
    graph = build_agent_graph()
    
    # MemorySaver stores state in memory (use SqliteSaver or PostgresSaver for production)
    checkpointer = MemorySaver()
    app = graph.compile(checkpointer=checkpointer)
    
    # Thread ID identifies this conversation
    thread_id = "devops-session-001"
    config = {"configurable": {"thread_id": thread_id}}
    
    # First message
    print("\n--- Turn 1 ---")
    result1 = app.invoke({
        "messages": [
            SystemMessage(content="You are a helpful DevOps assistant."),
            HumanMessage(content="Check the checkout service status"),
        ]
    }, config)
    print(f"Response: {result1['messages'][-1].content}")
    
    # Second message - continues the same conversation (same thread_id)
    print("\n--- Turn 2 ---")
    result2 = app.invoke({
        "messages": [HumanMessage(content="Now scale it to 5 replicas")],
    }, config)
    print(f"Response: {result2['messages'][-1].content}")
    
    # Third message
    print("\n--- Turn 3 ---")
    result3 = app.invoke({
        "messages": [HumanMessage(content="What's its status now?")],
    }, config)
    print(f"Response: {result3['messages'][-1].content}")
    
    # Show the full conversation history
    print("\n--- Full Conversation History ---")
    state = app.get_state(config)
    for msg in state.values["messages"]:
        role = type(msg).__name__
        content = msg.content[:80] + "..." if len(str(msg.content)) > 80 else msg.content
        print(f"  [{role}]: {content}")


def run_with_streaming():
    """
    Stream the agent's execution - see each step as it happens.
    
    Useful for:
    - Real-time UI updates
    - Debugging
    - Progress indication for long-running agents
    """
    
    print("\n" + "=" * 70)
    print("STREAMING EXECUTION")
    print("=" * 70)
    
    graph = build_agent_graph()
    app = graph.compile()
    
    print("\nStreaming events as they happen:\n")
    
    for event in app.stream({
        "messages": [
            SystemMessage(content="You are a helpful DevOps assistant."),
            HumanMessage(content="Check the inventory service and scale it to 3 replicas"),
        ]
    }):
        # Each event contains the output from one node
        for node_name, node_output in event.items():
            print(f"[{node_name}] completed")
            if "messages" in node_output:
                for msg in node_output["messages"]:
                    if hasattr(msg, 'tool_calls') and msg.tool_calls:
                        print(f"  → Tool calls: {[tc['name'] for tc in msg.tool_calls]}")
                    elif hasattr(msg, 'content') and msg.content:
                        content = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                        print(f"  → {content}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    run_simple()
    run_with_persistence()
    run_with_streaming()
