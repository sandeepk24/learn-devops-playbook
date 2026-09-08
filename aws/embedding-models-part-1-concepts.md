# Embedding Models, Part 1 — The Concepts

> **Who this is for:** You've deployed a Bedrock Knowledge Base, you've seen "embedding model" as a dropdown you picked once and never thought about again, and you want to actually understand what that component is doing — because when search results turn out unhelpful, "the embedding model" is usually where the investigation ends up. This guide opens the box. Part 1 is the theory: what an embedding actually is, how these models get trained, and what the choices on the AWS Bedrock model list mean in practice. From there: [Part 2](./embedding-models-part-2-choosing-a-model.md) covers picking a model and testing whether it actually works, [Part 3](./embedding-models-part-3-using-and-deploying.md) covers calling one from code and where to run it, and [Part 4](./embedding-models-part-4-running-in-production.md) covers keeping it healthy once it's live.

---

## 1. The one-sentence definition, explained

An embedding model takes a piece of text (or an image, or audio) and outputs a fixed-length list of numbers — a **vector** — that represents its *meaning*. That's it. Everything else in this document is elaboration on that sentence.

```
"The pod is stuck in CrashLoopBackOff"
        │
        ▼
  [ Embedding Model ]
        │
        ▼
[0.0142, -0.0891, 0.1033, ..., 0.0067]   ← 1024 numbers (for Titan v2)
```

The critical property, and the entire reason any of this is useful: **texts with similar meaning produce vectors that are numerically close together**, regardless of whether they share any words at all.

```
"The pod is stuck in CrashLoopBackOff"     →  vector A
"Container keeps restarting and failing"   →  vector B   (close to A — 0 shared words!)
"What's for lunch today?"                  →  vector C   (far from A and B)
```

Compare that to older keyword search (think Elasticsearch's default BM25): it matches on literal tokens. "CrashLoopBackOff" and "container keeps restarting" share zero words, so keyword search misses the connection entirely. Embeddings capture the *semantic* relationship. This is the single fact that justifies the entire RAG architecture you built in the Knowledge Bases guide — retrieval by meaning, not by string match.

## 2. Where the vector space comes from

It's worth resisting the urge to treat this as magic. Here's the mechanism, compressed to what you need operationally.

An embedding model is a neural network — almost always a **transformer encoder** (the same family of architecture behind BERT, and a cousin of the decoder-only transformers that power Claude and GPT). It's trained with a straightforward objective: given a large corpus of paired or related texts, adjust the network's weights so that related pairs end up close together in vector space and unrelated pairs end up far apart.

Concretely, training typically uses **contrastive learning**:

1. Take a batch of texts, some known to be related (a question and its answer, a sentence and its paraphrase, a title and its article body).
2. Run each through the model to get a vector.
3. Compute a loss that *pulls* related pairs' vectors together and *pushes* unrelated pairs' vectors apart.
4. Backpropagate, adjust weights, repeat — across millions to billions of pairs.

After training, the model has learned a **geometry** where distance encodes semantic relationship. Nobody designed that geometry by hand; it emerged from the training data. This matters practically: an embedding model trained mostly on English news and Wikipedia will be mediocre at embedding Python stack traces or Kubernetes YAML, because it never learned a useful geometry for that kind of text. This is why domain-specific benchmarking (Part 2) isn't optional — the model that tops a leaderboard on general text can genuinely underperform on your logs.

## 3. Vectors, dimensions, and what "1024-dimensional" actually means

Each embedding is a fixed-length array of floating-point numbers — the **dimensionality**. Common sizes: 384, 768, 1024, 1536, 3072.

You cannot visualize a 1024-dimensional space, and you shouldn't try. But the 2D/3D intuition still transfers loosely: more dimensions generally mean more capacity to encode nuance, at the cost of more storage and slower similarity search. This is a real, tunable trade-off, not just a number to copy from a tutorial:

| Dimensionality | Storage per 1M vectors (float32) | Typical use case |
|---|---|---|
| 384 | ~1.5 GB | Lightweight, high-QPS search, mobile/edge |
| 768 | ~3 GB | General-purpose default (BERT-era standard) |
| 1024 | ~4 GB | Strong general quality (Titan v2, Cohere default) |
| 1536–3072 | ~6–12 GB | Maximum quality, higher cost, slower ANN search |

**Matryoshka embeddings** are worth knowing about: some newer models (Titan Text Embeddings V2, OpenAI's `text-embedding-3` family) are trained so that *truncating* the vector — just taking the first 256 or 512 numbers instead of all 1024 — still yields a usable, if slightly lower-quality, embedding. This lets you trade quality for storage/speed at query time without retraining or re-embedding anything, by simply asking the API for a shorter output dimension. It's the practical reason Titan v2 offers 256 / 512 / 1024 as selectable output dimensions.

## 4. Measuring "closeness": distance metrics

Given two vectors, how do you quantify how "close" they are? Three metrics dominate:

**Cosine similarity** — measures the *angle* between two vectors, ignoring their magnitude. Ranges from -1 (opposite) to 1 (identical direction). This is the default for almost every text embedding use case, because it makes comparisons insensitive to how "long" the text was.

**Dot product** — like cosine similarity but *does* factor in magnitude. Some models (notably ones trained with dot-product loss) are calibrated specifically for this metric, and using cosine instead can give subtly wrong rankings. Always check the model card for which metric it was trained against.

**Euclidean (L2) distance** — straight-line distance in the vector space. Common in general ML but less common for text embeddings specifically; more prevalent in image embedding pipelines.

Getting the wrong metric for a given model is a real, quiet failure mode: results still come back, scores still look plausible, but ranking quality is worse than it should be. When you configure a vector store (OpenSearch, pgvector, Neptune), you explicitly set the distance metric per index — it does not auto-detect from the embedding model. Mismatch this against the model's training objective and you've built a system that silently underperforms with no error message anywhere.

## 5. Embedding models are not one thing — the taxonomy

"Embedding model" is an umbrella term covering several genuinely different tools. Picking the wrong category is a bigger mistake than picking the wrong model within a category.

### 5.1 Dense embeddings
What we've described so far — every dimension has a value, vectors are compared by cosine/dot-product similarity. This is what Bedrock's Titan and Cohere Embed models produce, and what powers the vast majority of RAG systems. Strong at semantic/conceptual matching, weaker on exact-term matching (an embedding model may consider "error code 500" and "error code 503" quite similar, when for your purposes they're completely different tickets).

### 5.2 Sparse embeddings
Vectors that are mostly zeros, with a handful of dimensions corresponding roughly to specific terms or concepts (think: a smarter, learned version of TF-IDF). Models like SPLADE produce these. They're excellent at exact-term matching — which is precisely dense embeddings' weak spot — and this complementary strength is why **hybrid search** (dense + sparse/keyword, merged and reranked) consistently outperforms either alone in real systems, especially in domains full of exact identifiers: error codes, part numbers, service names, CVE IDs.

### 5.3 Multi-vector / late-interaction models (ColBERT-style)
Instead of collapsing a whole document into one vector, these keep a vector *per token* and compare query tokens against document tokens at search time. Higher retrieval quality, especially on long documents, at real cost in storage and compute. Not currently a first-class Bedrock offering — you'd self-host this.

### 5.4 Multimodal embeddings
Models like Titan Multimodal Embeddings put images and text into the *same* vector space, so you can search images with a text query or vice versa. Different training objective (usually contrastive learning across image-caption pairs, in the CLIP tradition), different use cases: product search, visual similarity, image-and-text RAG.

### 5.5 Instruction-tuned / task-aware embeddings
Some newer models (Cohere Embed v3+, several open-source entries) accept a "task instruction" alongside the text — e.g., telling the model *"this is a search query"* versus *"this is a document to be searched"* — and generate different embeddings accordingly, because asymmetric search (short query, long document) benefits from encoding them differently. Ignoring this and treating queries and documents identically is a common, quiet quality bug.

## 6. Symmetric vs. asymmetric search — the distinction that breaks people

This deserves its own section because it's the most common conceptual mistake.

**Symmetric search**: query and documents are similar in length and structure. "Find me a duplicate of this sentence" is symmetric.

**Asymmetric search**: a short query against long documents — exactly what RAG does. "What's our rollback procedure?" (6 words) against a 400-word runbook chunk.

A model trained/tuned for symmetric search can perform noticeably worse on the asymmetric case your Knowledge Base actually runs, because a short query and a long passage don't naturally land close together in vector space even when the passage answers the query well — the length mismatch itself works against you. This is exactly what instruction-tuned models (§5.5) and models with explicit `search_query` vs. `search_document` input types (Cohere Embed) are built to correct. If you're evaluating a model, test it on your *actual* query-vs-chunk shape, not on sentence-pair benchmarks that look symmetric.

## 7. The Bedrock embedding model lineup

As of this writing, Bedrock's embedding options are:

| Model | Dimensions | Notable properties |
|---|---|---|
| **Amazon Titan Text Embeddings V2** | 256 / 512 / 1024 (selectable, Matryoshka) | AWS-native, strong multilingual support, the default "just works" choice |
| **Amazon Titan Multimodal Embeddings** | 384 / 1024 | Joint text+image space |
| **Cohere Embed (English / Multilingual)** | 1024 | Explicit `input_type` parameter for query vs. document vs. classification vs. clustering asymmetry |

Verify current model IDs and regional availability in the Bedrock console before committing — Bedrock's model catalog changes faster than any static doc can track, and this is exactly the kind of "current state" fact worth checking rather than assuming.

## 8. What embeddings are for, beyond RAG retrieval

Treating "embedding model" as synonymous with "the thing inside my Knowledge Base" undersells it. The same vectors power a family of adjacent capabilities you'll likely be asked about:

- **Semantic search** — the RAG case: find the most relevant chunks for a query.
- **Clustering** — group similar documents/logs/tickets without predefined categories (k-means or HDBSCAN over embeddings). Useful for "what are our support tickets actually about" style analysis.
- **Classification** — embed text, then train a lightweight classifier (even logistic regression) on top of the vectors instead of fine-tuning a whole LLM. Cheap and often surprisingly effective.
- **Deduplication / near-duplicate detection** — flag documents whose embeddings are near-identical, useful for cleaning a corpus before it goes into a Knowledge Base.
- **Anomaly detection** — a log line whose embedding is far from every cluster centroid is, definitionally, unusual. This is a legitimate lightweight alternative to hand-written anomaly rules.
- **Recommendation** — "more like this" by nearest-neighbor search over embeddings of items a user engaged with.

Recognizing these as the same underlying primitive means you don't need a different tool every time one of these problems shows up — you likely already have the infrastructure.

## 9. Quantization — the cost lever most people don't know exists

Storing a million 1024-dimensional float32 vectors costs about 4 GB. Two techniques shrink that substantially, at some quality cost:

- **Scalar quantization** — store each dimension as an int8 instead of a float32 (4x smaller), by mapping the float range to a smaller integer range. Modest quality loss, large storage/speed win, and it's a checkbox in OpenSearch Serverless and most modern vector stores.
- **Product quantization** — split the vector into sub-vectors, cluster each sub-vector space independently, and store cluster IDs instead of raw values. More aggressive compression (10–30x), more quality loss, more tuning complexity. Common in FAISS-based self-hosted setups; less commonly exposed as a simple toggle in managed AWS vector stores today.

This matters operationally the moment your corpus crosses from "demo with 500 documents" to "every runbook, postmortem, and design doc the org has ever written" — at that scale, the vector store's storage and query-latency bill is driven directly by the dimensionality and quantization choices made back in Part 1's §3, which is exactly why that choice deserves more thought than "leave it on default."

---

**Continue to [Part 2 — Picking a Model and Checking It Actually Works](./embedding-models-part-2-choosing-a-model.md):** why the public leaderboards only get you partway there, how to build a small test using your own real questions, and when it's actually worth training a custom model instead of using an existing one.
