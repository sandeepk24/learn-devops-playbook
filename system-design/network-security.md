# Network Security

The classic network security model draws a perimeter. Everything inside is trusted. Everything outside is not. The perimeter is the firewall. If you get past the firewall, you're in, and everything inside the network treats you as legitimate.

This model fails in the cloud. The "inside" spans multiple accounts, multiple regions, third-party SaaS integrations, shared VPCs, and containerized workloads with ephemeral IPs. The perimeter is porous by design. Treating the VPC boundary as a trust boundary means a compromised EC2 instance has lateral access to every other service in the VPC.

Defense in depth is the replacement model: multiple independent layers, each enforcing access controls, so a failure at one layer doesn't give an attacker unrestricted access.

## Fundamentals

### Security groups

Stateful firewalls attached to elastic network interfaces. Every EC2 instance, RDS instance, Lambda in a VPC, and ECS task has one or more security groups. Rules define allowed inbound and outbound traffic by protocol, port range, and source/destination (CIDR block or another security group).

Stateful: if an inbound connection is allowed, the return traffic is automatically allowed. You don't write a corresponding outbound rule for established connections.

Security groups are the primary enforcement mechanism for service-to-service access within a VPC. The right model: each service has its own security group. Access is granted by referencing the source security group, not a CIDR range. "Allow inbound port 5432 from the application-tier security group" is more precise and more maintainable than "allow inbound port 5432 from 10.0.0.0/8." When the application tier scales, adds instances, or changes IPs, the security group rule remains correct without modification.

### NACLs

Network Access Control Lists operate at the subnet level. Stateless: inbound and outbound rules are evaluated independently. If you allow inbound TCP on port 443, you must explicitly allow outbound on the ephemeral port range (1024–65535) for the return traffic to flow.

NACLs are evaluated before traffic reaches an instance. They're coarser than security groups — they apply to all traffic entering or leaving a subnet, not to specific instances or services within it.

The practical division: security groups handle service-to-service access control. NACLs handle subnet-level boundaries — blocking known-bad IP ranges, enforcing that traffic between subnet tiers flows only in the intended direction, adding a secondary layer that's harder for a compromised instance to modify (security groups can be modified by anyone with EC2 permissions; NACLs require VPC permissions, which are typically more restricted).

```
Inbound traffic path:

Internet Gateway / Transit Gateway
         │
         ▼
    NACL (subnet level, stateless)
         │  evaluate inbound rule
         ▼
  Security Group (instance level, stateful)
         │  evaluate inbound rule
         ▼
       Instance
```

### Zero trust

Zero trust is a model, not a product. The principle: no request is trusted by default, regardless of network origin. Every request is authenticated and authorized. The network location — inside the VPC, on the corporate network, whatever — grants nothing on its own.

Operationally this means:
- Service-to-service calls are authenticated, not just network-reachable. mTLS between services. IAM-signed requests. JWT validation at every service boundary.
- Least privilege on network access — a service can reach only the specific services it needs, not the entire internal network.
- Short-lived credentials. No long-lived static API keys. IAM roles with temporary tokens, rotated automatically.
- All traffic logged and auditable, even traffic that stays entirely within the VPC.

The shift from perimeter security to zero trust is not binary. Most production environments implement it incrementally: service mesh for mTLS between services, stricter IAM policies, private endpoints for AWS services, VPC Flow Logs for audit visibility.

### Encryption in transit and at rest

**In transit.** TLS between all service-to-service calls, not just at the edge. An attacker who compromises a node in the network should not be able to read unencrypted traffic between internal services. Enforce TLS at the load balancer and between services. Listener certificates on ALBs, ACM-managed certificates, automatically renewed.

**At rest.** EBS volumes encrypted with KMS. S3 server-side encryption (SSE-S3 or SSE-KMS). RDS encryption at the instance level — enables encryption for storage, automated backups, snapshots, and read replicas. Enable at creation; enabling encryption on an existing unencrypted RDS instance requires a snapshot, restore to new encrypted instance, cutover.

Default encryption matters. Enable default EBS encryption per region. Enable default S3 bucket encryption per account. These settings mean any new resource created without explicit encryption configuration gets encryption by default, eliminating the human error of "I forgot to check the encryption box."

## Operations

### Security group sprawl

Security groups accumulate. New service gets deployed, someone creates a new security group, adds rules, and forgets to clean it up when the service is decommissioned. After a year, there are security groups with no attached resources, security groups with overly permissive rules added "temporarily" for debugging, and rules that reference security groups which no longer exist.

Audit regularly. AWS Config rules can detect security groups with unrestricted inbound access (`0.0.0.0/0` on non-public ports). `aws ec2 describe-security-groups` with filters to find unused groups. Tag security groups with the service and team that owns them — makes the audit conversation straightforward.

The most common overly permissive rule: `0.0.0.0/0` on port 22 (SSH) or port 3389 (RDP) left open from a debugging session. These should be alarmed on, not just audited periodically.

### VPC Flow Logs

Flow logs record metadata about every network connection in a VPC — source IP, destination IP, port, protocol, bytes, packets, accept/reject. Not payload content. Metadata only.

They answer: did this connection happen, and was it allowed or rejected? Invaluable for security investigations ("did this compromised instance make outbound connections to unexpected IPs?") and for debugging security group rules ("why is this connection being rejected?").

Flow logs go to CloudWatch Logs or S3. CloudWatch Logs Insights queries are fast for operational debugging. S3 with Athena is better for bulk analysis and retention of long-term audit history. The cost is non-trivial in high-traffic VPCs — consider logging rejected traffic only, or sampling, if full logging is prohibitively expensive.

### Private endpoints

By default, AWS service API calls (S3, DynamoDB, SSM, Secrets Manager, etc.) from inside a VPC route through the public internet. The traffic leaves the VPC, hits the AWS public endpoint, returns. This has two problems: latency over the public path, and exposure — if the instance's outbound internet access is compromised, AWS API calls are observable.

VPC Endpoints keep this traffic entirely within the AWS network, never touching the public internet.

**Gateway endpoints.** Free. Available for S3 and DynamoDB only. Route table entries direct traffic to the endpoint rather than the internet gateway.

**Interface endpoints (AWS PrivateLink).** Elastic network interfaces inside the VPC, one per AZ. Available for most AWS services and third-party services. Charged per hour and per GB processed. For a service making frequent calls to Secrets Manager, SSM Parameter Store, or ECR (container image pulls), interface endpoints reduce latency and eliminate the internet path.

In a VPC with no internet gateway — common for sensitive workloads — interface endpoints are required for any AWS service the workload needs to call.

### Least privilege network access

Security groups should not default to "allow everything from the VPC CIDR." That's a wide blast radius. A compromised Lambda with access to the entire VPC CIDR block can reach every database, every internal API, every service on any port.

The right default: deny everything, allow explicitly. Each service's security group allows inbound only from the specific security groups of the services that need to call it. Outbound rules are similarly specific. A database security group allows inbound port 5432 from the application security group. Not from the VPC. Not from the internet.

This requires discipline at deployment time — updating security group references when a new calling service is added — but limits the blast radius of a compromise to the specific access that service had been explicitly granted.

## Deep Dive: network security on AWS

**AWS Network Firewall.** Stateful, managed firewall for VPC-level inspection. Sits inline in the network path. Supports Suricata-compatible rules for intrusion detection and prevention. Traffic passes through before reaching downstream resources. Use for: blocking known-bad domains, inspecting egress traffic for data exfiltration patterns, enforcing that workloads don't make unexpected outbound calls.

Positioned in a dedicated firewall subnet. Traffic routing: internet-bound traffic routes to the firewall first, then to the internet gateway. Implementation requires route table changes and a transit gateway or firewall VPC for hub-spoke network designs.

**WAF (Web Application Firewall).** Layer 7 protection for ALB, API Gateway, CloudFront, and AppSync. Managed rule groups for OWASP Top 10, known bad IPs, bot detection. Rate-based rules per IP. Custom rules matching request attributes. WAF is not a network firewall — it inspects HTTP, not raw IP packets.

**AWS Shield.** DDoS protection. Standard is free and automatic for all AWS customers — protects against common network and transport layer attacks. Shield Advanced adds detection and mitigation for more sophisticated attacks, 24/7 DDoS response team access, cost protection for scaling events caused by attacks, and Route 53 DNS-level protection.

**GuardDuty.** Threat detection service. Analyzes CloudTrail, VPC Flow Logs, and DNS logs for malicious activity patterns — port scanning, unusual API calls, connections to known malicious IPs, cryptocurrency mining patterns, data exfiltration. Generates findings that require action. Not a prevention control — it detects, it doesn't block. Combine with automated remediation: GuardDuty finding → EventBridge rule → Lambda that quarantines the instance.

**IAM + resource policies as network complements.** Network controls are one layer. IAM is another. S3 bucket policies can restrict access to specific VPCs using `aws:SourceVpc` conditions. DynamoDB resource policies can restrict to specific VPC endpoints. Layering network controls and IAM controls means both must be satisfied — an attacker who bypasses a security group still faces IAM authorization.

| Control | Layer | Stateful | Scope | Best for |
|---|---|---|---|---|
| Security groups | Instance (ENI) | Yes | Per resource | Service-to-service access control |
| NACLs | Subnet | No | Per subnet | Subnet boundary enforcement, IP blocking |
| Network Firewall | VPC | Yes | VPC-wide | Deep packet inspection, egress control |
| WAF | Application (HTTP) | Yes | ALB/CF/APIGW | OWASP rules, bot protection, rate limiting |
| PrivateLink/VPC Endpoints | Network path | N/A | Per service | Eliminating public internet for AWS API calls |

## What's next

Day 24: capacity planning — how to size a system before it falls over, translating business requirements into infrastructure numbers, and the forecasting methods that are actually useful versus the ones that look rigorous and aren't.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
