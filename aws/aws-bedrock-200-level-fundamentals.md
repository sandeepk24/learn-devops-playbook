# AWS Bedrock — From Zero to Your First AI Product

> *Not a tutorial that ends at "Hello World." A foundation that explains the why behind every decision, so your second, third, and tenth Bedrock project are faster than your first.*

**Tags:** `AWS` `Bedrock` `GenAI` `AI` `Cloud` `Beginner` `200-Level`

**Prerequisites:** Basic AWS knowledge (IAM, S3, Lambda concepts), Python basics

---

## Why This Article Exists

Most "intro to Bedrock" content falls into one of two failure modes. Either it's a five-minute click-through of the AWS console that leaves you with no mental model of what you actually built, or it's a wall of code that works until you try to change anything and then breaks mysteriously.

This article builds the mental model first, then the code. By the end, you will understand not just *how* to call Bedrock, but *what* it is doing and *why* certain patterns exist. That understanding is what lets you debug problems, make architectural decisions, and extend what you've built.

We will build three things across this article, each one extending the last:

1. A basic AI assistant that answers questions using a foundation model
2. The same assistant, now with access to your private company documents (RAG)
3. A simple AI agent that can take actions, not just answer questions

---

## Part 1 — What Is Bedrock, and Why Does It Exist?

### The problem Bedrock solves

Before Bedrock existed, if you wanted to add AI capabilities to an AWS application, you had three options: call OpenAI's API directly (which meant your data left AWS), download and host a model yourself on EC2 or SageMaker (which required significant ML infrastructure expertise), or build fine-tuned models from scratch (expensive, slow, requires data science teams).

Bedrock is AWS's answer: a managed service that gives you access to a curated selection of the world's best foundation models, all within your AWS account, with the same IAM security model you use for everything else, billed through your AWS bill.

### What foundation models actually are

A foundation model is a large neural network trained on massive amounts of text (and increasingly images, code, and audio) that develops general-purpose capabilities: answering questions, writing, summarising, translating, reasoning, coding.

You do not train these from scratch. Training GPT-4 cost an estimated $100 million. What Bedrock lets you do is *use* these already-trained models through an API — you send text in, you get text back — and optionally *adapt* them to your specific domain through techniques like fine-tuning and Retrieval-Augmented Generation (RAG).

```
┌──────────────────────────────────────────────────────────────────────┐
│               WHAT HAPPENS WHEN YOU CALL BEDROCK                      │
│                                                                        │
│  Your App                                                              │
│    │                                                                   │
│    │  "Explain what a VPC is to a devops engineer"                     │
│    ▼                                                                   │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │              Amazon Bedrock (AWS Service)                        │ │
│  │                                                                  │ │
│  │  • Authenticates your request using IAM                         │ │
│  │  • Routes to the model you specified                            │ │
│  │  • Enforces any safety policies you've configured               │ │
│  │  • Meters and bills your token usage                            │ │
│  │  • Returns the response                                         │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│    │                                                                   │
│    ▼                                                                   │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐  │
│  │ Claude   │   │ Amazon   │   │  Llama   │   │ Stable Diffusion │  │
│  │(Anthropic│   │  Nova    │   │  (Meta)  │   │  (Stability AI)  │  │
│  │  models) │   │  (AWS)   │   │          │   │  image models    │  │
│  └──────────┘   └──────────┘   └──────────┘   └──────────────────┘  │
│                                                                        │
│  100+ models available. You pick. Bedrock handles the hosting.        │
└──────────────────────────────────────────────────────────────────────┘
```

### The model families you will actually use

**Claude (Anthropic)** — The strongest reasoning models on Bedrock. Claude Sonnet is the workhorse: excellent at complex analysis, coding, writing, and following detailed instructions. Claude Haiku is the fast, cheap option for high-volume simpler tasks. Most production AI products on AWS use Claude.

**Amazon Nova** — AWS's own model family, optimised for cost and AWS service integration. Nova Lite is extremely cheap for simple tasks. Nova Pro handles more complex reasoning. Good default choice when you want tight AWS cost control.

**Llama (Meta)** — Open-source models that you can access through Bedrock. Useful when you need models you could also self-host for compliance reasons, or when you want to fine-tune with your own data.

**Titan Embeddings (Amazon)** — Not for generating text, but for converting text into numerical vectors. This is what powers search and RAG. You will use this constantly once you go beyond basic chat.

### How you pay

Bedrock uses token-based pricing. A token is roughly 0.75 words. You pay for tokens you send to the model (input tokens) plus tokens the model generates back (output tokens). Input tokens are cheaper than output tokens.

A simple chat message might use 100 tokens. A complex document analysis might use 10,000 tokens. For context, Claude Sonnet costs roughly $3 per million input tokens and $15 per million output tokens as of 2025.

There is no monthly subscription or idle cost for basic inference — you only pay when you make a request.

---

## Part 2 — Setting Up: The Right Way From the Start

### Enable model access — the step everyone forgets

Bedrock does not give you access to all models automatically. You must explicitly enable each model you want to use. This is a one-time console action, not a code change, and skipping it is responsible for more first-time confusion than anything else.

```
AWS Console → Amazon Bedrock → Model access (left sidebar) 
→ Manage model access → Check the models you need → Request access

For this article, enable:
✓ Anthropic Claude 3.5 Sonnet v2 (or Claude Sonnet 4 series)
✓ Amazon Titan Embeddings V2 (for Part 2 — RAG)
```

Access is usually granted immediately. Some models require a brief approval period.

### IAM permissions — minimal, correct, and understood

Your application or local development environment needs IAM permissions to call Bedrock. The principle here is least privilege: grant only what is needed.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInference",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude*",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan*"
      ]
    }
  ]
}
```

Notice the Resource field restricts to specific model ARN prefixes. This means if someone compromises your application credentials, they cannot use your IAM permissions to invoke every model on Bedrock — only the ones your app needs.

For local development, attach this policy to an IAM user and configure `aws configure` with that user's access key. For deployed applications, attach it to the Lambda execution role or EC2 instance profile — never hardcode credentials.

### Install and verify

```bash
pip install boto3 botocore

# Verify your credentials and region are configured
aws sts get-caller-identity
# Should return your AWS account ID and the IAM entity you're using

# Verify Bedrock is accessible from your region
aws bedrock list-foundation-models \
  --region us-east-1 \
  --query 'modelSummaries[?contains(modelId, `claude`)].{Model:modelId}' \
  --output table
```

---

## Part 3 — Your First Real Bedrock Call

### Understanding the Converse API

Bedrock has two ways to invoke models: `InvokeModel` (sends raw model-specific JSON) and `Converse` (a unified API that works identically across all text models). Always use `Converse` for new code. It means you can swap models with a single string change instead of rewriting your request format.

```
┌────────────────────────────────────────────────────────────────────┐
│              THE CONVERSE API REQUEST STRUCTURE                      │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  system (optional)                                           │  │
│  │  "You are an expert AWS architect..."                        │  │
│  │  Sets the model's role and behaviour constraints.           │  │
│  │  Only sent once per conversation, not with every message.   │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  messages (required)                                         │  │
│  │  [                                                           │  │
│  │    {"role": "user",      "content": [{"text": "..."}]},     │  │
│  │    {"role": "assistant", "content": [{"text": "..."}]},     │  │
│  │    {"role": "user",      "content": [{"text": "..."}]}      │  │
│  │  ]                                                           │  │
│  │  The conversation history. Alternates user/assistant.       │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  inferenceConfig (optional but important)                    │  │
│  │  maxTokens: how long the response can be                    │  │
│  │  temperature: 0.0 = deterministic, 1.0 = creative          │  │
│  │  topP: nucleus sampling threshold                           │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

### A simple assistant — built correctly from the start

```python
import boto3
from botocore.exceptions import ClientError

class BedrockAssistant:
    """
    A reusable Bedrock assistant that maintains conversation history
    for multi-turn conversations.
    """
    
    def __init__(
        self,
        model_id: str = "us.anthropic.claude-sonnet-4-5-20251001-v1:0",
        system_prompt: str = "You are a helpful assistant.",
        region: str = "us-east-1",
        max_tokens: int = 1024,
        temperature: float = 0.3
    ):
        self.client = boto3.client("bedrock-runtime", region_name=region)
        self.model_id = model_id
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.conversation_history = []
    
    def chat(self, user_message: str) -> str:
        """
        Send a message and get a response.
        Conversation history is maintained automatically.
        """
        # Add the user's message to history
        self.conversation_history.append({
            "role": "user",
            "content": [{"text": user_message}]
        })
        
        try:
            response = self.client.converse(
                modelId=self.model_id,
                system=[{"text": self.system_prompt}],
                messages=self.conversation_history,
                inferenceConfig={
                    "maxTokens": self.max_tokens,
                    "temperature": self.temperature
                }
            )
        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code == "ThrottlingException":
                raise RuntimeError("Bedrock rate limit hit. Try again in a moment.")
            elif error_code == "AccessDeniedException":
                raise RuntimeError("IAM permissions missing. Check bedrock:InvokeModel permission.")
            elif error_code == "ValidationException":
                raise RuntimeError(f"Invalid request: {e.response['Error']['Message']}")
            raise
        
        # Extract the assistant's response
        assistant_message = response["output"]["message"]
        response_text = assistant_message["content"][0]["text"]
        
        # Add the assistant's response to history for the next turn
        self.conversation_history.append(assistant_message)
        
        # Log token usage — important for cost monitoring
        usage = response["usage"]
        print(f"[Tokens: {usage['inputTokens']} in, {usage['outputTokens']} out]")
        
        return response_text
    
    def reset(self):
        """Clear conversation history to start a fresh conversation."""
        self.conversation_history = []


# Use it
assistant = BedrockAssistant(
    system_prompt=(
        "You are a senior AWS DevOps engineer. "
        "Give precise, practical answers. "
        "Include code examples when relevant. "
        "Admit uncertainty rather than speculating."
    )
)

# First turn
response = assistant.chat("What is the difference between ECS and EKS?")
print(response)
print()

# Second turn — the model remembers the context from the first turn
response = assistant.chat("For a team of 3 engineers with no Kubernetes experience, which would you recommend?")
print(response)
```

Notice a few things in this code:

The `conversation_history` list is what enables multi-turn conversations. On every call, the full history is sent to the model. The model has no memory of its own between calls — you are responsible for maintaining and sending the context. This is fundamental: there is no magic session state in the cloud.

The error handling catches specific `ClientError` codes and translates them into meaningful messages. `ThrottlingException` means you are hitting rate limits. `AccessDeniedException` means IAM is wrong. `ValidationException` means your request is malformed. In production, these need different handling strategies.

The token logging is not optional for production systems. Tokens are your cost metric. An assistant that sends growing conversation history on every call will have linearly increasing token costs per message in a long conversation.

### Understanding temperature — the most misunderstood parameter

Temperature controls how "creative" or "deterministic" the model's responses are.

```python
# temperature = 0.0 — completely deterministic
# Same input → same output every time
# Use for: code generation, data extraction, fact lookup, structured output
assistant_factual = BedrockAssistant(temperature=0.0)
response = assistant_factual.chat("What is the AWS shared responsibility model?")
# Will give the same answer every call

# temperature = 0.7 — creative, varied
# Same input → different outputs each time
# Use for: brainstorming, content writing, idea generation
assistant_creative = BedrockAssistant(temperature=0.7)
response = assistant_creative.chat("Write a tagline for our cloud migration service")
# Will generate different taglines on each call

# temperature = 1.0+ — highly unpredictable
# Rarely useful in production — outputs can become incoherent
```

For most DevOps and technical applications, `0.2–0.4` is the sweet spot: mostly consistent, but with enough variation to not feel robotic.

### Streaming — essential for user experience

When a model generates a long response, it does not write the whole thing and then send it. It generates token by token. Streaming lets you display the response as it generates, rather than making the user stare at a blank screen for 5–10 seconds.

```python
def stream_chat(user_message: str, model_id: str = "us.anthropic.claude-sonnet-4-5-20251001-v1:0"):
    """
    Stream a response token by token.
    Critical for chat interfaces where users expect immediate feedback.
    """
    client = boto3.client("bedrock-runtime", region_name="us-east-1")
    
    response = client.converse_stream(
        modelId=model_id,
        messages=[{
            "role": "user",
            "content": [{"text": user_message}]
        }],
        inferenceConfig={"maxTokens": 2048, "temperature": 0.3}
    )
    
    full_response = ""
    
    for event in response["stream"]:
        # A chunk of generated text arrived
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"]["delta"]
            if "text" in delta:
                chunk = delta["text"]
                print(chunk, end="", flush=True)  # print without newline
                full_response += chunk
        
        # Model finished generating
        elif "messageStop" in event:
            stop_reason = event["messageStop"]["stopReason"]
            if stop_reason == "max_tokens":
                print("\n[Response truncated — increase maxTokens if needed]")
            print()  # final newline
    
    return full_response


# Test streaming
stream_chat("Explain how AWS Lambda cold starts work and how to mitigate them.")
```

---

## Part 4 — Prompting: The Skill That Multiplies Everything Else

The model you choose matters. The prompts you write matter more. Two developers using the same model and the same task will get dramatically different results based on how they structure their prompts. This is not fuzzy art — there are concrete, teachable techniques.

### System prompts: scope and constrain

The system prompt defines the model's role, capabilities, and boundaries for the entire conversation. Weak system prompts produce generic, hedged responses. Strong system prompts produce focused, useful ones.

```python
# Weak system prompt — model will produce safe, generic responses
weak = "You are a helpful assistant."

# Strong system prompt — specific role, specific constraints, specific style
strong = """You are a senior DevOps engineer at a fintech company.
You have deep expertise in AWS, Kubernetes, and CI/CD pipelines.

When answering questions:
- Give direct, opinionated recommendations based on production experience
- Include concrete examples or code snippets when they help
- State trade-offs explicitly, not just the recommended approach
- If you are uncertain about something, say so rather than speculating
- Do not pad responses with unnecessary caveats or disclaimers

Your audience: mid-level engineers who know AWS basics but lack production experience."""
```

The difference in response quality between these two system prompts on the same question is substantial. The strong version produces answers that are opinionated, concise, and actionable. The weak version produces answers that are hedged, padded, and often too generic to be directly useful.

### The prompt patterns that matter most

**Be explicit about output format:**
```python
# Vague — model picks whatever format it feels like
user_message = "What are the pros and cons of serverless?"

# Explicit — model formats specifically for your use case
user_message = """Compare serverless vs container-based architectures for a 
REST API handling 10k requests/day.

Format your response as:
| Criteria | Serverless | Containers |
|----------|------------|------------|
[table rows]

Then provide a 2-sentence recommendation based on the scenario."""
```

**Provide context you would give to a human:**
```python
# Without context — model guesses at what you need
user_message = "Review this Terraform code."

# With context — model knows what to look for
user_message = """Review this Terraform code for an ECS service deployment.

Context:
- Production environment, us-east-1
- 50-100 concurrent users expected
- Team has had two prior incidents related to security group misconfiguration

Focus on: security issues, reliability concerns, and missing best practices.
Do not comment on formatting or naming conventions.

Code:
[terraform code here]"""
```

**Use few-shot examples for structured tasks:**
```python
user_message = """Convert these AWS CloudWatch error messages to a structured incident report.

Example input:
ERROR [2025-03-15 14:23:01] ECS task stopped: OutOfMemory container=api, exit_code=137

Example output:
{
  "severity": "HIGH",
  "component": "ECS / api container",
  "type": "OOMKilled",
  "timestamp": "2025-03-15T14:23:01Z",
  "action_required": "Increase memory limit on api task definition"
}

Now convert these messages:
[your error messages here]"""
```

---

## Part 5 — Knowledge Bases: Giving the Model Your Private Data

Foundation models are trained on data up to a certain date. They know nothing about your company's internal documentation, your runbooks, your product specs, or anything that happened after their training cutoff. Bedrock Knowledge Bases solve this through Retrieval-Augmented Generation (RAG).

### What RAG actually does — the concept before the code

RAG is a two-step process that happens on every user query:

**Step 1 — Retrieve:** Your documents are stored as vector embeddings (numerical representations of meaning) in a vector database. When a user asks a question, the question is also converted to a vector, and the database finds the document chunks whose meaning is most similar to the question.

**Step 2 — Augment and Generate:** The retrieved chunks are bundled into the prompt along with the user's question. The model is now answering based on the retrieved context, not just its training data.

```
┌────────────────────────────────────────────────────────────────────────┐
│                    HOW RAG WORKS — STEP BY STEP                         │
│                                                                          │
│  BEFORE ANY QUERY: Document Ingestion (runs once, or when docs update) │
│                                                                          │
│  Your S3 bucket          Bedrock Knowledge Base Pipeline               │
│  ┌──────────────┐                                                        │
│  │ runbook.pdf  │──► Split into chunks ──► Embed each chunk ──► Store   │
│  │ sla-doc.md   │                          (text → numbers)   in vector │
│  │ policy.txt   │                                              database  │
│  └──────────────┘                                                        │
│                                                                          │
│  AT QUERY TIME:                                                          │
│                                                                          │
│  User: "What is our SLA for P1 incidents?"                              │
│    │                                                                      │
│    │  1. Embed the question (text → numbers)                            │
│    │                                                                      │
│    │  2. Find chunks with similar meaning in vector database            │
│    │     → "P1 incidents require response within 15 minutes"           │
│    │     → "Escalation path for critical incidents is..."              │
│    │                                                                      │
│    │  3. Build prompt:                                                   │
│    │     [system prompt]                                                 │
│    │     + [retrieved chunks as context]                                │
│    │     + [user question]                                              │
│    │                                                                      │
│    │  4. Model answers using retrieved context                          │
│    │     + cites which document it got the answer from                  │
│    ▼                                                                      │
│  "Based on our SLA policy document, P1 incidents require a 15-minute   │
│   initial response time. [Source: sla-doc.md, page 3]"                 │
└────────────────────────────────────────────────────────────────────────┘
```

### Setting up a Knowledge Base — the components you need

```
┌────────────────────────────────────────────────────────────────────────┐
│               KNOWLEDGE BASE INFRASTRUCTURE COMPONENTS                  │
│                                                                          │
│  1. Amazon S3 bucket                                                    │
│     Your documents live here: PDFs, Word docs, Markdown, HTML, text    │
│                                                                          │
│  2. IAM Role for Bedrock                                                │
│     Bedrock needs permission to read from S3 and write to vector DB    │
│                                                                          │
│  3. Vector store                                                        │
│     Where the embeddings are stored and searched                        │
│     Options (cheapest to most expensive):                               │
│     • Amazon S3 Vectors — new at re:Invent 2025, up to 90% cheaper    │
│     • Amazon OpenSearch Serverless — ~$100/month minimum               │
│     • Amazon Aurora PostgreSQL — if you have RDS already               │
│                                                                          │
│  4. Embedding model                                                     │
│     Converts text to vectors. Amazon Titan Embed v2 is the default.    │
│     IMPORTANT: whichever model you choose at setup, you must use        │
│     the same model for all future ingestion AND all queries.            │
│     Changing it later means re-ingesting everything.                    │
└────────────────────────────────────────────────────────────────────────┘
```

### Creating a Knowledge Base with boto3

```python
import boto3
import time

bedrock_agent = boto3.client("bedrock-agent", region_name="us-east-1")

def create_knowledge_base(
    name: str,
    s3_bucket_arn: str,
    s3_prefix: str,
    execution_role_arn: str,
    opensearch_collection_arn: str
) -> dict:
    """
    Create a Bedrock Knowledge Base connected to an S3 bucket.
    
    Prerequisites:
    - S3 bucket with your documents uploaded
    - OpenSearch Serverless collection created (or S3 Vectors bucket)
    - IAM role with permissions to read S3 and write to OpenSearch
    """
    
    # Step 1: Create the Knowledge Base
    kb_response = bedrock_agent.create_knowledge_base(
        name=name,
        description=f"Knowledge base for {name}",
        roleArn=execution_role_arn,
        knowledgeBaseConfiguration={
            "type": "VECTOR",
            "vectorKnowledgeBaseConfiguration": {
                "embeddingModelArn": (
                    "arn:aws:bedrock:us-east-1::foundation-model/"
                    "amazon.titan-embed-text-v2:0"
                ),
                "embeddingModelConfiguration": {
                    "bedrockEmbeddingModelConfiguration": {
                        "dimensions": 1024  # must match your vector index
                    }
                }
            }
        },
        storageConfiguration={
            "type": "OPENSEARCH_SERVERLESS",
            "opensearchServerlessConfiguration": {
                "collectionArn": opensearch_collection_arn,
                "vectorIndexName": "bedrock-kb-index",
                "fieldMapping": {
                    "vectorField": "bedrock-knowledge-base-default-vector",
                    "textField": "AMAZON_BEDROCK_TEXT",
                    "metadataField": "AMAZON_BEDROCK_METADATA"
                }
            }
        }
    )
    
    kb_id = kb_response["knowledgeBase"]["knowledgeBaseId"]
    print(f"Knowledge base created: {kb_id}")
    
    # Step 2: Create a data source (S3 bucket connection)
    ds_response = bedrock_agent.create_data_source(
        knowledgeBaseId=kb_id,
        name=f"{name}-s3-source",
        dataSourceConfiguration={
            "type": "S3",
            "s3Configuration": {
                "bucketArn": s3_bucket_arn,
                "inclusionPrefixes": [s3_prefix]  # only ingest docs in this folder
            }
        },
        vectorIngestionConfiguration={
            "chunkingConfiguration": {
                # Fixed-size chunks: simple, reliable, good starting point
                # 512 tokens per chunk with 20% overlap between chunks
                # The overlap prevents losing context at chunk boundaries
                "chunkingStrategy": "FIXED_SIZE",
                "fixedSizeChunkingConfiguration": {
                    "maxTokens": 512,
                    "overlapPercentage": 20
                }
            }
        }
    )
    
    ds_id = ds_response["dataSource"]["dataSourceId"]
    print(f"Data source created: {ds_id}")
    
    # Step 3: Start an ingestion job to process documents
    ingest_response = bedrock_agent.start_ingestion_job(
        knowledgeBaseId=kb_id,
        dataSourceId=ds_id
    )
    
    job_id = ingest_response["ingestionJob"]["ingestionJobId"]
    print(f"Ingestion job started: {job_id}")
    
    # Step 4: Wait for ingestion to complete
    print("Ingesting documents", end="")
    while True:
        job_status = bedrock_agent.get_ingestion_job(
            knowledgeBaseId=kb_id,
            dataSourceId=ds_id,
            ingestionJobId=job_id
        )["ingestionJob"]["status"]
        
        if job_status == "COMPLETE":
            print(" ✓ Done")
            break
        elif job_status == "FAILED":
            raise RuntimeError("Ingestion failed — check CloudWatch logs")
        else:
            print(".", end="", flush=True)
            time.sleep(10)
    
    return {"knowledge_base_id": kb_id, "data_source_id": ds_id}
```

### Querying your Knowledge Base

Once documents are ingested, querying is simple. The `RetrieveAndGenerate` API handles the entire RAG pipeline — retrieval plus generation — in a single call.

```python
def ask_knowledge_base(
    question: str,
    knowledge_base_id: str,
    model_id: str = "us.anthropic.claude-sonnet-4-5-20251001-v1:0"
) -> dict:
    """
    Ask a question and get an answer grounded in your knowledge base documents.
    Returns the answer plus citations showing which documents it came from.
    """
    bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
    
    response = bedrock_runtime.retrieve_and_generate(
        input={"text": question},
        retrieveAndGenerateConfiguration={
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": knowledge_base_id,
                "modelArn": f"arn:aws:bedrock:us-east-1::foundation-model/{model_id}",
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "numberOfResults": 5,  # retrieve top 5 matching chunks
                    }
                },
                "generationConfiguration": {
                    "promptTemplate": {
                        # This template controls how context is presented to the model
                        # $search_results$ is replaced with retrieved chunks
                        # $output_format_instructions$ adds citation formatting
                        "textPromptTemplate": (
                            "You are a helpful assistant. Answer the question using "
                            "only the information provided in the context below. "
                            "If the context does not contain enough information to "
                            "answer the question, say so explicitly — do not guess.\n\n"
                            "Context:\n$search_results$\n\n"
                            "$output_format_instructions$\n\n"
                            "Question: "
                        )
                    }
                }
            }
        }
    )
    
    answer = response["output"]["text"]
    
    # Extract citations — which documents contributed to this answer
    citations = []
    for citation in response.get("citations", []):
        for ref in citation.get("retrievedReferences", []):
            source = ref.get("location", {}).get("s3Location", {}).get("uri", "unknown")
            excerpt = ref.get("content", {}).get("text", "")[:200]
            citations.append({
                "source": source,
                "excerpt": excerpt + "..."
            })
    
    return {
        "answer": answer,
        "citations": citations,
        "sources_used": len(citations)
    }


# Use it
result = ask_knowledge_base(
    question="What is our escalation procedure for P1 database outages?",
    knowledge_base_id="YOUR_KB_ID"
)

print(f"Answer: {result['answer']}")
print(f"\nSources used: {result['sources_used']}")
for i, citation in enumerate(result["citations"], 1):
    print(f"\n[{i}] {citation['source']}")
    print(f"    {citation['excerpt']}")
```

### What to do when RAG gives wrong answers

RAG failures are almost always one of four things:

**Documents not ingested correctly.** Check the ingestion job status. Look for warnings about failed files. PDF files with scanned images (not text) will produce empty chunks. You need the Foundation Model Parser option enabled for complex PDFs.

**Chunks too large or too small.** If your chunk size (512 tokens by default) is larger than the actual answer, the relevant content will be buried in a large chunk filled with irrelevant text. If chunks are too small, an answer that requires reading two paragraphs together will be split across multiple chunks and retrieved incompletely. Tune `maxTokens` in the chunking configuration based on your document structure.

**Query phrasing does not match document language.** The vector search finds chunks whose *meaning* is similar to the query. If your documents use formal technical language and users ask casual questions, the semantic similarity may be low. Try rewording the question using the same terminology as your documents.

**Not enough retrieved chunks.** The default `numberOfResults: 5` may not be enough for complex questions that require synthesising multiple documents. Try 8–10 for comprehensive answers.

---

## Part 6 — Your First Agent: Giving the Model the Ability to Act

A chat assistant answers questions. An agent can take actions — call APIs, query databases, send notifications, trigger workflows. The difference is tools.

### What a tool is

A tool is a function your code provides to the model. You describe what it does in plain English, define its inputs and outputs, and the model decides when to call it based on the user's request. You implement the actual function; the model decides when to invoke it.

```
┌─────────────────────────────────────────────────────────────────────┐
│               HOW TOOLS WORK — THE BASIC FLOW                        │
│                                                                       │
│  1. You define a tool with a name, description, and input schema    │
│                                                                       │
│  2. User asks: "What are the running ECS services in prod?"         │
│                                                                       │
│  3. Model thinks: "I need to call get_ecs_services to answer this"  │
│                                                                       │
│  4. Model returns a structured tool call request:                   │
│     { "tool": "get_ecs_services", "inputs": {"env": "prod"} }       │
│                                                                       │
│  5. Your code executes get_ecs_services("prod") for real            │
│                                                                       │
│  6. Your code returns the result back to the model                  │
│                                                                       │
│  7. Model reads the result and generates a natural language answer  │
│                                                                       │
│  KEY POINT: The model never directly calls AWS APIs.                │
│  Your code does. The model decides what to call and with what args. │
└─────────────────────────────────────────────────────────────────────┘
```

### A minimal agent with two tools

```python
import boto3
import json
from typing import Any

client = boto3.client("bedrock-runtime", region_name="us-east-1")

# ── Define the tools ────────────────────────────────────────────────────────

TOOLS = [
    {
        "toolSpec": {
            "name": "get_ec2_instances",
            "description": (
                "Lists EC2 instances in a specific environment (dev, staging, prod). "
                "Returns instance IDs, types, states, and names. "
                "Use this when the user asks about running servers or EC2 instances."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "environment": {
                            "type": "string",
                            "enum": ["dev", "staging", "prod"],
                            "description": "The environment to check"
                        }
                    },
                    "required": ["environment"]
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "get_cloudwatch_alarms",
            "description": (
                "Retrieves active CloudWatch alarms. "
                "Use this when the user asks about system health, alerts, or whether "
                "anything is currently alarming or degraded."
            ),
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {
                        "state": {
                            "type": "string",
                            "enum": ["OK", "ALARM", "INSUFFICIENT_DATA"],
                            "description": "Filter by alarm state. Use ALARM to see active problems."
                        }
                    },
                    "required": ["state"]
                }
            }
        }
    }
]


# ── Implement the tools (real AWS calls) ─────────────────────────────────────

def get_ec2_instances(environment: str) -> dict:
    """Real implementation — queries EC2 with a tag filter."""
    ec2 = boto3.client("ec2", region_name="us-east-1")
    
    response = ec2.describe_instances(
        Filters=[
            {"Name": "tag:Environment", "Values": [environment]},
            {"Name": "instance-state-name", "Values": ["running", "stopped"]}
        ]
    )
    
    instances = []
    for reservation in response["Reservations"]:
        for instance in reservation["Instances"]:
            name = ""
            for tag in instance.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
            
            instances.append({
                "id": instance["InstanceId"],
                "type": instance["InstanceType"],
                "state": instance["State"]["Name"],
                "name": name
            })
    
    return {
        "environment": environment,
        "instance_count": len(instances),
        "instances": instances
    }


def get_cloudwatch_alarms(state: str) -> dict:
    """Real implementation — queries CloudWatch for alarms in a given state."""
    cloudwatch = boto3.client("cloudwatch", region_name="us-east-1")
    
    response = cloudwatch.describe_alarms(StateValue=state)
    
    alarms = [
        {
            "name": alarm["AlarmName"],
            "state": alarm["StateValue"],
            "reason": alarm["StateReason"],
            "metric": alarm.get("MetricName", "N/A")
        }
        for alarm in response["MetricAlarms"]
    ]
    
    return {
        "state_filter": state,
        "alarm_count": len(alarms),
        "alarms": alarms
    }


# ── The agent loop ────────────────────────────────────────────────────────────

def run_agent(user_message: str) -> str:
    """
    A simple agent that can check EC2 instances and CloudWatch alarms.
    Implements the ReAct (Reason + Act) loop manually.
    """
    messages = [
        {"role": "user", "content": [{"text": user_message}]}
    ]
    
    system = [{
        "text": (
            "You are an AWS infrastructure assistant. "
            "Use the available tools to answer questions about the infrastructure. "
            "Always gather information before providing a summary. "
            "Be concise and precise."
        )
    }]
    
    print(f"User: {user_message}\n")
    
    for iteration in range(5):  # max 5 tool calls per query
        response = client.converse(
            modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
            system=system,
            messages=messages,
            toolConfig={"tools": TOOLS},
            inferenceConfig={"maxTokens": 1024}
        )
        
        stop_reason = response["stopReason"]
        assistant_message = response["output"]["message"]
        messages.append(assistant_message)
        
        # Model finished — return the answer
        if stop_reason == "end_turn":
            final_answer = ""
            for block in assistant_message["content"]:
                if "text" in block:
                    final_answer += block["text"]
            return final_answer
        
        # Model wants to call a tool
        if stop_reason == "tool_use":
            tool_results = []
            
            for block in assistant_message["content"]:
                if "toolUse" not in block:
                    continue
                
                tool_name = block["toolUse"]["name"]
                tool_input = block["toolUse"]["input"]
                tool_use_id = block["toolUse"]["toolUseId"]
                
                print(f"  → Calling tool: {tool_name}({json.dumps(tool_input)})")
                
                # Execute the tool
                try:
                    if tool_name == "get_ec2_instances":
                        result = get_ec2_instances(**tool_input)
                    elif tool_name == "get_cloudwatch_alarms":
                        result = get_cloudwatch_alarms(**tool_input)
                    else:
                        result = {"error": f"Unknown tool: {tool_name}"}
                    
                    print(f"     Result: {result['instance_count'] if 'instance_count' in result else result['alarm_count']} items found")
                    
                    tool_results.append({
                        "toolUseId": tool_use_id,
                        "content": [{"json": result}]
                    })
                    
                except Exception as e:
                    # Return error to the model — it can handle tool failures gracefully
                    tool_results.append({
                        "toolUseId": tool_use_id,
                        "content": [{"text": f"Error: {str(e)}"}],
                        "status": "error"
                    })
            
            # Send tool results back to the model
            messages.append({
                "role": "user",
                "content": [{"toolResult": r} for r in tool_results]
            })
    
    return "Could not complete the request within the allowed number of steps."


# Use it
print("=" * 60)
answer = run_agent("Are there any active alarms in our infrastructure, and how many prod servers are running?")
print(f"\nAgent: {answer}")
```

---

## Part 7 — Guardrails: Making It Safe for Production

Guardrails are Bedrock's policy enforcement layer. They are not optional for production systems that external users interact with. They protect against:

- Users trying to make the model do things outside its intended scope
- The model generating harmful, inaccurate, or policy-violating content
- PII (personal data) appearing in responses when it shouldn't

```
┌────────────────────────────────────────────────────────────────────┐
│            WHAT GUARDRAILS INTERCEPT                                 │
│                                                                      │
│  User input                                                          │
│      │                                                               │
│      ▼  ← Guardrail checks INPUT                                    │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Is this input asking about a blocked topic?                 │  │
│  │  Does it contain a prompt injection attempt?                 │  │
│  │  Does it contain PII that should be redacted?               │  │
│  └──────────────────────────────────────────────────────────────┘  │
│      │  (if blocked → return canned response, no model call)        │
│      ▼  (if allowed → model inference runs)                         │
│      │                                                               │
│      ▼  ← Guardrail checks OUTPUT                                   │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Does the response contain harmful content?                  │  │
│  │  Is the response grounded in the provided context?          │  │
│  │  Does it contain PII it should not be exposing?             │  │
│  └──────────────────────────────────────────────────────────────┘  │
│      │  (if blocked → replace with safe message)                    │
│      ▼  (if allowed → return to user)                               │
│  User receives response                                              │
└────────────────────────────────────────────────────────────────────┘
```

```python
import boto3

bedrock = boto3.client("bedrock", region_name="us-east-1")

# Create a guardrail for a customer support assistant
guardrail_response = bedrock.create_guardrail(
    name="customer-support-guardrail",
    description="Guardrail for customer-facing support assistant",
    
    # Topics the model should refuse to discuss
    topicPolicyConfig={
        "topicsConfig": [
            {
                "name": "competitor-comparison",
                "definition": "Questions asking to compare our products with competitors or recommend competitors",
                "examples": [
                    "Is AWS better than Azure?",
                    "Should I use GCP instead of AWS?"
                ],
                "type": "DENY"
            },
            {
                "name": "pricing-commitments",
                "definition": "Questions asking for specific price quotes or discounts",
                "type": "DENY"
            }
        ]
    },
    
    # Content filters — thresholds for harmful content
    contentPolicyConfig={
        "filtersConfig": [
            # NONE / LOW / MEDIUM / HIGH — how strictly to filter
            {"type": "HATE",     "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "VIOLENCE", "inputStrength": "MEDIUM", "outputStrength": "HIGH"},
            {"type": "SEXUAL",   "inputStrength": "HIGH", "outputStrength": "HIGH"},
            {"type": "INSULTS",  "inputStrength": "MEDIUM", "outputStrength": "MEDIUM"}
        ]
    },
    
    # PII detection — detect personal data and block or redact it
    sensitiveInformationPolicyConfig={
        "piiEntitiesConfig": [
            {"type": "EMAIL",         "action": "ANONYMIZE"},  # replace with [EMAIL]
            {"type": "PHONE",         "action": "ANONYMIZE"},
            {"type": "CREDIT_DEBIT_CARD_NUMBER", "action": "BLOCK"},  # block entire response
            {"type": "US_SOCIAL_SECURITY_NUMBER", "action": "BLOCK"}
        ]
    },
    
    # Custom message shown to users when a guardrail blocks a request
    blockedInputMessaging=(
        "I'm not able to help with that request. "
        "Please contact sales@company.com for pricing questions."
    ),
    blockedOutputsMessaging=(
        "I was unable to generate a suitable response. "
        "Please rephrase your question or contact support."
    )
)

guardrail_id = guardrail_response["guardrailId"]
print(f"Guardrail created: {guardrail_id}")


# Create a version (required before attaching to production traffic)
version_response = bedrock.create_guardrail_version(
    guardrailIdentifier=guardrail_id,
    description="Initial production version"
)

guardrail_version = version_response["version"]
print(f"Guardrail version: {guardrail_version}")


# Use the guardrail in inference
bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")

response = bedrock_runtime.converse(
    modelId="us.anthropic.claude-sonnet-4-5-20251001-v1:0",
    messages=[{"role": "user", "content": [{"text": "Is Azure cheaper than AWS?"}]}],
    guardrailConfig={
        "guardrailIdentifier": guardrail_id,
        "guardrailVersion": guardrail_version,
        "trace": "enabled"  # returns details of what the guardrail did
    }
)

# Check if guardrail intervened
if response.get("stopReason") == "guardrail_intervened":
    print("Guardrail blocked this request")
    # The response will contain the blockedInputMessaging text
else:
    print(response["output"]["message"]["content"][0]["text"])
```

---

## Part 8 — The Architecture Decision Map

As your requirements grow, here is how to choose the right Bedrock components:

```
┌───────────────────────────────────────────────────────────────────────────┐
│         BEDROCK COMPONENT SELECTION GUIDE                                  │
│                                                                             │
│  What do you need?                                                          │
│  │                                                                          │
│  ├── Just AI text generation                                                │
│  │   → Converse API + inference profiles                                   │
│  │   → Tools: boto3, bedrock-runtime client                                │
│  │                                                                          │
│  ├── AI + your private data (internal docs, knowledge base)                │
│  │   → Bedrock Knowledge Bases + RetrieveAndGenerate                       │
│  │   → Storage: S3 Vectors (cheap) or OpenSearch Serverless (fast)        │
│  │   → Embedding: Amazon Titan Embed v2                                    │
│  │                                                                          │
│  ├── AI that takes actions (calls APIs, queries databases)                 │
│  │   → Converse API with tool_use (manual control)                        │
│  │   → OR Strands SDK (higher-level abstraction)                          │
│  │                                                                          │
│  ├── AI product used by external users (safety + compliance)               │
│  │   → Add Bedrock Guardrails to every inference call                     │
│  │   → Configure topic denial, content filters, PII detection             │
│  │                                                                          │
│  └── Production scale (many users, persistent memory, observability)       │
│      → AgentCore Runtime + Memory + Gateway + Observability               │
│      → Framework: Strands (AWS-native) or LangGraph/CrewAI (custom)       │
│                                                                             │
│  ADD TO EVERYTHING IN PRODUCTION:                                          │
│  ✓ Cross-region inference profiles (us. prefix) for rate limit resilience │
│  ✓ Token usage logging for cost monitoring                                 │
│  ✓ Error handling for ThrottlingException with exponential backoff         │
│  ✓ Guardrails for any user-facing surface                                  │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Part 9 — Five Mistakes That Will Cost You Time and Money

**Mistake 1 — Not logging token usage.** Every call to Bedrock has a token cost. Without logging `response["usage"]["inputTokens"]` and `outputTokens` on every call, you will have no visibility into your costs until the AWS bill arrives. Log tokens from day one. Set a CloudWatch billing alarm.

**Mistake 2 — Sending full conversation history without limits.** A multi-turn conversation where you send the full history on every call will have costs that grow quadratically. A 20-message conversation sends roughly 10× more tokens than a 2-message conversation. Implement a history limit (keep last N messages) or summarise old history periodically.

**Mistake 3 — Confusing Bedrock's two SDKs.** `bedrock` client (boto3) = control plane, for managing resources: creating knowledge bases, guardrails, model evaluation jobs. `bedrock-runtime` client = inference plane, for calling models. First-time errors almost always come from using `bedrock` when you need `bedrock-runtime` or vice versa.

**Mistake 4 — Choosing a vector store before understanding your query volume.** Amazon OpenSearch Serverless costs roughly $100/month at baseline even with zero queries. For a prototype or low-volume internal tool, S3 Vectors is dramatically cheaper. For a high-QPS production system, OpenSearch is worth the cost. Do not default to OpenSearch because it is mentioned first in the docs.

**Mistake 5 — Treating the model as a reliable fact source without grounding.** Foundation models will confidently generate plausible-sounding but incorrect information, especially about your specific internal systems. Any answer about your company's data, procedures, or systems needs to come from a Knowledge Base with grounding enabled, not from the model's training data. Never deploy a customer-facing assistant that answers from model memory alone.

---

## What to Build Next

Now that you have the foundations, here is a natural learning path:

**Build a document Q&A tool for your team.** Upload your team's runbooks, architecture docs, and SOPs to S3. Create a Knowledge Base pointing at that bucket. Build a simple chat interface on top of `RetrieveAndGenerate`. This is the highest-ROI first Bedrock project for most DevOps teams.

**Add an agent that reads from your monitoring stack.** Extend the simple agent from Part 6 to query CloudWatch metrics, pull recent deployment history from CodeDeploy, and check ECS service health. Now you have an AI assistant that can answer "is anything broken right now?" with actual data.

**Move to Strands for cleaner agent code.** The manual ReAct loop in Part 6 is educational but verbose. Install the Strands SDK (`pip install strands-agents strands-agents-tools`) and rewrite the agent using the `@tool` decorator. The code will be half the length and easier to extend.

**Read the advanced article in this series.** The companion article covers the full production architecture: AgentCore Runtime for scaling agents to multiple users, multi-agent supervisor patterns, persistent memory across sessions, and the ten production insights that only emerge at scale.

---

## Reference Cheat Sheet

```python
# ── Create the clients ─────────────────────────────────────────────────────
import boto3

bedrock         = boto3.client("bedrock", region_name="us-east-1")         # control plane
bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1") # inference
bedrock_agent   = boto3.client("bedrock-agent", region_name="us-east-1")   # KB/agent mgmt
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime", region_name="us-east-1") # KB query

# ── Inference ──────────────────────────────────────────────────────────────
response = bedrock_runtime.converse(modelId=..., messages=[...])
response = bedrock_runtime.converse_stream(modelId=..., messages=[...])  # streaming

# ── Knowledge Base ─────────────────────────────────────────────────────────
response = bedrock_agent_runtime.retrieve(knowledgeBaseId=..., retrievalQuery={"text": ...})
response = bedrock_agent_runtime.retrieve_and_generate(input={"text": ...}, ...)

# ── Useful model IDs (2025) ────────────────────────────────────────────────
# Cross-region inference profiles (us. prefix) — use these in production
CLAUDE_SONNET  = "us.anthropic.claude-sonnet-4-5-20251001-v1:0"  # workhorse
CLAUDE_HAIKU   = "us.anthropic.claude-haiku-4-5-20251001-v1:0"   # fast + cheap
NOVA_PRO       = "us.amazon.nova-pro-v1:0"                         # AWS-native, complex
NOVA_LITE      = "us.amazon.nova-lite-v1:0"                        # AWS-native, cheap
TITAN_EMBED    = "amazon.titan-embed-text-v2:0"                    # for RAG / embeddings

# ── Temperature guide ─────────────────────────────────────────────────────
# 0.0 — Deterministic: code gen, data extraction, structured output
# 0.3 — Balanced: technical Q&A, summarisation, analysis
# 0.7 — Creative: writing, brainstorming, content generation
# 1.0 — Unpredictable: rarely useful in production

# ── Error codes to handle ──────────────────────────────────────────────────
# ThrottlingException     — rate limit, retry with exponential backoff
# AccessDeniedException   — IAM permissions missing
# ValidationException     — malformed request (wrong schema, invalid model ID)
# ModelNotReadyException  — model not enabled in your account (check Model access)
# ServiceQuotaExceededException — account-level quota, request increase via Support
```

---

*All code validated against boto3 1.35+, Python 3.10+. Model IDs use the 2025 cross-region inference profile naming convention. Enable model access in the Bedrock console before running any inference code.*
