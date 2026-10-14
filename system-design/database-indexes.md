# Database Indexes

An index is a separate data structure that lets the database find rows without reading the entire table. Without one, every query scans every row. With one, the database jumps directly to the relevant rows. The difference in performance at scale is not marginal — it's orders of magnitude.

The trade-off is writes. Every index you add is a data structure that must be updated on every insert, update, and delete. More indexes mean slower writes. A table with twelve indexes on it will have noticeably worse write throughput than the same table with two. The work of maintaining indexes is rarely visible in development on small datasets. It shows up in production under load.

## Fundamentals

### B-tree indexes

The default index type in every major relational database. A balanced tree where each internal node contains key values and pointers to child nodes. Leaf nodes contain the actual key values and row pointers (or the row itself, in a clustered index). Lookups, range scans, and sorted queries all run efficiently. Inserts and updates maintain balance through page splits.

B-trees work well for equality queries (`WHERE user_id = 1234`) and range queries (`WHERE created_at BETWEEN x AND y`). They support ordering, so `ORDER BY` on an indexed column can use the index rather than a sort. This is the index you reach for first.

### Hash indexes

Exact equality only. Fast — O(1) lookup — but no range support. `WHERE email = 'user@example.com'` is ideal. `WHERE score > 100` can't use a hash index at all. PostgreSQL supports hash indexes explicitly. MySQL's InnoDB uses an adaptive hash index internally on frequently-accessed B-tree pages.

### Composite indexes

An index on multiple columns: `(user_id, created_at)`. Column order matters significantly. The index can be used for queries that filter on the leading columns. A composite index on `(A, B, C)` serves queries filtering on A alone, A and B together, or A, B, and C together. It cannot serve a query filtering on B alone or C alone — the leading column must be present.

This is the source of most "why isn't my index being used" debugging sessions. The query filters on the second column of a composite index without including the first. The index is useless for that query.

```
Composite index: (user_id, created_at)

Queries that can use it:
  WHERE user_id = X                      ✓ (leading column)
  WHERE user_id = X AND created_at > Y   ✓ (leading columns in order)

Queries that cannot:
  WHERE created_at > Y                   ✗ (missing leading column)
  WHERE created_at > Y AND user_id = X   ✗ (optimizer may help, but structure doesn't match)
```

### Clustered vs non-clustered

**Clustered index.** The table rows are physically stored in the order of the index. One per table. In InnoDB, the primary key is always the clustered index. Lookups by primary key are fast because the row is in the index itself — no second read required.

**Non-clustered index.** A separate structure that stores index keys and pointers back to the heap (or clustered index). A lookup by secondary index requires two reads: one to find the row pointer in the index, one to fetch the actual row. This second read is called a "heap fetch" or "bookmark lookup" and is the cost that makes secondary indexes slower than primary key lookups for single-row reads.

A covering index eliminates the heap fetch. If the index contains all the columns the query needs, the database can return results from the index alone without touching the table. For frequently run queries on large tables, a covering index can be a significant performance improvement — at the cost of a larger index that's more expensive to maintain.

## Operations

### Index bloat

Indexes grow over time. Rows are inserted, updated, deleted. In B-trees, deletes mark pages as dead space rather than immediately reclaiming them. Over time, a heavily updated table accumulates page bloat — the index is physically larger than the data it represents, with fragmented, partially-empty pages. Range scans become slower because there's more index to traverse.

PostgreSQL has `VACUUM` and `REINDEX`. MySQL has `OPTIMIZE TABLE`. Both defragment and reclaim space. For tables with very high update/delete rates, scheduled maintenance is not optional.

Index bloat is easy to miss because it accumulates gradually. The query that ran in 20ms a year ago now takes 200ms. The table size hasn't grown dramatically. The data hasn't changed structurally. But the index is twice the size it needs to be.

### Unused indexes

Every index has a write cost. An index that no query uses is pure overhead — it slows writes without helping anything. Production databases accumulate unused indexes when query patterns change, features get removed, or someone adds an index to debug a slow query and forgets to re-evaluate it later.

PostgreSQL tracks index usage in `pg_stat_user_indexes`. `idx_scan = 0` on an index that's been up for months is a strong signal it can be dropped. MySQL has `sys.schema_unused_indexes`. Audit periodically. Drop indexes that aren't earning their write cost.

### Index-driven query design

The right way to think about indexing: start with the queries, work backward to the indexes. Not the reverse. An index that exists without a query that uses it is waste. A query without an appropriate index is a table scan waiting to become a production incident.

`EXPLAIN` (or `EXPLAIN ANALYZE` in PostgreSQL) shows the query plan. `Seq Scan` on a large table in a plan that's supposed to be a lookup is the tell. The plan also shows estimated vs actual row counts — when estimates are wildly off, statistics are stale (`ANALYZE` fixes this) and the optimizer is making bad decisions.

### Partial indexes

Index a subset of rows based on a condition. `CREATE INDEX ON orders (created_at) WHERE status = 'pending'`. Only pending orders are in the index. Smaller than a full index. Faster to maintain. Faster to scan. Useful when queries consistently filter on a low-cardinality column value that represents a small fraction of the table — active records, unprocessed jobs, open tickets.

## Deep Dive: indexes on AWS

**RDS and Aurora.** Same index behavior as the underlying engine (PostgreSQL or MySQL). Performance Insights is the tool to reach for first — it shows which queries are consuming the most DB time, broken down by wait states. A query with high `io/table/sql/reading_rows` wait time is doing table scans. Enhanced monitoring gives you per-process CPU and I/O at the OS level, useful when the database is under load but Performance Insights doesn't show an obvious query culprit.

Aurora's storage is distributed and handles I/O differently than EBS-backed RDS, but index design principles are identical. One Aurora-specific consideration: read replicas share storage with the primary, so a heavy index rebuild on the primary immediately affects replica read performance through I/O contention on shared storage.

**DynamoDB.** No B-trees. Two index types, both structured differently than relational indexes.

*Local Secondary Index (LSI).* Same partition key, different sort key. Must be defined at table creation. Cannot be added later. Shares read/write capacity with the base table. Useful for alternate sort orders on the same partition — `user_id` partition key, sort by `created_at` instead of the default.

*Global Secondary Index (GSI).* Different partition key, optional sort key. Can be added after table creation. Has its own read/write capacity, separate from the base table. Sparse — only rows that have the GSI's key attribute are indexed. A GSI on an attribute that most rows don't have is naturally small. The write cost: every write to the base table that affects GSI attributes also writes to the GSI.

GSI write capacity is a common DynamoDB cost surprise. A table with five GSIs effectively multiplies its write cost by up to six. Each write to the base table fans out to all GSIs that index the written attributes.

| Index type | Best for | Limitation |
|---|---|---|
| B-tree | Range queries, equality, sorting | Overhead on high-write tables |
| Hash | Exact equality, very high-speed lookup | No range support |
| Composite | Multi-column filter/sort | Leading column must be in query |
| Covering | Read-heavy queries on large tables | Larger, more expensive to maintain |
| Partial | Filtered subsets of rows | Only useful for matching WHERE condition |
| DynamoDB GSI | Alternate access patterns | Separate capacity, write fan-out cost |

## What's next

Day 14: DNS and service discovery — how services find each other in a dynamic fleet, what breaks when they can't, and the operational problems that look like application failures until you check DNS.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
