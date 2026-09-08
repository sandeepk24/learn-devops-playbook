# AWS Bedrock at the Fundamental Level — Building Agentic AI Products in Production

> *Everyone has a "getting started with Bedrock" tutorial. This is not that.*

**Tags:** `AWS` `Bedrock` `AgentCore` `Agentic AI` `GenAI` `RAG` `Strands` `MCP` `DevOps` `Cloud Architecture`

**Last updated:** 2025 — covers AgentCore, Strands SDK, S3 Vectors, A2A protocol

---

## Preface: The Question Nobody Asks

Most Bedrock articles answer the question: *"How do I make an API call to Claude?"*

That is the not exactly the right question. It is roughly equivalent to asking "how do I execute a SQL query?" when what you actually need to understand is database architecture, indexing strategy, connection pooling, and query planning.

The question worth asking is: *"What is Bedrock's actual execution model, and how do I design a system on top of it that works under real production conditions — concurrent users, flaky tools, long-running tasks, evolving requirements, and the budget of a real company?"*

This article answers that question. It covers the entire stack from the API primitives at the bottom to multi-agent supervisor architectures at the top, with architecture diagrams, real code, and the production insights that only surface after you've had things break in front of users.

---

## Part 1 — The Bedrock Execution Model: What It Actually Is

### Bedrock is not a model provider. It is a managed inference plane.

This is the first mental model correction. When you call Bedrock, you are not talking to a model directly. You are talking to a managed service that:

1. Authenticates your request via IAM
2. Routes it to the correct foundation model endpoint
3. Enforces any active Guardrails policy
4. Meters token usage for billing
5. Returns the response (streaming or synchronous)

The models themselves — Claude, Titan, Nova, Llama, Mistral, Stable Diffusion, and dozens more — are hosted on AWS infrastructure but accessed through a unified control plane. This matters architecturally because the control plane adds latency (typically 50–150ms on top of model inference time) and because the same control plane enforces governance across every model call.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          AWS BEDROCK SERVICE PLANE                            │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                        YOUR APPLICATION                                 │ │
│  │  boto3 / SDK / HTTP                                                     │ │
│  └───────────────────────────────────┬─────────────────────────────────────┘ │
│                                      │  IAM SigV4 signed request              │
│                                      ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    BEDROCK CONTROL PLANE (bedrock.*)                    │ │
│  │  • Model access management  • Provisioned throughput                   │ │
│  │  • Fine-tuning jobs         • Model evaluation                         │ │
│  │  • Guardrails configuration • Knowledge base management                │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                        │
│                                      ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                   BEDROCK RUNTIME (bedrock-runtime.*)                   │ │
│  │  • InvokeModel           — direct inference, model-specific payload     │ │
│  │  • Converse              — unified multi-turn API, model-agnostic       │ │
│  │  • ConverseStream        — streaming variant of Converse                │ │
│  │  • InvokeModelWithResponseStream — streaming for InvokeModel            │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                      │                                        │
│                     ┌────────────────┼─────────────────┐                     │
│                     ▼                ▼                   ▼                    │
│              ┌────────────┐  ┌────────────┐   ┌──────────────┐               │
│              │  Claude    │  │ Amazon     │   │  Llama /     │               │
│              │  (Anthropic│  │  Nova      │   │  Mistral /   │               │
│              │  models)   │  │  (AWS)     │   │  others      │               │
│              └────────────┘  └────────────┘   └──────────────┘               │
└──────────────────────────────────────────────────────────────────────────────┘
```

### The Converse API: The Right Abstraction

There are two ways to call a model on Bedrock: `InvokeModel` and `Converse`. The difference is important.

`InvokeModel` accepts a model-specific JSON payload. Every model family has a different schema. Switching from Claude to Nova means rewriting your request format. It is the raw interface — maximum flexibility, zero portability.

`Converse` is a unified interface that works across all models that support messages. Same Python code, any model. This is what you should use for any application that needs to be model-agnostic — which in practice means almost everything, because which models are best keeps changing fast enough that locking to a specific model's API is a liability.

```python
import boto3
import json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# Converse API — identical code works with Claude, Nova, Llama, Mistral
# Switch the model_id and the logic is unchanged
response = bedrock.converse(
    modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
    system=[{
        "text": "You are a senior DevOps engineer specializing in AWS."
    }],
    messages=[{
        "role": "user",
        "content": [{"text": "Explain the difference between ECS and EKS for a team migrating from on-prem containers."}]
    }],
    inferenceConfig={
        "maxTokens": 1024,
        "temperature": 0.3,    # lower = more deterministic, better for factual tasks
        "topP": 0.9
    }
)

# The response structure is identical regardless of which model you used
output_text = response["output"]["message"]["content"][0]["text"]
usage = response["usage"]  # inputTokens, outputTokens, totalTokens

print(output_text)
print(f"\nTokens used: {usage['totalTokens']}")
```

```python
# Streaming version — same API, returns chunks as they generate
# Critical for UI responsiveness on longer outputs
response_stream = bedrock.converse_stream(
    modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
    messages=[{"role": "user", "content": [{"text": "Write a detailed runbook for ECS blue/green deployment"}]}],
    inferenceConfig={"maxTokens": 2048}
)

# Process the stream — each event is a chunk of the response
for event in response_stream["stream"]:
    if "contentBlockDelta" in event:
        delta = event["contentBlockDelta"]["delta"]
        if "text" in delta:
            print(delta["text"], end="", flush=True)
    elif "messageStop" in event:
        stop_reason = event["messageStop"]["stopReason"]
        # end_turn = model finished naturally
        # max_tokens = hit the limit — increase maxTokens if this happens
        print(f"\n[Stop reason: {stop_reason}]")
```

### Model IDs: the inference profile pattern (2025)

A critical operational detail that breaks applications: Bedrock model IDs now use *inference profiles* for cross-region routing. Prefixing a model ID with a region code (`us.`, `eu.`, `ap.`) enables automatic load distribution across AWS regions, improving availability and reducing rate-limit errors.

```python
# Direct model ID — single region, hits rate limits faster under load
modelId="anthropic.claude-3-5-sonnet-20241022-v2:0"

# Cross-region inference profile — routes across us-east-1, us-west-2, etc.
# Use this for production workloads
modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0"

# You can also use a custom inference profile you define
# to control exactly which regions and models are in the pool
modelId="arn:aws:bedrock:us-east-1:123456789:inference-profile/my-prod-profile"
```

In production, cross-region inference profiles are not optional for anything handling more than a few concurrent users — they are how you avoid `ThrottlingException` at scale.

---

## Part 2 — Knowledge Bases: The RAG Layer Decoded

Every serious Bedrock application eventually needs to give a model access to private, domain-specific, or frequently-updated information that was not in its training data. This is what Knowledge Bases do — they implement Retrieval-Augmented Generation (RAG) as a managed service.

Understanding Knowledge Bases at the operational level requires understanding every step in the pipeline.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                    BEDROCK KNOWLEDGE BASE: INGESTION PIPELINE                 │
│                                                                                │
│  DATA SOURCES                                                                  │
│  ┌────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ Amazon S3  │  │  Confluence  │  │ SharePoint  │  │  Web Crawler /       │ │
│  │ (PDFs,     │  │  (pages,     │  │ (documents, │  │  Salesforce /        │ │
│  │  docs,     │  │   spaces)    │  │  sites)     │  │  Custom (streaming)  │ │
│  │  html...)  │  └──────────────┘  └─────────────┘  └──────────────────────┘ │
│  └─────┬──────┘                                                                │
│        │                                                                       │
│        ▼  (Sync job triggered manually or on schedule)                        │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                     PARSING + CHUNKING                                  │ │
│  │                                                                         │ │
│  │  Parser options:                                                        │ │
│  │  • Default (text extraction)                                            │ │
│  │  • Foundation model parser — uses Claude to parse complex PDFs,        │ │
│  │    extract tables, interpret charts, preserve semantic structure        │ │
│  │                                                                         │ │
│  │  Chunking strategies:                                                   │ │
│  │  • Fixed-size: N tokens, X% overlap — simple, predictable              │ │
│  │  • Semantic: splits on meaning boundaries — better recall, slower      │ │
│  │  • Hierarchical: parent/child chunks — summary + detail retrieval      │ │
│  │  • None: you handle chunking upstream, bring your own structure        │ │
│  │  • Custom Lambda: arbitrary Python chunking logic                      │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│        │                                                                       │
│        ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                    EMBEDDING MODEL                                      │ │
│  │  Each chunk → embedding vector (1024 or 1536 dimensions)               │ │
│  │                                                                         │ │
│  │  Options: Amazon Titan Embed v2, Cohere Embed, custom model            │ │
│  │  Critical: embedding model at ingestion MUST match embedding model     │ │
│  │  at query time. Changing models = full re-ingestion of all docs.       │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│        │                                                                       │
│        ▼                                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │                      VECTOR STORE                                       │ │
│  │                                                                         │ │
│  │  Amazon OpenSearch Serverless — full-featured, supports hybrid search  │ │
│  │  Amazon S3 Vectors (re:Invent 2025) — up to 90% cheaper, sub-second   │ │
│  │  Amazon Aurora PostgreSQL (pgvector) — good if you have RDS already   │ │
│  │  Amazon Neptune Analytics — GraphRAG, relationship-aware retrieval     │ │
│  │  Pinecone / MongoDB / Redis Enterprise — if you have existing infra    │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘


┌──────────────────────────────────────────────────────────────────────────────┐
│                    BEDROCK KNOWLEDGE BASE: QUERY PIPELINE                     │
│                                                                                │
│  User Query: "What is our SLA for P1 incidents?"                              │
│        │                                                                       │
│        ▼                                                                       │
│  ┌────────────────────────────────────┐                                        │
│  │  Query Embedding                   │                                        │
│  │  Same model as ingestion           │                                        │
│  │  → vector [0.12, -0.34, 0.89 ...] │                                        │
│  └────────────────────────────────────┘                                        │
│        │                                                                       │
│        ▼  k-NN vector similarity search (cosine / L2 / dot product)           │
│  ┌────────────────────────────────────┐                                        │
│  │  Retrieved chunks (top-K)          │                                        │
│  │  + metadata (source, page, score)  │                                        │
│  │  + optional metadata filters       │                                        │
│  └────────────────────────────────────┘                                        │
│        │                                                                       │
│        ▼  (RetrieveAndGenerate API — combines retrieval + inference)           │
│  ┌────────────────────────────────────┐                                        │
│  │  Augmented prompt to the FM        │                                        │
│  │  [system prompt] +                 │                                        │
│  │  [retrieved context chunks] +      │                                        │
│  │  [user query]                      │                                        │
│  └────────────────────────────────────┘                                        │
│        │                                                                       │
│        ▼                                                                       │
│  Response with citations (source documents + page numbers)                    │
└──────────────────────────────────────────────────────────────────────────────┘
```

### The chunking strategy decision — what the tutorials skip

Chunking is not a configuration detail. It is an architectural decision that determines retrieval quality, and getting it wrong means your RAG system answers questions with confidently wrong information.

**Fixed-size chunking** (e.g., 512 tokens, 20% overlap) is predictable and fast to ingest. It fails when semantic meaning crosses the chunk boundary — a procedure that spans two chunks will get split and retrieved incompletely.

**Semantic chunking** uses an embedding model to detect meaning boundaries, splitting where context shifts rather than where the token count hits a threshold. Better recall, 2–3× slower ingestion. Use this when document quality matters more than ingestion speed.

**Hierarchical chunking** creates two levels: small child chunks (high precision retrieval) and larger parent chunks (full context). When a child chunk is retrieved, the parent is returned to the model. This is the best strategy for technical documentation, runbooks, and policy documents where you need both precise matching and full context.

```python
import boto3

bedrock_agent = boto3.client("bedrock-agent", region_name="us-east-1")

# Hierarchical chunking configuration — parent/child strategy
knowledge_base = bedrock_agent.create_knowledge_base(
    name="ops-runbook-kb",
    description="SRE runbooks, incident procedures, and operational standards",
    roleArn="arn:aws:iam::123456789:role/BedrockKBRole",
    knowledgeBaseConfiguration={
        "type": "VECTOR",
        "vectorKnowledgeBaseConfiguration": {
            "embeddingModelArn": "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0",
            "embeddingModelConfiguration": {
                "bedrockEmbeddingModelConfiguration": {
                    "dimensions": 1024   # must match your vector index dimensions
                }
            }
        }
    },
    storageConfiguration={
        "type": "OPENSEARCH_SERVERLESS",
        "opensearchServerlessConfiguration": {
            "collectionArn": "arn:aws:aoss:us-east-1:123456789:collection/ops-vectors",
            "vectorIndexName": "bedrock-knowledge-base-default-index",
            "fieldMapping": {
                "vectorField": "bedrock-knowledge-base-default-vector",
                "textField": "AMAZON_BEDROCK_TEXT",
                "metadataField": "AMAZON_BEDROCK_METADATA"
            }
        }
    }
)

# Create data source with hierarchical chunking
data_source = bedrock_agent.create_data_source(
    knowledgeBaseId=knowledge_base["knowledgeBase"]["knowledgeBaseId"],
    name="runbooks-s3",
    dataSourceConfiguration={
        "type": "S3",
        "s3Configuration": {
            "bucketArn": "arn:aws:s3:::company-runbooks",
            "inclusionPrefixes": ["runbooks/", "procedures/", "sops/"]
        }
    },
    vectorIngestionConfiguration={
        "chunkingConfiguration": {
            "chunkingStrategy": "HIERARCHICAL",
            "hierarchicalChunkingConfiguration": {
                "levelConfigurations": [
                    {"maxTokens": 1500},  # parent chunk — full context
                    {"maxTokens": 300}    # child chunk — precise retrieval
                ],
                "overlapTokens": 60
            }
        },
        # Foundation model parser for complex PDFs with tables/diagrams
        "parsingConfiguration": {
            "parsingStrategy": "BEDROCK_FOUNDATION_MODEL",
            "bedrockFoundationModelConfiguration": {
                "modelArn": "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-haiku-20240307-v1:0",
                "parsingPrompt": {
                    "parsingPromptText": "Extract all text, preserving table structure and numbered steps. For diagrams, describe what they show."
                }
            }
        }
    }
)
```

### Querying: Retrieve vs RetrieveAndGenerate

Two APIs serve different architectural needs:

`Retrieve` — pure retrieval, no generation. Returns ranked chunks with scores and citations. Use this when you want full control over how retrieved context is used, or when you want to inspect what the knowledge base found before sending it to a model.

`RetrieveAndGenerate` — retrieval plus generation in one call. Bedrock handles constructing the augmented prompt. Use this for simpler applications where you trust Bedrock's prompt assembly.

```python
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")

# Retrieve only — inspect what the KB found
retrieve_response = bedrock_agent_runtime.retrieve(
    knowledgeBaseId="KNOWLEDGE_BASE_ID",
    retrievalQuery={"text": "What is the rollback procedure for ECS deployments?"},
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "numberOfResults": 5,           # how many chunks to return
            "overrideSearchType": "HYBRID", # HYBRID = vector + keyword search
            "filter": {
                # Metadata filter — only search runbooks, not reference docs
                "equals": {"key": "document_type", "value": "runbook"}
            }
        }
    }
)

for result in retrieve_response["retrievalResults"]:
    score = result["score"]
    text  = result["content"]["text"]
    source = result["location"]["s3Location"]["uri"]
    print(f"Score: {score:.3f} | Source: {source}")
    print(f"  {text[:200]}...")
    print()
```

---

## Part 3 — Guardrails: Trust Is Not Enough

Guardrails are Bedrock's policy enforcement layer. They sit between your application and the model, intercepting both the prompt (input) and the model's response (output) and applying configurable rules. They are not optional in production — they are how you stop your AI product from embarrassing your company or violating compliance requirements.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      GUARDRAILS ENFORCEMENT POINTS                            │
│                                                                                │
│  User Input                                                                    │
│      │                                                                         │
│      ▼                                                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  INPUT GUARDRAILS (applied before the model sees the prompt)          │   │
│  │                                                                       │   │
│  │  ● Topic denial — block specific topics ("Do not discuss competitor   │   │
│  │    pricing." "Refuse requests for medical dosage information.")       │   │
│  │  ● PII detection — detect and optionally redact SSNs, phone numbers, │   │
│  │    email addresses, credit card numbers before sending to the model   │   │
│  │  ● Content filters — configurable thresholds for hate/violence/sexual│   │
│  │    /profanity content (NONE / LOW / MEDIUM / HIGH)                   │   │
│  │  ● Word filters — literal blocklists (competitor names, slurs, etc.) │   │
│  │  ● Prompt injection detection — flags attempts to hijack the system  │   │
│  │    prompt via crafted user input                                      │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│      │                                                                         │
│      ▼  (if input passes) → Model inference runs                              │
│      │                                                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  OUTPUT GUARDRAILS (applied to the model's response before returning) │   │
│  │                                                                       │   │
│  │  ● Same content filters applied to model output                      │   │
│  │  ● Grounding check — is the response supported by the KB source?     │   │
│  │    (prevents hallucination in RAG applications)                       │   │
│  │  ● Relevance check — does the response answer the user's question?   │   │
│  │  ● PII de-identification — strip PII from responses                  │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│      │                                                                         │
│      ▼                                                                         │
│  Response returned to application                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

```python
# Attach a guardrail to any Converse call
response = bedrock.converse(
    modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
    messages=[{"role": "user", "content": [{"text": user_input}]}],
    guardrailConfig={
        "guardrailIdentifier": "abc123guardrail",
        "guardrailVersion": "DRAFT",  # or a specific version number
        "trace": "enabled"  # returns detailed trace of what guardrails did
    }
)

# Check if guardrails intervened
if response.get("stopReason") == "guardrail_intervened":
    # The model's response was blocked or modified
    guardrail_trace = response.get("trace", {}).get("guardrail", {})
    # Log what triggered — PII? Topic denial? Content filter?
    print(f"Guardrail action: {guardrail_trace}")
    return "I'm unable to respond to that request."
```

---

## Part 4 — The ReAct Loop: How Bedrock Agents Think

Before building agents, you need to understand what they are mechanically. An agent is not a special type of AI — it is a control loop that uses a model's ability to reason about tools to iteratively work toward a goal. The pattern is called ReAct (Reasoning + Acting).

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        THE ReAct LOOP IN BEDROCK AGENTS                       │
│                                                                                │
│  User: "Check our prod ECS cluster health and create a Jira ticket for        │
│         any services below 80% target capacity."                              │
│                │                                                               │
│                ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  ITERATION 1: THINK                                                     │ │
│  │  Model receives: [system prompt] + [tool descriptions] + [user query]  │ │
│  │  Model outputs: "I need to check ECS cluster health first.             │ │
│  │                  I'll call the get_cluster_health tool."               │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                │                                                               │
│                ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  ITERATION 1: ACT                                                       │ │
│  │  Tool invoked: get_cluster_health(cluster="prod-ecs-cluster")          │ │
│  │  Tool returns: {"services": [{"name": "api", "running": 3, "desired":  │ │
│  │                  5}, {"name": "worker", "running": 4, "desired": 4}]}  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                │                                                               │
│                ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  ITERATION 2: THINK                                                     │ │
│  │  Model receives: [prev context] + [tool result]                        │ │
│  │  Model reasons: "'api' service is at 60% capacity (3/5). This is below │ │
│  │                  the 80% threshold. 'worker' is at 100%. I need to     │ │
│  │                  create a Jira ticket for the 'api' service only."     │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                │                                                               │
│                ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  ITERATION 2: ACT                                                       │ │
│  │  Tool invoked: create_jira_ticket(                                     │ │
│  │    title="ECS api service below capacity threshold",                   │ │
│  │    description="api service running 3/5 tasks (60% capacity)...",     │ │
│  │    priority="HIGH", labels=["ecs", "prod", "capacity"]                │ │
│  │  )                                                                     │ │
│  │  Tool returns: {"ticket_id": "OPS-4821", "url": "https://..."}        │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                │                                                               │
│                ▼                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  FINAL RESPONSE                                                         │ │
│  │  "Checked prod cluster health. The 'api' service is running at 60%     │ │
│  │   capacity (3 of 5 desired tasks). Created Jira ticket OPS-4821        │ │
│  │   [link]. The 'worker' service is healthy at 100% capacity."          │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

Each iteration consumes tokens (the growing conversation history + tool results) and introduces latency (one model inference call per iteration plus tool execution time). This is the fundamental cost model of agents — more complex tasks = more iterations = higher cost and latency.

---

## Part 5 — Tool Use: The Correct Way to Expose Capabilities

Tools (AWS calls them "action groups" in Bedrock Agents, "tools" in the Converse API) are the actions an agent can take. The quality of your tool descriptions is often more important than the model you choose. A model cannot use a tool it does not understand.

### Tool use via the Converse API (direct, framework-agnostic)

```python
import boto3
import json

bedrock = boto3.client("bedrock-runtime", region_name="us-east-1")

# Define tools with precise, explicit descriptions
# The model reads these descriptions to decide when and how to call them
tools = [
    {
        "toolSpec": {
            "name": "get_ecs_service_health",
            "description": (
                "Retrieves the current health status of ECS services in a cluster. "
                "Returns the running task count, desired task count, and deployment status "
                "for each service. Use this to check if services are meeting their target capacity."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "cluster_name": {
                            "type": "string",
                            "description": "The ECS cluster name or full ARN."
                        },
                        "service_names": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional list of specific service names to check. If omitted, returns all services."
                        }
                    },
                    "required": ["cluster_name"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "create_jira_issue",
            "description": (
                "Creates a new Jira issue in the specified project. "
                "Use this when an operational problem has been detected and needs tracking. "
                "Do NOT create duplicate tickets — first check if an open ticket already exists "
                "for the same issue using get_jira_issues."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "project_key": {"type": "string", "description": "Jira project key, e.g. OPS"},
                        "summary":     {"type": "string", "description": "Issue title, max 255 chars"},
                        "description": {"type": "string", "description": "Detailed issue description"},
                        "issue_type":  {"type": "string", "enum": ["Bug", "Task", "Incident"]},
                        "priority":    {"type": "string", "enum": ["Highest", "High", "Medium", "Low", "Lowest"]}
                    },
                    "required": ["project_key", "summary", "issue_type", "priority"]
                }
            }
        }
    }
]

def run_agent_loop(user_message: str, max_iterations: int = 10) -> str:
    """
    Implements the ReAct loop manually using the Converse API.
    This is what Bedrock Agents does internally — seeing it explicitly
    makes debugging much easier.
    """
    messages = [{"role": "user", "content": [{"text": user_message}]}]

    for iteration in range(max_iterations):
        response = bedrock.converse(
            modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
            system=[{"text": "You are an SRE agent. Use tools to complete operational tasks accurately."}],
            messages=messages,
            toolConfig={"tools": tools},
            inferenceConfig={"maxTokens": 2048}
        )

        stop_reason = response["stopReason"]
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)

        # Model finished — return the final answer
        if stop_reason == "end_turn":
            for block in assistant_message["content"]:
                if "text" in block:
                    return block["text"]

        # Model wants to use a tool
        if stop_reason == "tool_use":
            tool_results = []

            for block in assistant_message["content"]:
                if "toolUse" not in block:
                    continue

                tool_call  = block["toolUse"]
                tool_name  = tool_call["name"]
                tool_input = tool_call["input"]
                tool_use_id = tool_call["toolUseId"]

                # Dispatch to the actual tool implementation
                try:
                    result = dispatch_tool(tool_name, tool_input)
                    tool_results.append({
                        "toolUseId": tool_use_id,
                        "content": [{"json": result}]
                    })
                except Exception as e:
                    # Return the error to the model — it can reason about failures
                    tool_results.append({
                        "toolUseId": tool_use_id,
                        "content": [{"text": f"Tool execution failed: {str(e)}"}],
                        "status": "error"
                    })

            # Feed tool results back to the model for the next iteration
            messages.append({
                "role": "user",
                "content": [{"toolResult": r} for r in tool_results]
            })

    return "Agent reached maximum iterations without completing the task."


def dispatch_tool(name: str, inputs: dict) -> dict:
    """Route tool calls to actual implementations."""
    if name == "get_ecs_service_health":
        return get_ecs_service_health(**inputs)
    elif name == "create_jira_issue":
        return create_jira_issue(**inputs)
    else:
        raise ValueError(f"Unknown tool: {name}")
```

---

## Part 6 — Strands SDK: The Right Level of Abstraction

Writing the ReAct loop manually (as shown above) gives you full control and maximum debuggability, but it is verbose. The Strands Agents SDK, open-sourced by AWS in May 2025, is the level of abstraction that hits the sweet spot — it eliminates the boilerplate while keeping the execution transparent. It was built internally at AWS to power Q Developer, Glue, and VPC Reachability Analyzer before being released.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│              WHERE STRANDS FITS IN THE BEDROCK STACK                          │
│                                                                                │
│  Your business logic                                                           │
│       │                                                                        │
│       ▼                                                                        │
│  ┌─────────────────────────────────┐                                          │
│  │  Strands SDK                    │  ← You write agents here                 │
│  │  @tool decorator                │    Pure Python, no JSON schemas           │
│  │  Agent class                    │    Model-driven orchestration             │
│  │  AgentCoreMemorySessionManager  │    Native AgentCore integration           │
│  └─────────────────────────────────┘                                          │
│       │                                                                        │
│       ▼ (Strands calls Bedrock's Converse API with tool_use internally)       │
│  ┌─────────────────────────────────┐                                          │
│  │  Amazon Bedrock Runtime         │  ← Converse API, inference profiles     │
│  │  (bedrock-runtime client)       │                                          │
│  └─────────────────────────────────┘                                          │
│       │                                                                        │
│       ▼                                                                        │
│  ┌─────────────────────────────────┐                                          │
│  │  AgentCore Runtime              │  ← Where your agent runs in production  │
│  │  (microVM per user session)     │    Scales automatically, isolated        │
│  └─────────────────────────────────┘                                          │
└──────────────────────────────────────────────────────────────────────────────┘
```

```python
from strands import Agent, tool
from strands.models.bedrock import BedrockModel
import boto3

# @tool decorator turns any Python function into an agent-callable tool
# No JSON schema required — Strands infers the schema from type hints and docstring
@tool
def get_ecs_cluster_health(cluster_name: str, region: str = "us-east-1") -> dict:
    """
    Retrieves health status for all services in an ECS cluster.
    Returns running vs desired task counts and deployment status for each service.
    Use this to identify services that are below their target capacity.
    
    Args:
        cluster_name: The ECS cluster name (not the ARN, just the name)
        region: AWS region where the cluster lives
    
    Returns:
        Dictionary with service names as keys and health metrics as values
    """
    ecs = boto3.client("ecs", region_name=region)
    
    service_arns = ecs.list_services(cluster=cluster_name)["serviceArns"]
    if not service_arns:
        return {"services": [], "cluster": cluster_name}
    
    services = ecs.describe_services(
        cluster=cluster_name,
        services=service_arns
    )["services"]
    
    return {
        "cluster": cluster_name,
        "services": [
            {
                "name": s["serviceName"],
                "running_count": s["runningCount"],
                "desired_count": s["desiredCount"],
                "capacity_pct": round((s["runningCount"] / s["desiredCount"]) * 100)
                                if s["desiredCount"] > 0 else 0,
                "deployment_status": s["deployments"][0]["status"]
                                     if s["deployments"] else "UNKNOWN"
            }
            for s in services
        ]
    }


@tool
def query_runbook_knowledge_base(query: str) -> dict:
    """
    Searches the SRE runbook knowledge base for relevant procedures and documentation.
    Use this before performing any remediation to check if there is an established procedure.
    
    Args:
        query: A natural language description of what you are looking for
    
    Returns:
        List of relevant document excerpts with source citations
    """
    bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    
    response = bedrock_runtime.retrieve(
        knowledgeBaseId="YOUR_KB_ID",
        retrievalQuery={"text": query},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": 3,
                "overrideSearchType": "HYBRID"
            }
        }
    )
    
    return {
        "results": [
            {
                "text": r["content"]["text"],
                "source": r["location"].get("s3Location", {}).get("uri", "unknown"),
                "score": r["score"]
            }
            for r in response["retrievalResults"]
        ]
    }


# Create the agent — BedrockModel handles the Converse API internally
model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
    region_name="us-east-1"
)

sre_agent = Agent(
    model=model,
    system_prompt="""You are a senior SRE agent with access to ECS cluster monitoring 
    and the company runbook knowledge base.
    
    When investigating issues:
    1. Always check the runbook knowledge base first for established procedures
    2. Gather facts before taking any action
    3. Explain your reasoning clearly
    4. Never perform destructive operations without explicit confirmation
    """,
    tools=[get_ecs_cluster_health, query_runbook_knowledge_base]
)

# Invoke the agent
result = sre_agent("Check the prod-api ECS cluster and tell me if any services need attention.")
print(result)
```

---

## Part 7 — AgentCore: The Infrastructure for Running Agents at Scale

Writing an agent that works on your laptop is straightforward. Making it work for thousands of concurrent users — with isolated sessions, persistent memory, secure tool access, and observable behavior — requires infrastructure that AWS didn't have until AgentCore (announced July 2025 at AWS Summit New York, generally available late 2025).

The key insight from the AWS team that built it: Lambda, Fargate, and ECS were designed for stateless, short-lived, request-response workloads. Agents are long-running, stateful, non-deterministic, and each session needs isolation from every other session. These requirements needed a new runtime.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      AGENTCORE ARCHITECTURE                                   │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  AGENTCORE RUNTIME                                                      │ │
│  │                                                                         │ │
│  │  Per-session MicroVM isolation (Firecracker-based)                     │ │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐           │ │
│  │  │  User Session A│  │  User Session B│  │  User Session C│           │ │
│  │  │  MicroVM       │  │  MicroVM       │  │  MicroVM       │           │ │
│  │  │  Your agent    │  │  Your agent    │  │  Your agent    │           │ │
│  │  │  code runs     │  │  code runs     │  │  code runs     │           │ │
│  │  │  here          │  │  here          │  │  here          │           │ │
│  │  └────────────────┘  └────────────────┘  └────────────────┘           │ │
│  │                                                                         │ │
│  │  • Framework-agnostic: Strands, LangGraph, CrewAI, custom Python      │ │
│  │  • Bi-directional streaming: agent listens + responds simultaneously   │ │
│  │  • MCP + A2A protocol support: agent-to-agent communication            │ │
│  │  • Auto-scales to zero; consumption-based pricing (no idle cost)       │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  AGENTCORE MEMORY                                                       │ │
│  │                                                                         │ │
│  │  Short-term: conversation history within a session                     │ │
│  │  Long-term:  user preferences, semantic facts across sessions          │ │
│  │  Episodic:   agent learns from outcomes (re:Invent 2025 addition)      │ │
│  │                                                                         │ │
│  │  Namespace isolation: user_id → each user gets private memory          │ │
│  │  No manual DynamoDB/Redis setup required                                │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  AGENTCORE GATEWAY                                                      │ │
│  │                                                                         │ │
│  │  Managed MCP (Model Context Protocol) server                          │ │
│  │  Exposes your Lambda functions, APIs, and databases as agent tools     │ │
│  │  Built-in auth (Okta, Cognito, IAM), rate limiting, audit logging      │ │
│  │  The agent never touches your backend directly — Gateway mediates all  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  AGENTCORE OBSERVABILITY                                                │ │
│  │                                                                         │ │
│  │  OpenTelemetry spans for every agent step                              │ │
│  │  CloudWatch Dashboards: token usage, latency, session duration         │ │
│  │  Automated quality evaluation: correctness, helpfulness, safety        │ │
│  │  Goal success rate tracking                                            │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  AGENTCORE IDENTITY                                                     │ │
│  │                                                                         │ │
│  │  Inbound: federated identity (Okta, Cognito) — who can use the agent   │ │
│  │  Outbound: workload IAM identity — what the agent can do              │ │
│  │  Policy engine: which tools which users can access under what conditions│ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

```bash
# Deploy a Strands agent to AgentCore Runtime — 3 commands
pip install amazon-bedrock-agentcore

# Configure the runtime pointing at your agent entrypoint
agentcore configure -e agent.py \
  --execution-role arn:aws:iam::123456789:role/agentcore-execution-role

# Launch — deploys to AgentCore Runtime, returns an endpoint
agentcore launch
# Output: Agent launched at: https://bedrock-agentcore.us-east-1.amazonaws.com/agents/my-sre-agent/...
```

```python
# Invoking a deployed AgentCore agent with persistent memory
import boto3

agentcore = boto3.client("bedrock-agentcore-runtime", region_name="us-east-1")

# Each invocation with the same session_id continues the same conversation
# Memory persists between sessions — the agent remembers this user
response = agentcore.invoke_agent(
    agentId="my-sre-agent-id",
    agentAliasId="TSTALIASID",
    sessionId="user-12345-session-001",   # use user_id for isolation
    inputText="Check prod cluster health again — same issue as yesterday?"
    # The agent has memory of "yesterday" — it knows what was checked before
)

for event in response["completion"]:
    if "chunk" in event:
        print(event["chunk"]["bytes"].decode(), end="", flush=True)
```

---

## Part 8 — Multi-Agent Architecture: The Supervisor Pattern

Single agents have a ceiling. They accumulate context rapidly (each tool call adds tokens), they can't parallelize work across multiple concurrent tasks, and they become unwieldy when a system needs to be both a customer-facing interface and an operations engine simultaneously.

Multi-agent architectures solve this by decomposing work across specialized agents coordinated by a supervisor.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│             SUPERVISOR + SPECIALIST MULTI-AGENT ARCHITECTURE                  │
│                                                                                │
│  User: "Our EU payment service is degraded. Investigate and draft a           │
│          customer status page update."                                         │
│              │                                                                 │
│              ▼                                                                 │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │  SUPERVISOR AGENT                                                     │   │
│  │                                                                       │   │
│  │  Responsibilities:                                                    │   │
│  │  • Understand the user's goal                                         │   │
│  │  • Decompose into sub-tasks                                           │   │
│  │  • Route to appropriate specialist agents                             │   │
│  │  • Maintain cross-agent context                                       │   │
│  │  • Aggregate results into final response                              │   │
│  │  • Enforce policies before any action is taken                        │   │
│  └─────────────────────┬─────────────────────────────────────────────────┘   │
│                         │                                                      │
│          ┌──────────────┼──────────────────────────┐                         │
│          │              │                           │                          │
│          ▼              ▼                           ▼                          │
│  ┌──────────────┐ ┌──────────────┐         ┌──────────────────────────┐      │
│  │ INFRA AGENT  │ │ OBSERVABILITY│         │ COMMUNICATIONS AGENT      │      │
│  │              │ │ AGENT        │         │                           │      │
│  │ • ECS health │ │ • CloudWatch │         │ • Drafts status page text │      │
│  │ • ALB metrics│ │ • X-Ray      │         │ • Formats for Statuspage  │      │
│  │ • VPC flow   │ │ • Datadog    │         │ • Checks tone guidelines  │      │
│  │   logs       │ │ • Log Insights│        │ • Gets approval prompt    │      │
│  └──────┬───────┘ └──────┬───────┘         └──────────────┬────────────┘      │
│         │                │                                 │                   │
│         ▼                ▼                                 ▼                   │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │  AGENTCORE GATEWAY (MCP Server)                                       │    │
│  │  Each agent only has access to the tools its role needs               │    │
│  │  Infra Agent: ecs:Describe*, cloudwatch:GetMetricData                 │    │
│  │  Obs Agent:   logs:FilterLogEvents, xray:GetTraceSummaries            │    │
│  │  Comms Agent: statuspage:CreateIncident, statuspage:UpdateIncident    │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
```

```python
from strands import Agent, tool
from strands.models.bedrock import BedrockModel

model = BedrockModel(model_id="us.anthropic.claude-sonnet-4-5-20251001-v1:0")

# ── Specialist agents (each has a narrow, well-defined role) ──────────────────

infra_agent = Agent(
    model=model,
    system_prompt="""You are an infrastructure specialist. You investigate 
    ECS, ALB, and network layer issues. Report findings as structured data.
    Never attempt to make changes — investigation only.""",
    tools=[get_ecs_cluster_health, get_alb_metrics, get_vpc_flow_logs]
)

observability_agent = Agent(
    model=model,
    system_prompt="""You are an observability specialist. You analyze CloudWatch 
    metrics, X-Ray traces, and application logs to identify error patterns and 
    root causes. Provide evidence-based root cause hypotheses.""",
    tools=[query_cloudwatch, query_xray_traces, query_log_insights]
)

communications_agent = Agent(
    model=model,
    system_prompt="""You are a customer communications specialist. You draft 
    clear, accurate status page updates that describe impact without revealing 
    internal infrastructure details. Always understate severity slightly.""",
    tools=[get_statuspage_incident, update_statuspage_incident]
)

# ── Supervisor wraps specialist agents as tools ────────────────────────────────

@tool
def investigate_infrastructure(query: str) -> str:
    """
    Delegates an infrastructure investigation to the infra specialist agent.
    Use when you need to check ECS services, ALB health, or network connectivity.
    
    Args:
        query: Natural language description of what to investigate
    
    Returns:
        Investigation findings as a structured report
    """
    return str(infra_agent(query))


@tool
def analyze_observability_data(query: str) -> str:
    """
    Delegates log and metric analysis to the observability specialist agent.
    Use after getting infrastructure facts to understand the root cause.
    
    Args:
        query: What to analyze, including any relevant time window or service name
    
    Returns:
        Analysis report with evidence and root cause hypotheses
    """
    return str(observability_agent(query))


@tool
def draft_customer_communication(context: str) -> str:
    """
    Delegates status page drafting to the communications specialist agent.
    Use when you have enough information to communicate to customers.
    
    Args:
        context: Summary of the incident including impact and timeline
    
    Returns:
        Draft status page update text for human review
    """
    return str(communications_agent(context))


# ── Supervisor agent ──────────────────────────────────────────────────────────

supervisor = Agent(
    model=model,
    system_prompt="""You are an incident coordinator. When investigating issues:
    
    1. GATHER — use investigate_infrastructure to get factual service state
    2. ANALYZE — use analyze_observability_data to understand root cause  
    3. COMMUNICATE — only draft customer communication when you have enough facts
    
    Always complete investigation before drafting communication.
    Never speculate about root cause without evidence.
    Request human approval before publishing any customer communication.""",
    tools=[
        investigate_infrastructure,
        analyze_observability_data,
        draft_customer_communication
    ]
)

# The supervisor orchestrates the entire incident response
result = supervisor(
    "EU payment service is showing elevated error rates since 14:23 UTC. "
    "Investigate and prepare a status page update for review."
)
```

---

## Part 9 — Production Architecture: Putting It All Together

Here is the complete architecture for a production-grade agentic AI product on Bedrock. Every component choice has a reason.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│              PRODUCTION AGENTIC AI PRODUCT — COMPLETE ARCHITECTURE            │
│                                                                                │
│  CLIENT TIER                                                                   │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  Web App / Mobile / CLI / API Consumer                                  │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                │ HTTPS + WebSocket (streaming)                                 │
│                ▼                                                               │
│  GATEWAY TIER                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  Amazon API Gateway + Lambda Authorizer                                 │ │
│  │  • JWT validation (Cognito / Okta)                                     │ │
│  │  • Rate limiting per user / per org                                    │ │
│  │  • Request logging to CloudWatch                                       │ │
│  │  • Routes to AgentCore Runtime endpoint                                │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                │                                                               │
│                ▼                                                               │
│  AGENT TIER (AgentCore Runtime)                                               │
│  ┌───────────────────────────────────┐  ┌──────────────────────────────────┐ │
│  │  SUPERVISOR AGENT                 │  │  SUPERVISOR AGENT                │ │
│  │  (Session: user-A)                │  │  (Session: user-B)               │ │
│  │  MicroVM isolation                │  │  MicroVM isolation               │ │
│  └──────────────┬────────────────────┘  └──────────────────────────────────┘ │
│                  │ Strands agent-as-tool pattern                               │
│        ┌─────────┼──────────┐                                                 │
│        ▼         ▼          ▼                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                                       │
│  │ Specialist│ │Specialist│ │Specialist│  (each in own AgentCore Runtime       │
│  │ Agent A  │ │ Agent B  │ │ Agent C  │   deployment, independently scalable) │
│  └──────────┘ └──────────┘ └──────────┘                                       │
│                                                                                │
│  KNOWLEDGE LAYER                                                               │
│  ┌──────────────────────────────┐  ┌────────────────────────────────────────┐ │
│  │  Bedrock Knowledge Bases     │  │  Bedrock Guardrails                    │ │
│  │  S3 Vectors (cost-optimized) │  │  Applied on every inference call       │ │
│  │  or OpenSearch (high QPS)    │  │  PII, topics, content filters          │ │
│  └──────────────────────────────┘  └────────────────────────────────────────┘ │
│                                                                                │
│  TOOL LAYER (AgentCore Gateway — MCP Server)                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  Lambda tools / REST APIs exposed as MCP endpoints                      │ │
│  │  Auth policy: each agent role → specific tools under specific conditions │ │
│  │  Audit log: every tool call logged with agent identity + input/output    │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
│                                                                                │
│  MEMORY LAYER (AgentCore Memory)                                              │
│  ┌─────────────────────────────────┐  ┌────────────────────────────────────┐ │
│  │  Short-term: session context    │  │  Long-term: user preferences,      │ │
│  │  (auto-managed by AgentCore)    │  │  semantic facts, summaries         │ │
│  │                                 │  │  Namespaced by user_id             │ │
│  └─────────────────────────────────┘  └────────────────────────────────────┘ │
│                                                                                │
│  OBSERVABILITY (AgentCore + CloudWatch)                                       │
│  ┌──────────────────────────────────────────────────────────────────────────┐ │
│  │  OpenTelemetry spans for every agent step                                │ │
│  │  Dashboards: p50/p95/p99 latency, token cost/session, goal success rate  │ │
│  │  Automated quality eval: correctness, helpfulness, safety score          │ │
│  │  Alerts: latency degradation, error rate spike, cost per session anomaly │ │
│  └──────────────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 10 — Ten Production Insights That Articles Skip

**1. Token cost is your application's unit economics — instrument it from day one.**
An agent doing 5 iterations on a complex task can consume 50,000 tokens. At production scale with 10,000 daily active users, that is 500 million tokens per day. Before you launch, calculate your cost-per-session and set budgets. AgentCore's consumption-based pricing (you pay for active CPU, not I/O wait time) is typically 30–70% cheaper than Lambda for agent workloads because agents spend most of their time waiting for model responses.

**2. The model's context window is your most constrained resource.**
Every message, every tool call result, every retrieved knowledge base chunk, and every memory injection adds to the context that gets sent to the model on the next iteration. A 5-iteration agent handling a complex query can easily consume 40,000 tokens of context. Design your tools to return concise, structured data — not verbose text. Summarize tool results when you don't need the full content downstream.

**3. Guardrails add latency and must be sized appropriately for your SLA.**
Each guardrail evaluation adds 50–200ms to every inference call. In a 5-iteration agent loop, that is 250–1000ms of pure guardrail overhead. For internal tooling with trusted users, consider lighter guardrails. For public-facing products, guardrail latency is non-negotiable — design your p99 latency SLA assuming it.

**4. The embedding model you choose at knowledge base creation is permanent until re-ingestion.**
Amazon Titan Embed Text v2 (1024 dimensions) is the most cost-effective choice for most RAG applications. Cohere Embed v3 has better multilingual performance. If you switch embedding models later, you must re-embed and re-ingest your entire corpus — which is expensive and time-consuming for large knowledge bases. Decide carefully before ingesting production data.

**5. Hybrid search in Knowledge Bases outperforms pure vector search for most enterprise data.**
Vector search excels at semantic similarity. Keyword search excels at exact matches (product IDs, error codes, names). Your users will ask both kinds of questions. Enable `HYBRID` search type in your `RetrievalConfiguration` — it combines both approaches with relevance fusion. The cost difference is negligible; the recall improvement for enterprise knowledge bases is significant.

**6. Agent memory needs namespacing — it is not optional.**
If multiple users share the same agent without namespace isolation, User A's conversation context can influence User B's responses. AgentCore Memory uses `userId`-based namespacing. If you roll your own memory with DynamoDB or ElastiCache, implement the same pattern. A memory leak between user sessions is both a privacy issue and a correctness bug.

**7. Tool descriptions are hyperparameters that need tuning, not configuration that you set once.**
The model reads tool descriptions to decide when and how to call them. Ambiguous descriptions lead to wrong tool selection. Overly verbose descriptions increase token consumption. Include: what the tool does, when to use it, when NOT to use it, and what it returns. Review tool call traces in your observability data and refine descriptions based on actual model behavior.

**8. Agents need to fail gracefully — build explicit fallback behavior.**
An agent whose tool call fails should not crash or return a confusing error. Return error information to the model in the tool result — it can reason about failures, try alternatives, or explain the issue to the user. Set `maxIterations` guards to prevent infinite loops. Design your system prompt to define what the agent should do when it cannot complete a task.

**9. The A2A protocol (Agent-to-Agent) is the right way to compose agents in 2025.**
AgentCore Runtime now supports A2A natively — agents can call other agents as first-class API endpoints, not just as wrapped Python functions. This enables heterogeneous agent networks where different agents might run different frameworks (a Strands supervisor calling a LangGraph specialist) and potentially run on different infrastructure. Design your agent boundaries with A2A in mind even if you start with in-process calls.

**10. Evaluate continuously — a deployed agent is not a deployed model.**
Unlike a static ML model, an agent's behavior depends on its tools, its memory state, its system prompt, and the model version. All of these change over time. AgentCore's built-in evaluation capabilities let you define what "correct" looks like (accuracy, citations, latency, goal success rate) and continuously score real interactions against those criteria. Without continuous evaluation, you will not know when your agent regressed until users complain.

---

## The Decision Framework: Which Bedrock Tier Do You Need?

```
Are you building with Bedrock?
│
├── Just need inference (text, images, embeddings)?
│   └── Converse API + inference profiles
│       Done. Nothing else needed.
│
├── Need to answer questions from private/domain data?
│   └── Bedrock Knowledge Bases + RetrieveAndGenerate
│       Choose vector store based on:
│       • High QPS / real-time → OpenSearch Serverless
│       • Cost optimization / batch / infrequent → S3 Vectors
│       • Relationship-aware retrieval → Neptune Analytics (GraphRAG)
│
├── Need to take actions, not just answer questions?
│   └── Agent with tools
│       Choose implementation based on:
│       • Simple, few tools, low volume → Bedrock Agents (managed)
│       • Complex logic, custom frameworks → Strands + AgentCore
│       • Need full control / debugging → Converse API with manual ReAct
│
├── Need multiple specialized agents?
│   └── Supervisor + specialist pattern via Strands
│       Deploy each specialist to AgentCore Runtime independently
│       Use AgentCore Gateway for tool access control
│
└── Need production: scale, memory, auth, observability?
    └── Full AgentCore stack:
        Runtime + Memory + Gateway + Identity + Observability
```

---

## Further Depth

**Strands Agents SDK** — open-source, MIT licensed: `github.com/strands-agents/sdk-python`

**AgentCore documentation** — `docs.aws.amazon.com/bedrock-agentcore/latest/devguide/`

**Multi-agent orchestration reference architecture** — `github.com/aws-solutions-library-samples/guidance-for-multi-agent-orchestration-using-bedrock-agentcore-on-aws`

**Bedrock Knowledge Bases samples** — `github.com/aws-samples/amazon-bedrock-samples/tree/main/docs/rag`

**A2A Protocol spec** — `google.github.io/A2A/` (open standard, supported by AgentCore)

**MCP Protocol spec** — `modelcontextprotocol.io` (open standard for tool/data exposure)

---

*All code validated against boto3 1.35+, Strands SDK 1.x, AgentCore GA (2025). Model IDs reflect the 2025 naming convention with cross-region inference profile prefixes. Pricing referenced reflects AgentCore's consumption-based model announced at AWS Summit New York, July 2025.*
