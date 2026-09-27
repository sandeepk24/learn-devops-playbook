# Upgrading an EKS cluster

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#Upgrades`

An EKS upgrade is one minor version of the control plane, then the nodes, with the add-ons at versions that minor accepts. EKS will not skip minors. The API stays up. What fails is a workload using an API the minor removed, a node group that cannot drain, or an add-on config that was only on the live object.

The clock is the support calendar. Fourteen months of standard support at $0.10 per cluster-hour, twelve months of extended support at $0.60, then an automatic upgrade if you still have not moved. The upgrade policy is in the [control plane note](./eks-control-plane-what-you-own.md). `EXTENDED` buys a window. It does not buy an indefinite stay.

---

## Order

Kubelet may trail the API server. It may not lead it. Since the 1.28 skew policy the trail is three minors. EKS enforces the skew it documents and rejects a control plane update when your nodes are outside it. I do not plan to use the three-minor gap. Nodes finish in the same window as the control plane.

Add-ons are stricter than kubelet skew. The VPC CNI, kube-proxy, and CoreDNS each have a minimum version for the target minor. Upgrade insights are how EKS tells you about that minimum, and about deprecated APIs still in the cluster.

The order I use:

1. Read the EKS release notes for the target minor. Not the upstream Kubernetes blog alone. EKS adds its own changes to the VPC CNI, IAM, and the AMI.
2. Run upgrade insights. Fix deprecated APIs before the control plane moves. A removed API fails closed when the apiserver bumps, often as an operator or a CRD that can no longer reconcile.
3. If an insight says an add-on is below the minimum for the target, upgrade that add-on on the current minor and let the DaemonSet settle. Configuration comes from git. The [add-on note](./eks-addons.md) is why `OVERWRITE` without git is how you lose prefix delegation in the same change.
4. Make sure a drain can finish. PodDisruptionBudgets, single-replica deployments, and Karpenter budgets are the usual blockers. [Scheduling](./pending-pods-pdbs-and-spread.md) has the PDB I actually want. A Karpenter pool with a business-hours budget of zero will not drift nodes until the budget opens. Either open it or do the node roll another way.
5. Update the control plane by one minor. Wait until the cluster is `ACTIVE`.
6. Roll nodes to an AMI built for that minor. Managed node groups: update the group. Karpenter: change the pinned AMI alias and let drift replace nodes inside the budget.
7. Restart Fargate pods so they come back on a platform version that matches. Fargate does not have an AMI for you to pin.
8. Upgrade the remaining add-ons, then the Helm-managed controllers (load balancer controller, Karpenter, ExternalDNS, anything with a CRD) to versions that state support for the minor you are on.

```bash
aws eks list-insights --cluster-name app
aws eks describe-insight --cluster-name app --id <insight-id>
```

The insight I do not skip is deprecated API use. `kubectl get` on the objects it names, in the namespaces it names. Fix the manifests in git. Deleting a live object that git will recreate is not a fix.

```bash
aws eks update-cluster-version \
  --name app \
  --kubernetes-version 1.35

aws eks list-updates --name app
aws eks describe-update --name app --update-id <update-id>
aws eks wait cluster-active --name app
```

`wait cluster-active` can sit there for half an hour or more. A second `update-cluster-version` because the first one "seems stuck" gives you a second update to unwind. Read `describe-update`. `UPDATING` with no errors is the control plane moving. Errors in that object are the thing to act on.

Do not update the AMI first. A kubelet newer than the API server is outside skew. Control plane, then nodes.

---

## Nodes

Managed node group, EKS-optimized AMI: an update rolls instances under `maxUnavailable`. If the group is at min size and a PDB refuses eviction, the update waits until it times out, and you have a group on two versions. Raise surge (`maxUnavailable` stays 1, max size has room, and the cluster has subnet IPs and EC2 quota) or fix the PDB. Do not set max unavailable to the size of the group to force it through.

Karpenter: pin `amiSelectorTerms.alias` to the new AMI and let drift do the replacement. `@latest` will also move, at whatever hour AWS publishes, which is not your change window. The [Karpenter note](./karpenter-on-eks.md) has the budget I use so this does not happen at 14:00 UTC on a weekday unless I meant it to.

Confirm after the roll:

```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,KUBELET:.status.nodeInfo.kubeletVersion
aws eks describe-cluster --name app --query 'cluster.version' --output text
```

Every kubelet should be the minor you just installed, or at worst still inside skew because a PDB blocked one node. A blocked node is a finish-the-drain task, not a new normal.

---

## What I run before production

One non-production cluster with the same add-ons, the same CNI config, and the same CRDs, already on the target minor, for at least a few days. The failures that show up are deprecated APIs in a Helm chart you forgot, a webhook that does not start on the new minor, and a DaemonSet that needed a new IAM action. Those are cheap there.

In-place is the default. A second cluster, cut over with DNS or the load balancer, is for a change you cannot roll back inside the cluster: a CNI you are leaving, an IPv6 decision, a list of removed APIs you will not fix in time. It doubles the control plane and the data plane until you cut. I do not do it because an in-place upgrade feels tense. They all feel tense. The insights API exists so the tension is not a surprise.

---

## After

```bash
kubectl get nodes
kubectl -n kube-system get pods
aws eks describe-cluster --name app --query 'cluster.{version:version,status:status}'
```

Watch error rate and p99 on the load balancer for the length of a normal deploy, not for thirty seconds. A control plane blip during the update is expected. A sustained 5xx after the nodes have rolled is a workload or an add-on, and the newest DaemonSet is the first place I look.

Write down the AMI alias and the add-on versions that survived. The next upgrade starts from that, not from memory.
