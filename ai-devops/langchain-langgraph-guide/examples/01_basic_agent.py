"""
01_basic_agent.py - The simplest possible LangChain agent

This is the "Hello World" of agents: a model with one tool.
The model decides when to call the tool based on the user's question.

Run: python 01_basic_agent.py
Requires: OPENAI_API_KEY environment variable
"""

import os
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage

# -----------------------------------------------------------------------------
# Step 1: Define a simple tool
# -----------------------------------------------------------------------------
# A tool is just a function with a docstring. The docstring tells the model
# WHEN to use this tool - write it like a commit message someone has to
# understand with zero context.

@tool
def get_current_time() -> str:
    """Get the current date and time. Use this when the user asks what time it is."""
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@tool  
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression. Use for any math calculations.
    
    Args:
        expression: A valid Python math expression like '2 + 2' or '(10 * 5) / 2'
    """
    try:
        # In production, use a safer eval library like numexpr
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error calculating: {e}"


# -----------------------------------------------------------------------------
# Step 2: Create a model and bind tools to it
# -----------------------------------------------------------------------------
# bind_tools() tells the model these tools exist. The model will decide
# when to call them based on the conversation.

model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
model_with_tools = model.bind_tools([get_current_time, calculate])


# -----------------------------------------------------------------------------
# Step 3: The manual agent loop
# -----------------------------------------------------------------------------
# This is what an "agent" really is - a loop that:
# 1. Asks the model what to do
# 2. If the model wants to call a tool, run it and show the result
# 3. Repeat until the model gives a final answer

def run_agent(user_message: str) -> str:
    """
    A minimal agent loop that handles tool calls manually.
    
    This is verbose on purpose - it shows exactly what's happening at each step.
    LangGraph automates this loop, but understanding it manually first is key.
    """
    from langchain_core.messages import ToolMessage
    
    # Map tool names to actual functions
    tools_by_name = {
        "get_current_time": get_current_time,
        "calculate": calculate,
    }
    
    # Start with the user's message
    messages = [HumanMessage(content=user_message)]
    
    # Maximum iterations to prevent infinite loops (critical for production)
    max_iterations = 5
    iteration = 0
    
    while iteration < max_iterations:
        iteration += 1
        print(f"\n--- Iteration {iteration} ---")
        
        # Ask the model what to do
        response = model_with_tools.invoke(messages)
        messages.append(response)
        
        # Check if the model wants to call tools
        if not response.tool_calls:
            # No tool calls = final answer
            print(f"Final answer: {response.content}")
            return response.content
        
        # Model wants to call tools - execute them
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"Tool call: {tool_name}({tool_args})")
            
            # Execute the tool
            tool_fn = tools_by_name[tool_name]
            result = tool_fn.invoke(tool_args)
            print(f"Tool result: {result}")
            
            # Add the result back to the conversation
            # The model needs to see what the tool returned
            messages.append(
                ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            )
    
    return "Max iterations reached - agent did not converge"


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Example 1: Simple question (no tool needed)")
    print("=" * 60)
    result = run_agent("What is the capital of France?")
    
    print("\n" + "=" * 60)
    print("Example 2: Time question (tool needed)")
    print("=" * 60)
    result = run_agent("What time is it right now?")
    
    print("\n" + "=" * 60)
    print("Example 3: Math question (tool needed)")
    print("=" * 60)
    result = run_agent("What is 42 * 17 + 89?")
    
    print("\n" + "=" * 60)
    print("Example 4: Multi-step (multiple tool calls)")
    print("=" * 60)
    result = run_agent("What's the current time, and what's 2024 minus the current hour?")
