# Agentic AI — Design Patterns for DevOps Engineers Building Agents

> **Who this is for:** engineers who've read the difference between GenAI and Agentic AI, understand what MCP is, and now want to actually build something that plans, calls tools, and takes multi-step action — not just monitor or deploy one that someone else built.

---

## How this is different from the other AI folders in this repo

This repo already covers AI from a few angles, and it's worth being clear about where each one stops so you know where to look for what:

| Folder | What it covers | What it doesn't cover |
|---|---|---|
| [`ai-devops/`](../ai-devops/) | Running, monitoring, and securing AI systems already in production — evals, guardrails, SRE for LLMs, RAG, MCP concepts | The engineering decisions you make *while building* an agent's internals |
| [`anthropic/`](../anthropic/) | Claude specifically — API, SDK, prompting, exam prep | Framework-agnostic patterns that apply regardless of model provider |
| [`learning-amazon-bedrock-agentcore/`](../learning-amazon-bedrock-agentcore/) | Deploying an already-built agent on AWS AgentCore — packaging, runtime, ops | The design of the agent's loop, memory, and tools themselves |
| [`mcp-server-for-devops/`](../mcp-server-for-devops/) | Building an MCP *server* — the tool side of the equation | The *agent* side — how a model decides which tool to call and when |
| **`agentic-ai/` (this folder)** | The architecture patterns behind the agent itself: the loop, memory, multi-agent coordination, tool design, and the threat model — framework and cloud-agnostic | Specific SDKs, specific cloud deployment steps (those live in the folders above) |

Read this folder for the "how do I design this" questions. Read the others for the "how do I run this" and "how do I use this specific SDK" questions.

---

## Series

| # | File | What's in it |
|---|---|---|
| 1 | [`01-agentic-ai-fundamentals-for-devops.md`](./01-agentic-ai-fundamentals-for-devops.md) | What actually makes something an "agent" vs. a chatbot or a workflow, the perceive-plan-act loop, and when *not* to build one |
| 2 | [`02-agent-memory-context-and-state.md`](./02-agent-memory-context-and-state.md) | Short-term vs. long-term memory, context window management, and treating agent state like a reconciliation loop |
| 3 | [`03-multi-agent-orchestration-patterns.md`](./03-multi-agent-orchestration-patterns.md) | Single agent vs. orchestrator-worker vs. pipeline vs. swarm, the framework landscape, and MCP vs. A2A |
| 4 | [`04-tool-use-and-function-calling-design.md`](./04-tool-use-and-function-calling-design.md) | What a "tool" actually is to a model, and the design principles that keep agents from doing something dumb with them |
| 5 | [`05-agentic-ai-security-threat-model.md`](./05-agentic-ai-security-threat-model.md) | Prompt injection, excessive agency, tool poisoning, and the "lethal trifecta" — mapped to controls you already know from IAM and least privilege |

---

## Prerequisites

You don't need a machine learning background. You do need:

- Enough Python to read and write functions and classes comfortably — see the [Python roadmap](../python/README.md) if you're not there yet
- The [Pydantic guide](../python/python_pydantic_devops_guide.md) — every serious agent framework uses Pydantic (or something shaped exactly like it) to define tool schemas and structured outputs
- A skim of [GenAI vs Agentic AI, part 1](../ai-devops/genai-vs-agentic-ai-part1.md) if you haven't already — this series assumes you know the difference and moves straight into how to build the "acts on your behalf" half

---

## How to use this series

Read 01 through 05 in order the first time — each one assumes the last. After that, it's a reference for design reviews: before you ship an agent, the checklists at the bottom of 04 and 05 are worth running through like a pre-deploy checklist.

None of this is framework-specific on purpose. Whether you end up building on LangGraph, CrewAI, AWS Strands, Bedrock AgentCore, or a homegrown loop, the concepts here — the loop, the memory model, the orchestration pattern, the tool contract, the threat model — are the part that transfers. The SDK syntax is the easy part; get that from the docs.

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*
