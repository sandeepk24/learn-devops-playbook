# DevOps Field Notes

> Long-form field notes from the parts of DevOps that bite you in production — AWS, ECS/EKS, Kubernetes, Docker internals, networking, CI/CD, SRE, observability, Linux, API Gateway, MCP, and a growing AI/LLMOps stack. The reference I wish someone had handed me before I started writing runbooks from memory.

[![Stars](https://img.shields.io/github/stars/sandeepk24/devops-field-notes?style=flat-square)](https://github.com/sandeepk24/devops-field-notes/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/sandeepk24/devops-field-notes?style=flat-square)](https://github.com/sandeepk24/devops-field-notes/commits/main)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](./LICENSE)
![AWS](https://img.shields.io/badge/AWS-orange?style=flat-square&logo=amazon-aws&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326ce5?style=flat-square&logo=kubernetes&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![Bedrock](https://img.shields.io/badge/Bedrock-232F3E?style=flat-square&logo=amazon-aws&logoColor=white)
![DevOps](https://img.shields.io/badge/DevOps-informational?style=flat-square)

---

## Why this exists

These are notes I've kept while working through AWS containers, Docker internals, Kubernetes, networking, and — increasingly — the AI and LLMOps work that's landed on every DevOps engineer's desk. I wrote them mostly for myself: the second time I had to re-derive how an ALB listener rule actually resolves to an ECS target, I decided I should write it down properly instead.

Most of them are long-form rather than one-liners. If a topic deserves a mental model, I'd rather spend 800 lines getting it right than paste a cheat sheet I won't trust at 2 a.m.

They're aimed at DevOps and cloud engineers who are past "hello world" and want the mechanics — the stuff that makes the difference between "the deployment succeeded" and "the application is actually serving traffic."

---

## Start here by role

Not sure where to jump in? Pick the path that fits where you are right now.

### If you're a junior DevOps / cloud engineer just getting started
1. [Linux for modern DevOps engineers](./linux/linux-for-modern-devops-engineers.md) — your foundation
2. [Networking 101 for DevOps & cloud engineers](./networking/01-networking-101-devops-cloud.md) — packets before pods
3. [DNS deep dive](./networking/02-dns-deep-dive.md) — it really is always DNS
4. [Docker internals, part 1](./docker/docker-advanced-part-1.md) — understand what Docker actually is before you Dockerize anything
5. [ECS fundamentals for DevOps engineers](./ecs/what-devops-engineers-should-understand-about-ecs.md) — ECS from first principles
6. [ECS task health is not application health](./ecs/ecs-task-health-is-not-the-same-as-app-health.md) — read this before you wire up your first pipeline
7. [GitHub DevOps fundamentals & best practices](./ci-cd/01_GITHUB_DEVOPS_FUNDAMENTALS.md) — getting CI/CD right from day one
8. [OpenTelemetry 101](./sre/otel_101.md) — observability before something breaks

### If you're a mid-level engineer moving into cloud architecture
1. [VPC networking deep dive](./networking/04-vpc-networking.md) — the AWS network plane
2. [ALB + ECS deep dive](./aws/aws-alb-ecs-deep-dive.md) — how traffic actually reaches your containers
3. [ECS vs EKS for enterprise applications](./aws/ecs-vs-eks-for-enterprise-applications.md) — the decision you'll be asked to make
4. [Kubernetes networking deep dive](./networking/05-kubernetes-networking.md) — CNI, kube-proxy, and the packet's journey to a pod
5. [EKS: ALB · NLB · Ingress deep dive](./eks/aws-alb-nlb-ingress-eks-deep-dive.md) — getting traffic into EKS end-to-end
6. [Deployment strategies — canary vs blue/green vs rolling](./sre/canary-vs-blue-green-vs-rolling-deployments.md) — and how to pitch each one as a business decision
7. [API Gateway: fundamentals → observability](./apigateway/) — the full 7-chapter series

### If you're an AI / ML engineer or working on LLMOps
1. [GenAI vs Agentic AI — part 1](./ai-devops/genai-vs-agentic-ai-part1.md) — the framing that makes the rest make sense
2. [Bedrock 200-level fundamentals](./aws/aws-bedrock-200-level-fundamentals.md) — build the mental model before you write the code
3. [MCP — the DevOps engineer's field guide](./ai-devops/MCP_DevOps_Guide.md) — what MCP is and why it matters
4. [Building your first MCP server](./mcp-server-for-devops/05-your-first-mcp-server.md) — hands-on from scratch
5. [SRE for LLM applications](./ai-devops/sre-for-llm--applications.md) — what being on-call for an LLM actually looks like
6. [LLMOps evaluation pipeline for DevOps bots](./ai-devops/llmops-evaluation-pipeline-for-devops-bots.md) — catching prompt drift before users do
7. [Bedrock AgentCore for DevOps engineers](./learning-amazon-bedrock-agentcore/) — the operational half of deploying an agent

---

## What's inside

### 🤖 AI / LLMOps for DevOps
| Note | What's in it |
|---|---|
| [GenAI vs Agentic AI — part 1](./ai-devops/genai-vs-agentic-ai-part1.md) | The foundational distinction: AI that helps you *think* vs AI that *acts* on your behalf — and why getting it wrong costs you in security, compliance, and architecture. |
| [GenAI vs Agentic AI on AWS — part 2](./ai-devops/genai-vs-agentic-ai-part2.md) | The actual AWS services behind the vocabulary, and what you can build with them right now. |
| [AI incident triage agent](./ai-devops/ai-incident-triage-agent.md) | From alert noise to root cause in seconds — designing an AIOps triage agent for real incident response. |
| [RAG knowledge base for DevOps runbooks](./ai-devops/rag-knowledge-base-devops-runbooks.md) | Turning a pile of runbooks into a retrieval-augmented knowledge base — golden datasets, chunking, and grounding. |
| [LLMOps evaluation pipeline for DevOps bots](./ai-devops/llmops-evaluation-pipeline-for-devops-bots.md) | Catching prompt drift, model regression, and silent quality decay before they compound into incidents. |
| [AI monitoring fundamentals — part 1](./ai-devops/part-1-ai-monitoring-fundamentals.md) | The core signals and concepts you need before you can monitor anything AI-shaped. |
| [AI monitoring operations — part 2](./ai-devops/part-2-ai-monitoring-operations.md) | Putting monitoring into practice: dashboards, alerts, and the SLOs that actually matter. |
| [AI monitoring deep dives — part 3](./ai-devops/part-3-ai-monitoring-deep-dives.md) | Latency profiling, cost attribution, and debugging model-level failures in production. |
| [Monitoring AI agents in production](./ai-devops/how-to-monitor-ai-agents-in-production.md) | Why AI monitoring is a different problem, and how to catch false outputs before users do. |
| [SRE for LLM applications](./ai-devops/sre-for-llm--applications.md) | What being on-call for an LLM actually looks like — written from the on-call seat, not the demo. |
| [Guardrails for AI DevOps agents](./ai-devops/guardrails-for-ai-devops-agents.md) | The safety controls you need before an agent touches anything in your infrastructure. |
| [Human-in-the-loop approval patterns for AI agents](./ai-devops/human-in-the-loop-approval-patterns-for-ai-agents.md) | When to pause and ask a human, and how to wire that into your agent architecture. |
| [MCP — the DevOps engineer's field guide](./ai-devops/MCP_DevOps_Guide.md) | Model Context Protocol in plain English: what it is, why it exists, and where it fits. |
| [MCP advanced guide for DevOps engineers & architects](./ai-devops/MCP_Advanced_DevOps_Guide.md) | LLMs vs RAG vs MCP, advanced server patterns, and the architecture trade-offs. |
| [AWS Strands Agents — complete guide](./ai-devops/strands-agents-bedrock-guide.md) | The Strands SDK for cloud & DevOps engineers: what it is and why you'd reach for it. |
| [Amazon Bedrock model availability](./ai-devops/amazon-bedrock-model-availability.md) | Why your model isn't available — and how to actually fix it instead of fighting IAM blind. |

### 🧠 Anthropic / Claude
> Study series for the Claude Certified Architect – Foundations (CCAR-F) exam, written from a DevOps/cloud perspective. See the [series README](./anthropic/README.md) for the full exam outline.

| Note | What's in it |
|---|---|
| [Anthropic foundations](./anthropic/01-anthropic-foundations.md) | Constitutional AI, RLHF, safety philosophy, and the Claude model family — the "why" before the API. |
| [Claude API and SDK](./anthropic/02-claude-api-and-sdk.md) | Messages API, streaming, token counting, and SDK integration for Python and TypeScript. |
| [Prompting, context, and reliability](./anthropic/03-prompting-context-and-reliability.md) | Prompt engineering that actually works in production — context windows, structured outputs, and reliability patterns. |
| [Tool use, MCP, and agents](./anthropic/04-tool-use-mcp-and-agents.md) | Wiring Claude to external tools and systems with Tool Use and the Model Context Protocol. |
| [Production: DevOps, security, and evals](./anthropic/05-production-devops-security-and-evals.md) | Deploying Claude responsibly: rate limits, cost controls, PII handling, and evaluation pipelines. |
| [Exam prep & roadmap](./anthropic/06-exam-prep-roadmap.md) | Exam structure, domain weights, the 20 topics most likely to trip you up, and a study schedule. |

### ☁️ AWS
| Note | What's in it |
|---|---|
| [ALB + ECS deep dive](./aws/aws-alb-ecs-deep-dive.md) | ALB components, listener rules, target groups, and how ECS services actually register. End-to-end. |
| [ECS vs EKS for enterprise applications](./aws/ecs-vs-eks-for-enterprise-applications.md) | A no-BS guide to picking your AWS container platform — from the trenches, for people who just want to ship. |
| [EBS volumes on EKS](./aws/ebs-volumes-on-eks-the-complete-guide-for-devops-engineers.md) | What problem EBS actually solves, the CSI driver, and how persistent storage works on EKS. |
| [AWS Cognito complete guide](./aws/aws-cognito-complete-guide.md) | User authentication without the headaches — user pools, identity pools, and the flows that trip people up. |
| [CPU vs GPU — the missing manual](./aws/cpu-vs-gpu-the-devops-engineers-missing-manual.md) | CPU pipeline internals, the Python GIL + asyncio, Java JIT, Kubernetes throttling, GPU/CUDA, and AWS instance selection — with real benchmarks. |
| [Bedrock 200-level fundamentals](./aws/aws-bedrock-200-level-fundamentals.md) | Building the mental model before the code. Your first Bedrock project without the copy-paste tutorial trap. |
| [Bedrock agentic AI in production](./aws/aws-bedrock-advanced-agentic-ai.md) | AgentCore, Strands SDK, S3 Vectors, A2A, MCP — and what breaks under real concurrency. |
| [Bedrock Knowledge Bases — part 1: concepts](./aws/bedrock-knowledge-bases-part-1-concepts.md) | What Knowledge Bases actually are, how ingestion works, and the chunking decisions that shape retrieval quality. |
| [Embedding models — part 1: concepts](./aws/embedding-models-part-1-concepts.md) | What embeddings are, why they matter, and how to think about vector space before you write a line of code. |
| [Embedding models — part 2: choosing a model](./aws/embedding-models-part-2-choosing-a-model.md) | Titan vs Cohere vs open-source models — the trade-offs that actually matter for your use case. |
| [Embedding models — part 3: using and deploying](./aws/embedding-models-part-3-using-and-deploying.md) | Batch embedding, endpoint design, and how to wire embeddings into a retrieval pipeline on AWS. |
| [Embedding models — part 4: running in production](./aws/embedding-models-part-4-running-in-production.md) | Cost control, latency budgets, and the operational concerns that show up once you're past the prototype. |
| [What happens when you type www.google.com](./aws/what-happens-when-you-type-www-google-com.md) | The full request lifecycle — DNS, TLS, routing, the lot — as a systems-thinking warm-up. |

### 🌐 Networking
| Note | What's in it |
|---|---|
| [Networking 101 for DevOps & cloud engineers](./networking/01-networking-101-devops-cloud.md) | What actually matters in production — the fundamentals you keep needing and never wrote down. |
| [DNS deep dive](./networking/02-dns-deep-dive.md) | Resolution, failure modes, CoreDNS, and Route 53 — why "it's always DNS" is usually right. |
| [TLS/SSL deep dive](./networking/03-tls-ssl-deep-dive.md) | Certificates, mTLS, and how to actually debug a handshake in production. |
| [VPC networking deep dive](./networking/04-vpc-networking.md) | Subnets, routing, NAT, peering, and Transit Gateway — the AWS network plane explained. |
| [Kubernetes networking deep dive](./networking/05-kubernetes-networking.md) | CNI, kube-proxy, Services, and Ingress — how a packet actually reaches a pod. |
| [Load balancing deep dive](./networking/06-load-balancing.md) | ALB, NLB, health checks, and connection draining — and why a "healthy" target still drops requests. |
| [Network security](./networking/07-network-security.md) | Security groups, NACLs, Zero Trust, and WAF — the layered model and where each control belongs. |
| [Network observability](./networking/08-network-observability.md) | Flow logs, tcpdump, packet analysis, and distributed tracing for when the network is the suspect. |

### 🐳 Docker
| Note | What's in it |
|---|---|
| [Docker internals, part 1 — execution stack, namespaces, cgroups](./docker/docker-advanced-part-1.md) | How Docker actually works at the kernel level. |
| [Docker internals, part 2 — OverlayFS, OCI, BuildKit](./docker/docker-advanced-part-2.md) | Storage engine and build architecture, and why they shape image design. |
| [Docker internals, part 3 — networking, security, signals, debugging](./docker/docker-advanced-part-3.md) | Production failure modes and the security model. |
| [Docker advanced tutorial](./docker/docker-advanced-tutorial.md) | Compose, Swarm, registry ops, checkpointing — the production-grade workflow field guide. |
| [`docker build` vs `docker buildx`](./docker/docker-build-vs-buildx-is-not-just-a-new-command.md) | Not a version upgrade. A different mental model for where your builds live. |
| [Docker Compose → ECS playbook](./docker/docker-compose-local-to-ecs-the-complete-devops-playbook.md) | The local-to-production path: why Compose exists and how to take it all the way to ECS. |

### 📦 ECS
| Note | What's in it |
|---|---|
| [ECS fundamentals for DevOps engineers](./ecs/what-devops-engineers-should-understand-about-ecs.md) | Cluster, service, task, task definition — with the kubectl equivalents for anyone crossing over from Kubernetes. |
| [ECS task health is not application health](./ecs/ecs-task-health-is-not-the-same-as-app-health.md) | The four layers of health and why teams stop reading at the wrong one. |
| [ECS task distribution & resource management](./ecs/ecs-task-distribution-guide.md) | How containers are scheduled, distributed, and packed across an ECS cluster. |
| [ECS — part 1: fundamentals](./ecs/ecs-part-1-fundamentals.md) | Task definitions, launch types, IAM roles, networking modes — the building blocks. |
| [ECS — part 2: operations](./ecs/ecs-part-2-operations.md) | Service deployments, rolling updates, service discovery, and secrets management. |
| [ECS — part 3: deep dives](./ecs/ecs-part-3-deep-dives.md) | Spot capacity, Fargate Spot, EFS mounts, and the operational concerns that come with complexity. |
| [ECS — part 4: resource exhaustion](./ecs/ecs-part-4-resource-exhaustion.md) | What happens when you run out of CPU, memory, or ENIs — and how to see it coming. |
| [ECS reliability — part 1: building the cluster](./ecs/ecs-reliability-part1-building-the-cluster.md) | The configuration decisions at cluster-build time that determine how reliable it is at 3 a.m. |
| [ECS reliability — part 2: keeping it alive](./ecs/ecs-reliability-part2-keeping-it-alive.md) | Health checks, auto-scaling, circuit breakers, and the runbook patterns that catch problems early. |
| [ECS cost optimization & failure domains](./ecs/ecs-deep-dive-cost-and-failures.md) | When to use Fargate vs EC2, and how ECS actually behaves when things fail. |
| [ECS zero-downtime deployments](./ecs/ecs-zero-downtime-deployments.md) | Blue/green and rolling deployments on ECS — what the console hides and what you need to know. |

### ⚙️ Kubernetes / EKS / CKAD
| Note | What's in it |
|---|---|
| [EKS: ALB · NLB · Ingress deep dive](./eks/aws-alb-nlb-ingress-eks-deep-dive.md) | End-to-end deep dive on getting traffic into EKS, and the mental-model shift from ECS load balancing. |
| [CrashLoopBackOff — part 1: foundations](./eks/crashloopbackoff-part1-foundations.md) | What CrashLoopBackOff actually means, the backoff algorithm, and how to read what the pod is telling you. |
| [CrashLoopBackOff — part 2: advanced debugging](./eks/crashloopbackoff-part2-advanced.md) | OOM kills, init container failures, readiness probe deadlocks, and the fixes that stick. |
| [IRSA explained for real EKS workloads](./eks/irsa-explained-real-eks-workloads.md) | IAM Roles for Service Accounts — the right way to give your pods AWS permissions, and why node-level roles are the wrong answer. |
| [`kubectl rollout status` is underrated](./eks/kubectl-rollout-status-is-underrated.md) | The pipeline gatekeeper command most teams forget to use. |
| [CKAD deployments — part 1](./ckad/ckad-deployments-part-1.md) | Annotated Deployment YAML, every spec field, exam-speed imperative generation. |
| [CKAD deployments — part 2](./ckad/ckad-deployments-part-2.md) | Advanced patterns, rollout strategies, and the 10 rules I'd tell anyone sitting the exam. |
| [Kubernetes Ingress — CKAD exam + EKS production](./ckad/kubernetes-ingress-ckad-exam-and-eks-production-mastery.md) | The Ingress mental model, enough to pass CKAD and to actually ship it on EKS. |
| [Kubernetes CronJob 101](./ckad/kubernetes_cronjob_101_guide.md) | CronJob spec, concurrency policies, failure handling, and what to watch in production. |

### 🔌 API Gateway
> Seven chapters that take you from "what is an API" to running a production-grade API Gateway on AWS. There's also a [prerequisites track](./apigateway/prerequisites/) for engineers who want to build the API fundamentals first.

| Note | What's in it |
|---|---|
| [Chapter 1: Fundamentals & request lifecycle](./apigateway/api-gateway-ch1-fundamentals-request-lifecycle.md) | What API Gateway is, how a request flows through it, and the execution model that governs everything else. |
| [Chapter 2: Endpoint types & resource design](./apigateway/api-gateway-ch2-endpoint-types-resource-design.md) | Regional vs edge-optimized vs private — and how to design resources and methods that won't need a rewrite. |
| [Chapter 3: Integration types deep dive](./apigateway/api-gateway-ch3-integration-types-deep-dive.md) | Lambda proxy vs HTTP proxy vs AWS service integrations — the differences that bite you in production. |
| [Chapter 4: Building and deploying](./apigateway/api-gateway-ch4-building-deploying.md) | Stages, deployment strategies, canary releases, and the deployment quirks you'll hit exactly once. |
| [Chapter 5: Security & access control](./apigateway/api-gateway-ch5-security-access-control.md) | IAM auth, Cognito authorizers, Lambda authorizers, API keys, and WAF integration. |
| [Chapter 6: Traffic management & custom domains](./apigateway/api-gateway-ch6-traffic-management-domains.md) | Throttling, usage plans, custom domains, and ACM certificate wiring. |
| [Chapter 7: Observability & troubleshooting](./apigateway/api-gateway-ch7-observability-troubleshooting.md) | CloudWatch metrics, access logging, X-Ray tracing, and the debug workflow when a request disappears. |

**Prerequisites track** — start here if you want the API foundation first:

| Note | What's in it |
|---|---|
| [Part 1: What is an API](./apigateway/prerequisites/part-1-what-is-an-api.md) | APIs demystified — what they are, how they work, and why everything in modern infrastructure speaks HTTP. |
| [Part 2: APIs in practice for junior engineers](./apigateway/prerequisites/part-2-apis-in-practice-junior-engineers.md) | Calling APIs, reading responses, handling errors, and building the intuition for what's happening under the hood. |
| [Part 3: API design for software engineers](./apigateway/prerequisites/part-3-api-design-software-engineers.md) | REST conventions, versioning, pagination, and the contract decisions that make or break a public API. |
| [Part 4: APIs for DevOps engineers](./apigateway/prerequisites/part-4-apis-devops-engineers.md) | Rate limits, retries, circuit breakers, auth flows, and the operational patterns that keep a system stable. |
| [Part 5: Advanced API architecture](./apigateway/prerequisites/part-5-advanced-api-architecture.md) | GraphQL, gRPC, event-driven patterns, and how to pick the right API style for the problem at hand. |

### 🔌 MCP — Model Context Protocol
> A six-part series on building MCP servers from scratch. Goes from "why AI needs doors" all the way to production-grade remote deployments.

| Note | What's in it |
|---|---|
| [Part 1: Why AI needs doors](./mcp-server-for-devops/01-why-ai-needs-doors.md) | The problem MCP solves and why bolting tools onto LLMs without a protocol is a bad idea. |
| [Part 2: Async Python for MCP](./mcp-server-for-devops/02-async-python-for-mcp.md) | The asyncio patterns you need before you can build a performant MCP server. |
| [Part 3: Protocol under the hood](./mcp-server-for-devops/03-protocol-under-the-hood.md) | JSON-RPC, the transport layer, message framing, and how client-server communication actually works. |
| [Part 4: Tools, resources, and prompts](./mcp-server-for-devops/04-tools-resources-prompts.md) | The three primitives an MCP server exposes — and when to use each one. |
| [Part 5: Your first MCP server](./mcp-server-for-devops/05-your-first-mcp-server.md) | Building a working MCP server end-to-end. The one to read first if you want to ship something today. |
| [Part 6: Going remote](./mcp-server-for-devops/06-going-remote.md) | Deploying MCP servers beyond localhost — auth, transport options, and production considerations. |

### 🚀 Amazon Bedrock AgentCore
> Five-part operational guide for DevOps engineers deploying agents on Bedrock AgentCore. Assumes you already know ECS; focuses entirely on what's different and what can break. See the [series README](./learning-amazon-bedrock-agentcore/README.md).

| Note | What's in it |
|---|---|
| [Part 1: AgentCore foundations](./learning-amazon-bedrock-agentcore/01-agentcore-foundations.md) | What AgentCore is, the execution model, and how it differs from rolling your own agent infra on ECS. |
| [Part 2: Application anatomy](./learning-amazon-bedrock-agentcore/02-agentcore-application-anatomy.md) | The config manifest, entrypoints, runtime requirements, and the build artifacts AgentCore expects. |
| [Part 3: Local development and testing](./learning-amazon-bedrock-agentcore/03-local-development-and-testing.md) | Running AgentCore workloads locally before you push them anywhere. |
| [Part 4: Deployment options](./learning-amazon-bedrock-agentcore/04-deployment-options.md) | The deployment surface: what you control, what AWS manages, and the trade-offs. |
| [Part 5: Production DevOps readiness](./learning-amazon-bedrock-agentcore/05-production-devops-readiness.md) | Logging, health checks, rollback, scaling, and the runbook items that keep an agent alive in production. |

### 🔁 CI/CD
| Note | What's in it |
|---|---|
| [GitHub DevOps fundamentals & best practices](./ci-cd/01_GITHUB_DEVOPS_FUNDAMENTALS.md) | The foundations — repo hygiene, Actions, and the practices that keep a pipeline sane. |
| [GitHub DevOps complete implementation](./ci-cd/github-devops-implementation-02.md) | Building the pipeline for real: workflows, jobs, and a working Python app to hang it on. |
| [GitHub DevOps production deployment](./ci-cd/github-devops-production-03.md) | Taking the pipeline to production deploys against AWS ECS. |
| [GitLab CI/CD 101](./ci-cd/gitlab-cicd-101.md) | End-to-end GitLab CI/CD from first principles — what CI/CD is and why it matters. |
| [GitLab CI pipeline — part 1: structure](./ci-cd/gitlab-ci-pipeline-part1-structure.md) | Pipeline YAML anatomy, stages, jobs, runners, and the execution model. |
| [GitLab CI pipeline — part 2: security & rollback](./ci-cd/gitlab-ci-pipeline-part2-security-rollback.md) | Secrets management, protected branches, and the rollback patterns that actually work. |
| [Golden paths for application deployment](./ci-cd/golden-paths-for-application-deployment.md) | Opinionated deployment templates — the "paved road" approach that reduces decision fatigue at scale. |
| [Platform engineering vs traditional DevOps](./ci-cd/platform-engineering-vs-traditional-devops.md) | What changes when you move from "everyone owns their own pipeline" to an internal developer platform. |
| [Branch strategies](./ci-cd/branch-strategies.md) | A no-nonsense look at the branching models and when each one actually fits. |
| [Trunk-based development](./ci-cd/trunk-based-development.md) | Why long-lived branches hurt, and how trunk-based development avoids the Monday merge marathon. |

### 📈 SRE / Observability
| Note | What's in it |
|---|---|
| [OpenTelemetry 101](./sre/otel_101.md) | The beginner's mental model for modern observability — metrics, logs, and traces in one language. |
| [OpenTelemetry for cloud architects](./sre/otel_intermediate.md) | AWS at scale, multi-cloud from day one, and the OTel mistakes teams keep repeating. |
| [OpenTelemetry 101 — modern observability](./observability/opentelemetry-101-modern-observability.md) | Core OTel concepts for engineers setting up instrumentation from scratch. |
| [OpenTelemetry Collector deep dive](./observability/opentelemetry-part2-collector-deep-dive.md) | The Collector pipeline, processors, exporters, and how to run it without it becoming a bottleneck. |
| [CloudWatch dashboard design for EKS](./sre/cloudwatch-dashboard-design-for-eks.md) | Stitching control plane, data plane, the K8s object model, and app metrics into one pane of glass. |
| [Deployment strategies — canary vs blue/green vs rolling](./sre/canary-vs-blue-green-vs-rolling-deployments.md) | Every deployment strategy, when to use it, and how to pitch it as the business decision it is. |
| [Post-deployment validation checklist](./sre/post-deployment-validation-checklist.md) | Why green CI isn't "done," and what to actually check after the pipeline passes. |

### 🐍 Python
| Note | What's in it |
|---|---|
| [FastAPI for DevOps engineers](./python/what-devops-engineers-should-know-about-fastapi-in-production.md) | Python fundamentals → production-grade FastAPI. For DevOps folks building internal tools, automation APIs, and AI pipelines. |
| [Pydantic — the complete DevOps guide](./python/python_pydantic_devops_guide.md) | Why Pydantic matters in DevOps and how to use it for config, validation, and data contracts. |
| [Uvicorn vs Gunicorn explained](./python/uvicorn-vs-gunicorn-explained.md) | When to use which ASGI/WSGI server, and how to configure them correctly for production workloads. |

### 🐧 Linux
| Note | What's in it |
|---|---|
| [Linux for modern DevOps engineers](./linux/linux-for-modern-devops-engineers.md) | The Linux fundamentals that actually show up in day-to-day DevOps work — not a certification study guide. |
| [grep, awk, sed — log parsing in production](./linux/grep-awk-sed-log-parsing.md) | The three tools you'll reach for every time a log file has what you need but won't give it up easily. |
| [Disk space debugging](./linux/disk-space-debugging.md) | `df`, `du`, inode exhaustion, and the exact sequence of commands to use when a disk fills at 3 a.m. |
| [File permissions & ownership](./linux/file-permissions-ownership.md) | chmod, chown, ACLs, and sticky bits — permission errors explained so you don't just chmod 777 everything. |
| [Process management & resource limits](./linux/process-management-resource-limits.md) | `ps`, `top`, `ulimit`, cgroups, and how Linux actually enforces resource boundaries on processes. |
| [systemctl & service management](./linux/systemctl-service-management.md) | Managing systemd services — start, stop, enable, journal, and writing your own unit files. |
| [curl, dig, traceroute — networking from the terminal](./linux/curl-dig-traceroute-networking.md) | The command-line toolkit for debugging network problems without leaving the shell. |
| [CI/CD build log debugging](./linux/cicd-build-log-debugging.md) | Reading build logs like a surgeon — the patterns that point to broken dependencies, env var leaks, and flaky tests. |
| [Idempotent scripting & automation](./linux/idempotent-scripting-automation.md) | Writing shell scripts that are safe to run twice. The single most underrated skill in DevOps automation. |
| [kubectl daily toolkit](./linux/kubectl-daily-toolkit.md) | The kubectl commands and patterns you'll actually use every day — not the ones that only appear in tutorials. |
| [SQLite for DevOps — part 1](./linux/sqlite-for-devops-part-1.md) | SQLite as a DevOps tool: lightweight state storage, audit logs, and local data wrangling without spinning up a database. |
| [SQLite for DevOps — part 2](./linux/sqlite-for-devops-part-2.md) | Advanced patterns: JSON columns, FTS, WAL mode, and embedding SQLite into automation scripts. |

### 📐 System Design
| Note | What's in it |
|---|---|
| [What is system design for DevOps engineers](./system-design/what-is-system-design-for-devops-engineers.md) | Why system design matters for DevOps, the vocabulary, and how to approach the questions that come up in architecture reviews. |
| [Latency vs throughput](./system-design/latency-vs-throughput.md) | The distinction that governs every performance decision — and why optimizing for the wrong one makes things worse. |
| [Scalability: vertical vs horizontal](./system-design/scalability-vertical-vs-horizontal.md) | When to scale up vs scale out, and the architectural implications of each choice. |

---

## Highlights

A few of the notes I reach for most often:

- **[ECS task health is not application health](./ecs/ecs-task-health-is-not-the-same-as-app-health.md)** — the note I wish every team read before they wire up their first ECS deployment pipeline. Explains the four layers of health and why `RUNNING` tells you almost nothing.
- **[ALB + ECS deep dive](./aws/aws-alb-ecs-deep-dive.md)** — the one I re-read every time I have to debug why a target is unhealthy for reasons that aren't actually about the target.
- **[GenAI vs Agentic AI — part 1](./ai-devops/genai-vs-agentic-ai-part1.md)** — the framing I keep sending people: the difference between AI that helps you think and AI that acts on your behalf, and why that line matters for security and architecture.
- **[SRE for LLM applications](./ai-devops/sre-for-llm--applications.md)** — written from the on-call seat, not the demo. If you're about to put an LLM in front of real users, start here.
- **[Idempotent scripting & automation](./linux/idempotent-scripting-automation.md)** — the single most underrated skill in shell automation. Writing scripts that are safe to run twice sounds boring until you're debugging a half-applied config at midnight.
- **[`docker build` vs `docker buildx`](./docker/docker-build-vs-buildx-is-not-just-a-new-command.md)** — written after I watched one too many engineers treat buildx as a drop-in upgrade and then lose an image to the cache.
- **[Bedrock AgentCore: production DevOps readiness](./learning-amazon-bedrock-agentcore/05-production-devops-readiness.md)** — what you're accountable for once an agent is live and on-call is watching it.
- **[CrashLoopBackOff — part 1](./eks/crashloopbackoff-part1-foundations.md)** — because everyone hits this and nobody explains the backoff algorithm.

---

## Repo stats

- **130 notes** across 20 topic areas
- **~80,000 lines** of content
- Everything is plain Markdown — clone and `grep -r "some error" .` works better than any search UI

---

## How I use this repo

- **Browse on GitHub** — the folder structure maps to the sections above. Click a section heading to go straight to it.
- **Clone and grep locally** — `git clone` and `grep -r "some error" .` is how I actually find things when I'm mid-incident. Plain markdown, that's the point.
- **Fork and adapt** — if the structure works for you, rip it out and make it your team's reference. That's what it's for.

---

## Contributing

If I got something wrong, open an issue or a PR — I'd rather be right than look right. Corrections, additions, and "actually, here's a sharper way to put it" are all welcome. These notes improve every time someone pushes back on them.

---

## License

MIT. Use it, fork it, lift bits for your own team's runbooks.
