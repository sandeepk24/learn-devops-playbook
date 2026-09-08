# AWS Strands Agents: The Complete Guide for Cloud & DevOps Engineers

> 🎯 **Who this is for:** Cloud Engineers, DevOps Engineers, and Senior Engineers building GenAI or Agentic AI applications on AWS. This guide takes you from "what even is this?" to deploying production-ready agents with RAG, multi-agent orchestration, and full observability.

---

## Table of Contents

1. [What Is Strands Agents and Why Should You Care?](#1-what-is-strands-agents-and-why-should-you-care)
2. [The Big Picture: Where Strands Fits in the AWS AI Stack](#2-the-big-picture-where-strands-fits-in-the-aws-ai-stack)
3. [How the Agent Loop Actually Works](#3-how-the-agent-loop-actually-works)
4. [Getting Started: Installation and First Agent](#4-getting-started-installation-and-first-agent)
5. [The Three Pillars: Model, Tools, and Prompt](#5-the-three-pillars-model-tools-and-prompt)
6. [Tools Deep Dive: The Secret Weapon](#6-tools-deep-dive-the-secret-weapon)
7. [RAG with Bedrock Knowledge Bases](#7-rag-with-bedrock-knowledge-bases)
8. [Multi-Agent Systems](#8-multi-agent-systems)
9. [IAM: What Permissions You Actually Need](#9-iam-what-permissions-you-actually-need)
10. [Production Deployment with AgentCore](#10-production-deployment-with-agentcore)
11. [Observability and Monitoring](#11-observability-and-monitoring)
12. [Security Best Practices](#12-security-best-practices)
13. [Strands vs. LangChain vs. LangGraph: When to Pick What](#13-strands-vs-langchain-vs-langgraph-when-to-pick-what)
14. [Common Pitfalls and How to Avoid Them](#14-common-pitfalls-and-how-to-avoid-them)
15. [Architecture Decision Checklist](#15-architecture-decision-checklist)

---

## 1. What Is Strands Agents and Why Should You Care?

Let's be honest — "agentic AI" is one of the most over-hyped phrases in tech right now. Half the articles you read are either too basic ("an agent calls tools!") or too academic to be useful. So let's cut through it.

**Strands Agents** is an open-source Python SDK released by AWS in 2025. The core idea is simple: instead of you writing a rigid workflow like "step 1 → step 2 → step 3", you hand a modern LLM a goal and a set of tools, and the model figures out what to do, in what order, and whether it needs to try again.

That's what "model-driven" means. The model drives. You don't hand-code the flow.

Here's the before/after of why this matters:

**Before Strands (traditional workflow approach):**
```python
# You hardcode every decision yourself
def handle_code_issue(code, error):
    analysis = call_llm(f"Analyze this error: {error}")
    if "import" in analysis:
        fix = call_llm(f"Fix the import: {code}")
    elif "syntax" in analysis:
        fix = call_llm(f"Fix the syntax: {code}")
    else:
        fix = call_llm(f"Fix this: {code}")
    tests = run_tests(fix)
    if not tests.passed:
        # Now what? Write more if-else...
```

**After Strands (model-driven approach):**
```python
from strands import Agent, tool

@tool
def run_tests(code: str) -> str:
    """Run tests on the provided Python code and return results."""
    # your test runner logic here
    ...

agent = Agent(
    system_prompt="You are an expert Python engineer. Fix code issues and verify with tests.",
    tools=[run_tests]
)

agent("This code is throwing a NameError: " + error_message)
# The model decides when to run tests, how many times to retry, etc.
```

The name "Strands" comes from DNA — two strands that are inseparable. In this case, the two strands are the **model** (reasoning) and the **tools** (actions). You can't have a useful agent without both.

Multiple AWS teams already use Strands in production: Amazon Q Developer, AWS Glue, and VPC Reachability Analyzer are all built on it.

---

## 2. The Big Picture: Where Strands Fits in the AWS AI Stack

Before you start building, you need to understand what problem each AWS AI service actually solves. This is the part that confuses most teams, because the names all sound similar.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Your Application / Users                          │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │        Strands Agents SDK       │
                    │   (The Brain / Orchestration)   │
                    │   Reasoning, tool selection,    │
                    │   multi-step planning           │
                    └───────────────┬────────────────┘
                                    │
          ┌─────────────────────────┼───────────────────────┐
          │                         │                        │
          ▼                         ▼                        ▼
┌─────────────────┐    ┌────────────────────┐   ┌──────────────────────┐
│  Amazon Bedrock │    │  Bedrock Knowledge  │   │   AgentCore Runtime  │
│  (Foundation    │    │  Bases (RAG /       │   │   (Deployment,       │
│   Models)       │    │  Retrieval)         │   │   Memory, Identity,  │
│                 │    │                     │   │   Observability)     │
│  Claude, Nova,  │    │  OpenSearch, S3     │   │                      │
│  Llama, Titan   │    │  Vectors, etc.      │   │  Production hosting  │
└─────────────────┘    └────────────────────┘   └──────────────────────┘
          │                         │                        │
          └─────────────────────────┼────────────────────────┘
                                    │
          ┌─────────────────────────┼───────────────────────┐
          │                         │                        │
          ▼                         ▼                        ▼
┌─────────────────┐    ┌────────────────────┐   ┌──────────────────────┐
│   MCP Servers   │    │  Bedrock Guardrails │   │  CloudWatch / OTEL   │
│  (Tool access   │    │  (Content safety,   │   │  (Logs, traces,      │
│  via protocol)  │    │   PII filtering)    │   │   metrics)           │
└─────────────────┘    └────────────────────┘   └──────────────────────┘
```

**The plain English version of this stack:**

| Service | What It Actually Does |
|---|---|
| **Strands Agents SDK** | The orchestration brain. Decides what to do next, which tools to call, when it's done. |
| **Amazon Bedrock** | The underlying LLM(s) that power the reasoning — Claude, Nova, Llama, etc. |
| **Bedrock Knowledge Bases** | Your RAG layer. Stores documents as vectors, retrieves them semantically. |
| **AgentCore Runtime** | Where you deploy Strands agents to production. Handles session, memory, and scaling. |
| **Bedrock Guardrails** | Safety filters. Block bad inputs, PII, off-topic content. |
| **MCP Servers** | Standardized protocol for giving your agent access to external tools and APIs. |
| **CloudWatch / OTEL** | Observability. Traces, logs, and metrics so you know what your agent did. |

---

## 3. How the Agent Loop Actually Works

This is the part most tutorials skip, but understanding the loop is critical for debugging production issues and understanding why your agent is making certain decisions.

```
                         ┌──────────────────────────┐
                         │   User sends a message    │
                         └──────────────┬────────────┘
                                        │
                         ┌──────────────▼────────────┐
                         │   Agent sends message to   │
                         │   the LLM with:            │
                         │   - System prompt          │
                         │   - Conversation history   │
                         │   - Available tools list   │
                         └──────────────┬────────────┘
                                        │
                    ┌───────────────────▼──────────────────┐
                    │     Does the model want to call a     │
                    │     tool, or is it done?              │
                    └───────────────────┬──────────────────┘
                                        │
              ┌─────────────────────────┼──────────────────────┐
              │                                                  │
    ┌─────────▼────────┐                             ┌──────────▼────────┐
    │  Model calls a   │                             │   Model gives a   │
    │  tool            │                             │   final answer    │
    │  (e.g., retrieve,│                             │                   │
    │   run_test,      │                             │   → Stream        │
    │   call_api)      │                             │     response to   │
    └─────────┬────────┘                             │     user          │
              │                                      └───────────────────┘
    ┌─────────▼────────┐
    │  Strands         │
    │  executes the    │
    │  tool locally    │
    │  (your Python    │
    │  function runs)  │
    └─────────┬────────┘
              │
    ┌─────────▼────────┐
    │  Tool result is  │
    │  appended to the │
    │  conversation    │
    │  history         │
    └─────────┬────────┘
              │
              └─────────── (loop back up to "send message to LLM")
```

This loop continues until the model decides it has enough information to give a final answer — or until it hits a max iteration limit (which you can configure).

**Why this matters operationally:**
- Each loop iteration = another Bedrock API call = latency + cost
- A misbehaving tool that always returns incomplete data will cause the agent to loop repeatedly
- You should monitor the number of iterations per agent invocation as a key metric
- Strands gives you callbacks (called *event handlers*) at each step so you can log, trace, or interrupt

---

## 4. Getting Started: Installation and First Agent

### Prerequisites

Before you write a single line of Strands code, confirm the following:

1. AWS credentials configured (`aws configure` or IAM role attached to your compute)
2. Model access enabled in the Bedrock console for the model you want to use
3. Python 3.10+

### Installation

```bash
# Create and activate a virtual environment (always do this)
python -m venv .venv
source .venv/bin/activate          # Linux/macOS
# .venv\Scripts\activate           # Windows

# Install Strands SDK and the pre-built tools package
pip install strands-agents strands-agents-tools
```

### Your First Agent in 5 Lines

```python
from strands import Agent
from strands_tools import calculator

# That's it. The default model is Claude via Bedrock in us-west-2.
agent = Agent(tools=[calculator])
agent("What is 15% of 847, and then multiply that by the square root of 144?")
```

When you run this, Strands will:
1. Send your question to Claude via Bedrock
2. Claude decides to call the `calculator` tool
3. Strands runs the calculator locally
4. The result is fed back to Claude
5. Claude gives you a final, human-readable answer

> ⚠️ **First-run gotcha:** The default model is `claude-sonnet-4` in `us-west-2`. You need model access enabled for that model in your account, in that region. If you get an `AccessDeniedException`, go to the Bedrock console → Model access and enable it.

---

## 5. The Three Pillars: Model, Tools, and Prompt

Every Strands agent is built from exactly three things. Get these three right, and everything else follows.

### Pillar 1: The Model

Strands supports a wide range of models — not just Bedrock:

```python
from strands import Agent
from strands.models import BedrockModel
from strands.models.ollama import OllamaModel

# --- Option 1: Amazon Bedrock (recommended for production) ---
bedrock_model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",  # cross-region profile
    temperature=0.3,      # lower = more deterministic, good for code tasks
    streaming=True,       # stream tokens as they're generated
)

# --- Option 2: Ollama for local dev (no AWS costs, great for testing) ---
local_model = OllamaModel(
    host="http://localhost:11434",
    model_id="llama3"
)

# --- Use whichever model you want ---
agent = Agent(model=bedrock_model, tools=[...])
```

**Model selection guidance for your use case:**

| Use Case | Recommended Model | Why |
|---|---|---|
| Code analysis / debugging | `claude-sonnet-4` or `claude-opus-4` | Strong reasoning, good at multi-step code problems |
| RAG / document Q&A | `amazon.nova-pro` or `claude-sonnet-4` | Good at synthesis from retrieved context |
| High-volume, simple tasks | `amazon.nova-lite` or `claude-haiku` | Cheaper, faster for simpler tool calls |
| Local dev / testing | Ollama + `llama3` | Free, no API calls, fast iteration |

### Pillar 2: Tools

Tools are just Python functions. That's really all they are. The `@tool` decorator exposes them to the model by turning the function signature and docstring into a tool description that the LLM understands.

```python
from strands import Agent, tool

@tool
def check_ec2_health(instance_id: str, region: str = "us-east-1") -> dict:
    """
    Check the health status of an EC2 instance.
    
    Args:
        instance_id: The EC2 instance ID (e.g., 'i-1234567890abcdef0')
        region: AWS region where the instance is located
    
    Returns:
        A dict with health status and recent CloudWatch alarms
    """
    import boto3
    ec2 = boto3.client('ec2', region_name=region)
    cloudwatch = boto3.client('cloudwatch', region_name=region)
    
    response = ec2.describe_instance_status(InstanceIds=[instance_id])
    statuses = response.get('InstanceStatuses', [])
    
    alarms = cloudwatch.describe_alarms_for_metric(
        Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
        MetricName='CPUUtilization',
        Namespace='AWS/EC2'
    )
    
    return {
        "status": statuses[0]['InstanceState']['Name'] if statuses else "unknown",
        "system_health": statuses[0]['SystemStatus']['Status'] if statuses else "unknown",
        "alarm_count": len(alarms.get('MetricAlarms', []))
    }

agent = Agent(
    system_prompt="You are an AWS infrastructure monitoring assistant.",
    tools=[check_ec2_health]
)

agent("Is instance i-0abc123def456 healthy? It's in us-east-1.")
```

> 💡 **Pro tip:** The docstring is *critical*. The LLM reads it to understand when and how to call your tool. Write clear docstrings — this is the most impactful thing you can do to improve tool selection accuracy.

### Pillar 3: The System Prompt

The system prompt defines your agent's personality, constraints, and domain expertise. Think of it as the job description you hand to a new hire.

```python
DEVOPS_AGENT_PROMPT = """
You are a senior DevOps engineer at this company.

Your responsibilities:
- Monitor and diagnose infrastructure issues across AWS
- Analyze CloudWatch logs and metrics
- Recommend and implement fixes for common cloud issues
- Always check the current state before suggesting changes
- Prefer non-destructive actions first; confirm before any deletes

What you never do:
- Terminate instances without explicit user confirmation
- Make changes in production without stating what you're about to do
- Guess — if you need more information, use your tools to get it

When you're done investigating, always summarize:
1. What you found
2. What you did (or recommend doing)
3. What to watch for next
"""

agent = Agent(
    system_prompt=DEVOPS_AGENT_PROMPT,
    tools=[check_ec2_health, get_cloudwatch_logs, list_alarms]
)
```

---

## 6. Tools Deep Dive: The Secret Weapon

### Pre-Built Tools from `strands-agents-tools`

Strands ships with 20+ pre-built tools you can use immediately:

```python
from strands_tools import (
    retrieve,          # Semantic search against Bedrock Knowledge Bases (RAG)
    calculator,        # Math operations
    http_request,      # Make HTTP calls to any API
    shell,             # Execute shell commands (use carefully!)
    file_read,         # Read files from disk
    file_write,        # Write files to disk
    python_repl,       # Execute Python code dynamically
    current_time,      # Get current date/time
)
```

### MCP Servers as Tools

One of Strands' most powerful features is its native support for **Model Context Protocol (MCP)** servers. There are thousands of published MCP servers — for GitHub, Slack, databases, AWS docs, Jira, and more. You can plug any of them into your agent with a few lines:

```python
from strands import Agent
from strands.tools.mcp import MCPClient
from mcp import stdio_client, StdioServerParameters

# Connect to the official AWS Documentation MCP server
aws_docs_client = MCPClient(
    lambda: stdio_client(
        StdioServerParameters(
            command="uvx",
            args=["awslabs.aws-documentation-mcp-server@latest"]
        )
    )
)

# The `with` block manages the connection lifecycle
with aws_docs_client:
    tools = aws_docs_client.list_tools_sync()
    agent = Agent(tools=tools)
    response = agent("What are the IAM permissions needed to use Bedrock Knowledge Bases?")
```

This agent can now search AWS documentation in real-time and answer your questions with up-to-date information.

### Handling Massive Tool Libraries with Semantic Search

Here's a real problem at scale: what if your agent needs access to hundreds or thousands of tools? You can't list them all in the context window — LLMs can't reliably pick from that many options.

Strands has a clean fix for this: the `retrieve` tool for tool discovery:

```python
from strands import Agent
from strands_tools import retrieve

# Instead of passing all 500 tools at once, the agent retrieves
# the most relevant ones based on the current task using semantic search.
# AWS internally has agents with over 6,000 tools using this pattern.

agent = Agent(
    system_prompt="""
    You are an infrastructure automation agent.
    When you need to perform an action, first use the retrieve tool
    to find the right tool from the tool knowledge base, then use it.
    Tool knowledge base ID: {YOUR_TOOLS_KB_ID}
    """,
    tools=[retrieve]  # Only the retriever is listed — it fetches the rest
)
```

---

## 7. RAG with Bedrock Knowledge Bases

RAG (Retrieval-Augmented Generation) is how you give your agent access to your own documents, runbooks, wikis, or any private knowledge — without retraining a model.

The flow is:

```
User asks a question
        │
        ▼
Agent calls the `retrieve` tool
        │
        ▼
retrieve queries Bedrock Knowledge Base
(semantic vector search against your docs)
        │
        ▼
Top-N relevant documents returned
        │
        ▼
Documents injected into LLM context
        │
        ▼
LLM generates an answer grounded in YOUR docs
```

### Setting Up Bedrock Knowledge Base (CLI)

```bash
# Step 1: Create the Knowledge Base
aws bedrock-agent create-knowledge-base \
  --name "MyRunbookKB" \
  --description "Company runbooks and incident response guides" \
  --role-arn "arn:aws:iam::123456789:role/AmazonBedrockExecutionRole" \
  --knowledge-base-configuration '{
    "type": "VECTOR",
    "vectorKnowledgeBaseConfiguration": {
      "embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }' \
  --storage-configuration '{
    "type": "OPENSEARCH_SERVERLESS",
    "opensearchServerlessConfiguration": {
      "collectionArn": "arn:aws:aoss:us-east-1:123456789:collection/my-collection",
      "vectorIndexName": "bedrock-knowledge-base-index",
      "fieldMapping": {
        "vectorField": "embedding",
        "textField": "AMAZON_BEDROCK_TEXT",
        "metadataField": "AMAZON_BEDROCK_METADATA"
      }
    }
  }'
```

### Using RAG in a Strands Agent

```python
import os
from strands import Agent
from strands.models import BedrockModel
from strands_tools import retrieve

KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    region_name=REGION
)

# The agent will automatically decide when to call retrieve
# based on the question — you don't wire this manually
agent = Agent(
    model=model,
    system_prompt=f"""
    You are an infrastructure support agent with access to our internal runbook library.
    
    When answering questions about procedures, incidents, or configurations:
    1. Always search the knowledge base first using the retrieve tool
    2. Ground your answers in the retrieved documentation
    3. Cite which document the information came from
    4. If the docs don't cover it, say so clearly
    
    Knowledge Base ID: {KNOWLEDGE_BASE_ID}
    Region: {REGION}
    """,
    tools=[retrieve]
)

# Interactive loop
while True:
    question = input("\nYour question: ")
    if question.lower() == "quit":
        break
    agent(question)
```

### Advanced: Direct Retrieval Control

Sometimes you want to search the KB yourself and control what goes to the model:

```python
# Direct retrieval without going through the full agent loop
kb_results = agent.tool.retrieve(
    text="How do I respond to a DynamoDB throttling alert?",
    knowledgeBaseId=KNOWLEDGE_BASE_ID,
    numberOfResults=5,      # how many chunks to retrieve
    score=0.4,              # minimum similarity threshold (0-1)
    region=REGION,
)

# Build a custom augmented prompt
context = "\n\n".join([r['content'] for r in kb_results['results']])
augmented_prompt = f"""
Use ONLY the following runbook excerpts to answer the question.
If the answer isn't in the excerpts, say "I don't have that in the runbooks."

Runbook Excerpts:
{context}

Question: How do I respond to a DynamoDB throttling alert?
"""

agent(augmented_prompt)
```

---

## 8. Multi-Agent Systems

Single agents are powerful. Multi-agent systems are where things get really interesting for complex workflows — and where Strands really shines compared to other frameworks.

The idea: instead of one agent trying to do everything, you have specialized agents that each do one thing well, and an orchestrator that routes work between them.

### Pattern 1: Orchestrator → Specialist Agents

```python
from strands import Agent
from strands.models import BedrockModel

model = BedrockModel(model_id="us.anthropic.claude-sonnet-4-20250514-v1:0")

# --- Specialist: Handles log analysis ---
log_analyzer = Agent(
    model=model,
    system_prompt="""
    You are a CloudWatch log analysis specialist.
    You parse log patterns, identify errors, and extract meaningful signals.
    Be precise. Output structured findings.
    """
)

# --- Specialist: Handles infrastructure changes ---
infra_agent = Agent(
    model=model,
    system_prompt="""
    You are an AWS infrastructure remediation specialist.
    Given a problem description, you identify and apply the right fix.
    Always state what you're about to do before doing it.
    """
)

# --- Wrap specialist agents as tools for the orchestrator ---
from strands import tool

@tool
def analyze_logs(log_content: str) -> str:
    """Analyze CloudWatch logs and extract error patterns and root cause signals."""
    response = log_analyzer(log_content)
    return str(response)

@tool
def fix_infrastructure(problem_description: str) -> str:
    """Apply infrastructure fixes based on a problem description."""
    response = infra_agent(problem_description)
    return str(response)

# --- Orchestrator uses the specialist agents as tools ---
orchestrator = Agent(
    model=model,
    system_prompt="""
    You are an incident response orchestrator.
    When an incident is reported:
    1. Use analyze_logs to understand what went wrong
    2. Use fix_infrastructure to remediate the issue
    3. Summarize what was done
    """,
    tools=[analyze_logs, fix_infrastructure]
)

# Trigger the whole multi-agent workflow with one call
orchestrator("""
    INCIDENT ALERT: API gateway returning 5xx errors on /checkout endpoint.
    
    Recent logs:
    [ERROR] 2025-05-12T14:23:01Z - Lambda timeout after 29900ms - function: checkout-processor
    [ERROR] 2025-05-12T14:23:04Z - DynamoDB ProvisionedThroughputExceededException - table: orders
    [ERROR] 2025-05-12T14:23:08Z - Lambda timeout after 29900ms - function: checkout-processor
""")
```

### Pattern 2: Using the Built-in `agent_graph` Tool

Strands has a built-in `agent_graph` tool for when you need parallel execution or more complex routing:

```python
from strands import Agent
from strands_tools import agent_graph  # Built-in multi-agent tool

orchestrator = Agent(
    system_prompt="Coordinate parallel analysis across multiple specialized agents.",
    tools=[agent_graph]
)
```

---

## 9. IAM: What Permissions You Actually Need

This is the part that bites people most often, so let's be thorough.

### Minimum IAM Policy for a Basic Strands Agent

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvoke",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:Converse",
        "bedrock:ConverseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/*",
        "arn:aws:bedrock:us-west-2::foundation-model/*",
        "arn:aws:bedrock:us-east-1:*:inference-profile/us.*",
        "arn:aws:bedrock:us-west-2:*:inference-profile/us.*"
      ]
    }
  ]
}
```

### Adding Knowledge Base (RAG) Permissions

```json
{
  "Sid": "BedrockKnowledgeBase",
  "Effect": "Allow",
  "Action": [
    "bedrock:Retrieve",
    "bedrock:RetrieveAndGenerate",
    "bedrock:ListKnowledgeBases",
    "bedrock:GetKnowledgeBase"
  ],
  "Resource": [
    "arn:aws:bedrock:us-east-1:123456789:knowledge-base/*"
  ]
}
```

### Adding Guardrails Permissions

```json
{
  "Sid": "BedrockGuardrails",
  "Effect": "Allow",
  "Action": [
    "bedrock:ApplyGuardrail"
  ],
  "Resource": [
    "arn:aws:bedrock:us-east-1:123456789:guardrail/*"
  ]
}
```

### If Your Agent Tools Access Other AWS Services

Your agent's IAM role also needs permissions for whatever your tools do. For example, if your agent has an EC2 monitoring tool:

```json
{
  "Sid": "AgentToolPermissions",
  "Effect": "Allow",
  "Action": [
    "ec2:DescribeInstances",
    "ec2:DescribeInstanceStatus",
    "cloudwatch:DescribeAlarms",
    "cloudwatch:GetMetricStatistics",
    "logs:GetLogEvents",
    "logs:FilterLogEvents"
  ],
  "Resource": "*"
}
```

> ⚠️ **Principle of least privilege:** Don't give your agent's role admin access because it's easier. Scope permissions to exactly what your tools need. Agents can make mistakes — a properly scoped role limits the blast radius.

### Guardrails with Strands (Highly Recommended for Production)

```python
from strands import Agent
from strands.models import BedrockModel

model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    guardrail_config={
        "guardrailIdentifier": "your-guardrail-id",
        "guardrailVersion": "DRAFT",  # or a specific version number
        "trace": "enabled"  # see what the guardrail filtered
    },
    # Only evaluate the latest message (saves cost in long conversations)
    guardrail_latest_message=True
)

agent = Agent(model=model, tools=[...])
```

---

## 10. Production Deployment with AgentCore

Building an agent that runs locally is the easy part. Getting it to run reliably at scale, with session management, persistent memory, and proper authentication, is where things get hard. That's exactly what **Amazon Bedrock AgentCore** solves.

### What AgentCore Gives You

| Feature | What It Does |
|---|---|
| **AgentCore Runtime** | Serverless container hosting for your Strands agent. Scales automatically, handles concurrency, supports tasks up to 8 hours. |
| **AgentCore Memory** | Persistent memory across sessions — user preferences, conversation summaries, semantic facts. |
| **AgentCore Identity** | OAuth, Cognito, and IAM-based auth in front of your agent endpoint. |
| **AgentCore Gateway** | Converts your APIs and Lambda functions into MCP-compatible tools. |
| **AgentCore Observability** | Native CloudWatch + OpenTelemetry tracing for every agent invocation. |

### Deploying to AgentCore Runtime

```python
# agent.py — your agent file, with 3 extra lines to deploy to AgentCore

import json
from strands import Agent, tool
from strands_tools import calculator, retrieve

# ---- The 3 lines you add for AgentCore Runtime ----
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()  # Creates the AgentCore wrapper
# ---- End of additions ----

SYSTEM_PROMPT = """
You are a DevOps support agent. Use your tools to investigate
and resolve infrastructure issues.
"""

@tool
def check_service_health(service_name: str) -> dict:
    """Check the health status of an internal service."""
    # your health check logic
    ...

agent = Agent(
    system_prompt=SYSTEM_PROMPT,
    tools=[check_service_health, retrieve]
)

# This is the entry point AgentCore calls
@app.entrypoint  # The decorator that marks your entry point
def invoke(payload, context):
    user_message = payload.get("prompt", "")
    response = agent(user_message)
    return {"response": str(response)}

if __name__ == "__main__":
    app.run()
```

### Deploying via the AgentCore CLI

```bash
# Install the AgentCore CLI
pip install bedrock-agentcore

# Configure your project (run once)
agentcore configure --entrypoint agent.py
# You'll be prompted for IAM role, region, and other settings

# Deploy to AgentCore Runtime
agentcore launch \
  --env KNOWLEDGE_BASE_ID=kb-abc123 \
  --env AWS_REGION=us-east-1

# Your agent is now live with a secure HTTPS endpoint
# AgentCore handles: container build, ECR push, scaling, TLS termination
```

### Persistent Memory with AgentCore Memory

This is one of the most powerful features for building agents that feel intelligent across sessions:

```python
from strands import Agent
from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager
)

# Create a memory instance with all three memory strategies
client = MemoryClient(region_name="us-east-1")
memory = client.create_memory_and_wait(
    name="DevOpsAgentMemory",
    strategies=[
        {
            "semanticMemoryStrategy": {
                "name": "FactExtractor",
                # Stores: "production DB is RDS PostgreSQL 14 in us-east-1"
                "namespaceTemplates": ["/facts/{actorId}/"]
            }
        },
        {
            "summaryMemoryStrategy": {
                "name": "SessionSummarizer",
                # Stores: condensed summary of each conversation
                "namespaceTemplates": ["/summaries/{actorId}/{sessionId}/"]
            }
        },
        {
            "userPreferenceMemoryStrategy": {
                "name": "PreferenceLearner",
                # Stores: "user prefers Terraform over CloudFormation"
                "namespaceTemplates": ["/preferences/{actorId}/"]
            }
        }
    ]
)

# Use the memory in your agent
config = AgentCoreMemoryConfig(
    memory_id=memory['id'],
    session_id="session-123",   # unique per conversation
    actor_id="engineer-456",    # unique per user
    batch_size=10
)

with AgentCoreMemorySessionManager(config, region_name='us-east-1') as session_manager:
    agent = Agent(
        system_prompt="You are a DevOps assistant with memory of past conversations.",
        session_manager=session_manager,
        tools=[...]
    )
    
    agent("What's the quickest way to scale our ECS service?")
    agent("Actually, make it 10 tasks instead of 5")
    # Memory is automatically flushed when the `with` block exits
```

---

## 11. Observability and Monitoring

Agents are non-deterministic. You absolutely need visibility into what they're doing.

### Built-in Event Callbacks

Strands gives you hooks at every step of the agent loop:

```python
from strands import Agent
from strands.handlers import PrintingCallbackHandler
import logging

# Option 1: Use the built-in handler for development
agent = Agent(
    tools=[...],
    callback_handler=PrintingCallbackHandler()  # Prints every step to stdout
)

# Option 2: Write your own callback handler for production
class ProductionCallbackHandler:
    def on_tool_use(self, tool_name: str, tool_input: dict):
        logging.info(f"TOOL_CALL: {tool_name} | input={tool_input}")
    
    def on_tool_result(self, tool_name: str, tool_result):
        logging.info(f"TOOL_RESULT: {tool_name} | result={str(tool_result)[:200]}")
    
    def on_llm_response(self, response):
        logging.info(f"LLM_RESPONSE: tokens={response.usage.total_tokens}")

agent = Agent(
    tools=[...],
    callback_handler=ProductionCallbackHandler()
)
```

### OpenTelemetry Tracing

Strands has built-in OTEL support — critical for distributed tracing across multi-agent workflows:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from strands.telemetry import setup_telemetry

# Point at CloudWatch, Jaeger, Datadog, or any OTEL-compatible backend
setup_telemetry(
    otlp_endpoint="http://localhost:4317",    # local OTEL collector
    # or use CloudWatch OTEL endpoint for AWS-native observability
    service_name="devops-strands-agent",
    enable_tracing=True
)

agent = Agent(tools=[...])
```

### Key Metrics to Monitor in Production

| Metric | Why It Matters | Alert Threshold (starting point) |
|---|---|---|
| `agent_iterations_per_request` | High iterations = confused agent or broken tools | > 8 iterations |
| `tool_call_latency_ms` | Slow tools cause slow agents | > 5000ms |
| `bedrock_token_usage` | Directly tied to cost | Set a budget alarm |
| `guardrail_blocks_per_hour` | Spike = possible misuse or prompt injection | > 10/hour |
| `agent_error_rate` | General health indicator | > 2% |
| `knowledge_base_retrieval_score` | Low scores = wrong KB or bad chunking | Avg < 0.5 |

---

## 12. Security Best Practices

### Input Validation and Prompt Injection Defense

Agents are vulnerable to **prompt injection** — malicious content in retrieved documents or user input that tries to hijack the agent's behavior.

```python
from strands import Agent
from strands.models import BedrockModel

def sanitize_input(user_input: str) -> str:
    """
    Basic sanitization before sending to the agent.
    For production, use a proper content scanning service.
    """
    # Remove common prompt injection patterns
    suspicious_patterns = [
        "ignore previous instructions",
        "disregard your system prompt",
        "you are now",
        "forget everything"
    ]
    lower_input = user_input.lower()
    for pattern in suspicious_patterns:
        if pattern in lower_input:
            raise ValueError(f"Suspicious input pattern detected: {pattern}")
    return user_input

# Use Bedrock Guardrails for production-grade content filtering
model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
    guardrail_config={
        "guardrailIdentifier": "your-guardrail-id",
        "guardrailVersion": "1",
        "trace": "enabled"
    }
)

agent = Agent(model=model, tools=[...])

def safe_invoke(user_input: str) -> str:
    clean_input = sanitize_input(user_input)  # basic pre-filter
    return agent(clean_input)               # guardrails handle the rest
```

### Tool Safety: Confirm Before Destructive Actions

```python
from strands import Agent, tool

@tool
def delete_s3_objects(bucket: str, prefix: str) -> str:
    """
    Delete S3 objects matching the given prefix.
    REQUIRES explicit confirmation from the user before executing.
    """
    # This tool should never execute without the agent first
    # presenting what it's about to do and getting confirmation.
    # Design your system prompt to enforce this.
    ...

SAFE_AGENT_PROMPT = """
Before calling any destructive tool (delete, terminate, drop, remove):
1. Tell the user exactly what you're about to do
2. List all resources that will be affected
3. Ask for explicit confirmation with "Please type YES to confirm"
4. Only proceed if the user types exactly "YES"
Never perform destructive actions without this confirmation loop.
"""
```

### Encryption and Sensitive Data

```python
# If your tools handle sensitive data (credentials, PII):
# 1. Never log tool inputs/outputs containing secrets
# 2. Use AWS Secrets Manager — never hardcode credentials
# 3. Use KMS for encrypting stored conversation history

import boto3

@tool
def get_database_credentials(db_name: str) -> dict:
    """Retrieve database credentials from AWS Secrets Manager."""
    secrets_client = boto3.client('secretsmanager')
    secret = secrets_client.get_secret_value(SecretId=f"prod/{db_name}/credentials")
    return {"retrieved": True, "message": "Credentials retrieved — not logged"}
    # Return only what the agent needs to know, not the raw credentials
```

---

## 13. Strands vs. LangChain vs. LangGraph: When to Pick What

This comes up in every team conversation, so let's address it directly.

| Factor | Strands Agents | LangChain | LangGraph |
|---|---|---|---|
| **Philosophy** | Model-driven: the LLM decides the flow | Tool-driven: you wire the chains | Graph-based: you explicitly define state + edges |
| **Setup complexity** | Very low — 3 lines for a working agent | Moderate | High — requires explicit graph definition |
| **AWS / Bedrock integration** | Native, first-class | Good, but not native | Good, but not native |
| **Multi-agent support** | Built-in with `agent_graph` | Via LangGraph or custom | Built-in |
| **Predictability** | Lower — model decides the path | Higher — you control chains | Highest — explicit state machine |
| **Best for** | Open-ended tasks, complex tool use, rapid iteration | Familiar ecosystem, lots of existing examples | Workflows where the path MUST be deterministic |
| **Production deployment** | AgentCore (managed) | Self-managed | Self-managed |

**The honest take:**

Use **Strands** when you're on AWS, want fast iteration, and your tasks benefit from the model's reasoning (most GenAI applications, code analysis, Q&A, incident response).

Use **LangGraph** when you have strict compliance or audit requirements where you need to guarantee the agent follows a specific sequence of steps — like a regulated financial workflow.

Use **LangChain** mainly if your team already has significant investment in it, or you need its wide range of existing integrations.

---

## 14. Common Pitfalls and How to Avoid Them

These are the mistakes that cause the most confusion and lost hours.

**1. Vague tool docstrings → wrong tool selected**

The model reads your docstrings to understand what a tool does. If the docstring is vague, the model will pick the wrong tool or not call it at all.

```python
# ❌ Bad — too vague
@tool
def get_info(resource_id: str) -> dict:
    """Get information."""
    ...

# ✅ Good — specific and clear
@tool
def get_ec2_instance_details(instance_id: str) -> dict:
    """
    Retrieve current state, tags, and resource utilization for an EC2 instance.
    Use this when you need to understand the configuration or health of a specific instance.
    Returns: instance type, state, CPU/memory utilization, and associated security groups.
    """
    ...
```

**2. Giving the agent too many tools at once**

Don't dump 50 tools on an agent expecting it to pick perfectly. Limit to the tools relevant to the task. Use the semantic retrieval pattern for large tool libraries.

**3. Not handling tool exceptions**

If your tool throws an unhandled exception, the agent will crash. Always wrap tool implementations:

```python
@tool
def call_external_api(endpoint: str) -> dict:
    """Call an external REST API and return the JSON response."""
    try:
        import requests
        response = requests.get(endpoint, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        return {"error": "Request timed out after 10 seconds", "endpoint": endpoint}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}", "endpoint": endpoint}
    except Exception as e:
        return {"error": str(e), "endpoint": endpoint}
    # Always return a dict, never raise — let the agent decide what to do with the error
```

**4. Forgetting to enable model access in Bedrock**

Your agent will fail with `ResourceNotFoundException` even if your IAM is correct. Go to Bedrock console → Model access and enable the model.

**5. Using the wrong model ID format**

For cross-region inference (recommended for production), use the `us.` prefix:

```python
# ❌ Region-pinned (fragile)
model_id = "anthropic.claude-sonnet-4-20250514-v1:0"

# ✅ Cross-region inference profile (resilient)
model_id = "us.anthropic.claude-sonnet-4-20250514-v1:0"
```

**6. Building one mega-agent for everything**

It's tempting to put every tool into one agent. Resist. Specialized agents with narrow scopes are more reliable, cheaper to run, and easier to debug.

---

## 15. Architecture Decision Checklist

Use this before you build:

**Model selection:**
- [ ] Have I checked model availability in my target region?
- [ ] Is model access enabled in my AWS account?
- [ ] Am I using a cross-region inference profile for resilience?
- [ ] Have I picked the right model for cost vs. capability?

**Tools:**
- [ ] Are my tool docstrings specific and descriptive?
- [ ] Do all tools handle exceptions gracefully?
- [ ] Are destructive tools protected with confirmation logic?
- [ ] Have I tested each tool in isolation before connecting it to the agent?

**IAM:**
- [ ] Does the agent's role have only the permissions its tools actually need?
- [ ] Does the role include `bedrock:Converse` and `bedrock:InvokeModel`?
- [ ] If using Knowledge Bases, does the role include `bedrock:Retrieve`?

**RAG / Knowledge Bases:**
- [ ] Is the embedding model appropriate for my content type?
- [ ] Have I tuned the retrieval score threshold?
- [ ] Am I syncing the data source after document updates?

**Production / Security:**
- [ ] Are Guardrails configured and tested?
- [ ] Is observability (OTEL/CloudWatch) connected?
- [ ] Are my key metrics alerting in CloudWatch?
- [ ] Have I done basic prompt injection testing?

---

## Further Reading

- [Strands Agents Official Docs](https://strandsagents.com)
- [Strands Agents SDK GitHub](https://github.com/strands-agents/sdk-python)
- [AWS Blog: Introducing Strands Agents](https://aws.amazon.com/blogs/opensource/introducing-strands-agents-an-open-source-ai-agents-sdk/)
- [AWS Blog: Strands Technical Deep Dive](https://aws.amazon.com/blogs/machine-learning/strands-agents-sdk-a-technical-deep-dive-into-agent-architectures-and-observability/)
- [Amazon Bedrock AgentCore Docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [Bedrock Knowledge Bases Docs](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [AWS Samples: Bedrock for Beginners (includes Strands)](https://github.com/aws-samples/sample-amazon-bedrock-for-beginners)

---

*Found something outdated or want to add a pattern? PRs are welcome.*
