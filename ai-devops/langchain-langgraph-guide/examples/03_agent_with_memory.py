"""
03_agent_with_memory.py - Agent that remembers conversation history

LLM API calls are stateless - each call knows nothing about previous calls.
"Memory" in LangChain means re-injecting prior conversation turns into each
new request so the model can maintain context across a multi-turn conversation.

This example shows:
- Basic message history tracking
- How memory affects the conversation
- Different memory strategies

Run: python 03_agent_with_memory.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

# -----------------------------------------------------------------------------
# Tools (same as before)
# -----------------------------------------------------------------------------

SERVICES = {
    "checkout": {"status": "healthy", "replicas": 3, "cpu": "45%", "memory": "2.1GB"},
    "payment": {"status": "degraded", "replicas": 2, "cpu": "89%", "memory": "3.8GB"},
    "inventory": {"status": "healthy", "replicas": 5, "cpu": "22%", "memory": "1.5GB"},
}

@tool
def get_service_metrics(service_name: str) -> str:
    """Get current metrics for a service: status, replicas, CPU, memory usage.
    
    Args:
        service_name: Name of the service
    """
    if service_name not in SERVICES:
        return f"Service '{service_name}' not found. Available: {list(SERVICES.keys())}"
    s = SERVICES[service_name]
    return f"{service_name}: status={s['status']}, replicas={s['replicas']}, cpu={s['cpu']}, memory={s['memory']}"


@tool
def scale_service(service_name: str, replicas: int) -> str:
    """Scale a service to a specific number of replicas.
    
    Args:
        service_name: Name of the service
        replicas: Target number of replicas (1-10)
    """
    if service_name not in SERVICES:
        return f"Service '{service_name}' not found"
    if not 1 <= replicas <= 10:
        return "Replicas must be between 1 and 10"
    
    old_replicas = SERVICES[service_name]["replicas"]
    SERVICES[service_name]["replicas"] = replicas
    return f"Scaled {service_name} from {old_replicas} to {replicas} replicas"


# -----------------------------------------------------------------------------
# Agent with Memory
# -----------------------------------------------------------------------------

class ConversationalAgent:
    """
    An agent that maintains conversation history across multiple turns.
    
    This is the pattern you'd use for a chat-based DevOps assistant where
    the user can ask follow-up questions without repeating context.
    """
    
    def __init__(self, system_prompt: str):
        self.model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        self.tools = [get_service_metrics, scale_service]
        self.model_with_tools = self.model.bind_tools(self.tools)
        self.tools_by_name = {t.name: t for t in self.tools}
        
        # This is the "memory" - just a list of messages we keep appending to
        self.message_history = [SystemMessage(content=system_prompt)]
    
    def chat(self, user_input: str) -> str:
        """Process a user message and return the response."""
        
        # Add user's message to history
        self.message_history.append(HumanMessage(content=user_input))
        
        max_iterations = 5
        for _ in range(max_iterations):
            # Send FULL history to the model - this is what makes memory work
            response = self.model_with_tools.invoke(self.message_history)
            self.message_history.append(response)
            
            if not response.tool_calls:
                return response.content
            
            # Execute tools and add results to history
            for tool_call in response.tool_calls:
                result = self.tools_by_name[tool_call["name"]].invoke(tool_call["args"])
                self.message_history.append(
                    ToolMessage(content=str(result), tool_call_id=tool_call["id"])
                )
        
        return "Max iterations reached"
    
    def get_history_summary(self) -> str:
        """Show what's in the memory (for debugging)."""
        lines = []
        for msg in self.message_history:
            if isinstance(msg, SystemMessage):
                lines.append(f"[System]: {msg.content[:50]}...")
            elif isinstance(msg, HumanMessage):
                lines.append(f"[Human]: {msg.content}")
            elif isinstance(msg, AIMessage):
                if msg.tool_calls:
                    lines.append(f"[AI]: (calling {len(msg.tool_calls)} tool(s))")
                else:
                    lines.append(f"[AI]: {msg.content[:100]}...")
            elif isinstance(msg, ToolMessage):
                lines.append(f"[Tool]: {msg.content[:50]}...")
        return "\n".join(lines)
    
    def clear_history(self):
        """Reset memory, keeping only the system prompt."""
        self.message_history = [self.message_history[0]]


# -----------------------------------------------------------------------------
# Demo
# -----------------------------------------------------------------------------

def demo_with_memory():
    """Show how memory enables multi-turn conversations."""
    
    agent = ConversationalAgent(
        system_prompt="You are a helpful DevOps assistant. Be concise."
    )
    
    print("=" * 70)
    print("CONVERSATION WITH MEMORY")
    print("=" * 70)
    
    # Turn 1: Ask about payment service
    print("\n[User]: How's the payment service doing?")
    response = agent.chat("How's the payment service doing?")
    print(f"[Agent]: {response}")
    
    # Turn 2: Follow-up referencing "it" - the agent remembers we were talking about payment
    print("\n[User]: Can you scale it up to 4 replicas?")
    response = agent.chat("Can you scale it up to 4 replicas?")
    print(f"[Agent]: {response}")
    
    # Turn 3: Another follow-up
    print("\n[User]: What does it look like now?")
    response = agent.chat("What does it look like now?")
    print(f"[Agent]: {response}")
    
    # Show what's in memory
    print("\n" + "-" * 70)
    print("MESSAGE HISTORY (what the model sees):")
    print("-" * 70)
    print(agent.get_history_summary())


def demo_without_memory():
    """Show what happens without memory - each call is independent."""
    
    print("\n" + "=" * 70)
    print("CONVERSATION WITHOUT MEMORY (each call is fresh)")
    print("=" * 70)
    
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    tools = [get_service_metrics, scale_service]
    model_with_tools = model.bind_tools(tools)
    
    # Turn 1
    messages1 = [HumanMessage(content="How's the payment service doing?")]
    response1 = model_with_tools.invoke(messages1)
    
    # If it wants to call a tool, we'd need to handle that, but for this demo
    # let's just show it tries to call the tool
    print("\n[User]: How's the payment service doing?")
    print(f"[Agent]: (would call tool: {response1.tool_calls[0]['name'] if response1.tool_calls else 'none'})")
    
    # Turn 2 - Fresh conversation, no context from Turn 1
    messages2 = [HumanMessage(content="Can you scale it up to 4 replicas?")]
    response2 = model_with_tools.invoke(messages2)
    
    print("\n[User]: Can you scale it up to 4 replicas?")
    print(f"[Agent]: {response2.content}")
    print("^ Notice: Without memory, the agent doesn't know what 'it' refers to!")


# -----------------------------------------------------------------------------
# Memory strategies
# -----------------------------------------------------------------------------

def demo_memory_strategies():
    """
    Different ways to manage memory when conversations get long.
    
    The naive approach (keep all messages) doesn't scale - after many turns,
    you'll hit token limits and costs will skyrocket.
    """
    
    print("\n" + "=" * 70)
    print("MEMORY STRATEGIES")
    print("=" * 70)
    
    print("""
    1. FULL HISTORY (what we used above)
       - Keep all messages
       - Simple but doesn't scale
       - Good for: short conversations, debugging
    
    2. SLIDING WINDOW
       - Keep only the last N messages
       - Loses early context but bounded cost
       - Good for: long-running assistants
    
    3. SUMMARIZATION
       - Periodically summarize old messages into a shorter form
       - Preserves key context while reducing tokens
       - Good for: complex multi-step workflows
    
    4. HYBRID
       - Keep recent messages in full + summary of older ones
       - Best of both worlds
       - Good for: production systems
    
    Example sliding window implementation:
    """)
    
    # Sliding window example
    class SlidingWindowAgent(ConversationalAgent):
        def __init__(self, system_prompt: str, window_size: int = 10):
            super().__init__(system_prompt)
            self.window_size = window_size
        
        def chat(self, user_input: str) -> str:
            # Before processing, trim history to window size
            # Keep system prompt (index 0) + last N messages
            if len(self.message_history) > self.window_size + 1:
                self.message_history = [self.message_history[0]] + self.message_history[-(self.window_size):]
            
            return super().chat(user_input)
    
    print("    class SlidingWindowAgent(ConversationalAgent):")
    print("        def chat(self, user_input: str) -> str:")
    print("            if len(self.message_history) > self.window_size + 1:")
    print("                self.message_history = [self.message_history[0]] + self.message_history[-(self.window_size):]")
    print("            return super().chat(user_input)")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    demo_with_memory()
    demo_without_memory()
    demo_memory_strategies()
