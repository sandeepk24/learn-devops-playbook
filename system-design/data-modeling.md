# Data Modeling

The data model is the first decision in a system and the hardest to change later. Every performance problem, every query that scans too much data, every schema migration that requires a multi-hour maintenance window — most of them trace back to a data modeling decision made early when the access patterns weren't fully understood.

The choice of database type isn't the primary decision. The primary decision is: what access patterns does this system need to support, and what data model fits those patterns with acceptable performance and acceptable operational cost?

## Fundamentals

### Relational model

Tables, rows, columns, foreign keys, joins. The model for data with complex relationships and unpredictable query patterns. Normalizing data — removing duplication by splitting into related tables — keeps writes cheap and consistent. Joins reassemble the data at query time.

The strength: flexibility. A well-designed relational schema can answer queries you haven't written yet. Ad hoc reporting, joins across entities, aggregations across the dataset — all work because the optimizer can construct an execution plan for arbitrary SQL.

The cost: join performance degrades with scale. A query joining five tables at 10 million rows per table is a different proposition than the same query at 100 rows. Indexes help, but they're not free (Day 13). At high read volume on large datasets, the relational model's flexibility starts working against you.

Relational databases are the correct default for most systems until proven otherwise. PostgreSQL or MySQL for transactional workloads with complex relationships. Change the model when there's a concrete performance or scale reason to, not because a different model sounds more sophisticated.

### Document model

Documents — JSON or BSON objects — stored and retrieved as units. No schema enforced at the database level. A document can contain nested objects and arrays. Related data is often embedded in the same document rather than split across tables.

The strength: access patterns that retrieve a complete entity in one read. If you always read a blog post with its tags, author, and comments together, storing them in one document eliminates the joins. The read is a single key lookup.

The cost: queries that cut across documents are slow. "Find all posts tagged with 'kubernetes' by authors with more than 100 followers" requires either multiple reads and application-side joins, or a schema design that anticipated this query. The flexibility in schema design is also a curse — inconsistent document shapes accumulate over time in the absence of application-level validation.

MongoDB is the standard document store. DynamoDB also supports document-like structures but with different key design requirements.

### Wide-column model

Rows identified by a key, with a variable number of columns per row. Cassandra, HBase, BigTable, DynamoDB in its native key-value form. The key design determines everything — partitioning, access patterns, and performance.

Built for write-heavy workloads at scale. Cassandra writes are fast: append to a commit log, write to an in-memory memtable, done. Reads are optimized for queries that match the primary key structure. Queries that don't match the key structure require secondary indexes or full scans — both expensive.

The access pattern design requirement is strict. You design the table schema around the queries you'll run, not around the entities in your domain. If you need to query by three different access patterns, you might need three tables — one per pattern — storing redundant copies of the data. This is not a design smell in wide-column systems. It's how they work.

### Graph model

Nodes and edges. Relationships are first-class citizens, not foreign keys. Traversal queries — "find all users who follow someone who follows user X, who also purchased product Y" — are efficient in a graph database because relationship traversal is the native operation.

Relational databases can model graphs via join tables, but recursive queries are expensive and awkward to write. Graph databases (Neo4j, Amazon Neptune) make traversal queries straightforward.

Appropriate for: fraud detection (connected entities), social networks (follow graphs, recommendations), knowledge graphs, identity and access management hierarchies. Not appropriate as a general-purpose database — graph databases sacrifice write throughput and aggregate query performance for traversal performance.

### Time-series model

Data with a timestamp as the primary dimension. Sensor readings, metrics, financial tick data, server logs. Optimized for write-heavy append patterns, range queries on time windows, and downsampling/aggregation over time.

Standard relational databases work for time-series at small scale. They degrade when the dataset grows to billions of rows because index maintenance on a high-cardinality timestamp column becomes expensive and partitioning by time range requires manual management. Dedicated time-series databases (InfluxDB, Prometheus, Amazon Timestream) handle retention policies, downsampling, and time-window queries natively.

## Operations

### DynamoDB access pattern design

DynamoDB deserves specific treatment because the access pattern design requirement is stricter than any other database in common production use, and the failures from ignoring it are expensive.

Every DynamoDB table has a partition key and an optional sort key. The partition key determines the physical partition a item lives on. Items with the same partition key and different sort keys co-locate on the same partition and can be queried together efficiently.

**Design the keys around the queries, not the entities.** Start by listing every query the application needs. For each query, identify the partition key and sort key that would make it a single partition lookup or an efficient range scan.

Example: a multi-tenant SaaS application needs to fetch all orders for a user, ordered by date.
- Partition key: `user_id`
- Sort key: `order_date#order_id`
- Query: `PK = user123, SK begins_with 2026-10`

This is a single partition scan. Efficient. Now add the requirement: fetch a single order by order ID.
- That query can't use the same table structure efficiently without a GSI.
- Add a GSI with `order_id` as partition key. Sparse, fast, purpose-built for that access pattern.

The anti-pattern: using a single generic table structure that requires a full table scan or heavy GSI usage for every query. That's a relational mental model applied to DynamoDB, and it produces throttling and cost problems at scale.

### Normalization vs denormalization

**Normalize** to reduce write duplication and ensure consistency. One source of truth for each fact. Changes happen in one place. The cost: reads require joins to reassemble data.

**Denormalize** to optimize reads. Store pre-joined, pre-aggregated data. Reads are fast and simple. The cost: writes must update multiple places consistently. Data can drift.

Most production systems are selectively denormalized — normalized for the entities where write consistency matters, denormalized for the read-heavy query paths where join performance is a concern.

In DynamoDB there's no join. Denormalization is mandatory. You store data in the shape it will be read. If the same data is needed in multiple shapes, you store multiple copies and keep them consistent at write time.

### Schema migrations at scale

Altering a table with 500 million rows is not a DDL statement that runs in seconds. `ALTER TABLE ADD COLUMN` in PostgreSQL requires a full table rewrite for some operations. The table is locked. Everything stops.

Mitigation strategies:
- **PostgreSQL `ALTER TABLE ... ADD COLUMN` with a nullable column** is now instant in recent versions — metadata change only, no rewrite.
- **`pg_repack`** rewrites a table without holding an exclusive lock.
- **Online schema change tools**: `pt-online-schema-change` (Percona Toolkit) for MySQL, `gh-ost` for MySQL, `pglive` for PostgreSQL. They create a shadow table, copy data, keep it in sync via triggers or replication, and swap at the end.
- **Expand/contract pattern** (Day 26): add the new column, deploy code that handles both, backfill, deploy code that uses only the new, drop the old.

The mistake: running a DDL that locks a large table during business hours without testing it first on a staging database of the same size. Schema migrations should be tested on production-size data before being run on production.

## Deep Dive: data modeling on AWS

**RDS (PostgreSQL/MySQL).** The default for relational workloads. PostgreSQL for complex queries, JSON support, and richer data types. MySQL for simpler workloads and broader tool compatibility. Aurora PostgreSQL and Aurora MySQL are drop-in replacements with better performance and availability, worth the slightly higher cost for production workloads.

For schema migrations on RDS: `pg_repack` can be installed as an RDS extension. `gh-ost` runs from an EC2 instance, connects to the RDS endpoint. Plan migration windows and test against a restored snapshot of production before running on live data.

**DynamoDB.** Single-table design vs multi-table design is a genuine debate. Single-table design puts all entity types in one table with composite keys — efficient at runtime, difficult to reason about, harder to query ad hoc. Multi-table is more conventional and easier to work with. Single-table makes sense when access patterns are fully understood and query performance is the primary concern. Multi-table is more maintainable for teams still discovering their access patterns.

NoSQL Workbench for DynamoDB is worth using during the design phase. Visualizes the data model, lets you test queries against mock data before building application code, and generates the create-table statements.

**Amazon Keyspaces (Cassandra).** For Cassandra workloads without the operational overhead of managing Cassandra clusters. The same partition key design rules apply. Wide partitions — too many items under one partition key — are as problematic in Keyspaces as in self-managed Cassandra. Design partition keys for even data distribution and bounded partition size.

**Neptune (Graph).** Supports both Gremlin (Apache TinkerPop) and SPARQL (RDF) query languages. Appropriate when the core queries are traversals over a relationship graph. Pricing by instance class plus I/O — graph traversal queries that touch many edges can be expensive. Right-size the instance to the graph traversal depth and concurrency your workload requires.

**Timestream.** Time-series database. Separates recent data (in-memory, expensive, fast) from historical data (magnetic, cheap, slower). Retention policies automatically move data between tiers. Purpose-built query functions for time-series operations — time-window aggregations, interpolation, rate of change. Query syntax is SQL-like but not standard SQL.

| Model | Best for | Joins | Schema flexibility | Scale ceiling |
|---|---|---|---|---|
| Relational (RDS) | Complex relationships, ad hoc queries | Native | Low (schema enforced) | Vertical + read replicas |
| Document (MongoDB) | Entity-centric reads, variable schema | Application-side | High | Horizontal (sharding) |
| Wide-column (DynamoDB) | High-throughput key-value and range queries | None (design the table for the query) | Low (keys are fixed) | Effectively unbounded |
| Graph (Neptune) | Relationship traversal | Native (traversal) | Medium | Vertical (mostly) |
| Time-series (Timestream) | Time-windowed metrics and events | Limited | Low (time + dimensions) | Horizontal (managed) |

## What's next

Day 28: search systems — why databases aren't search engines, how inverted indexes work, and Elasticsearch/OpenSearch on AWS for full-text search, faceted filtering, and relevance ranking.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
