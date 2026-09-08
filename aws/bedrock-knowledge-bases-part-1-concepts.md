# Amazon Bedrock Knowledge Bases, Part 1 — The Concepts

> **Who this is for:** You know your way around AWS — IAM, S3, maybe some ECS/EKS — but "Knowledge Base" and "RAG" are words you've mostly seen in Slack threads. This two-part guide takes you from zero to a working, automated Knowledge Base. Part 1 builds the mental model: what a Knowledge Base actually is under the hood and how it plugs into Bedrock. [Part 2](./bedrock-knowledge-bases-part-2-building-and-connecting.md) covers standing one up and wiring it into an application.

---

## 1. The problem Knowledge Bases solve

A foundation model like Claude or Amazon Nova knows what it learned during training. That knowledge has two hard limits:

1. **It's frozen in time.** The model has no idea what changed after its training cutoff.
2. **It's generic.** It has never seen your runbooks, your Confluence pages, your incident postmortems, or your internal API docs.

So when someone asks the model *"What's our rollback procedure for the payments service?"*, the model either says "I don't know" or — worse — invents a plausible-sounding answer. Neither is acceptable in production.

You have two broad ways to fix this:

| Approach | What it means | When it makes sense |
|---|---|---|
| **Fine-tuning** | Retrain the model's weights on your data | Changing the model's *behavior or style*; expensive, slow, data goes stale |
| **RAG (Retrieval-Augmented Generation)** | Leave the model alone; fetch relevant documents at query time and paste them into the prompt | Giving the model *facts*; cheap, updatable in minutes, auditable |

For "make the model answer questions about our stuff," RAG wins almost every time. A **Knowledge Base is AWS's managed implementation of the retrieval half of RAG.**

## 2. What RAG actually does, step by step

Strip away the acronym and RAG is a simple pipeline:

1. **Ingest:** Take your documents (PDFs, Markdown, HTML, Confluence exports, whatever).
2. **Chunk:** Split them into pieces small enough to be useful — a 200-page PDF is useless as one blob, so you cut it into chunks of a few hundred tokens each.
3. **Embed:** Run each chunk through an *embedding model*, which converts text into a vector — a long list of numbers (e.g., 1,024 floats) that encodes the chunk's *meaning*. Chunks about "database failover" end up numerically close to each other; chunks about "holiday party planning" end up far away.
4. **Store:** Put those vectors into a *vector database* that can answer "give me the N vectors closest to this one" very fast.
5. **Retrieve (at query time):** When a user asks a question, embed the *question* with the same model, find the nearest chunks, and pull the original text back out.
6. **Generate:** Hand the model a prompt that says, roughly, *"Using only these excerpts, answer this question."* The model now answers from your documents instead of its imagination, and you can cite exactly which chunk each claim came from.

Every RAG system on earth — LangChain, LlamaIndex, homegrown scripts — is some flavor of this pipeline. The difference is who operates it.

## 3. Where Bedrock fits

Amazon Bedrock is AWS's managed service for foundation models: one API in front of Claude (Anthropic), Nova (Amazon), Llama (Meta), Mistral, and others. No GPUs to manage, IAM-native auth, per-token billing.

**Bedrock Knowledge Bases** is the feature inside Bedrock that runs steps 1–5 of the RAG pipeline *for* you:

- You point it at a **data source** (S3 bucket, Confluence, SharePoint, Salesforce, a web crawler, or custom).
- You pick an **embedding model** (Titan Text Embeddings v2 and Cohere Embed are the usual choices).
- You pick (or let it create) a **vector store**.
- You hit **Sync**, and it chunks, embeds, and indexes everything.
- At query time you call one API and get back either raw chunks (`Retrieve`) or a finished, cited answer (`RetrieveAndGenerate`).

The thing to internalize as a DevOps engineer: **a Knowledge Base is not a database you write to. It's a managed indexing pipeline plus a query API.** The source of truth stays in S3 (or Confluence, etc.); the KB is a derived, rebuildable index — much like a search index or a read replica. If it's ever wrong or corrupted, you re-sync from source. That mental model drives every operational decision you'll make.

## 4. The moving parts, named precisely

When you create a Knowledge Base, you're really assembling five components:

```
┌─────────────────────────────────────────────────────────────┐
│                    Knowledge Base (the resource)             │
│                                                              │
│  ┌────────────┐   ┌──────────┐   ┌───────────┐   ┌────────┐ │
│  │ Data Source │──▶│ Chunking │──▶│ Embedding │──▶│ Vector │ │
│  │ (S3, etc.)  │   │ strategy │   │  model    │   │ store  │ │
│  └────────────┘   └──────────┘   └───────────┘   └────────┘ │
│         ▲                                             │      │
│         │            (Sync / Ingestion Job)           │      │
└─────────┼─────────────────────────────────────────────┼──────┘
          │                                             ▼
   Your documents                              Retrieve /
   (source of truth)                        RetrieveAndGenerate
```

**Data source.** Where documents live. S3 is the workhorse. One KB can have multiple data sources. Supported file types include PDF, TXT, MD, HTML, DOCX, CSV, XLSX — with size limits per file (50 MB is the common ceiling; check current quotas).

**Chunking strategy.** Set per data source at creation time (changing it later means recreating the data source):
- *Fixed-size* — every N tokens with overlap. Dumb but predictable.
- *Default* — ~300-token chunks. Fine for prototyping.
- *Hierarchical* — small child chunks for precise matching, larger parent chunks returned for context. Good for long structured docs.
- *Semantic* — splits at meaning boundaries. Better quality, more embedding cost.
- *None* — one file = one chunk. Only if you pre-chunk yourself.
- *Custom (Lambda)* — you write the chunking logic. Escape hatch for weird formats.

**Embedding model.** Locked in at KB creation. You cannot swap it later — switching models means a new KB and full re-embedding, because vectors from different models live in incompatible spaces. This is the closest thing a KB has to an irreversible decision, so note it in your design doc.

**Vector store.** Where vectors live. Your options:
- **Amazon OpenSearch Serverless** — the default "quick create" path. Solid, but the serverless OCU billing has a cost floor that surprises people on small projects.
- **S3 Vectors** — newer, cheapest option for large, latency-tolerant workloads.
- **Amazon Aurora PostgreSQL (pgvector)** — great if your team already runs Postgres; you can join vector search with relational data.
- **Pinecone, Redis Enterprise Cloud, MongoDB Atlas** — third-party options if you're already invested there.
- **Amazon Neptune Analytics** — used for GraphRAG, where the KB also builds a graph of entities and relationships across documents.

**Sync (ingestion job).** The batch job that diffs the data source against the index, then chunks/embeds/upserts what changed. Syncs are incremental — it doesn't re-embed the whole corpus every time. **Nothing updates automatically when you drop a file in S3.** Until a sync runs, queries serve the old index. In practice you trigger syncs from EventBridge (on S3 object events, debounced) or on a schedule. This is the piece most likely to be *your* job to automate.

## 5. The two query APIs

**`Retrieve`** — "just give me the chunks." Returns the top-K matching text excerpts with scores and source URIs. Use this when your application (or an agent framework like LangGraph) wants to control the prompt itself.

**`RetrieveAndGenerate`** — "give me the answer." Bedrock retrieves the chunks, builds the prompt, calls a model of your choosing, and returns a generated answer with citations back to the source documents. Fastest path to a working Q&A feature; less control over the prompt.

There's a third integration worth knowing: **Bedrock Agents** (and the newer AgentCore tools) can attach a Knowledge Base as a tool, so an agent decides *on its own* when to consult your documents mid-task. Same KB, different consumer.

## 6. Retrieval quality knobs you'll actually touch

- **Search type:** *Semantic* (pure vector similarity) vs. *Hybrid* (vector + keyword). Hybrid usually wins when queries contain exact terms — error codes, service names, ticket IDs — because embeddings are fuzzy about exact strings.
- **Number of results (top-K):** More chunks = more context = more tokens = more cost and more noise. 5 is a common starting point; tune with real queries.
- **Metadata filtering:** Alongside each document in S3 you can place a `<filename>.metadata.json` sidecar file with attributes (`{"team": "payments", "doc_type": "runbook"}`). At query time you filter on those attributes — retrieval only searches matching chunks. This is how you do multi-tenancy or scope queries per environment *inside one KB*.
- **Reranking:** An optional second-pass model that reorders retrieved chunks by relevance before they hit the LLM. Costs a little latency, often noticeably improves answers.

## 7. What it costs (the shape, not the numbers)

Prices change; the *structure* doesn't:

1. **Embedding tokens** — you pay the embedding model per token during sync. Re-embedding a large corpus is the expensive event, which is another reason the incremental sync matters.
2. **Vector store** — OpenSearch Serverless bills OCUs continuously (this is usually the biggest line item for small workloads); Aurora bills as normal Aurora; S3 Vectors bills storage + requests.
3. **Generation tokens** — every `RetrieveAndGenerate` call pays normal model pricing for input (your question **plus all retrieved chunks**) and output. Retrieval inflates input tokens — that's the hidden multiplier people miss when estimating.
4. **Extras** — reranking calls, GraphRAG's Neptune costs, Lambda for custom chunking.

---


---

**Continue to [Part 2 — Building and Connecting One](./bedrock-knowledge-bases-part-2-building-and-connecting.md):** console walkthrough, Python (boto3) examples for sync and both query APIs, the two IAM roles everyone confuses, a Terraform sketch, and the operational habits that keep a KB trustworthy.
