# VPC CNI and pod IPs

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#VPC` `#CNI`

On EKS the default CNI gives every pod a VPC IP. That IP comes out of the subnet the node is using for pod traffic. When the subnet runs out, scheduling still succeeds and the pod sits in `ContainerCreating` with `failed to assign an IP address to container`. The cluster looks healthy. The rollout does not.

This note is how the addresses are handed out, and the three configurations that change the math: warm pools, prefix delegation, and custom networking.

Security groups for pods are a different feature. They are covered in the [ingress note](./aws-alb-nlb-ingress-eks-deep-dive.md). Do not turn them on to fix an IP shortage. Branch ENIs lower pod density.

---

## What the CNI actually allocates

Each node has a primary ENI, used by the node, and secondary ENIs the CNI attaches. Each secondary ENI holds secondary IPs, and each secondary IP is a pod. The instance type decides how many ENIs and how many IPs per ENI. That product, minus a few reserved for the node and add-ons, is `maxPods` unless you change it.

A small instance and a large subnet can still schedule only a handful of pods per node. The subnet is not the limit you hit first. A large instance and a `/24` is the opposite problem: the node is willing, the subnet is not.

The CNI keeps a warm pool so the next pod does not wait on an EC2 `AssignPrivateIpAddresses` call. The warm pool is unused addresses you are paying for in CIDR space. On a quiet node that is a few IPs. Across a hundred nodes it is a subnet.

| Variable | Effect |
|---|---|
| `WARM_ENI_TARGET` | How many spare ENIs to keep attached. The old default behavior. Wastes the most addresses. |
| `WARM_IP_TARGET` | How many spare IPs to keep ready. |
| `MINIMUM_IP_TARGET` | How many IPs to pre-allocate even if no pod needs them yet. |
| `WARM_PREFIX_TARGET` | How many spare `/28` prefixes to keep, once prefix delegation is on. |

`WARM_IP_TARGET` or `MINIMUM_IP_TARGET` overrides `WARM_PREFIX_TARGET`. Set one strategy, not all of them, and write down which.

I start with prefix delegation for any cluster that will run more than a few dozen pods per node, and I size subnets for prefixes rather than for pods.

---

## Prefix delegation

A prefix is a `/28`: 16 addresses, allocated as a unit. Nitro instance types can hold far more pod IPs this way than with secondary IPs. The cost is waste and blast radius. One warm prefix on a node that runs two pods is 16 addresses gone. A leaked warm-prefix setting across a large group empties a `/22` without a corresponding number of running pods.

```bash
kubectl set env daemonset aws-node -n kube-system ENABLE_PREFIX_DELEGATION=true
kubectl set env daemonset aws-node -n kube-system WARM_PREFIX_TARGET=1
```

Doing this with `kubectl set env` and an add-on resolve policy of `OVERWRITE` means the next add-on update deletes it. Put the values in the add-on's `configurationValues` and keep them in git. The [add-on note](./eks-addons.md) is why.

Prefix delegation does nothing useful if kubelet still advertises the old `maxPods`. The node will refuse pods while the ENI has room. On AL2023 the cap is nodeadm, not the AL2 bootstrap script:

```yaml
apiVersion: node.eks.aws/v1alpha1
kind: NodeConfig
spec:
  kubelet:
    config:
      maxPods: 110
```

Set `maxPods` from the instance types you actually run, not from a number you saw in a blog. 110 on a type that cannot hold 110 prefixes just moves the failure from the scheduler to the CNI. Karpenter sets this on the EC2NodeClass kubelet block. Managed node groups set it in the launch template user data. Existing nodes keep the old value until you replace them.

After it is on, confirm a new node has prefixes rather than a long list of secondary IPs:

```bash
aws ec2 describe-instances --instance-ids i-0123456789abcdef0 \
  --query 'Reservations[].Instances[].NetworkInterfaces[].Ipv4Prefixes'
```

---

## Custom networking

Use this when the node subnets are small and you cannot renumber them, or when you want pod IPs in a dedicated range, often a secondary CIDR such as `100.64.0.0/10` associated with the VPC.

The node keeps its IP in the node subnet. Pod IPs come from an `ENIConfig` subnet. The CNI picks the `ENIConfig` whose name matches the node's zone label. The label key defaults to `topology.kubernetes.io/zone`, so the object must be named `us-east-1a`, not `pod-subnet-a`.

```yaml
apiVersion: crd.k8s.amazonaws.com/v1alpha1
kind: ENIConfig
metadata:
  name: us-east-1a
spec:
  subnet: subnet-0abc   # pod subnet in 1a
  securityGroups:
    - sg-nodes
```

```bash
kubectl set env daemonset aws-node -n kube-system AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG=true
```

Create one `ENIConfig` per zone before you enable the flag. A node in `us-east-1c` with no matching object fails IP allocation for every pod on it.

Turn this on before the node group exists, or recycle the nodes after. The CNI does not move pods that already have addresses. Security groups in the `ENIConfig` are what pods use for VPC traffic. If those groups do not allow the load balancer, health checks fail while the pod is Ready. That looks like an ingress bug.

Pod subnets need the internal-elb tag only if you also want load balancers there. Usually you do not. They need free IPs, a route back to the node subnets, and room for prefixes if prefix delegation is also on. The two features compose. They do not replace each other.

---

## IPv6 is a create-time decision

An IPv6 EKS cluster assigns pod IPs from the VPC's IPv6 CIDR. You do not do this to an existing IPv4 cluster in place. Dual-stack application behavior, security group rules, and every `ipFamily: IPv4` Service have to be intended.

I bring it up so nobody treats it as the fix for a full IPv4 subnet. Widen the CIDR, add a secondary CIDR and custom networking, or reduce warm IPs. Those work on the cluster you have.

---

## Subnet sizing

Count prefixes, not pods, once delegation is on.

A `/24` is 256 addresses, which is 16 prefixes, and some of those addresses are reserved by AWS. A handful of nodes with one warm prefix each will fill it. A `/19` or larger per zone is the range I start from for a cluster that will run real workloads. Three zones means three of those, not one big subnet shared across AZs. ENIs are zonal. A node in 1a cannot use a free prefix in 1b.

Watch `AvailableIpAddressCount` on the pod subnets. Alert before zero. At zero, deployments fail one pod at a time and the error is easy to misread as an application crash.

```bash
aws ec2 describe-subnets --subnet-ids subnet-pod-1a subnet-pod-1b subnet-pod-1c \
  --query 'Subnets[].{id:SubnetId,az:AvailabilityZone,free:AvailableIpAddressCount}'
```

---

## The node security group is still the pod's security group

Without security groups for pods, every pod on the node is the node's security group. A pod allowed to reach RDS means every pod on that node can reach RDS, as far as the security group is concerned. NetworkPolicy is the in-cluster control. The security group is the VPC control. You want both, aimed at different boundaries.

NetworkPolicy on the VPC CNI is the `aws-network-policy-agent` container in the `aws-node` DaemonSet, enabled with `ENABLE_NETWORK_POLICY=true` on current CNI versions. It enforces Kubernetes `NetworkPolicy` objects. It does not create AWS security groups.

A default-deny policy in an application namespace is reasonable after you have the egress list: DNS to CoreDNS, the namespace's own pods, and the AWS endpoints those pods call. A default-deny copied from a blog on a Friday takes down DNS and then everything else. CoreDNS is in `kube-system`. Egress to it is `namespaceSelector` plus `podSelector`, or you open UDP and TCP 53 more widely and accept that.

I do not install a second CNI, and I do not install Calico next to the VPC CNI policy agent unless there is a feature the agent does not have. Two policy engines is how a packet gets accepted by one and dropped by the other.

---

## Reading a failed assign

```bash
kubectl describe pod <pod> -n <ns>
kubectl -n kube-system logs daemonset/aws-node --tail=50
```

| Event or log | Cause |
|---|---|
| `failed to assign an IP address` | Subnet full, or ENI at its limit, or `maxPods` already raised past what the instance can attach |
| `InsufficientFreeAddressesInSubnet` or a free-IP count of 0 | Size or warm pool. Not the application. |
| ENIConfig errors | Custom networking on, object missing or misnamed for that AZ |
| Pod Pending, not ContainerCreating | Scheduler. CPU, memory, taint, topology. Not the CNI. See [scheduling](./pending-pods-pdbs-and-spread.md). |
| IP assigned, probes fail, SG timeouts | Security group or route. The IP existed. The path did not. |

The CNI's IAM is the other silent failure. If the node role no longer has `AmazonEKS_CNI_Policy` and the `aws-node` service account has no Pod Identity or IRSA role, new nodes launch and no pod gets an IP. `sts get-caller-identity` from a debug pod does not test this. The DaemonSet's identity does. Check the aws-node service account and the node role, in that order.
