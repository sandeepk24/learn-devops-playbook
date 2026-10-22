# Infrastructure as Code and GitOps

Infrastructure defined in code rather than clicked together in a console. The benefits are obvious: version history, code review, repeatability, disaster recovery. The discipline to make it work is less obvious — the same patterns that make application code maintainable apply here, and skipping them produces the same result: a codebase that works but that nobody fully understands or trusts.

GitOps extends the principle to operations. The desired state of the system lives in a Git repository. A reconciliation loop continuously compares actual state to desired state and applies corrections. The Git repository is the source of truth. Changes go through the repository, not directly to the system.

## Fundamentals

### Infrastructure as Code principles

**Declarative over imperative.** Describe what the end state should be, not the steps to get there. Terraform, CloudFormation, and Kubernetes manifests are declarative — specify the desired configuration and let the tool figure out the sequence of API calls. Imperative scripts (a bash file that calls `aws ec2 run-instances`) are fragile: they fail mid-execution and leave the system in an unknown partial state.

**Idempotent.** Applying the same configuration twice produces the same result as applying it once. Terraform's plan phase shows what will change; if nothing changed in the configuration, the plan is empty and apply does nothing. Idempotency is what makes it safe to re-run after a partial failure.

**Version controlled.** Every change to infrastructure goes through a pull request with review. The merge history is an audit log: who changed what, when, with what justification. No undocumented manual changes.

**Tested before applied.** `terraform plan` shows the diff before `apply` changes anything. Policy-as-code tools (OPA, Checkov, tfsec) catch misconfigurations before they reach production. The same review and testing discipline as application code.

### Terraform state

Terraform tracks the current state of managed resources in a state file. The state maps Terraform resource definitions to real infrastructure IDs. Without state, Terraform can't know whether a resource already exists, what its current configuration is, or what needs to change.

State is sensitive — it contains resource metadata including secrets referenced by resources. Store state in a remote backend with encryption and access controls: S3 with server-side encryption and a DynamoDB table for state locking.

State locking prevents concurrent applies from corrupting the state. Two engineers running `terraform apply` simultaneously without locking would both read the same state, both compute a plan, both apply changes, and produce a corrupted final state. DynamoDB's conditional writes provide the atomic lock mechanism.

State drift: the actual state of infrastructure diverges from Terraform's recorded state due to manual changes, external automation, or out-of-band API calls. `terraform refresh` updates state to match reality. `terraform import` brings existing resources under Terraform management. The operational discipline to prevent drift: no manual changes to Terraform-managed resources. Everything goes through the Terraform workflow.

### Module design

A Terraform module is a reusable, encapsulated unit of infrastructure. A module for an ECS service bundles the task definition, ECS service, target group, ALB listener rule, security group, and CloudWatch log group. Teams instantiate the module with parameters rather than writing each resource from scratch.

Good module design:
- **Single responsibility.** A module for a load-balanced ECS service. Not a module for "everything a team needs."
- **Versioned.** Module source pinned to a specific version tag. `source = "git::https://github.com/org/modules.git//ecs-service?ref=v2.3.0"`. Unversioned module references pick up breaking changes silently.
- **Opinionated defaults.** Sensible default values for parameters that most callers don't need to override. The calling code specifies exceptions, not boilerplate.
- **Minimal outputs.** Expose only what consumers need — ARN, name, endpoint URL. Not every internal resource attribute.

### GitOps for Kubernetes

GitOps applies particularly cleanly to Kubernetes because the desired state — Deployment manifests, ConfigMaps, Service definitions — is already declarative YAML. A GitOps controller (Argo CD, Flux) watches a Git repository and applies changes to the cluster when the repository changes.

The workflow:
1. Developer merges a change to the deployment manifest (updated image tag, resource limit change).
2. Argo CD detects the diff between the Git state and the cluster state.
3. Argo CD applies the change to the cluster.
4. If the cluster state drifts from Git (manual `kubectl apply`, someone edited a resource directly), Argo CD detects the drift and can automatically reconcile.

The key constraint: the cluster state is authoritative only if it matches the Git state. Direct `kubectl` changes to production are changes that will be overwritten by the next sync. This is the point — the repository is the only valid change mechanism.

## Operations

### Drift detection and remediation

Drift is the gap between what the code says and what the infrastructure actually is. It accumulates from manual changes, automated processes that write to infrastructure directly, and Terraform applies that partially succeeded.

Detection:
- **Terraform:** `terraform plan` in a scheduled pipeline (no apply). If the plan is non-empty, drift is present. Alert when the plan shows unexpected changes.
- **AWS Config:** continuous recording of resource configuration changes. Rules that detect deviations from expected configurations. Findings when a security group rule is added manually or an EBS volume is created without encryption.
- **Argo CD:** `OutOfSync` status on an Application resource means the cluster state doesn't match the Git state. Dashboard shows exactly which resources differ and how.

Remediation policy matters. Automatic remediation (Argo CD `selfHeal: true`) will overwrite manual changes without warning. Useful for preventing drift in production where all changes should go through Git. Dangerous if the pipeline has a bug — the loop will continuously apply a broken configuration. Set `selfHeal: true` only after the pipeline is reliable and has tested rollback.

### Secrets in IaC

Infrastructure code should not contain secrets. A database password in a Terraform variable file that's committed to Git is an immediate security incident.

Patterns that keep secrets out of code:
- **References, not values.** Terraform resources reference Secrets Manager ARNs. The secret value stays in Secrets Manager; only the reference goes in code.
- **`sops` for encrypted secrets in Git.** Secrets encrypted in the repository using AWS KMS or age. The encrypted ciphertext is safe to commit. Decryption happens at apply time on the machine or pipeline that has the KMS key.
- **External secrets operator.** In Kubernetes, the External Secrets Operator synchronizes secrets from Secrets Manager or Parameter Store into Kubernetes Secret objects. The manifest references the secret by name in Secrets Manager, not the value.

The `.gitignore` rule for `terraform.tfvars` that contains secrets is not sufficient security — the file will eventually be committed by someone. Build the workflow so the secrets never appear in files that could be committed.

### Pipeline security for IaC

Terraform apply runs with AWS credentials. Those credentials need write access to the resources Terraform manages. That's significant permission scope. The pipeline that runs Terraform is a high-value target.

Protections:
- **OIDC for CI/CD authentication.** GitHub Actions, GitLab CI, and Bitbucket Pipelines all support OIDC federation with AWS IAM. The pipeline gets a temporary role session; no long-lived credentials stored in CI secrets.
- **Separate roles for plan and apply.** Plan needs read access to query current state. Apply needs write access to make changes. The PR pipeline runs plan with a read-only role. The merge-to-main pipeline runs apply with the write role. Reviewers see the plan output in the PR; they know exactly what will change before approving.
- **Policy enforcement in the pipeline.** Checkov, tfsec, or OPA policy checks run before plan. A resource missing required tags, a security group allowing `0.0.0.0/0`, an unencrypted S3 bucket — caught in the pipeline before the plan reaches reviewers.

## Deep Dive: IaC and GitOps on AWS

**Terraform with S3 and DynamoDB backend.** The standard AWS setup. State in S3 with versioning enabled (accidental state overwrites are recoverable). DynamoDB table with `LockID` as the partition key for state locking. S3 bucket policy restricting access to the IAM roles that run Terraform. Separate state files per environment (`envs/prod/terraform.tfstate`, `envs/staging/terraform.tfstate`).

Terraform workspace vs directory-per-environment: workspaces share a backend configuration but separate state. Directories separate configuration entirely. Workspaces are appropriate when environments are structurally identical. Directories are appropriate when environments have meaningful configuration differences. For most organizations: directory-per-environment.

**AWS CDK.** Infrastructure defined in TypeScript, Python, Java, or Go rather than HCL. Compiles to CloudFormation templates. Enables infrastructure logic — conditionals, loops, abstraction patterns — that HCL makes difficult. The trade-off: CloudFormation as the execution layer, with its own constraints and slower feedback cycles compared to Terraform.

CDK Constructs are the CDK equivalent of Terraform modules. L1 constructs map directly to CloudFormation resources. L2 constructs are higher-level abstractions with sensible defaults (an `ApplicationLoadBalancedFargateService` that bundles ALB, ECS service, and related resources). L3 constructs are complete patterns — a construct that deploys a full three-tier application.

**Argo CD on EKS.** Argo CD runs as a Deployment in the cluster. Applications (Argo CD's resource type) define a source repository, a path in the repository, and a destination cluster and namespace. The sync policy controls whether sync is manual (reviewer approves in the UI) or automatic (syncs on repository change). `syncOptions: [CreateNamespace=true]` creates the namespace if it doesn't exist.

Argo CD Image Updater: watches a container registry for new image tags matching a pattern, commits the updated image tag to the Git repository, which triggers Argo CD to sync. Automates the "update image tag in deployment manifest" step of the CI/CD pipeline without requiring the CI job to have write access to the deployment repository.

**AWS Service Catalog.** Publish approved CloudFormation or Terraform templates as catalog products. Teams provision infrastructure from the catalog rather than writing IaC from scratch. Enforces organizational standards — every EC2 instance provisioned through the catalog has the required tags, the required security configuration, and is in the approved VPC configuration. Appropriate for large organizations where central platform teams need to enforce standards across many product teams without reviewing every PR.

| Approach | Execution layer | State management | Language | Best for |
|---|---|---|---|---|
| Terraform | Direct AWS APIs | S3 + DynamoDB | HCL | Multi-cloud, mature ecosystem, most organizations |
| AWS CDK | CloudFormation | CloudFormation stacks | TypeScript/Python/Go | AWS-native, imperative logic needed |
| CloudFormation | Native AWS | AWS-managed | JSON/YAML | Fully AWS-native, StackSets for multi-account |
| Pulumi | Direct APIs | Pulumi Cloud or S3 | TypeScript/Python/Go | Developer-friendly, general-purpose languages |
| Argo CD | Kubernetes API | Git | YAML | Kubernetes GitOps, continuous reconciliation |

## What's next

Day 40: incident response and post-mortems — how a well-run incident response process limits the blast radius of outages, and how post-mortems extract durable improvements rather than blame.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
