# EKS add-ons that take the cluster down

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#Addons` `#VPC-CNI`

EKS add-ons are the AWS-packaged installs of components you would otherwise run yourself. The dangerous ones are the three the data plane needs before a pod can start and be found: the VPC CNI, kube-proxy, and CoreDNS. Everything else can be down and the cluster is degraded. Those three can be down and the cluster is a control plane with nowhere to put work.

Related: [pod IPs](./vpc-cni-pod-ips.md), [upgrades](./eks-upgrades.md), [Pod Identity](./eks-pod-identity.md).

---

## What I install on purpose

| Add-on | Why it is here |
|---|---|
| `vpc-cni` | Pod IPs. Managed so the version tracks the cluster. |
| `kube-proxy` | ClusterIP and NodePort. Still required for east-west Service traffic. |
| `coredns` | Cluster DNS. |
| `eks-pod-identity-agent` | If pods assume IAM roles this way. |
| `aws-ebs-csi-driver` | If anything uses EBS. The controller needs its own IAM role. |
| `aws-efs-csi-driver` | Only if you have a real ReadWriteMany case. |

The AWS Load Balancer Controller and Karpenter are not in that list. I run them from their Helm charts, pinned, because that is how their config is actually documented. You can wrap some of them as add-ons. Pick one install path. An add-on and a Helm release managing the same DaemonSet will overwrite each other and you will lose a weekend to it.

GuardDuty and the CloudWatch observability add-on are optional and belong to the security and dashboard notes, not to cluster boot.

---

## Version and configuration live in git

`latest` is not a version. Add-on versions look like `v1.19.2-eksbuild.1` and they are compatible with a specific set of Kubernetes minors. Ask EKS. Do not copy a version out of a year-old snippet.

```bash
aws eks describe-addon-versions \
  --addon-name vpc-cni \
  --kubernetes-version 1.35 \
  --query 'addons[].addonVersions[].addonVersion'
```

Configuration has a schema per version. Pass the version the previous command returned:

```bash
aws eks describe-addon-configuration \
  --addon-name vpc-cni \
  --addon-version <version-from-describe-addon-versions>
```

Pass values that match that schema. For the CNI, environment variables are the lever for prefix delegation and the warm pool:

```bash
aws eks create-addon \
  --cluster-name app \
  --addon-name vpc-cni \
  --addon-version <version-from-describe-addon-versions> \
  --service-account-role-arn arn:aws:iam::111122223333:role/AmazonEKS_CNI_Role \
  --resolve-conflicts OVERWRITE \
  --configuration-values '{"env":{"ENABLE_PREFIX_DELEGATION":"true","WARM_PREFIX_TARGET":"1"}}'
```

`--service-account-role-arn` is how the CNI stops using the node role. Create that role with Pod Identity or IRSA before you point the add-on at it. If you set the role ARN and the role's trust policy is wrong, new pods stop getting IPs. Have the node role's CNI policy still attached the first time you roll a node, confirm the DaemonSet's identity with logs, then remove `AmazonEKS_CNI_Policy` from the node role.

---

## OVERWRITE, not a hand edit

| `resolve-conflicts` | Behavior |
|---|---|
| `NONE` | The update fails if the live object differs from the add-on. |
| `PRESERVE` | Keeps your kubectl edits. The update can still fail, or succeed and leave you running a config the next person cannot see. |
| `OVERWRITE` | The add-on config wins. |

I use `OVERWRITE` and I keep `configurationValues` in Terraform or in the repo that applies the add-on. `kubectl set env daemonset aws-node` is how prefix delegation gets turned on in an incident and turned off at the next add-on bump. If you must edit live, put the same change into the add-on config before the change window ends.

`PRESERVE` feels safer. It means production's CNI config is whatever someone typed, and git is a rumor.

---

## CoreDNS

The default is two replicas and a small memory limit. That is enough until a rollout makes every pod resolve a long list of names, or until `ndots: 5` turns one lookup into five. The symptom is `SERVFAIL` or timeouts in application logs, CoreDNS CPU pegged, and pods otherwise Ready. People restart the application. The application is waiting on DNS.

What I change, in the add-on configuration, not with a stray kubectl scale:

- Memory request and limit high enough that a traffic spike does not OOMKill CoreDNS. An OOMKill here is a cluster-wide brownout.
- A PodDisruptionBudget of `maxUnavailable: 1`, and at least two replicas on nodes that are not the same node. Topology spread across zones. If both replicas land on one node, a drain takes DNS with it.
- NodeLocal DNSCache only after you have seen CoreDNS become the bottleneck. It is another DaemonSet and another failure mode. It is the right fix when the bottleneck is real.

Do not schedule CoreDNS on spot nodes that Karpenter is free to empty during the day. A system pool, or the tainted managed group, is the place. The [Karpenter note](./karpenter-on-eks.md) has the taint.

---

## kube-proxy

Leave the mode EKS shipped. IP-mode load balancers skip kube-proxy for north-south traffic. ClusterIP between pods does not. Deleting kube-proxy because "we use the VPC CNI" breaks Service traffic inside the cluster.

If you run network policy or prefix delegation, those are CNI settings. They are not a reason to replace kube-proxy with something else in the same change.

---

## The EBS CSI driver

The controller needs IAM to create volumes, and the node plugin needs to attach them. One add-on, one role for the controller service account. Without the role, PVCs sit Pending and the event is a cloud error, not a scheduler error.

`WaitForFirstConsumer` and the AZ rule are in the [storage note](./eks-storage-choices.md). Installing the add-on does not set a sane default StorageClass by itself in every cluster. Check `kubectl get storageclass` after install. A default of `gp2`, or two classes marked default, is how a database volume lands on the wrong disk.

---

## Before you upgrade them

Add-on upgrades restart DaemonSets. A bad CNI version, or a good version with empty configuration that wipes prefix delegation, shows up as pods stuck in `ContainerCreating` on the nodes that rolled first. Upgrade one add-on, watch a node, then continue.

```bash
kubectl -n kube-system rollout status ds/aws-node
kubectl -n kube-system rollout status ds/kube-proxy
kubectl -n kube-system rollout status deploy/coredns
```

`rollout status` on a DaemonSet returns when every node that should be updated has the new pod. It does not return when the new pod is healthy if readiness is wrong. Check the logs of `aws-node` on one node after a CNI bump. Look for IP allocation errors before you update the next add-on.

Compatibility with the next Kubernetes minor is an upgrade-insight problem and a `describe-addon-versions` problem. Some control plane upgrades refuse to start until the CNI is at a minimum version. Do that minimum bump first, on the current Kubernetes version, and let it settle. The [upgrade note](./eks-upgrades.md) is the order. This note is so the minimum bump does not also change five environment variables you forgot were only on the live DaemonSet.
