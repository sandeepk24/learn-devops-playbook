# LangChain Agent Examples

Runnable Python examples that progressively build from a basic agent to a production-ready system with guardrails.

## Setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set your OpenAI API key
export OPENAI_API_KEY="your-key-here"
# Or create a .env file with: OPENAI_API_KEY=your-key-here
```

## The Examples

### 01_basic_agent.py - Start Here
The simplest possible agent: a model with tools and a manual loop.

**You'll learn:**
- What a "tool" actually is (just a function with a docstring)
- The difference between a model *requesting* a tool call vs *executing* it
- The basic agent loop: ask model → run tool → feed result back → repeat

```bash
python 01_basic_agent.py
```

---

### 02_agent_with_tools.py - DevOps Tools
An agent with realistic DevOps tools: service status, deployment history, incidents.

**You'll learn:**
- Designing tools the model can reason about effectively
- Multi-tool agents where the model chains reasoning
- The importance of clear tool docstrings

```bash
python 02_agent_with_tools.py
```

---

### 03_agent_with_memory.py - Conversation History
An agent that remembers previous turns in the conversation.

**You'll learn:**
- Why LLM calls are stateless by default
- How "memory" is just re-injecting message history
- Different memory strategies (full history, sliding window, summarization)

```bash
python 03_agent_with_memory.py
```

---

### 04_langgraph_agent.py - Full LangGraph
The same agent loop, but built properly with LangGraph's StateGraph.

**You'll learn:**
- LangGraph's state management (TypedDict + annotations)
- Graph structure: nodes, edges, conditional routing
- Persistence with checkpointing
- Streaming execution

```bash
python 04_langgraph_agent.py
```

---

### 05_agent_with_guardrails.py - Production Safety
A production-ready agent with all the safety patterns from Part 3 of the guide.

**You'll learn:**
- Tool allowlisting (only certain services can be modified)
- Argument validation before execution
- Human-in-the-loop approval for destructive actions
- Iteration limits to prevent infinite loops
- Audit logging for every tool call

```bash
python 05_agent_with_guardrails.py
```

---

### 06_react_agent_prebuilt.py - Quick Start
Using LangGraph's prebuilt `create_react_agent` for rapid prototyping.

**You'll learn:**
- When to use prebuilt vs custom agents
- Multi-step investigation workflows
- Memory with the prebuilt agent

```bash
python 06_react_agent_prebuilt.py
```

---

## Progression Path

```
01_basic_agent.py          "What is an agent, really?"
        │
        ▼
02_agent_with_tools.py     "Add realistic tools"
        │
        ▼
03_agent_with_memory.py    "Remember conversations"
        │
        ▼
04_langgraph_agent.py      "Proper state management"
        │
        ▼
05_agent_with_guardrails.py "Production safety"
        │
        ▼
06_react_agent_prebuilt.py "Know when to use shortcuts"
```

## Key Concepts Demonstrated

| Concept | Example | Key Takeaway |
|---------|---------|--------------|
| Tool binding | 01 | Model requests tools, code executes them |
| Iteration limits | 01, 05 | Always cap loops to prevent runaway costs |
| Tool docstrings | 02 | Write them like commit messages - clear, context-free |
| Memory | 03 | Just message history re-injection |
| State management | 04 | TypedDict + add_messages annotation |
| Checkpointing | 04 | Survives restarts, enables human-in-the-loop |
| Allowlisting | 05 | Don't let the model touch everything |
| Argument validation | 05 | Never trust model-generated args blindly |
| Human approval | 05 | interrupt_before for destructive actions |
| Audit logging | 05 | Log every tool call, unconditionally |

## Related Documentation

- [Part 3: Tools and Agents](../03-tools-and-agents.md) - Conceptual guide these examples implement
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [LangChain Tools Guide](https://python.langchain.com/docs/concepts/tools/)
