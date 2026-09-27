# EKS compute: node groups, Fargate, Auto Mode

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#EC2` `#Fargate` `#Karpenter`

The control plane does not run your pods. Something else has to, and that choice is expensive to unwind if you pretend it is temporary. This is the decision, before any manifest.

Related: [control plane](./eks-control-plane-what-you-own.md), [Karpenter](./karpenter-on-eks.md), [pod IPs](./vpc-cni-pod-ips.md).

---

## The four options that are actually different

| Option | Who patches the node | How capacity appears | What you give up |
|---|---|---|---|
| Managed node group | AWS, on your update | An Auto Scaling group of one instance type (or a short list) | Bin-packing. One group is one shape. |
| Self-managed nodes | You | Whatever you launch | Your weekends, unless you already operate AMIs |
| Fargate | AWS | A profile matches namespace and labels, then a pod gets a microVM | DaemonSets, GPUs, host networking, cheap steady state |
| EKS Auto Mode | AWS | Karpenter-style NodePools, Bottlerocket, AWS-owned controller | SSH, custom AMIs, and you pay a management fee on top of EC2 |

Karpenter is not a fifth launch type. It is a controller you run, usually beside a small managed node group that exists only to host it. [That setup](./karpenter-on-eks.md) is the one I use when Auto Mode's fee is larger than the time I spend on the controller.

Cluster Autoscaler is the older controller for managed node groups. It changes the Auto Scaling group's desired count. It cannot change instance family. Karpenter can. Do not point both at the same nodes.

---

## Managed node groups

Use them for a known shape: the system pool that runs CoreDNS, the VPC CNI, and Karpenter, or a workload that must be a specific instance type and must not be consolidated out from under you.

The settings that matter:

- At least two nodes, across AZs, for anything you cannot tolerate losing during a drain.
- `updateConfig.maxUnavailable = 1`, or a percentage you have done the arithmetic on. A group of two with `maxUnavailable` of 1 is a rolling update. A group of two with `maxUnavailablePercentage` of 50 is the same. A group of two with max unavailable equal to the group size takes the service down.
- AMI: AL2023, or Bottlerocket if you do not need a custom bootstrap. Do not start a new group on Amazon Linux 2.
- A launch template when you need IMDSv2 hop limit, a larger root volume, or extra kubelet config. The console defaults are how pods inherit the node role.

IMDSv2 is the one I set explicitly. Hop limit 2 lets a pod on the node call the instance metadata service and assume the node role. Hop limit 1 stops that, because the packet from the pod is a second hop. Pods that need AWS call [Pod Identity](./eks-pod-identity.md) or [IRSA](./irsa-explained-real-eks-workloads.md).

```hcl
resource "aws_eks_node_group" "system" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "system"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = module.vpc.private_subnets
  instance_types  = ["m6i.large"]
  ami_type        = "AL2023_x86_64_STANDARD"

  scaling_config {
    min_size     = 2
    desired_size = 2
    max_size     = 4
  }

  update_config {
    max_unavailable = 1
  }

  taint {
    key    = "CriticalAddonsOnly"
    value  = "true"
    effect = "NO_SCHEDULE"
  }

  launch_template {
    id      = aws_launch_template.system.id
    version = aws_launch_template.system.latest_version
  }
}
```

```hcl
metadata_options {
  http_endpoint               = "enabled"
  http_tokens                 = "required"
  http_put_response_hop_limit = 1
}
```

Graviton (`AL2023_ARM_64_STANDARD`, m7g, c7g) is fine when every image is multi-arch. One amd64-only image and the pod fails with `exec format error`, which looks like a bad image and is actually the architecture. If you cannot prove the images are multi-arch, stay on x86_64.

Spot on a managed node group is an Auto Scaling group capacity type. Interruptions are real, the replacement is the same instance type, and you do not get Karpenter's consolidation. I use spot through Karpenter, not through a managed group, unless the workload is already fault-tolerant and I do not want another controller.

Node IAM is `AmazonEKSWorkerNodePolicy` and `AmazonEC2ContainerRegistryReadOnly`. `AmazonEKS_CNI_Policy` stays on the node only until the VPC CNI runs with its own service account. After that, take it off the node role. A pod that escapes onto the node role should not be able to create ENIs in the account.

---

## Fargate

A Fargate profile is a namespace plus optional label selectors. A pending pod that matches runs on Fargate. A pod that matches nothing stays pending until a node can take it.

What is not available, and will not become available by adding a flag:

- DaemonSets. No node exporter, no the VPC CNI you manage, no a logging agent on the node. Logging is the pod's stdout to CloudWatch, or a sidecar you accepted on purpose.
- Privileged ports, hostPath, hostNetwork, GPU.
- Security groups live on the pod. There is no node security group to hide behind.

Fargate is the right pool for a job that should be isolated and is not worth a node, and for a Karpenter controller if you refuse to keep a managed group alive just for it. It is the wrong pool for a high-throughput service you will run every hour of the month. You pay for the pod's requests for the life of the pod, and the cold start is slower than scheduling onto a node that is already there.

Profiles select. They do not reserve. An empty profile costs nothing. A profile that accidentally matches every pod in a namespace will silently move that namespace off your nodes the next time something is scheduled. Read the selectors after you apply them.

```bash
aws eks create-fargate-profile \
  --cluster-name app \
  --fargate-profile-name jobs \
  --pod-execution-role-arn arn:aws:iam::111122223333:role/eks-fargate-pod-execution \
  --subnets subnet-priv-a subnet-priv-b subnet-priv-c \
  --selectors namespace=batch,labels={workload=fargate}
```

The pod execution role needs ECR pull and log writes. It is not the application's AWS identity.

---

## EKS Auto Mode

Auto Mode is managed Karpenter, plus the load balancer controller, the EBS CSI driver, Pod Identity, and the core add-ons, run by AWS. Nodes are Bottlerocket. You do not SSH to them. You do not pick the AMI.

The NodePool API is still `karpenter.sh/v1`. The class is not Karpenter's `EC2NodeClass`. Auto Mode uses `NodeClass` in group `eks.amazonaws.com`.

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: general
spec:
  template:
    spec:
      nodeClassRef:
        group: eks.amazonaws.com
        kind: NodeClass
        name: default
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
        - key: eks.amazonaws.com/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
  limits:
    cpu: "200"
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 15m
    budgets:
      - nodes: "10%"
```

Labels are prefixed `eks.amazonaws.com/`, not `karpenter.k8s.aws/`. A nodeSelector copied from a self-managed Karpenter cluster will sit Pending forever. The API group on `nodeClassRef` is the other silent mismatch.

You pay EC2, and you pay an Auto Mode management fee that depends on instance type and region. The fee is independent of Reserved Instances, Savings Plans, and Spot. Those discounts apply to the EC2 line, not to the Auto Mode line. Look up the rate before you move a large steady-state cluster. On a small platform team, the fee is often cheaper than operating Karpenter, the AMI pipeline, and the add-on versions. On a large one, do the multiplication.

Auto Mode does not remove PodDisruptionBudgets, topology spread, or bad requests. It removes the controller hosting problem. Workloads still need the scheduling note.

---

## What I run

A platform team that wants one less system: Auto Mode, on-demand for the request path, spot only for batch pools with disruption budgets and a real retry story.

A platform team that already operates Karpenter well: a managed system node group, tainted, hop limit 1, two or three nodes, and Karpenter for everything else. Fargate only for the odd job.

Self-managed nodes when there is a kernel, a GPU driver, or a compliance AMI that neither AL2023 nor Bottlerocket will carry. That is a reason. "We have always launched ASGs" is not.

---

## The bill, since compute is where it hides

The control plane fee is the small line. The large lines are:

- NAT gateway hours and NAT data processing, for every image pull and every AWS API call that did not go to a VPC endpoint.
- Cross-AZ traffic. A Service that is not topology-aware will happily send to a pod in another zone, and you pay for it. The [CNI note](./vpc-cni-pod-ips.md) and topology spread are the controls.
- Idle nodes. A managed group with `desired` above what the pods need is a standing charge. Karpenter consolidation exists because of this. Auto Mode consolidation exists for the same reason. A group with min size 10 "just in case" is the case.
- One load balancer per Service. [Ingress groups](./aws-alb-nlb-ingress-eks-deep-dive.md) exist so you do not do that.
- Extended support, if you stopped upgrading.

I look at those five before I look at Graviton.
