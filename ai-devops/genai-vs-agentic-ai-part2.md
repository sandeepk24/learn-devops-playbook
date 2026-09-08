# Generative AI vs Agentic AI on AWS: What Engineers Are Actually Building

### Part 2 of 2 — AWS Services, Real Architectures, and What to Do with All of This

---

> "The best AWS architecture diagram is the one that ships to production and doesn't page you at 2am. Let's talk about where AI fits in that picture."

---

If you haven't read [Part 1](./genai-vs-agentic-ai-part1.md), go do that first. It covers the foundational concepts and vocabulary you'll need here. This part is where we get into the actual AWS services, what they do, how they differ, and what you as a DevOps or cloud engineer can build with them right now.

---

## Section 5: The AWS AI Stack — How It All Fits Together

AWS has built an end-to-end AI platform, but it's easy to get confused by the product names. Here's the clearest mental model:

```
┌───────────────────────────────────────────────────────┐
│              YOUR APPLICATION / WORKFLOW              │
├───────────────────────────────────────────────────────┤
│       Amazon Q (Business / Developer / Kiro)          │  ← End-user AI products
├───────────────────────────────────────────────────────┤
│       Amazon Bedrock AgentCore                        │  ← Agentic platform
│       Amazon Bedrock Agents                           │  ← Agent orchestration
│       Amazon Bedrock Knowledge Bases                  │  ← RAG / Retrieval
│       Amazon Bedrock Guardrails                       │  ← Safety + compliance
├───────────────────────────────────────────────────────┤
│       Amazon Bedrock (Foundation Model API)           │  ← Model access layer
├───────────────────────────────────────────────────────┤
│  Claude | Amazon Nova | LLaMA | Mistral | Stable Diff │  ← Foundation models
└───────────────────────────────────────────────────────┘
```

The bottom layer is the models themselves. Bedrock is the managed API layer that gives you access to them. Everything above that is where you build applications — ranging from simple generative chat to fully autonomous multi-agent systems.

---

## Section 6: Amazon Bedrock — The Foundation (And It's More Than You Think)

Amazon Bedrock is AWS's fully managed service for accessing foundation models and building AI applications. It powers more than 100,000 organisations worldwide. Critically, unlike calling OpenAI or Anthropic directly, Bedrock runs within your AWS account boundary — your data doesn't leave your VPC, you use your existing IAM policies, and everything is logged to CloudTrail.

For a cloud engineer, this matters enormously. You're not handing your infrastructure telemetry or internal documentation to a third-party API. It stays in your control plane.

### What Bedrock gives you

**Model access** — A unified API to invoke multiple foundation models: Anthropic Claude (including Claude Sonnet 4.6, the current flagship), Amazon Nova (AWS's own model family, optimised for throughput and cost), Meta LLaMA, Mistral, Stability AI for image generation, and more. You switch models by changing a single string — no re-architecting.

**Converse API** — A standardised, model-agnostic API for multi-turn conversations and tool use. The same code works regardless of which model you're calling underneath. This is how you avoid vendor lock-in at the API level.

**Knowledge Bases (RAG)** — Fully managed retrieval-augmented generation. You point it at your data sources — S3 buckets, Confluence, SharePoint, Salesforce, or a web crawler — and Bedrock handles the full pipeline: document chunking, embedding generation, vector storage, and retrieval at query time. Supported vector stores include OpenSearch Serverless, Aurora PostgreSQL, MongoDB Atlas, Pinecone, and Redis.

This is how you make Bedrock answer from *your* runbooks, your architecture docs, your internal wikis — not just from its training data. It also includes GraphRAG support for complex multi-hop queries across knowledge graphs.

**Guardrails** — Content filtering, PII masking, topic blocking, and hallucination detection. You define policies once and apply them across all your models and agents. Think of it as security groups for your AI layer.

### A practical example: Generative AI on Bedrock

You want to build an internal tool that lets your SRE team ask natural language questions about your incident history. Here's the architecture:

1. Export past incident reports from your incident management system to S3
2. Create a Bedrock Knowledge Base pointing at that S3 bucket
3. Build a simple chat interface (or use the AWS Console playground to prototype)
4. SRE engineer asks: "What caused the last three P1 incidents involving the payment service?"
5. Bedrock retrieves the relevant incident reports from the vector index, passes them to Claude, and returns a synthesised answer with source attribution

This is generative AI — the model is generating an answer. It's not taking any actions. It's not touching your AWS infrastructure. It's reading documents and synthesising insights.

---

## Section 7: Amazon Bedrock Agents — Where It Gets Agentic

Bedrock Agents is where generative AI transitions to agentic AI. You define:

- **A foundation model** to power the agent's reasoning
- **Action groups** — sets of tools the agent can use (Lambda functions, API schemas, code interpreter)
- **Knowledge bases** — so the agent can retrieve information as part of its reasoning
- **Memory** — so the agent can remember context across sessions
- **Guardrails** — to constrain its behaviour

When you invoke the agent with a high-level goal, it uses the ReAct pattern internally: it reasons about what to do, calls tools, observes results, and loops until it achieves the goal.

### Multi-agent collaboration

For complex workflows, you can compose multiple specialised agents. A **supervisor agent** receives the high-level request and delegates to sub-agents. Each sub-agent has its own defined tools and scope. This is how you build agentic systems that stay manageable — divide and conquer, with each agent limited to what it needs.

Example: an incident response multi-agent system might have:
- A **triage agent** that classifies incoming alerts
- A **diagnostics agent** that queries CloudWatch, traces, and metrics
- A **remediation agent** that proposes (or executes) fixes
- A **communication agent** that drafts stakeholder updates

Each agent only has IAM permissions for its specific scope. The blast radius of any one agent misbehaving is contained.

### Practical DevOps example: Agentic incident response

Scenario: a Lambda function starts throwing 5xx errors at 2am.

With generative AI only: CloudWatch fires an alert, your on-call engineer wakes up, pastes the error logs into ChatGPT, gets a suggestion, manually investigates, manually fixes.

With an agentic system:
1. CloudWatch alarm triggers an EventBridge rule
2. EventBridge invokes a Bedrock Agent
3. The agent calls a tool to fetch the relevant CloudWatch log groups
4. It calls a tool to retrieve X-Ray traces for the failing requests
5. It searches the Knowledge Base for similar past incidents
6. It diagnoses: a downstream DynamoDB table hit a throttle limit
7. It checks the DynamoDB table's current capacity settings
8. It either (a) applies a temporary capacity increase autonomously if it's within pre-approved thresholds, or (b) creates a pre-populated PagerDuty incident with full diagnostic context and waits for human approval

Your on-call engineer wakes up to an alert that already contains root cause analysis and a proposed fix — or the system fixed it while they slept.

That's the difference. Same underlying model capabilities; fundamentally different architecture.

---

## Section 8: Amazon Bedrock AgentCore — The Production Agentic Platform

AgentCore, which reached general availability in late 2025, is AWS's answer to the question: "How do I run AI agents safely in production?"

It's an end-to-end platform that goes beyond Bedrock Agents with additional capabilities:

**AgentCore Runtime** — A managed execution environment for agents. Instead of managing Lambda timeouts, state machines, and retry logic yourself, AgentCore handles long-running agentic workloads. Agents can operate for extended periods without you hand-rolling the execution infrastructure.

**AgentCore Gateway** — Connects your agents to enterprise systems with automatic authentication handling. Your agent needs to query a ServiceNow ticket? Or search Confluence? The Gateway manages the auth flow. You configure it once; the agent uses it.

**AgentCore Memory** — Managed long-term memory that persists across agent sessions. The agent remembers past interactions, past mistakes, and established patterns — without you building a custom database layer.

**AgentCore Identity** — Fine-grained access control for agents, including cross-agent authorization. You define what each agent is allowed to do with specific resources, and Identity enforces it. This is how you implement least-privilege for AI agents — a non-negotiable in enterprise environments.

**AgentCore Code Interpreter** — A sandboxed environment for running code that the agent generates. The agent can write and execute Python, analyse data, generate charts, and work with files — in isolation from your production systems.

**AgentCore Browser Tool** — Allows agents to interact with web interfaces — reading dashboards, clicking through SaaS tools that don't have APIs, filling forms. Combined with MCP, this opens up integrations that would otherwise require custom scraper code.

**Observability and Evaluation** — Built-in tracing, metrics, and evaluation tools. You can replay agent runs, identify where reasoning went wrong, and continuously improve agent quality. For a DevOps engineer, this is your agent's equivalent of CloudWatch + X-Ray.

The 80% of participants in a recent AWS AI agent hackathon who built with AgentCore is a meaningful signal — it's becoming the default platform for production-grade agents on AWS.

---

## Section 9: Amazon Kiro — The Agentic IDE (And Why It Replaced Q Developer)

If you were using Amazon Q Developer, you need to know this: it's being sunset. New signups were blocked from May 15, 2026, and full end of support is April 30, 2027. AWS's replacement is Amazon Kiro — a significantly more powerful and philosophically different tool.

### What Kiro actually is

Kiro is an agentic IDE built on Code OSS (the open-source base of VS Code), with a deep AI agent layer on top powered by Bedrock. Your existing VS Code extensions, keybindings, and plugins carry across. But the development model is fundamentally different.

Kiro's thesis: the reason agentic coding produces inconsistent or production-unsafe code is that engineers skip the requirements phase. Kiro forces you through it.

### The spec-driven workflow

Before any agent writes a single line of code, Kiro requires three documents:

1. **requirements.md** — What does this feature need to do? Written in natural language, but structured.
2. **design.md** — How will it be built? Architecture decisions, data flows, API contracts.
3. **tasks.md** — What discrete implementation tasks need to happen?

The agent generates all three from your initial description. You review and approve them. Only then does code generation begin. This mirrors the way serious engineering teams actually work — and it produces code that's architecturally coherent rather than "it works on my machine."

### Agent Hooks — automation without prompting

Kiro has an event-driven automation layer called Hooks. You define triggers (file save, PR open, test failure, push event) and actions (run tests, update docs, regenerate fixtures, check for spec drift).

For a DevOps engineer, this is genuinely useful:
- On every Terraform file save: automatically run `terraform validate` and update the module documentation
- On every PR: agent reviews the code against your architecture specs and posts feedback
- When a test fails: agent analyses the failure and suggests a fix before you even look at it

### Steering Rules

A mechanism to encode your team's engineering norms into the agent — committed to the repository in a `.kiro/` directory. Rules like "all AWS SDK calls must use exponential backoff" or "never hardcode region strings, always use environment variables" persist across every session, every contributor, every feature — without needing to be re-stated in every prompt.

This is how you scale your team's standards across an AI-assisted codebase.

### Model routing

Kiro automatically routes between Claude Sonnet (for reasoning-heavy spec generation), Amazon Nova (for high-throughput code generation), and other models — all via Bedrock. You can pin a specific model when consistency matters more than cost optimisation. From May 29, 2026, the latest coding models (including Claude Opus 4.7) are available exclusively on Kiro.

### Kiro pricing

Free tier: 50 interactions/month with no AWS account required. Pro: $19/month.

---

## Section 10: Amazon Q Business — Generative AI for Your Organisation

Amazon Q Business is the enterprise-facing product built on Bedrock, designed for employees to ask questions and get answers from company data — not the open internet, not generic training data, but your organisation's internal knowledge.

As a DevOps team, you might use Q Business to:
- Give engineers a natural language interface to your internal wiki and runbooks
- Let non-technical stakeholders query deployment status from connected ticketing systems
- Provide contextual help based on your team's internal documentation
- Power chatbots that are grounded in your actual procedures

Q Business connects to existing data sources: SharePoint, Confluence, Jira, Salesforce, Google Drive, S3. It handles the ingestion, indexing, and retrieval. You manage access controls using your existing identity provider (IAM Identity Center).

The key difference from Bedrock Knowledge Bases: Q Business is a managed, end-user product. Knowledge Bases is a developer primitive you build on top of. If you're building a product for internal users who aren't engineers, Q Business. If you're building a custom application with fine-grained control, Bedrock Knowledge Bases.

---

## Section 11: AWS Architecture Patterns for DevOps Engineers

Here are concrete patterns you can implement today.

### Pattern 1: IaC Generation Pipeline (Generative AI)

**Use case**: Engineers describe infrastructure needs in plain English; the system generates validated Terraform or CloudFormation.

**Architecture**:
- Frontend: Simple web UI or Slack bot
- Backend: Lambda function → Bedrock (Claude Sonnet) → returns generated HCL/YAML
- Validation: Generated code automatically runs through `terraform validate` and `cfn-lint`
- Review: PR created in CodeCommit/GitHub for engineer approval before apply

**What makes it generative, not agentic**: The model generates code. A human validates and applies. There's no autonomous action.

---

### Pattern 2: Intelligent Runbook Assistant (Generative AI + RAG)

**Use case**: On-call engineers get contextual help during incidents, grounded in your actual runbooks.

**Architecture**:
- Runbooks stored in S3 or Confluence → ingested into Bedrock Knowledge Base
- Slack slash command → API Gateway → Lambda → Bedrock Converse API with Knowledge Base retrieval
- Returns answer with source attribution: "Based on Runbook v2.3 — Payment Service Failover..."
- Optional: inject current alert context (from CloudWatch) into the prompt automatically

**What makes it generative, not agentic**: The model retrieves and synthesises. It doesn't take action on your infrastructure.

---

### Pattern 3: Autonomous Deployment Validation Agent (Agentic AI)

**Use case**: After each deployment, an agent autonomously validates the rollout — checking metrics, logs, and synthetic tests — and either confirms success or triggers a rollback.

**Architecture**:
- CodePipeline post-deploy stage → EventBridge → triggers Bedrock Agent
- Agent tools: `get_cloudwatch_metrics`, `query_x_ray_traces`, `run_synthetic_test`, `get_error_rate`, `trigger_rollback`
- Agent reasons: "Error rate is 0.3% above baseline, latency P99 increased by 120ms, synthetic tests passing. Threshold not exceeded. Marking deployment successful."
- Or: "Error rate 4.2% — 8x above baseline. Triggering rollback and paging on-call."
- Human-in-the-loop checkpoint: for production deploys, agent creates a decision record and waits for approval before triggering rollback above a configurable threshold

---

### Pattern 4: Multi-Agent Incident Response System (Agentic AI)

**Use case**: Automated first-responder for production incidents, dramatically reducing time to diagnosis.

**Architecture using Bedrock multi-agent collaboration**:

- **Supervisor Agent**: receives alert from EventBridge, classifies severity, delegates to sub-agents
- **Diagnostics Agent** (tools: CloudWatch, X-Ray, CloudTrail): "What happened and where?"
- **Impact Agent** (tools: service dependency map, health dashboard): "What's affected?"
- **Knowledge Agent** (tools: Knowledge Base with past incidents): "Have we seen this before?"
- **Remediation Agent** (tools: SSM, EC2 API, Lambda, limited writes): "What can we fix?"
- **Communication Agent** (tools: PagerDuty, Slack): "Who needs to know?"

IAM roles for each sub-agent are tightly scoped. The Remediation Agent cannot write to anything the Diagnostics Agent reads, by design. AgentCore Identity enforces this.

Result: from alert to complete incident context in under 60 seconds. Mean time to resolution drops significantly.

---

### Pattern 5: Agentic Security Compliance Checker (Agentic AI)

**Use case**: Continuously audit AWS resources against your security policies and auto-remediate low-risk violations.

**Architecture**:
- Scheduled EventBridge rule (nightly) → triggers Bedrock Agent
- Agent tools: AWS Config API, S3 API, IAM API, EC2 API, Security Hub
- Agent checks: S3 bucket policies, unencrypted volumes, over-permissive IAM roles, public security groups
- For auto-remediable issues (e.g., enabling S3 versioning on a bucket that has it disabled but no data at risk): agent applies fix and logs it
- For policy violations requiring human review: agent creates a Security Hub finding with full context and recommended remediation
- Weekly summary report generated to S3 and linked in Slack

Human-in-the-loop: changes to IAM policies, security groups, or production resources always require human approval — enforced by AgentCore Identity, not just convention.

---

## Section 12: What's Still Maturing (Be Honest with Yourself)

It would be irresponsible to paint only the upside. Here's where things are still rough in 2026:

**Reliability of multi-step agents** — Agents can still get "stuck" in loops, take unexpected paths, or fail silently on edge cases that weren't covered in testing. Long-horizon tasks (anything spanning hours or multiple complex systems) still require careful guardrailing and extensive testing.

**Cost predictability** — Agentic workloads can consume far more tokens than expected because the model may call tools multiple times, reason extensively, or retry failed steps. Build cost monitoring and token budgets into your architecture from day one.

**Debugging agent failures** — When a multi-agent system produces the wrong result, tracing the failure to the specific reasoning step or tool call is non-trivial. AgentCore's observability tools help, but this is nothing like debugging a Lambda function. Invest in tracing infrastructure early.

**Security posture** — Giving an agent IAM permissions means its decisions can affect real infrastructure. Prompt injection attacks (where malicious content in a retrieved document instructs the agent to take unintended actions) are a real threat vector. Guardrails and careful tool scope definition are mitigations, not complete solutions. Treat agents like any other service in your threat model.

**Hallucination in high-stakes contexts** — Modern models are significantly better, but still not perfect. For a runbook assistant, a hallucinated answer is annoying. For an agent managing production deployments, it can be catastrophic. Build verification steps and HITL checkpoints proportional to the blast radius.

---

## Section 13: Where to Start — A Practical Roadmap

If you're a DevOps or cloud engineer looking to get hands-on:

**Week 1–2: Get comfortable with Bedrock**
- Set up Bedrock access in a non-production account
- Try the Bedrock Playground with Claude — experiment with infrastructure descriptions, IaC generation, log analysis
- Build a simple Lambda that calls the Bedrock Converse API
- Understand token usage and costs for your use cases

**Week 3–4: Build your first RAG application**
- Create a Bedrock Knowledge Base pointed at your team's runbook S3 bucket
- Build a simple internal Slack bot that queries it
- Measure answer quality against your actual documentation

**Month 2: Your first agent**
- Build a Bedrock Agent with 2–3 read-only tools (CloudWatch, Config, a knowledge base)
- Start with a diagnostics use case where the worst-case is a wrong answer, not a destructive action
- Add Guardrails and proper logging from the start
- Test extensively before showing anyone else

**Month 3+: Production considerations**
- Evaluate AgentCore for production deployments
- Implement HITL checkpoints for any write operations
- Set up token budget monitoring
- Build an evaluation framework to measure agent quality over time
- Set up Kiro for your team's development workflow

---

## The Bottom Line

Generative AI and agentic AI are not competing approaches — they're different layers of the same stack. You need to understand both clearly to deploy either safely.

Generative AI is powerful for accelerating human work: generating code, summarising logs, drafting runbooks, explaining errors. It's lower risk, easier to govern, and should be your starting point.

Agentic AI can automate workflows that currently require humans at every step: incident response, deployment validation, security compliance, infrastructure management. It's higher leverage, but also higher responsibility — agents with write access to production are a new kind of infrastructure component, and they need to be treated with the same rigour as your Terraform modules.

AWS has built a comprehensive stack for both — from the model access layer in Bedrock, through the orchestration capabilities in Bedrock Agents, to the production platform in AgentCore, and the development workflow in Kiro. The pieces are mature enough to build real systems with.

What separates engineers who succeed with this from those who don't isn't the ability to generate a cool demo. It's understanding the difference between *generating* and *acting*, knowing where the guardrails need to be, and treating AI components with the same engineering discipline you'd apply to any other production system.

The engineers who get that right are going to build things that seemed impossible two years ago.

---

*← Back to [Part 1: The Concepts, the Vocabulary, and How They Actually Differ](./genai-vs-agentic-ai-part1.md)*

---

**Further reading and hands-on resources:**
- [Amazon Bedrock documentation](https://docs.aws.amazon.com/bedrock/)
- [Amazon Bedrock AgentCore](https://aws.amazon.com/bedrock/agentcore/)
- [Amazon Kiro](https://kiro.dev)
- [AWS Well-Architected Responsible AI Lens](https://aws.amazon.com/architecture/well-architected/)
- [Bedrock multi-agent collaboration workshop](https://catalog.workshops.aws/)
