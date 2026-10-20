# Search Systems

Databases are not search engines. A `LIKE '%keyword%'` query does a full table scan. A `WHERE name = 'exact match'` with a B-tree index is fast but inflexible. Neither handles typos, synonyms, relevance ranking, or faceted filtering at scale. When users type into a search box, they expect results that make sense — not results that technically match a string literal.

Search systems solve a different problem than databases. They're optimized for finding relevant documents across large corpora, ranking them by relevance, and doing it fast. The trade-off: they're not your primary data store. They're a read-optimized projection of data that lives in a source-of-truth database, kept in sync by a pipeline you have to build and maintain.

## Fundamentals

### The inverted index

The data structure that makes full-text search fast.

A relational database index maps a column value to a row. An inverted index maps a term to the list of documents containing it. Searching for "kubernetes" looks up that term in the index and retrieves the document list directly — no scan.

Building the inverted index: text is tokenized into terms, normalized (lowercased, stemmed — "running" → "run"), and indexed. "AWS CloudWatch metrics for EKS clusters" tokenizes to `{aws, cloudwatch, metric, eks, cluster}`. Each term maps to the document ID. Later, looking up "metrics clusters eks" retrieves all three term lists and intersects them.

```
Document corpus:
  Doc 1: "AWS CloudWatch metrics for EKS"
  Doc 2: "EKS cluster autoscaling"
  Doc 3: "CloudWatch alarms and metrics"

Inverted index (simplified):
  aws       → [Doc 1]
  cloudwatch → [Doc 1, Doc 3]
  metric    → [Doc 1, Doc 3]
  eks       → [Doc 1, Doc 2]
  cluster   → [Doc 2]
  autoscal  → [Doc 2]
  alarm     → [Doc 3]

Query "cloudwatch metrics":
  cloudwatch → [Doc 1, Doc 3]
  metric     → [Doc 1, Doc 3]
  intersection → [Doc 1, Doc 3], ranked by relevance score
```

### Relevance scoring

Not all matching documents are equally relevant. TF-IDF (term frequency–inverse document frequency) is the classical relevance formula.

**Term frequency (TF):** how often the query term appears in the document. A document mentioning "kubernetes" fifteen times is probably more about Kubernetes than one mentioning it once.

**Inverse document frequency (IDF):** how rare the term is across the corpus. "The" appears in every document — finding it tells you nothing. "Karpenter" appears in few documents — finding it is highly informative. IDF down-weights common terms and up-weights rare ones.

BM25 (Best Match 25) is the practical successor to TF-IDF, used by Elasticsearch and OpenSearch. It adds document length normalization — a short document where the term appears twice is more relevant than a long document where it appears twice.

Beyond BM25, modern search systems incorporate vector search — embedding queries and documents in a semantic vector space, finding relevant documents by proximity rather than exact term match. "Kubernetes pod scheduling" and "container orchestration placement" are semantically similar but share no terms. Vector search handles this; BM25 doesn't.

### Analyzers

The pipeline that transforms raw text into indexed terms. Crucial and often overlooked.

A standard analyzer: lowercase → tokenize on whitespace/punctuation → apply stop word filter (remove "the", "a", "and") → apply stemmer (reduce words to root form).

Incorrect analyzer configuration causes queries to not match documents they should. A case-sensitive index won't match "CloudWatch" when the user types "cloudwatch." An index without stemming won't match "deploying" when the document says "deployment." An index with aggressive stemming might match "container" when the user searches "contain."

The analyzer at index time and the analyzer at query time must be consistent. Using different analyzers produces mismatches where indexed terms and query terms don't align, resulting in no results for queries that should return results.

## Operations

### Keeping the index in sync

The search index is a derived view of source data. When source data changes, the index needs to update. Three patterns:

**Synchronous dual-write.** Application writes to the database and the search index in the same request. Simple. Brittle — if the index write fails, the database has the record but search doesn't. Not atomic.

**Change data capture (CDC).** A stream reader watches the database write-ahead log or binlog. Every insert, update, and delete produces an event. The indexer consumes events and updates the search index. Decoupled from the application write path. Reliable — the CDC stream is the source of truth for what changed. Adds latency — search index updates lag the database by the CDC pipeline latency (typically seconds).

**Periodic bulk reindex.** A scheduled job queries the database and reindexes all records. Simple to implement. Poor freshness — changes made between runs aren't searchable. Appropriate only for data that changes infrequently or where search staleness is acceptable.

CDC is the right choice for most production systems that require near-real-time search freshness.

### Index lifecycle management

Search indices grow. Older data accumulates. Managing index size is operational work.

**Index aliases.** Give the application a stable name ("products") that points to the current index ("products-v3"). Reindex to a new index version in the background. When done, update the alias. Zero-downtime reindex with no application code changes.

**Index templates and rollover.** For time-series data (logs, events), automatically create new indices as the old ones reach a size or age threshold. `logs-2026-10-19` rolls over to `logs-2026-10-20`. Old indices are moved to cheaper storage tiers or deleted by lifecycle policy. This is how Elasticsearch handles log data without a single index growing unboundedly.

**Shard sizing.** Elasticsearch and OpenSearch distribute data across shards. Too few shards limits parallelism. Too many shards creates coordination overhead — each shard is a Lucene instance with memory overhead. The general guideline: shards between 10–50 GB in size. An index with 10 TB of data needs 200–1000 shards, not 1 shard.

### Relevance tuning

Out-of-the-box BM25 relevance is often wrong for your specific content. A product search where the description field matches but the product name doesn't should probably rank lower than a name match. Tuning this requires:

- **Field boosting.** Weight matches in `name` more than matches in `description`. `name^3, description^1` in the query.
- **Function score.** Incorporate non-text signals — recency, popularity, conversion rate — into the relevance score. A product with 10,000 sales that barely matches the query may rank higher than a perfect text match with zero sales.
- **Synonyms.** Map "k8s" to "kubernetes", "EC2" to "Elastic Compute Cloud". The synonym filter ensures queries for either term retrieve documents using the other.

Relevance tuning is empirical. Define evaluation metrics (click-through rate, search abandonment, conversion from search) and measure them before and after changes. Gut-feel tuning produces inconsistent results.

## Deep Dive: search on AWS

**Amazon OpenSearch Service.** Managed Elasticsearch/OpenSearch. Handles provisioning, patching, scaling, and snapshots. You configure instance types, shard count, replica count, and index lifecycle policies. The operational delta from self-managed: no cluster management, but you still own index design, query optimization, and mapping configuration.

Instance sizing: the cluster needs enough heap memory for the index hot data. A rough rule: heap is 50% of instance RAM (JVM best practice), and the heap should be larger than the hot index data. `r6g` instances (memory-optimized) for search-heavy workloads. `c6g` instances (compute-optimized) for aggregation-heavy analytics workloads.

**Dedicated master nodes.** Separate the cluster management role (tracking shards, coordinating state) from the data role (storing and searching documents). Without dedicated masters, a heavily loaded data node doing search and indexing work can cause master-election timeouts, which surfaces as cluster instability. Always use dedicated master nodes in production — three is standard, five for very large clusters.

**UltraWarm and Cold storage tiers.** Hot tier (SSD-backed data nodes) for actively queried data. UltraWarm tier (S3-backed, cached on data nodes) for older data that's queried occasionally — significantly cheaper per GB. Cold tier for archived data rarely queried. Index lifecycle policies move data between tiers automatically based on age or query frequency.

**OpenSearch Ingestion (managed OpenTelemetry Collector).** Pipeline service that ingests data from sources (Kinesis, S3, DynamoDB Streams) and writes to OpenSearch indices. Replaces the need for a custom Lambda-based indexing pipeline for common ingestion patterns. Managed scaling, retry, and dead-letter handling.

**Knn (k-nearest neighbor) for vector search.** OpenSearch supports approximate nearest neighbor search via the `knn` plugin. Store embeddings alongside documents. Query with an embedding vector, retrieve the `k` nearest documents. The foundation for semantic search, RAG retrieval, and similarity-based recommendations. Requires the `knn` index setting at creation time — cannot be added to an existing index.

For a full-text + semantic hybrid search architecture:

```
User query
    │
    ├──► BM25 query (keyword match)    ──► result set A
    │
    ├──► Embed query (vector)
    │    └──► knn search               ──► result set B
    │
    └──► Reciprocal Rank Fusion        ──► merged, re-ranked results
         (merges A and B by rank position)
```

| Concern | Recommendation |
|---|---|
| Index freshness | CDC from source database via DynamoDB Streams or Debezium |
| Zero-downtime reindex | Index aliases + background reindex to new index version |
| Relevance | BM25 baseline + field boosting + function score for business signals |
| Semantic search | knn with embeddings, hybrid with BM25 via RRF |
| Shard sizing | 10–50 GB per shard, avoid over-sharding |
| Cluster stability | Always use dedicated master nodes in production |
| Cost management | UltraWarm/Cold tiers for historical data, ILM policies |

## What's next

Day 29: streaming and batch processing — the architectural difference between processing data as it arrives versus processing it in bulk, and when each model is the right choice.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
