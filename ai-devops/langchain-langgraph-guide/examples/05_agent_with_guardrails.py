"""
05_agent_with_guardrails.py - Production-ready agent with safety patterns

This example demonstrates the safety patterns every production agent needs:

1. Tool allowlisting - Only certain services can be modified
2. Argument validation - Check args before running destructive tools
3. Human-in-the-loop - Pause for approval before dangerous actions
4. Iteration limits - Prevent infinite loops
5. Audit logging - Track every tool call

These are the same patterns from Part 3 of the guide, implemented in code.

Run: python 05_agent_with_guardrails.py
"""

import os
import json
from datetime import datetime
from typing import TypedDict, Annotated, Literal
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

# -----------------------------------------------------------------------------
# Configuration - what's allowed and what needs approval
# -----------------------------------------------------------------------------

# Services that can be modified (allowlist)
MODIFIABLE_SERVICES = {"checkout", "payment", "inventory"}

# Services that require human approval for any modification
REQUIRES_APPROVAL = {"payment"}  # e.g., payment is critical

# Maximum number of tool calls per agent run
MAX_TOOL_CALLS = 10

# Audit log
AUDIT_LOG = []


# -----------------------------------------------------------------------------
# Tools with different risk levels
# -----------------------------------------------------------------------------

SERVICES = {
    "checkout": {"status": "healthy", "version": "v2.3.1", "replicas": 3},
    "payment": {"status": "degraded", "version": "v1.8.0", "replicas": 2},
    "inventory": {"status": "healthy", "version": "v3.0.2", "replicas": 5},
    "database": {"status": "healthy", "version": "v5.0.0", "replicas": 1},  # NOT in allowlist
}


@tool
def get_service_status(service_name: str) -> str:
    """Get current status for a service. (Read-only, safe)"""
    if service_name not in SERVICES:
        return f"Unknown service: {service_name}"
    s = SERVICES[service_name]
    return f"{service_name}: {s['status']} ({s['version']}, {s['replicas']} replicas)"


@tool
def list_all_services() -> str:
    """List all services and their status. (Read-only, safe)"""
    lines = []
    for name, info in SERVICES.items():
        lines.append(f"  {name}: {info['status']}")
    return "Services:\n" + "\n".join(lines)


@tool
def scale_service(service_name: str, replicas: int) -> str:
    """Scale a service to a target number of replicas. (MUTATING - requires validation)"""
    # This tool is marked as mutating - the guardrail node will validate before allowing
    if service_name not in SERVICES:
        return f"Unknown service: {service_name}"
    old = SERVICES[service_name]["replicas"]
    SERVICES[service_name]["replicas"] = replicas
    return f"Scaled {service_name}: {old} -> {replicas} replicas"


@tool
def restart_service(service_name: str) -> str:
    """Restart a service. (MUTATING - requires validation)"""
    if service_name not in SERVICES:
        return f"Unknown service: {service_name}"
    SERVICES[service_name]["status"] = "healthy"
    return f"Restarted {service_name}"


@tool
def rollback_service(service_name: str, target_version: str) -> str:
    """Rollback a service to a previous version. (DESTRUCTIVE - requires approval)"""
    if service_name not in SERVICES:
        return f"Unknown service: {service_name}"
    old_version = SERVICES[service_name]["version"]
    SERVICES[service_name]["version"] = target_version
    return f"Rolled back {service_name}: {old_version} -> {target_version}"


# Tool classification
READ_ONLY_TOOLS = {"get_service_status", "list_all_services"}
MUTATING_TOOLS = {"scale_service", "restart_service"}
DESTRUCTIVE_TOOLS = {"rollback_service"}  # These need human approval


# -----------------------------------------------------------------------------
# State with guardrail tracking
# -----------------------------------------------------------------------------

class GuardedAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    tool_call_count: int  # Track iterations
    pending_approval: dict | None  # Store tool call awaiting human approval
    denied_tools: list  # Track denied tool calls for context


# -----------------------------------------------------------------------------
# Audit Logging
# -----------------------------------------------------------------------------

def log_tool_call(tool_name: str, args: dict, result: str, status: str):
    """Log every tool call for audit purposes."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "tool": tool_name,
        "args": args,
        "result": result[:100],  # Truncate for logging
        "status": status,  # "allowed", "denied", "pending_approval"
    }
    AUDIT_LOG.append(entry)
    print(f"  [AUDIT] {status.upper()}: {tool_name}({json.dumps(args)})")


# -----------------------------------------------------------------------------
# Graph Nodes
# -----------------------------------------------------------------------------

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
all_tools = [get_service_status, list_all_services, scale_service, restart_service, rollback_service]
model_with_tools = model.bind_tools(all_tools)
tools_by_name = {t.name: t for t in all_tools}


def call_model(state: GuardedAgentState) -> dict:
    """Invoke the LLM."""
    print("  [call_model] Invoking LLM...")
    response = model_with_tools.invoke(state["messages"])
    return {"messages": [response]}


def validate_and_execute_tools(state: GuardedAgentState) -> dict:
    """
    The guardrail node: validates tool calls before executing them.
    
    This is where all safety checks happen:
    1. Check iteration limit
    2. Validate arguments (allowlist, bounds checking)
    3. Route destructive tools to approval queue
    4. Log everything
    """
    last_message = state["messages"][-1]
    outputs = []
    new_count = state.get("tool_call_count", 0)
    pending = None
    denied = state.get("denied_tools", [])
    
    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        new_count += 1
        
        # ─────────────────────────────────────────────────────────────────────
        # Guardrail 1: Iteration limit
        # ─────────────────────────────────────────────────────────────────────
        if new_count > MAX_TOOL_CALLS:
            log_tool_call(tool_name, tool_args, "DENIED: max iterations", "denied")
            outputs.append(
                ToolMessage(
                    content=f"Denied: maximum tool calls ({MAX_TOOL_CALLS}) exceeded",
                    tool_call_id=tool_call["id"]
                )
            )
            denied.append({"name": tool_name, "reason": "max_iterations"})
            continue
        
        # ─────────────────────────────────────────────────────────────────────
        # Guardrail 2: Argument validation for mutating/destructive tools
        # ─────────────────────────────────────────────────────────────────────
        if tool_name in MUTATING_TOOLS or tool_name in DESTRUCTIVE_TOOLS:
            service = tool_args.get("service_name")
            
            # Check allowlist
            if service and service not in MODIFIABLE_SERVICES:
                log_tool_call(tool_name, tool_args, f"DENIED: {service} not in allowlist", "denied")
                outputs.append(
                    ToolMessage(
                        content=f"Denied: service '{service}' is not in the modifiable services allowlist",
                        tool_call_id=tool_call["id"]
                    )
                )
                denied.append({"name": tool_name, "reason": "allowlist", "service": service})
                continue
            
            # Check replica bounds for scale operations
            if tool_name == "scale_service":
                replicas = tool_args.get("replicas", 0)
                if not 1 <= replicas <= 10:
                    log_tool_call(tool_name, tool_args, "DENIED: replicas out of range", "denied")
                    outputs.append(
                        ToolMessage(
                            content=f"Denied: replicas must be between 1 and 10, got {replicas}",
                            tool_call_id=tool_call["id"]
                        )
                    )
                    denied.append({"name": tool_name, "reason": "validation"})
                    continue
        
        # ─────────────────────────────────────────────────────────────────────
        # Guardrail 3: Human approval for destructive operations
        # ─────────────────────────────────────────────────────────────────────
        if tool_name in DESTRUCTIVE_TOOLS:
            log_tool_call(tool_name, tool_args, "PENDING APPROVAL", "pending_approval")
            pending = {
                "tool_name": tool_name,
                "args": tool_args,
                "tool_call_id": tool_call["id"],
            }
            outputs.append(
                ToolMessage(
                    content=f"⚠️ This action requires human approval. Pending: {tool_name}({tool_args})",
                    tool_call_id=tool_call["id"]
                )
            )
            continue
        
        # Check if service requires approval (even for non-destructive ops)
        if tool_name in MUTATING_TOOLS:
            service = tool_args.get("service_name")
            if service in REQUIRES_APPROVAL:
                log_tool_call(tool_name, tool_args, "PENDING APPROVAL (critical service)", "pending_approval")
                pending = {
                    "tool_name": tool_name,
                    "args": tool_args,
                    "tool_call_id": tool_call["id"],
                }
                outputs.append(
                    ToolMessage(
                        content=f"⚠️ Modifications to '{service}' require human approval. Pending: {tool_name}({tool_args})",
                        tool_call_id=tool_call["id"]
                    )
                )
                continue
        
        # ─────────────────────────────────────────────────────────────────────
        # Passed all guardrails - execute the tool
        # ─────────────────────────────────────────────────────────────────────
        result = tools_by_name[tool_name].invoke(tool_args)
        log_tool_call(tool_name, tool_args, result, "allowed")
        outputs.append(
            ToolMessage(content=str(result), tool_call_id=tool_call["id"])
        )
    
    return {
        "messages": outputs,
        "tool_call_count": new_count,
        "pending_approval": pending,
        "denied_tools": denied,
    }


def should_continue(state: GuardedAgentState) -> Literal["validate_tools", "end"]:
    """Route based on whether there are tool calls."""
    last_message = state["messages"][-1]
    
    # If there's a pending approval, we should end and wait
    if state.get("pending_approval"):
        return "end"
    
    if last_message.tool_calls:
        return "validate_tools"
    return "end"


# -----------------------------------------------------------------------------
# Build Graph
# -----------------------------------------------------------------------------

def build_guarded_agent():
    graph = StateGraph(GuardedAgentState)
    
    graph.add_node("call_model", call_model)
    graph.add_node("validate_tools", validate_and_execute_tools)
    
    graph.set_entry_point("call_model")
    
    graph.add_conditional_edges(
        "call_model",
        should_continue,
        {"validate_tools": "validate_tools", "end": END}
    )
    
    graph.add_edge("validate_tools", "call_model")
    
    return graph


# -----------------------------------------------------------------------------
# Demo scenarios
# -----------------------------------------------------------------------------

def demo_safe_operations():
    """Demo: Read-only operations always work."""
    print("=" * 70)
    print("SCENARIO 1: Safe read-only operations")
    print("=" * 70)
    
    app = build_guarded_agent().compile()
    result = app.invoke({
        "messages": [
            SystemMessage(content="You are a DevOps assistant."),
            HumanMessage(content="List all services and their status"),
        ],
        "tool_call_count": 0,
        "pending_approval": None,
        "denied_tools": [],
    })
    print(f"\nResponse: {result['messages'][-1].content}")


def demo_allowlist_denial():
    """Demo: Attempts to modify non-allowlisted services are denied."""
    print("\n" + "=" * 70)
    print("SCENARIO 2: Allowlist denial (database not in allowlist)")
    print("=" * 70)
    
    app = build_guarded_agent().compile()
    result = app.invoke({
        "messages": [
            SystemMessage(content="You are a DevOps assistant."),
            HumanMessage(content="Scale the database service to 3 replicas"),
        ],
        "tool_call_count": 0,
        "pending_approval": None,
        "denied_tools": [],
    })
    print(f"\nResponse: {result['messages'][-1].content}")
    print(f"Denied tools: {result.get('denied_tools', [])}")


def demo_approval_required():
    """Demo: Destructive operations require approval."""
    print("\n" + "=" * 70)
    print("SCENARIO 3: Destructive operation requires approval")
    print("=" * 70)
    
    checkpointer = MemorySaver()
    app = build_guarded_agent().compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "approval-demo"}}
    
    result = app.invoke({
        "messages": [
            SystemMessage(content="You are a DevOps assistant."),
            HumanMessage(content="Rollback the checkout service to v2.2.0"),
        ],
        "tool_call_count": 0,
        "pending_approval": None,
        "denied_tools": [],
    }, config)
    
    print(f"\nResponse: {result['messages'][-1].content}")
    print(f"Pending approval: {result.get('pending_approval')}")
    
    # In a real system, you'd wait for human approval here
    # Then resume with: app.invoke(None, config)


def demo_critical_service():
    """Demo: Even non-destructive ops on critical services need approval."""
    print("\n" + "=" * 70)
    print("SCENARIO 4: Critical service (payment) requires approval even for scale")
    print("=" * 70)
    
    app = build_guarded_agent().compile()
    result = app.invoke({
        "messages": [
            SystemMessage(content="You are a DevOps assistant."),
            HumanMessage(content="Scale the payment service to 4 replicas"),
        ],
        "tool_call_count": 0,
        "pending_approval": None,
        "denied_tools": [],
    })
    print(f"\nResponse: {result['messages'][-1].content}")
    print(f"Pending approval: {result.get('pending_approval')}")


def demo_validation():
    """Demo: Argument validation catches out-of-bounds values."""
    print("\n" + "=" * 70)
    print("SCENARIO 5: Validation catches invalid arguments")
    print("=" * 70)
    
    app = build_guarded_agent().compile()
    result = app.invoke({
        "messages": [
            SystemMessage(content="You are a DevOps assistant."),
            HumanMessage(content="Scale the checkout service to 100 replicas"),
        ],
        "tool_call_count": 0,
        "pending_approval": None,
        "denied_tools": [],
    })
    print(f"\nResponse: {result['messages'][-1].content}")


def show_audit_log():
    """Display the audit log."""
    print("\n" + "=" * 70)
    print("AUDIT LOG")
    print("=" * 70)
    for entry in AUDIT_LOG:
        print(f"  {entry['timestamp']} | {entry['status']:15} | {entry['tool']}({json.dumps(entry['args'])})")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    demo_safe_operations()
    demo_allowlist_denial()
    demo_approval_required()
    demo_critical_service()
    demo_validation()
    show_audit_log()
