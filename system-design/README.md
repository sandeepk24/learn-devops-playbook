# System Design for DevOps & Cloud Engineers

75 days. One concept at a time. Written for engineers who get paged, not engineers who draw boxes on whiteboards.

This isn't interview prep dressed up as architecture content. It's the thinking behind why systems behave the way they do under load, under failure, and under time pressure — with real AWS service names and real operational trade-offs, not abstract theory.

---

## The series

| Day | Concept | What's in it |
|---|---|---|
| 1 | [What is system design for DevOps engineers](./what-is-system-design-for-devops-engineers.md) | Why DevOps system design is a different conversation than a coding interview, and the three questions every design has to answer. |
| 2 | [Scalability: vertical vs horizontal](./scalability-vertical-vs-horizontal.md) | When to scale up vs scale out, the stateless requirement, and why people reach for horizontal too early. |
| 3 | [Latency vs throughput](./latency-vs-throughput.md) | Two numbers that sound related, are often in tension, and get optimized for the wrong one constantly. |
| 4 | [CAP theorem](./cap-theorem.md) | Why "pick two" is a misleading frame, what CP vs AP actually means under a partition, and how AWS services expose the trade-off directly. |
| 5 | [Load balancing](./load-balancing.md) | Routing algorithms, Layer 4 vs 7, connection draining, thundering herd, and ALB vs NLB on AWS. |
| 6 | [Caching](./caching.md) | Where caches sit, how invalidation works, cache stampedes, cold starts, and ElastiCache/DAX/CloudFront. |
| 7 | [Database replication](./database-replication.md) | Synchronous vs async replication, replication lag, read replicas vs standby, failover sequences, and RDS/Aurora on AWS. |
| 8 | [Message queues and async messaging](./message-queues.md) | Queues vs pub/sub, delivery guarantees, dead letter queues, idempotency, and SQS/SNS/EventBridge on AWS. |
| 9 | [Rate limiting](./rate-limiting.md) | Token bucket, leaky bucket, sliding window, where to enforce limits, distributed rate limiting with Redis, and WAF/API Gateway on AWS. |

---

*Part of the [Learn DevOps Playbook](../README.md) — a hands-on library for DevOps, Cloud, and AI engineers.*
