# Connection Pooling and Resource Management

A database connection is not free. Establishing one requires a TCP handshake, TLS negotiation, authentication, and session initialization — tens to hundreds of milliseconds. Holding one consumes memory on both the application and the database server. A PostgreSQL connection consumes roughly 5–10MB of memory on the server side. A database with 500 active connections is consuming 2.5–5GB of RAM just for connection overhead, before a single query runs.

Connection pooling amortizes this cost. Connections are established once, kept alive, and reused across requests. The application borrows a connection, runs a query, returns it to the pool. The next request borrows the same connection without the establishment overhead.

The failure mode: exhausted pools. All connections are in use. A new request waits for one to become available. Waiting requests accumulate. Latency climbs. Threads block. The application becomes unresponsive — not because the database is slow, but because no one can get a connection to ask it anything.

## Fundamentals

### Pool sizing

Pool too small: connections exhaust under load, requests queue, latency spikes.
Pool too large: the database receives too many concurrent connections, its memory is consumed by connection overhead, and query execution suffers.

The right pool size is the number of concurrent queries the database can execute efficiently, which is bounded by its CPU core count and I/O throughput — not by application demand. A database with 16 CPU cores can execute roughly 16 queries concurrently without contention. A pool of 16–32 connections per application instance is often optimal. A pool of 500 is wasteful and counterproductive.

The HikariCP documentation's guidance applies broadly: optimal pool size is determined by the database's hardware, not the application's concurrency. Start with `number_of_cpu_cores × 2 + effective_spindle_count` as a baseline and measure.

The problem: multiple application instances, each with their own pool. Ten instances with pools of 30 = 300 connections to the database. Twenty instances after autoscaling = 600 connections. The application tier scales horizontally but the database connection count scales proportionally. At some point, the connection count itself becomes the bottleneck.

### Connection pool architecture

**Per-instance pool.** Each application instance manages its own pool. Connections are not shared across instances. Simple. Works well until the instance count grows large. Every autoscaling event changes the total connection count.

**External connection pooler.** A process that sits between the application and the database, managing a shared pool of real database connections. PgBouncer for PostgreSQL, ProxySQL for MySQL. The application connects to the pooler (cheap — no TCP/TLS overhead per query). The pooler maintains a smaller number of real database connections. One hundred application instances connecting to PgBouncer → PgBouncer maintains twenty real connections to the database.

Three pooling modes in PgBouncer:
- **Session mode.** A real connection is assigned to a client for the duration of the client's session. One-to-one mapping. Doesn't reduce connection count significantly.
- **Transaction mode.** A real connection is assigned to a client for the duration of a single transaction. Released back to the pool after `COMMIT` or `ROLLBACK`. Allows thousands of application connections to share tens of database connections. The standard mode for most applications.
- **Statement mode.** Connection released after each statement. Only works for single-statement transactions. Breaks multi-statement transactions.

Transaction mode is the target. It's also the mode that breaks prepared statements, `SET` commands, and advisory locks that span connection lifetimes — because the connection changes between statements. Applications using these features need adjustments.

### Connection lifecycle

**Idle connections.** An open connection sitting in the pool doing nothing still consumes memory on the database. Configure `maxIdleTime` (or equivalent) to close connections that have been idle for a set period. The pool will re-establish when needed. Common setting: close idle connections after 10 minutes.

**Connection validation.** A connection in the pool may be stale — the database restarted, a firewall killed the idle connection, a network hiccup closed it without the application knowing. Returning a dead connection to the application causes a query failure. Configure the pool to validate connections before handing them to the application (`testOnBorrow` in HikariCP/DBCP, `ping` on checkout in SQLAlchemy). The validation is a lightweight `SELECT 1` — cheap relative to the cost of a failed query and retry.

**Connection lifetime.** Long-lived connections can accumulate memory leaks on the database side — query plan caches, temp table allocations, open transaction logs. Configure a maximum connection lifetime (HikariCP `maxLifetime`, default 30 minutes) to periodically cycle connections. New connections are established transparently by the pool.

```
Application Instance
  │
  └── Connection Pool (10-30 connections)
        │
        ├── [idle] ready for next request
        ├── [active] executing query
        ├── [idle] ready for next request
        └── [active] executing query

Without pooler: N instances × pool_size = total DB connections
With PgBouncer:  N instances × pool_size = connections to pooler (cheap)
                                         PgBouncer → DB: fixed small count
```

## Operations

### Pool exhaustion in production

Pool exhaustion looks like application latency spikes with no corresponding increase in query time. The database shows idle connections while the application times out. Connection wait time in application metrics climbs.

Common causes:

**Slow queries holding connections.** A query that should run in 10ms starts taking 5 seconds. Connections are held for 5 seconds instead of 10ms. At the same request rate, the pool exhausts because connections take 500x longer to return. The fix is the slow query, not the pool. Set statement timeout on the database (`statement_timeout` in PostgreSQL) to kill runaway queries and return connections to the pool.

**Transaction held open too long.** Application starts a transaction, makes an external API call within the transaction, waits for the API to respond. The API takes 3 seconds. The connection is held for 3 seconds doing nothing. Never hold a database transaction open across an external I/O operation. Do the external call first, then start the transaction, do the writes, commit.

**Connection leak.** Application code acquires a connection, hits an exception path that doesn't return it to the pool. The connection is held forever. Pool size slowly decreases. Under load, the pool exhausts. Detectable: the pool's `activeConnections` metric trends upward over time without a corresponding increase in request rate. Fix: use connection management patterns that guarantee return on all code paths (Python context managers, Java try-with-resources, Go `defer`).

### Database max connections

PostgreSQL and MySQL have a hard limit on concurrent connections configured at the server level. Postgres default is 100; a typical production configuration raises this to 200–500. Beyond that, each additional connection increases memory pressure and scheduler overhead.

Diagram the connection path explicitly:
- How many application instances at peak?
- Pool size per instance?
- Total connections to the pooler?
- How many connections does the pooler maintain to the database?

The number that matters is the last one. Everything above it can scale; the database connection limit is fixed.

RDS instance class connection limits: a `db.t3.medium` supports roughly 170 connections. A `db.r6g.large` supports roughly 1,000. If the workload requires more than the instance class supports, either move up the instance class or introduce a connection pooler.

### Thread pools and event loops

Connection pools exist because connections are expensive. The same logic applies to threads and event loop capacity.

A synchronous request-handling model (one thread per request) has a thread pool. Each thread may be holding a connection waiting for a query. Thread pool size and connection pool size are coupled — a thread blocked on a database query holds both a thread and a connection. Oversize either pool and the other becomes the bottleneck.

Async request handling (Node.js, Python asyncio, Go goroutines) changes the model. A single thread can have many in-flight database queries if the database driver is async-capable. But async doesn't eliminate the connection count problem — it just means the application can issue more concurrent queries with fewer threads.

## Deep Dive: connection pooling on AWS

**RDS Proxy.** Managed connection pooler for RDS and Aurora. Sits between the application and the database, maintaining a pool of real database connections. The application connects to the RDS Proxy endpoint. RDS Proxy multiplexes application connections into a smaller number of real connections.

Connection limits are set as a percentage of the database's `max_connections`. At 100% utilization, RDS Proxy maintains as many real connections as the database allows. In practice, configuring it at 50–70% of `max_connections` leaves headroom for direct connections (admin access, monitoring tools).

RDS Proxy integrates with IAM authentication and Secrets Manager for credential management — the proxy handles the credential rotation without requiring application connection recycling when the password changes. The application authenticates to the proxy with IAM; the proxy authenticates to the database with the stored credential. Credential rotation becomes transparent to the application.

**PgBouncer on EC2 or ECS.** For applications not using RDS (self-managed PostgreSQL, Aurora with direct connections) or for workloads where RDS Proxy's limitations (no prepared statement support in transaction mode, limited supported PostgreSQL features) are a constraint. Run PgBouncer as a sidecar container in ECS or as a Deployment in EKS. Configure it with the database endpoint and pool settings. Application connects to the PgBouncer service endpoint.

EKS sidecar pattern: PgBouncer container in the same pod as the application container. They communicate over localhost. No network hop between application and pooler. Connection to the database is pooled by the PgBouncer sidecar.

**ElastiCache connection management.** Redis connections are cheaper than database connections but not free. A Redis cluster with thousands of persistent connections from application instances consumes memory and file descriptors. Use connection pooling in the Redis client. Most Redis clients (redis-py, Jedis, ioredis) support connection pools. For Lambda functions, initialize the connection pool outside the handler function so it persists across invocations.

**Lambda and database connections.** Lambda's ephemeral execution model is hostile to connection pooling. Each Lambda invocation may spin up a new execution environment, establishing a new database connection. A spike to 1,000 concurrent Lambda invocations = 1,000 simultaneous new connection requests. Databases get overwhelmed.

RDS Proxy is the solution for Lambda. Lambda connects to the RDS Proxy endpoint. The proxy maintains a small pool of real connections regardless of how many Lambda invocations are running. The proxy absorbs the connection burst that Lambda generates.

| Pooling mechanism | Connection multiplexing | Complexity | Best for |
|---|---|---|---|
| Per-instance pool (HikariCP, SQLAlchemy) | No (each instance has its own pool) | Low | Fixed-size application fleets |
| RDS Proxy | Yes (managed) | Low (managed service) | Lambda, large autoscaling fleets, RDS/Aurora |
| PgBouncer | Yes (transaction mode) | Medium (self-managed) | PostgreSQL, custom pooling requirements |
| ProxySQL | Yes | Medium | MySQL, query routing, read/write splitting |
| Redis connection pool | Client-side per-instance | Low | All Redis workloads |

## What's next

Day 37: traffic management and load shedding — what to do when traffic exceeds capacity, how to prioritize which requests to serve, and the difference between graceful degradation and cascading failure.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
