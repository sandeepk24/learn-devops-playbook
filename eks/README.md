# EKS

Notes on running Kubernetes on Amazon EKS.

If you're new to this, start with [Starting on EKS](./eks-for-devops-engineers-beginners-guide.md). Control plane versus nodes, the objects you'll touch, and how to read a stuck deploy. The rest of the folder assumes you can already ship a Deployment.

Read the cluster notes if you are building one or inheriting one. The older notes on ingress, IRSA, and crash loops are the ones to open when that specific thing is already on fire.

## Start here

| Note | What's in it |
|---|---|
| [Starting on EKS](./eks-for-devops-engineers-beginners-guide.md) | The objects, the daily commands, and which statuses mean the container never started. |

## The cluster

| Note | What's in it |
|---|---|
| [What you still own on the control plane](./eks-control-plane-what-you-own.md) | Endpoint access, version support and the hourly rate, secret encryption, and which logs are worth the CloudWatch bill. |
| [Compute: node groups, Fargate, Auto Mode](./eks-compute-node-groups-fargate-auto-mode.md) | Which launcher you are actually choosing, IMDSv2 hop limit, and where the bill hides. |
| [Karpenter](./karpenter-on-eks.md) | Where the controller runs, pinned AMIs, disruption budgets, and the NodeClaim error that is really a quota. |
| [VPC CNI and pod IPs](./vpc-cni-pod-ips.md) | Warm pools, prefix delegation, custom networking, and `failed to assign an IP address`. |
| [Add-ons](./eks-addons.md) | vpc-cni, kube-proxy, CoreDNS, and why add-on config belongs in git. |
| [Upgrades](./eks-upgrades.md) | One minor at a time, insights before the API bump, control plane before nodes. |

## Identity

| Note | What's in it |
|---|---|
| [Access entries](./eks-access-entries.md) | Replacing `aws-auth`, namespace-scoped deploy roles, and the node role entry that is not cluster admin. |
| [Pod Identity](./eks-pod-identity.md) | Associations, the trust policy, and the cross-account hop. |
| [IRSA](./irsa-explained-real-eks-workloads.md) | The OIDC path, for clusters that already have it, with the workload policies. |
| [Security defaults](./eks-security-defaults.md) | Hop limit, Pod Security Admission, and the IAM actions that do not belong on the node role. |

## Workloads

| Note | What's in it |
|---|---|
| [Pending pods, PDBs, and spread](./pending-pods-pdbs-and-spread.md) | Requests versus limits, a disruption budget a drain can satisfy, and how to read a scheduling event. |
| [Storage choices](./eks-storage-choices.md) | emptyDir, EBS and the AZ pin, EFS when it is actually shared. The long EBS walkthrough is [in the AWS notes](../aws/ebs-volumes-on-eks-the-complete-guide-for-devops-engineers.md). |
| [ALB, NLB, and Ingress](./aws-alb-nlb-ingress-eks-deep-dive.md) | How traffic reaches a pod, target type, and security groups for pods. |
| [CrashLoopBackOff, part 1](./crashloopbackoff-part1-foundations.md) | The backoff, and the first causes. |
| [CrashLoopBackOff, part 2](./crashloopbackoff-part2-advanced.md) | Init containers, IRSA failures, volumes, and the rest. |
| [`kubectl rollout status`](./kubectl-rollout-status-is-underrated.md) | The check between "apply succeeded" and "the new pods are ready." |

Dashboards for the data plane are in [CloudWatch dashboard design for EKS](../sre/cloudwatch-dashboard-design-for-eks.md).
