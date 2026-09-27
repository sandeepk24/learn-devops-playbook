# What you still own on an EKS control plane

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#AWS` `#Kubernetes`

AWS runs the API server, etcd, the scheduler, and the controller manager. You do not size those processes, you do not snapshot etcd, and you do not patch the API server yourself. The hourly charge for that is $0.10 per cluster while the minor version is in standard support, and $0.60 once it falls into extended support.

What is left is the part that decides whether the cluster is reachable, debuggable, and safe to upgrade. This note is that list.

Related: [compute](./eks-compute-node-groups-fargate-auto-mode.md), [access](./eks-access-entries.md), [upgrades](./eks-upgrades.md), [security defaults](./eks-security-defaults.md).

---

## The boundary

| AWS operates | You operate |
|---|---|
| API server, etcd, scheduler, controller manager | Endpoint exposure, and who can reach it |
| Control plane upgrades, when you ask, one minor at a time | When you ask, and whether nodes and add-ons can follow |
| etcd durability inside the control plane | Git as the source of manifests, and snapshots of your volumes |
| The Kubernetes version calendar | `STANDARD` vs `EXTENDED` upgrade policy |

etcd in EKS is not your datastore to back up. If the control plane is gone as an AWS incident, you recreate the cluster and reapply what is in git. Anything that lived only in etcd — a hand-edited ConfigMap, a Secret never stored elsewhere — is gone. Treat the API as a projection of git, not as the system of record.

---

## Endpoint access

Three settings, and they are easy to get wrong in combination.

| Setting | What it does |
|---|---|
| `endpointPublicAccess` | The API has a public endpoint. |
| `endpointPrivateAccess` | The API is also (or only) reachable from inside the VPC, via elastic network interfaces AWS places in your subnets. |
| `publicAccessCidrs` | The only public CIDRs allowed to call the public endpoint. Default is `0.0.0.0/0`. |

A cluster I will run:

- Private access on.
- Public access on only if something outside the VPC must call the API, and then `publicAccessCidrs` is the corporate egress or the CI NAT, not the internet.
- Nodes in private subnets. They join through the private endpoint. They do not need the public one.

Public access with `0.0.0.0/0` means every scanner on the internet can hit the API. Authentication still has to succeed. That is not the same as the endpoint being unauthenticated, and it is still a bad default. Kubernetes APIs get probed constantly. Keep the unauthenticated surface small.

Private-only is the cleaner end state. The cost is operational: `kubectl` from a laptop works only over VPN, Direct Connect, or a bastion, and GitHub-hosted runners cannot see the endpoint. Put the runner in the VPC, or keep a tight public CIDR for CI. Decide that before you turn public access off, or the next pipeline goes red and someone turns `0.0.0.0/0` back on under pressure.

```bash
aws eks update-cluster-config \
  --name my-cluster \
  --region us-east-1 \
  --resources-vpc-config \
    endpointPublicAccess=true,endpointPrivateAccess=true,publicAccessCidrs=203.0.113.10/32
```

This update replaces the CIDR list. It does not merge. Read the current config, then send the full list you intend to keep.

---

## The VPC has to work before any node joins

Nodes pull images and call AWS APIs. If they sit in private subnets, that traffic goes through a NAT gateway or through VPC endpoints. A private cluster with neither will join the API and then stick in `ContainerCreating` or fail image pulls. The CNI's own failures look similar. Check the path before you blame kubelet.

For a cluster that should keep working with the NAT gateway down, I want interface endpoints for:

- `ecr.api` and `ecr.dkr` (image manifests and layers)
- `sts` (IRSA and Pod Identity)
- `ec2` (the VPC CNI attaches ENIs)
- `logs` if the control plane or apps write to CloudWatch

and a gateway endpoint for `s3`, because ECR layers live in S3. Add `autoscaling` if you run Cluster Autoscaler, and `sqs` if Karpenter is consuming a spot interruption queue.

The EKS API for nodes is the cluster endpoint, not the public `eks` service endpoint. Private access is what places that endpoint in the VPC. Security groups on the cluster must allow 443 from the node security group. Managed node groups do this when AWS creates the cluster security group and you have not replaced it with something tighter that forgot 443.

Subnet tags still matter, and they are not optional decoration:

| Tag | Where |
|---|---|
| `kubernetes.io/cluster/<name> = shared` or `owned` | Every subnet the cluster uses |
| `kubernetes.io/role/internal-elb = 1` | Private subnets for internal load balancers |
| `kubernetes.io/role/elb = 1` | Public subnets for internet-facing load balancers |

The load balancer controller discovers subnets by these tags. Untagged subnets produce a controller error, not a default that happens to work. The [ingress note](./aws-alb-nlb-ingress-eks-deep-dive.md) covers what the controller builds after discovery succeeds.

Use at least three Availability Zones. Two zones means one zone failing removes half the capacity. Three zones removes a third, which is what PodDisruptionBudgets and topology spread are sized for.

---

## Version support is a billing decision

Each minor is in standard support for 14 months after EKS releases it, then extended support for 12 months. Extended support is the $0.60 rate. At the end of extended support, EKS upgrades the cluster for you.

The cluster upgrade policy chooses the behavior at the end of standard support:

| Policy | What happens |
|---|---|
| `STANDARD` | EKS auto-upgrades the control plane to the next supported minor. You do not pay the extended rate. You also do not pick the hour. |
| `EXTENDED` | The cluster stays, at $0.60 per hour, until extended support ends. Then it is auto-upgraded anyway. |

```bash
aws eks describe-cluster --name my-cluster \
  --query 'cluster.{version:version,policy:upgradePolicy.supportType}'

aws eks update-cluster-config \
  --name my-cluster \
  --upgrade-policy supportType=STANDARD
```

`EXTENDED` is for a real constraint: a vendor image, a deprecated API you have not finished removing, a change window you do not control. It is an expensive pause, not a strategy. The calendar moves whether or not you look at it. [Upgrades](./eks-upgrades.md) is the order of operations. Check dates with `aws eks describe-cluster-versions --include-all` rather than a table copied into a repo.

---

## Encrypt Kubernetes secrets with a key you control

EKS can envelope-encrypt Kubernetes Secret objects with a KMS key. etcd is already encrypted on the AWS side. This is a second layer, so a snapshot or a backup of etcd is not readable without your key, and so key use shows up in CloudTrail.

Turn it on at create time. Enabling it later is `aws eks associate-encryption-config`, and secrets written before that stay plaintext until something rewrites them. Rewriting every secret in the cluster is a production change, not a flag.

The failure mode on enable is a cluster update stuck in `FAILED` because the key policy does not allow `eks.amazonaws.com` to use the key. Use the key policy in the EKS envelope-encryption docs. Do not attach a wide `kms:*` to the node role and call that done. Nodes do not decrypt secrets. The API server does.

Secrets in etcd are still base64 in the API response to anyone who can `kubectl get secret`. Encryption at rest does not replace RBAC.

---

## Control plane logs

Five log types, all off by default, all billed as CloudWatch Logs once you enable them:

| Log | Keep it on? |
|---|---|
| `audit` | Yes. Who did what to the API. |
| `authenticator` | Yes. IAM to Kubernetes identity mapping failures show up here, not in the workload logs. |
| `api` | Only while you are chasing an API problem. High volume. |
| `controllerManager` | Rarely. You do not run those controllers. |
| `scheduler` | Rarely. Same reason. |

```bash
aws eks update-cluster-config \
  --name my-cluster \
  --logging '{"clusterLogging":[{"types":["audit","authenticator"],"enabled":true}]}'
```

That call sets the enabled types to exactly the list you send. If you later enable `api` and omit `audit`, you turn audit off.

`authenticator` is the log I open when a node will not join or an IAM principal gets a 401 that RBAC cannot explain. Access entries and the old `aws-auth` ConfigMap both surface there. See [access entries](./eks-access-entries.md).

Dashboard layout for the data plane is a separate note: [CloudWatch dashboards for EKS](../sre/cloudwatch-dashboard-design-for-eks.md).

---

## Cluster IAM role

The cluster role is what the control plane assumes. `AmazonEKSClusterPolicy` is the policy. It is not a place to hang application permissions, and it is not AdministratorAccess.

Application permissions go to Pod Identity or IRSA. Node permissions go to the node role, and even that role should be thin once the VPC CNI has its own service account. Both are covered later. The cluster role stays boring.

---

## A create that does not need a rescue later

```hcl
resource "aws_eks_cluster" "this" {
  name     = "app"
  version  = "1.35"
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = module.vpc.private_subnets
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = ["203.0.113.10/32"]
    security_group_ids      = [aws_security_group.cluster.id]
  }

  encryption_config {
    resources = ["secrets"]
    provider {
      key_arn = aws_kms_key.eks.arn
    }
  }

  access_config {
    authentication_mode                         = "API_AND_CONFIG_MAP"
    bootstrap_cluster_creator_admin_permissions = true
  }

  upgrade_policy {
    support_type = "STANDARD"
  }

  enabled_cluster_log_types = ["audit", "authenticator"]
}
```

`bootstrap_cluster_creator_admin_permissions = false` on a cluster whose authentication mode is `API` creates a control plane nobody can call. The creator is not special unless that flag, or a later access entry, says so. Leave it true until access entries exist for the break-glass role. Then you can take the creator off cluster-admin.

Pin `version` to a minor you have actually read the EKS release notes for. Do not track "latest" from Terraform. A plan that bumps the minor is a change window, not a refresh.

---

## What I check after create

```bash
aws eks describe-cluster --name app \
  --query 'cluster.{version:version,endpoint:endpoint,public:resourcesVpcConfig.endpointPublicAccess,private:resourcesVpcConfig.endpointPrivateAccess,cidrs:resourcesVpcConfig.publicAccessCidrs,logs:logging.clusterLogging,upgrade:upgradePolicy.supportType}'
```

Then, from a network that should be allowed:

```bash
aws eks update-kubeconfig --name app --region us-east-1
kubectl get ns
kubectl auth can-i '*' '*'
```

If `update-kubeconfig` works and `kubectl` times out, it is the endpoint or the security group, not IAM. If `kubectl` returns `Unauthorized`, it is the authenticator: access entries, `aws-auth`, or the caller is a role you did not map. IAM `Allow eks:*` does not grant Kubernetes API access. Those are different planes.
