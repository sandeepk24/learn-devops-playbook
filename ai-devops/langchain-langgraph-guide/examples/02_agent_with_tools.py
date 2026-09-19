"""
02_agent_with_tools.py - Agent with DevOps-relevant tools

This example shows an agent with tools that simulate real DevOps operations:
- Checking service status
- Looking up deployment history
- Querying incident tickets

The tools are stubs, but the pattern is exactly what you'd use with real APIs.

Run: python 02_agent_with_tools.py
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

# -----------------------------------------------------------------------------
# Simulated DevOps data (replace with real API calls)
# -----------------------------------------------------------------------------

SERVICES = {
    "checkout": {"status": "healthy", "last_deploy": "2024-01-15 14:30:00", "version": "v2.3.1"},
    "payment": {"status": "degraded", "last_deploy": "2024-01-15 10:00:00", "version": "v1.8.0"},
    "inventory": {"status": "healthy", "last_deploy": "2024-01-14 09:00:00", "version": "v3.0.2"},
    "api-gateway": {"status": "healthy", "last_deploy": "2024-01-13 16:45:00", "version": "v4.1.0"},
}

DEPLOYMENTS = {
    "checkout": [
        {"version": "v2.3.1", "time": "2024-01-15 14:30:00", "status": "success", "deployer": "alice"},
        {"version": "v2.3.0", "time": "2024-01-14 11:00:00", "status": "success", "deployer": "bob"},
        {"version": "v2.2.9", "time": "2024-01-12 16:00:00", "status": "rolled_back", "deployer": "alice"},
    ],
    "payment": [
        {"version": "v1.8.0", "time": "2024-01-15 10:00:00", "status": "success", "deployer": "charlie"},
        {"version": "v1.7.9", "time": "2024-01-10 09:00:00", "status": "success", "deployer": "alice"},
    ],
}

INCIDENTS = {
    "INC-4821": {"service": "payment", "status": "investigating", "summary": "Elevated error rates on payment processing"},
    "INC-4820": {"service": "checkout", "status": "resolved", "summary": "Memory leak in v2.2.9, rolled back to v2.2.8"},
    "INC-4819": {"service": "api-gateway", "status": "resolved", "summary": "Certificate expiration caused 503s"},
}


# -----------------------------------------------------------------------------
# DevOps Tools
# -----------------------------------------------------------------------------

@tool
def get_service_status(service_name: str) -> str:
    """Get the current health status, version, and last deploy time for a service.
    
    Args:
        service_name: Name of the service (e.g., 'checkout', 'payment', 'inventory')
    """
    if service_name not in SERVICES:
        return f"Service '{service_name}' not found. Available services: {list(SERVICES.keys())}"
    
    info = SERVICES[service_name]
    return f"Service: {service_name}\nStatus: {info['status']}\nVersion: {info['version']}\nLast Deploy: {info['last_deploy']}"


@tool
def get_deployment_history(service_name: str, limit: int = 5) -> str:
    """Get recent deployment history for a service.
    
    Args:
        service_name: Name of the service
        limit: Number of recent deployments to return (default 5)
    """
    if service_name not in DEPLOYMENTS:
        return f"No deployment history found for '{service_name}'"
    
    history = DEPLOYMENTS[service_name][:limit]
    lines = [f"Deployment history for {service_name}:"]
    for d in history:
        lines.append(f"  - {d['version']} at {d['time']} by {d['deployer']} ({d['status']})")
    return "\n".join(lines)


@tool
def get_incident(incident_id: str) -> str:
    """Look up an incident by its ID.
    
    Args:
        incident_id: The incident ID (e.g., 'INC-4821')
    """
    if incident_id not in INCIDENTS:
        return f"Incident '{incident_id}' not found"
    
    inc = INCIDENTS[incident_id]
    return f"Incident: {incident_id}\nService: {inc['service']}\nStatus: {inc['status']}\nSummary: {inc['summary']}"


@tool
def list_open_incidents() -> str:
    """List all incidents that are not yet resolved."""
    open_incidents = [(id, inc) for id, inc in INCIDENTS.items() if inc["status"] != "resolved"]
    
    if not open_incidents:
        return "No open incidents"
    
    lines = ["Open incidents:"]
    for id, inc in open_incidents:
        lines.append(f"  - {id}: [{inc['service']}] {inc['summary']} (Status: {inc['status']})")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Agent setup
# -----------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a DevOps assistant helping engineers investigate and resolve incidents.

You have access to tools for:
- Checking service health status
- Looking up deployment history  
- Finding incident details

When investigating an issue:
1. First check the service status to understand the current state
2. Look at recent deployments if the issue might be deployment-related
3. Check for related incidents

Be concise but thorough. If you find a likely cause, explain it clearly."""

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
tools = [get_service_status, get_deployment_history, get_incident, list_open_incidents]
model_with_tools = model.bind_tools(tools)


def run_devops_agent(user_message: str) -> str:
    """Run the DevOps agent with the given message."""
    
    tools_by_name = {t.name: t for t in tools}
    
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_message),
    ]
    
    max_iterations = 10
    
    for i in range(max_iterations):
        print(f"\n--- Step {i+1} ---")
        
        response = model_with_tools.invoke(messages)
        messages.append(response)
        
        if not response.tool_calls:
            print(f"\nFinal response:\n{response.content}")
            return response.content
        
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"Calling: {tool_name}({tool_args})")
            
            result = tools_by_name[tool_name].invoke(tool_args)
            print(f"Result:\n{result}\n")
            
            messages.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )
    
    return "Agent reached maximum iterations"


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 70)
    print("Example 1: Check a specific service")
    print("=" * 70)
    run_devops_agent("Is the checkout service healthy?")
    
    print("\n" + "=" * 70)
    print("Example 2: Investigate an issue (multi-step reasoning)")
    print("=" * 70)
    run_devops_agent("The payment service seems slow. What's going on?")
    
    print("\n" + "=" * 70)
    print("Example 3: Open incidents overview")
    print("=" * 70)
    run_devops_agent("Are there any open incidents I should know about?")
    
    print("\n" + "=" * 70)
    print("Example 4: Deep investigation")
    print("=" * 70)
    run_devops_agent(
        "I'm getting paged about INC-4821. Can you investigate and tell me "
        "what's happening, when the last deployment was, and what might be the cause?"
    )
