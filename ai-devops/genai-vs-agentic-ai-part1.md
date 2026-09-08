# Generative AI vs Agentic AI: What Every DevOps & Cloud Engineer Needs to Know

### Part 1 of 2 — The Concepts, the Vocabulary, and How They Actually Differ

---

> "Everyone's talking about AI. But when your CTO says 'let's add AI to our pipeline,' do they mean the same thing as when your developer says 'the agent fixed the bug automatically'? Spoiler: they don't."

---

## Why This Matters to You Specifically

If you're a DevOps or cloud engineer in 2026, AI isn't coming — it's already here, embedded in your IDE, your CI/CD pipeline, your incident runbooks, and your infrastructure code. But there's a critical difference between AI that **helps you think** and AI that **acts on your behalf**. Getting that wrong can cost you in security, in compliance, in architecture decisions, and in your career.

This article is written for engineers. Not for managers who need a slide deck. Not for marketers who want buzzwords. For the people who actually build and run the systems — the ones who need to understand what's happening under the hood.

Let's strip away the hype and make this clear.

---

## Section 1: Generative AI — The Smart Autocomplete (That's Much More Than That)

### What it actually is

Generative AI refers to AI models that **create new content** — text, code, images, audio, data — based on patterns learned from training data. The key characteristic: you give it a prompt, it gives you an output. One turn. Done. It doesn't remember what you said yesterday (unless you explicitly pass that context back in). It doesn't take action in the world. It generates.

Think of it like this: imagine you hire the world's most well-read consultant. You ask them a question, they give you an incredible answer — synthesised from millions of documents, code repos, and technical papers. But once they walk out of the room, they forget everything. Next time you meet, you start from scratch.

That's generative AI.

### The technical anatomy

Under the hood, most generative AI today is built on **Large Language Models (LLMs)** — neural networks (specifically transformer architectures) trained on enormous datasets. When you send a prompt, the model predicts the most statistically likely next tokens (words/subwords) given your input and its training. It's probabilistic, not deterministic.

For code generation specifically — which is your daily bread — the model has been trained on billions of lines of code from GitHub, Stack Overflow, documentation, and more. When you ask it to write a Terraform module, it's pattern-matching against every HCL file it ever "read."

### Real-world examples of Generative AI in your work

**Code generation and completion**
You type a comment: `# function to check if S3 bucket versioning is enabled` — and the model completes the function. This is pure generative AI. One prompt in, one code block out.

**Documentation generation**
You paste a Lambda function and ask: "Write the README for this." The model generates documentation. It doesn't create the file. It doesn't commit it. It writes text for you to review and use.

**IaC generation**
You describe your infrastructure: "I need a VPC with two public and two private subnets, a NAT gateway, and an internet gateway in us-east-1" — the model generates the CloudFormation or Terraform template.

**Log analysis and root cause suggestions**
You paste a stack trace from CloudWatch, and the model explains what went wrong and suggests fixes. It's giving you insight, not executing a fix.

**Writing runbooks and SOPs**
You describe a process, and the model drafts a runbook. You review, edit, publish. The model's job ended at generating the draft.

### What generative AI is NOT doing

This matters. Generative AI — in its pure form — is **not**:

- Accessing your AWS account
- Running your Terraform plan
- Checking your CloudWatch logs autonomously
- Opening a PR on your behalf
- Monitoring your pipeline and reacting to failures
- Making decisions across multiple steps

It receives a prompt. It returns a response. Full stop.

---

## Section 2: Agentic AI — When AI Gets a To-Do List and the Keys to the Kingdom

### What it actually is

Agentic AI (also called AI agents or autonomous agents) takes generative AI and adds something new: **the ability to take actions, use tools, remember context, plan across multiple steps, and operate with a degree of autonomy** — often without requiring human input at every single step.

An AI agent doesn't just answer your question. It:
1. Understands a high-level goal
2. Breaks it into sub-tasks
3. Uses tools (APIs, bash, browsers, databases) to execute those sub-tasks
4. Evaluates the results
5. Adjusts its approach if something fails
6. Delivers a final outcome

The same consultant analogy: this time, after the meeting, they get up, go check your servers, look at your monitoring dashboard, write the code, test it, and send you a pull request — while you're asleep. They act.

### Why this is architecturally different

It's not just "generative AI with extra steps." The core differences are:

| Dimension | Generative AI | Agentic AI |
|---|---|---|
| Execution model | Single prompt → single response | Goal → multi-step plan → execution |
| State | Stateless (within a single request) | Stateful — maintains memory across steps |
| Tool use | None by default | Accesses external tools, APIs, filesystems |
| Autonomy | Zero — waits for human input | Varies — can act without per-step approval |
| Failure handling | N/A — just generates output | Can retry, reroute, or escalate on failure |
| Security surface | Text generation only | Much larger — touches real systems |
| Observability needs | Basic logging | Requires full audit trails, tracing |

---

## Section 3: The Vocabulary — Terms You'll See Everywhere, Explained Properly

These terms come up constantly in job descriptions, AWS documentation, architecture diagrams, and vendor pitches. Here's what they actually mean.

---

### Foundation Models (FMs)

Large, pre-trained neural networks that serve as a starting point for AI applications. They're "foundational" because they're not built for a single task — they understand general patterns in language, code, and reasoning. Examples: Claude, GPT-4, Amazon Nova, Meta LLaMA.

As a cloud engineer, you don't typically train these from scratch. You consume them via APIs (like Amazon Bedrock) and optionally fine-tune them for your domain.

---

### LLM (Large Language Model)

A specific type of foundation model trained primarily on text (including code). The "large" refers to the number of parameters — billions to hundreds of billions of weights that encode learned patterns. When people say "the model," they usually mean the LLM at the core.

---

### Prompt Engineering

The craft of writing effective inputs to a model to get better outputs. It's a real skill, not a gimmick. Includes techniques like:

- **Zero-shot prompting** — ask the model directly, no examples
- **Few-shot prompting** — give 2–3 examples to guide the output format
- **Chain-of-thought** — instruct the model to reason step-by-step before answering
- **System prompts** — a persistent instruction set that shapes the model's behavior across a conversation

For DevOps engineers: good prompt engineering applied to IaC generation or incident analysis can be the difference between useful output and garbage.

---

### Tokens

The basic units models work with — not characters, not words exactly, but chunks of text. "CloudFormation" might be 2–3 tokens. "const" is 1 token. Why do you care? Because:

- Model APIs charge by token (input + output)
- Models have a **context window** — a maximum number of tokens they can process at once
- Large configuration files, long stack traces, or massive codebases can exceed context windows

Understanding tokens helps you architect cost-effectively and avoid silent truncation bugs.

---

### Context Window

The maximum amount of text (in tokens) a model can "see" at once — its working memory. Older models: 4K–8K tokens. Modern models: 128K–1M+ tokens.

Practical implication: if you're building a RAG pipeline (more on that below) or passing long CloudFormation templates to a model, you need to know your context limits. Chunking strategies, compression, and retrieval systems exist specifically to deal with this constraint.

---

### RAG (Retrieval-Augmented Generation)

One of the most practically important patterns in enterprise AI. The problem it solves: LLMs have a training cutoff and don't know your internal documentation, your company's Terraform modules, your runbooks, your architecture decisions.

RAG fixes this by:
1. Storing your documents in a **vector database** (after converting them to numerical embeddings)
2. At query time, retrieving the most relevant document chunks
3. Injecting them into the model's context before it answers

The model's knowledge + your company's knowledge = much more accurate, grounded responses.

As a cloud engineer building internal tools, RAG is how you make the AI answer based on *your* runbooks, not generic best practices it learned from the internet.

---

### Vector Database

A database optimised for storing and querying **embeddings** — high-dimensional numerical representations of text. When you do RAG, your documents get converted to embeddings (e.g., "VPC peering setup" becomes a vector of 1536 floating-point numbers). The vector DB can find documents with *semantically similar* meaning to a query, not just keyword matches.

AWS options: Amazon OpenSearch Serverless (with vector engine), Aurora PostgreSQL with pgvector, or Neptune Analytics.

---

### Embeddings

The numerical vector representations of text. Semantically similar text produces similar vectors — which is why "fix prod" and "resolve production incident" can return the same runbook in a RAG search. They're generated by embedding models (a specific type of smaller model designed for this task).

---

### Fine-tuning

Taking a pre-trained foundation model and continuing to train it on your own domain-specific data. This makes the model better at your specific tasks — writing your company's Terraform style, following your naming conventions, understanding your internal service terminology.

Fine-tuning is expensive and complex. Most teams should try RAG and prompt engineering first. Fine-tuning is for when you need consistent behaviour patterns, not just knowledge retrieval.

---

### Tool Use / Function Calling

The mechanism that turns a generative model into an agentic one. You define a set of "tools" (functions, APIs, bash commands) and their schemas. The model can decide to call these tools mid-response when it needs information or needs to take an action.

Example: you define a `get_cloudwatch_logs` tool that takes a log group name and time range. When the agent is diagnosing an incident, it can call this tool itself — rather than asking you to paste the logs.

This is the hinge point between generative and agentic.

---

### ReAct (Reasoning + Acting)

A popular pattern for AI agents. The model alternates between:
- **Thought**: reasoning about what to do next
- **Action**: calling a tool
- **Observation**: reading the tool's output
- **... repeat until done**

Most modern agentic frameworks implement some variant of this loop. When you see a model "thinking step by step" and then calling APIs, you're watching ReAct.

---

### Memory (Short-term, Long-term, Episodic)

Agents need to remember things. Types:

- **In-context (short-term)**: everything in the current conversation window. Fast, but limited by context size and lost when the session ends.
- **External (long-term)**: persisted to a database outside the model. The agent explicitly reads/writes. Survives across sessions.
- **Episodic**: memory of past interactions/outcomes. "Last time I ran this Terraform plan, it failed because X." Used to avoid repeating mistakes.

For production agents — like one that manages your deployments — long-term memory is not optional; it's a safety requirement.

---

### Guardrails

Mechanisms to constrain what an agent can do, say, or access. In production, you don't want your deployment agent writing to prod databases it shouldn't touch, or your chat assistant revealing internal API keys mentioned in docs.

Amazon Bedrock Guardrails, for example, can filter topics, mask sensitive information, detect hallucinations, and block toxic content. Think of guardrails as the IAM policies of the AI layer.

---

### Multi-Agent Systems

Instead of one agent that does everything, you build a team of specialised agents that collaborate. A **supervisor/orchestrator agent** breaks down a task and delegates to:

- A **code agent** that writes the fix
- A **test agent** that verifies it
- A **deployment agent** that ships it
- A **monitoring agent** that confirms the rollout

This mirrors your DevOps team structure. Each agent has limited, well-defined scope — which is also better for security and auditability.

---

### MCP (Model Context Protocol)

An open protocol (originally developed by Anthropic, now widely adopted) that standardises how AI models connect to external tools and data sources. Think of it like USB-C for AI integrations — instead of every agent needing custom connectors for every tool, MCP provides a standard interface.

As a DevOps engineer, when you see "MCP server for AWS," that means a standardised way for any MCP-compatible agent to query your AWS resources without writing custom integration code.

---

### Agentic Loops / Orchestration

The control flow that governs how an agent executes. Includes:
- How it plans
- How it decides when to use which tool
- What happens when a tool fails
- When it asks for human approval vs. acting autonomously
- When it considers the task done

Poorly designed loops = agents that spin endlessly, waste tokens, or worse — take destructive actions because no one defined a stopping condition.

---

### Human-in-the-Loop (HITL)

A design pattern where, at certain points in an agentic workflow, the system pauses and waits for human confirmation before proceeding. Critical for irreversible actions — like terminating EC2 instances or deploying to production.

The tradeoff: more HITL = safer, but slower. Less HITL = faster, but higher blast radius if something goes wrong. As a cloud engineer, your job is setting HITL checkpoints at the right places.

---

## Section 4: A Side-by-Side Mental Model

Here's how to quickly classify any AI use case you encounter:

**Ask yourself: "Does the AI just *output* something, or does it *do* something?"**

- Outputs text/code/analysis → Generative AI
- Does things, calls APIs, takes actions, operates across steps → Agentic AI

More practically:

**Generative AI pattern** — LLM-style interactions, code autocompletion, documentation generation, template creation, log analysis where you paste and it explains, security policy drafting.

**Agentic AI pattern** — automated incident response (the agent detects and acts), autonomous code review + PR creation, self-healing infrastructure, CI/CD pipeline agents that debug and re-run failing builds, chat bots that actually look up your real-time AWS cost data.

The line can blur. A single chatbot session might start generative (write me a runbook) and become agentic (now go create it in Confluence, tag it, and link it to the relevant alert). Modern platforms blur these deliberately — which is why understanding how the two actually differ matters.

---

## What's Coming in Part 2

In Part 2, we go hands-on with AWS. We'll cover:

- Amazon Bedrock — the full picture: models, RAG (Knowledge Bases), Agents, and AgentCore
- Amazon Kiro — AWS's new spec-driven agentic IDE (and why it replaced Amazon Q Developer)
- Amazon Q Business — generative AI for your organisation's internal knowledge
- Real architecture patterns for DevOps: agentic incident response, autonomous deployments, IaC generation pipelines
- What you can build *today* vs. what's still maturing
- Key questions to ask before putting agents anywhere near production

---

*Continue reading: [Part 2 → AWS in Practice: Building Generative and Agentic AI on the Cloud](./genai-vs-agentic-ai-part2.md)*
