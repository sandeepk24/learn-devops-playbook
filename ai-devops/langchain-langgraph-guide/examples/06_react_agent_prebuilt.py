"""
06_react_agent_prebuilt.py - Using LangGraph's prebuilt ReAct agent

LangGraph provides a prebuilt agent that implements the ReAct pattern
(Reasoning + Acting) out of the box. This is the fastest way to get
a working agent without building the graph manually.

Use the prebuilt agent when:
- You want a standard tool-calling agent
- You don't need custom control flow
- You're prototyping quickly

Build custom (like examples 04/05) when:
- You need human-in-the-loop approval
- You need custom guardrails
- You have complex branching logic

Run: python 06_react_agent_prebuilt.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import MemorySaver

# -----------------------------------------------------------------------------
# Tools
# -----------------------------------------------------------------------------

@tool
def search_logs(service: str, query: str, hours: int = 1) -> str:
    """Search logs for a service within the last N hours.
    
    Args:
        service: Service name to search logs for
        query: Search query (keyword or pattern)
        hours: How many hours back to search (default 1)
    """
    # Simulated log search results
    logs = {
        ("checkout", "error"): [
            "2024-01-15 14:32:01 ERROR [checkout] Connection timeout to payment service",
            "2024-01-15 14:32:15 ERROR [checkout] Retry failed after 3 attempts",
        ],
        ("payment", "timeout"): [
            "2024-01-15 14:31:55 WARN [payment] Slow response from database (2.3s)",
            "2024-01-15 14:32:00 ERROR [payment] Request timeout after 5s",
        ],
    }
    
    key = (service.lower(), query.lower())
    if key in logs:
        return f"Logs for {service} matching '{query}' (last {hours}h):\n" + "\n".join(logs[key])
    return f"No logs found for {service} matching '{query}' in the last {hours} hours"


@tool
def get_metrics(service: str, metric: str) -> str:
    """Get current metrics for a service.
    
    Args:
        service: Service name
        metric: Metric name (cpu, memory, error_rate, latency_p99)
    """
    metrics = {
        "checkout": {"cpu": "45%", "memory": "2.1GB", "error_rate": "0.5%", "latency_p99": "120ms"},
        "payment": {"cpu": "89%", "memory": "3.8GB", "error_rate": "5.2%", "latency_p99": "850ms"},
        "inventory": {"cpu": "22%", "memory": "1.5GB", "error_rate": "0.1%", "latency_p99": "45ms"},
    }
    
    if service not in metrics:
        return f"Unknown service: {service}"
    if metric not in metrics[service]:
        return f"Unknown metric: {metric}. Available: {list(metrics[service].keys())}"
    
    return f"{service} {metric}: {metrics[service][metric]}"


@tool
def get_recent_deployments(service: str) -> str:
    """Get recent deployments for a service."""
    deployments = {
        "checkout": [
            {"version": "v2.3.1", "time": "2024-01-15 14:30", "status": "success"},
            {"version": "v2.3.0", "time": "2024-01-14 11:00", "status": "success"},
        ],
        "payment": [
            {"version": "v1.8.0", "time": "2024-01-15 10:00", "status": "success"},
            {"version": "v1.7.9", "time": "2024-01-10 09:00", "status": "success"},
        ],
    }
    
    if service not in deployments:
        return f"No deployment history for {service}"
    
    lines = [f"Recent deployments for {service}:"]
    for d in deployments[service]:
        lines.append(f"  - {d['version']} at {d['time']} ({d['status']})")
    return "\n".join(lines)


@tool
def create_incident(title: str, service: str, severity: str) -> str:
    """Create a new incident ticket.
    
    Args:
        title: Short description of the incident
        service: Affected service
        severity: p1, p2, p3, or p4
    """
    # Simulated incident creation
    incident_id = f"INC-{hash(title) % 10000:04d}"
    return f"Created incident {incident_id}: [{severity.upper()}] {title} (service: {service})"


# -----------------------------------------------------------------------------
# Create the prebuilt agent
# -----------------------------------------------------------------------------

def create_devops_agent():
    """
    Create a ReAct agent using LangGraph's prebuilt function.
    
    This is equivalent to building the graph manually (like in example 04),
    but with less code. The trade-off is less customization.
    """
    
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    tools = [search_logs, get_metrics, get_recent_deployments, create_incident]
    
    # Optional: Add a system message for context
    system_message = """You are an expert DevOps engineer helping investigate and resolve incidents.

When investigating an issue:
1. First check the relevant metrics to understand the current state
2. Search logs for error patterns
3. Look at recent deployments if relevant
4. If you find a significant issue, create an incident ticket

Be thorough but efficient - don't call tools unnecessarily."""
    
    # create_react_agent builds the full graph for you
    agent = create_react_agent(
        model,
        tools,
        state_modifier=system_message,  # Adds system message to state
    )
    
    return agent


# -----------------------------------------------------------------------------
# Demo
# -----------------------------------------------------------------------------

def demo_simple_query():
    """Simple single-tool query."""
    print("=" * 70)
    print("EXAMPLE 1: Simple metrics query")
    print("=" * 70)
    
    agent = create_devops_agent()
    
    result = agent.invoke({
        "messages": [HumanMessage(content="What's the CPU usage on the payment service?")]
    })
    
    print(f"\nFinal response: {result['messages'][-1].content}")


def demo_multi_step_investigation():
    """Multi-step investigation requiring multiple tools."""
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Multi-step incident investigation")
    print("=" * 70)
    
    agent = create_devops_agent()
    
    print("\nQuery: 'The checkout service is slow. Can you investigate and create an incident if needed?'")
    print("\nAgent reasoning:\n")
    
    # Stream to see the agent's step-by-step process
    for event in agent.stream({
        "messages": [HumanMessage(
            content="The checkout service is slow. Can you investigate and create an incident if needed?"
        )]
    }):
        for node_name, node_output in event.items():
            if node_name == "agent":
                msg = node_output["messages"][-1]
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        print(f"  → Calling: {tc['name']}({tc['args']})")
            elif node_name == "tools":
                for msg in node_output["messages"]:
                    result_preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
                    print(f"  ← Result: {result_preview}")
    
    # Get final response
    final_result = agent.invoke({
        "messages": [HumanMessage(
            content="The checkout service is slow. Can you investigate and create an incident if needed?"
        )]
    })
    print(f"\nFinal response:\n{final_result['messages'][-1].content}")


def demo_with_memory():
    """Agent with conversation memory across turns."""
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Multi-turn conversation with memory")
    print("=" * 70)
    
    # Add checkpointer for memory
    checkpointer = MemorySaver()
    agent = create_react_agent(
        ChatOpenAI(model="gpt-4o-mini", temperature=0),
        [search_logs, get_metrics, get_recent_deployments, create_incident],
        checkpointer=checkpointer,
    )
    
    config = {"configurable": {"thread_id": "investigation-001"}}
    
    # Turn 1
    print("\n[Turn 1] User: Check the payment service metrics")
    result1 = agent.invoke(
        {"messages": [HumanMessage(content="Check the payment service metrics")]},
        config
    )
    print(f"Agent: {result1['messages'][-1].content}")
    
    # Turn 2 - references "it" (the payment service from turn 1)
    print("\n[Turn 2] User: Search its logs for timeout errors")
    result2 = agent.invoke(
        {"messages": [HumanMessage(content="Search its logs for timeout errors")]},
        config
    )
    print(f"Agent: {result2['messages'][-1].content}")
    
    # Turn 3
    print("\n[Turn 3] User: Create a P2 incident for this")
    result3 = agent.invoke(
        {"messages": [HumanMessage(content="Create a P2 incident for this")]},
        config
    )
    print(f"Agent: {result3['messages'][-1].content}")


def demo_prebuilt_vs_custom():
    """Explain when to use prebuilt vs custom."""
    print("\n" + "=" * 70)
    print("WHEN TO USE PREBUILT VS CUSTOM AGENTS")
    print("=" * 70)
    
    print("""
    ┌─────────────────────────────────────────────────────────────────────┐
    │                     USE PREBUILT (create_react_agent)               │
    ├─────────────────────────────────────────────────────────────────────┤
    │ ✓ Standard tool-calling agent                                       │
    │ ✓ Prototyping and quick experiments                                 │
    │ ✓ Simple conversational assistants                                  │
    │ ✓ When you don't need custom control flow                           │
    └─────────────────────────────────────────────────────────────────────┘
    
    ┌─────────────────────────────────────────────────────────────────────┐
    │                     BUILD CUSTOM (StateGraph)                       │
    ├─────────────────────────────────────────────────────────────────────┤
    │ ✓ Human-in-the-loop approval gates                                  │
    │ ✓ Custom guardrails and validation                                  │
    │ ✓ Complex branching (if X then do Y, else Z)                        │
    │ ✓ Multi-agent coordination                                          │
    │ ✓ Custom state beyond just messages                                 │
    │ ✓ Production systems with audit requirements                        │
    └─────────────────────────────────────────────────────────────────────┘
    
    The prebuilt agent is ~10 lines of code.
    The custom agent (example 05) is ~200 lines but gives you full control.
    
    Start with prebuilt for prototyping, migrate to custom when you need
    guardrails that the prebuilt agent can't provide.
    """)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    demo_simple_query()
    demo_multi_step_investigation()
    demo_with_memory()
    demo_prebuilt_vs_custom()
