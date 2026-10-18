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
| 10 | [Consistent hashing](./consistent-hashing.md) | Why modular hashing breaks on resize, the ring model, virtual nodes, and how ElastiCache and DynamoDB use it internally. |
| 11 | [Database sharding](./database-sharding.md) | Range vs hash vs directory sharding, choosing a shard key, cross-shard queries, resharding, and DynamoDB/Aurora Limitless on AWS. |
| 12 | [Circuit breakers](./circuit-breakers.md) | Closed/open/half-open state machine, failure thresholds, fallback responses, cascading failures, and implementation on AWS. |
| 13 | [Database indexes](./database-indexes.md) | B-tree vs hash vs composite, clustered vs non-clustered, covering indexes, index bloat, and RDS/DynamoDB GSI on AWS. |
| 14 | [DNS and service discovery](./dns-and-service-discovery.md) | Client vs server-side discovery, TTL and cache poisoning, split-horizon DNS, Cloud Map, ECS discovery, and CoreDNS in EKS. |
| 15 | [API design and versioning](./api-design-and-versioning.md) | Breaking vs non-breaking changes, versioning strategies, evolutionary design, idempotency keys, and API Gateway version management. |
| 16 | [Content delivery networks](./content-delivery-networks.md) | Edge caching, Cache-Control headers, origin shield, cache invalidation, CloudFront behaviors, and Lambda@Edge. |
| 17 | [Event-driven architecture](./event-driven-architecture.md) | Events vs commands, choreography vs orchestration, ordering problems, eventual consistency, and EventBridge/SNS/Kinesis/Step Functions. |
| 18 | [Observability](./observability.md) | Metrics, logs, and traces as a system, the four golden signals, SLIs/SLOs/error budgets, and CloudWatch/X-Ray/ADOT on AWS. |
| 19 | [Consensus and leader election](./consensus-and-leader-election.md) | Raft, quorum math, election storms, what quorum loss means operationally, and etcd in EKS. |
| 20 | [Microservices vs monolith](./microservices-vs-monolith.md) | Operational costs on each side, where each breaks, strangler fig migration pattern, and the AWS cost reality of microservices. |
| 21 | [Distributed transactions](./distributed-transactions.md) | 2PC and why it's fragile, sagas with choreography and orchestration, outbox pattern, and Step Functions/DynamoDB Transactions on AWS. |
| 22 | [Storage systems](./storage-systems.md) | Block vs object vs file storage, IOPS vs throughput vs latency, AZ pinning, and EBS/S3/EFS/FSx on AWS. |
| 23 | [Network security](./network-security.md) | Security groups vs NACLs, zero trust model, encryption in transit and at rest, VPC endpoints, WAF, GuardDuty, and Network Firewall. |
| 24 | [Capacity planning](./capacity-planning.md) | Little's Law, binding constraints, traffic modeling, headroom and autoscaling lag, and Compute Optimizer/load testing on AWS. |

---

*Part of the [Learn DevOps Playbook](../README.md) — a hands-on library for DevOps, Cloud, and AI engineers.*
