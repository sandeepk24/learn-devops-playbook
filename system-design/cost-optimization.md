# Cost Optimization

AWS costs are rarely a mystery. They're the predictable output of architectural decisions — instance sizes, data transfer patterns, storage tiers, and the services chosen for each layer. The bill is high because specific decisions made it high, and changing the bill means changing those decisions.

Cost optimization is not about being cheap. It's about aligning spend with value. A system where every dollar of infrastructure spend is justified by the workload it supports is well-optimized. A system with idle Reserved Instances, forgotten EBS volumes, and three-year-old NAT Gateway data transfer charges is not.

## Fundamentals

### Where AWS money actually goes

The four major cost categories in most AWS architectures:

**Compute.** EC2 instances, Fargate vCPU/memory, Lambda invocations and duration, RDS instance hours. Usually the largest line item. The biggest lever: right-sizing and purchase model (On-Demand vs Reserved vs Spot).

**Storage.** EBS volumes (charged for provisioned capacity whether used or not), S3 storage by GB and class, RDS storage, EFS. Often underestimated because individual storage costs are low per GB — but volumes and buckets accumulate without lifecycle management.

**Data transfer.** Egress from AWS to the internet is charged per GB. Data transfer between AZs within a region is charged at $0.01/GB in each direction. Cross-region transfer is higher. NAT Gateway charges per GB processed. Often the most surprising line item — internal traffic patterns that seem trivial at low scale become significant at high throughput.

**Managed service overhead.** ALB hourly charges plus LCU pricing. NAT Gateway hourly plus per-GB. CloudWatch Logs ingestion and storage. API Gateway request charges. These "glue" services add up when request volumes are high.

### The cost of over-provisioning

Over-provisioning is the most common cost problem. An instance sized for peak load that runs at 10% average CPU. A DynamoDB table with provisioned capacity sized for a traffic spike that happens once a month. A Multi-AZ RDS instance with 2TB of allocated storage using 200GB.

The root cause: engineers size for worst-case without mechanisms to right-size afterward. Provisioning takes five minutes. Right-sizing requires operational maturity — tagging, monitoring, someone reviewing the numbers regularly.

Compute Optimizer (Day 24) automates the right-sizing analysis for EC2, ECS, Lambda, and EBS. It identifies instances that are over-provisioned and estimates the saving from moving to the recommended size. Running it and acting on the recommendations is a few hours of work with potential savings of 30–50% on compute.

### Purchase models

**On-Demand.** Pay per hour or second, no commitment. Full flexibility. Highest per-unit cost.

**Reserved Instances / Savings Plans.** Commit to a usage level for 1 or 3 years in exchange for 30–60% discount. Reserved Instances lock to a specific instance type and region. Compute Savings Plans apply across any EC2, Fargate, and Lambda usage — more flexible. For stable baseline compute that runs continuously, Savings Plans pay for themselves within months.

The mistake: buying Reserved Instances before understanding the workload. A 3-year RI commitment on an instance type that gets replaced by a better option in 18 months is a loss. Compute Savings Plans are the safer default — they apply to whatever compute you're running, not to a specific instance type.

**Spot Instances.** Spare EC2 capacity at up to 90% discount. Can be interrupted with a 2-minute warning. Right for: batch workloads that checkpoint progress and can resume, stateless application tiers that tolerate instance interruption, CI/CD runners, ML training with checkpointing.

Wrong for: databases, stateful services, anything that can't tolerate a sudden instance termination.

## Operations

### Finding the cost

Before optimizing, know exactly where the money is. AWS Cost Explorer provides hourly and daily cost by service, region, account, and tag. The most useful views:

- Cost by service this month vs last month. Identifies what's growing.
- Cost by resource tag. If resources aren't tagged with team, environment, and service, the Cost Explorer data is noise. Enforce tagging as a deployment requirement, not a retroactive cleanup project.
- Data transfer cost broken out. NAT Gateway data transfer is often buried in "EC2-other." Find it explicitly — it's frequently the largest unexpected line item.

AWS Cost Anomaly Detection monitors spend and alerts when usage deviates from expected patterns. More useful than manually reviewing the bill because it catches problems in near-real-time rather than at month-end.

### Data transfer optimization

Data transfer costs accumulate silently. The most impactful reductions:

**AZ-aware routing.** Microservices calling each other across AZs pay $0.01/GB in each direction. At 10 TB/day of internal traffic, that's $200/day. Topology-aware load balancing (EKS topology spread, ECS with AZ-aware Service Connect, ALB with cross-zone load balancing disabled for intra-AZ traffic) routes traffic to instances in the same AZ first.

**S3 VPC endpoints.** Traffic from EC2 to S3 via an internet gateway or NAT gateway is charged as data transfer. An S3 Gateway endpoint routes the same traffic within the AWS network at no charge. Enabling it takes five minutes. For workloads that read or write significant data from S3, this is free money.

**CloudFront in front of S3.** Egress from S3 to CloudFront is free. Egress from CloudFront to users is charged at CloudFront's rate, which is lower than direct S3 egress rates for most regions. For public static content, CloudFront reduces both cost and latency.

**NAT Gateway alternatives.** NAT Gateway charges $0.045/hour plus $0.045/GB processed. For services that only need to reach AWS APIs (S3, DynamoDB, Secrets Manager, SSM), Interface Endpoints or Gateway Endpoints eliminate the NAT Gateway for that traffic. The endpoint hourly cost is often less than the NAT Gateway data processing charge at meaningful volumes.

### Storage cost management

EBS: every GB provisioned is charged, whether used or not. An instance with a 500GB root volume using 50GB pays for 500GB. Snapshots are charged per GB of changed blocks. Unattached EBS volumes — left over from terminated instances — are charged indefinitely.

Automate cleanup: EventBridge rule on EC2 instance termination → Lambda that identifies and optionally terminates orphaned EBS volumes. Tag volumes with instance ID at creation. Identify untagged or unattached volumes monthly.

S3: lifecycle rules are the cost control mechanism. Objects in Standard tier cost $0.023/GB. The same objects in Glacier Deep Archive cost $0.00099/GB. Logs that must be retained for compliance but are never queried after 90 days don't need to live in Standard for three years. Write the lifecycle rule at bucket creation.

RDS: allocated storage is charged even when unused. Start smaller and allow autostorage scaling rather than provisioning for peak. Snapshots outside the automated backup window are charged per GB. Automated backups within the backup retention window are free.

### Lambda cost

Lambda pricing: per invocation plus per GB-second of compute. For high-invocation-count functions at very short duration, invocation cost dominates. For long-running or memory-intensive functions, duration cost dominates.

Tuning memory allocation is often misunderstood. More memory = more CPU allocated by AWS = faster execution. A function that runs in 3,000ms at 128MB might run in 800ms at 512MB. The cost: 512MB × 0.8s = 409.6 GB-ms vs 128MB × 3s = 384 GB-ms. Similar cost, 3.75x faster. The AWS Lambda Power Tuning tool (open source, runs as a Step Functions state machine) benchmarks a function across memory configurations and plots cost vs performance. Run it before settling on a memory setting.

Functions with predictable invocation patterns: Provisioned Concurrency eliminates cold starts but costs per concurrency-hour. For latency-sensitive functions invoked frequently, provisioned concurrency plus Compute Savings Plans can reduce total cost vs On-Demand while improving latency.

## Deep Dive: cost tooling on AWS

**Cost Explorer.** The baseline. Free. Granularity down to hourly. Filter by linked account, service, region, usage type, tag. Forecast based on historical patterns. Reservation and Savings Plan coverage and utilization reports — tells you what percentage of eligible usage is covered by discounts and whether existing commitments are fully utilized.

**AWS Budgets.** Alert when actual or forecasted cost exceeds a threshold. Configure per service, per tag, per linked account. Budget actions can automatically apply an IAM policy to restrict spending if a threshold is exceeded — useful for development accounts where a runaway process shouldn't accumulate an unlimited bill.

**Compute Optimizer.** Right-sizing recommendations for EC2, ECS services, Lambda, EBS volumes, and Auto Scaling Groups. Export recommendations to S3 as CSV for bulk analysis. Enhanced recommendations mode uses CloudWatch Application Insights for richer utilization data. Acts on the actual utilization metrics, not provisioned capacity — a recommendation to downsize is based on observed CPU and memory, not on the instance type's maximum.

**AWS Cost and Usage Report (CUR).** The raw data. Hourly or daily, every resource, every charge type, all tags. Lands in S3. Query with Athena. The most granular cost data available — necessary for detailed allocation, chargeback models, and identifying specific resource-level cost drivers that Cost Explorer's aggregated view obscures.

**Trusted Advisor.** Checks for cost optimization opportunities alongside security and availability findings. Identifies idle EC2 instances, underutilized EBS volumes, unassociated Elastic IP addresses, and RDS instances with low utilization. Basic checks are free. Full checks require Business or Enterprise Support.

| Optimization | Effort | Typical saving | Risk |
|---|---|---|---|
| Right-size instances (Compute Optimizer) | Low | 20–40% compute | Minor performance regression if too aggressive |
| Savings Plans (1-year, no upfront) | Low | 30–40% on committed compute | Locked for 1 year |
| Spot for batch/stateless | Medium | Up to 90% on eligible compute | Interruption handling required |
| S3 lifecycle policies | Low | 60–90% on cold data | None |
| S3 VPC Gateway endpoints | Very low | Full NAT Gateway cost for S3 traffic | None |
| AZ-aware service routing | Medium | Variable (depends on cross-AZ traffic volume) | Increased AZ dependency |
| Lambda memory tuning | Low | 10–30% on duration cost | None if validated |
| Unattached EBS cleanup | Low | Direct elimination | Verify volumes are truly unused |

## What's next

Day 33: reliability and fault tolerance — designing systems that degrade gracefully, the failure modes that matter versus the ones that feel scary but rarely happen, and the SRE practices that make reliability a measurable property.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
