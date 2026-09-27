# Running Karpenter on EKS

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#Karpenter` `#EC2`

Karpenter watches unschedulable pods and calls `RunInstances`. It is fast, and it will do exactly what the NodePool says, including launching more capacity than the account should have, or draining a node that still has a singleton on it. The controller is not the hard part. The NodePool is.

This is self-managed Karpenter. EKS Auto Mode uses the same NodePool API and a different NodeClass. Do not mix the manifests. The [compute note](./eks-compute-node-groups-fargate-auto-mode.md) is the fork between them.

---

## Where the controller runs

Karpenter cannot be the thing that provisions the node it runs on, and then also be free to delete that node. If it consolidates itself away, nothing launches the replacement. Pods sit Pending and the logs you need are on a node that is gone.

Run it on a managed node group Karpenter does not own, or on Fargate. Taint that group with `CriticalAddonsOnly=true:NoSchedule`. Give the Karpenter deployment, CoreDNS, and the VPC CNI's DaemonSet the matching toleration. Application pods do not get that toleration.

Two nodes in that group, in different AZs. One node is a controller outage during a recycle.

---

## The node role and the class

The node role is a normal worker role: `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryReadOnly`, and the CNI policy only if the VPC CNI is still using the node role. Karpenter's controller role is a different role. The controller launches instances. The instance assumes the node role. If you attach the controller policy to the node, every pod that reaches IMDS can launch instances. Set the [hop limit to 1](./eks-compute-node-groups-fargate-auto-mode.md) anyway.

`spec.role` on the EC2NodeClass tells current Karpenter to create the instance profile. You do not create the profile by hand unless you have a reason to.

```yaml
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  role: KarpenterNodeRole-app
  amiSelectorTerms:
    - alias: al2023@v20240910
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: app
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: app
  metadataOptions:
    httpEndpoint: enabled
    httpTokens: required
    httpPutResponseHopLimit: 1
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        encrypted: true
        deleteOnTermination: true
  tags:
    karpenter.sh/discovery: app
```

`alias: al2023@latest` drifts every node when AWS publishes an AMI. In production I pin the alias to a date I have already rolled through dev. Drift is how the new AMI rolls out, and drift respects disruption budgets only for the voluntary path you configured. A Monday morning AMI publish plus `@latest` is an unplanned rollout.

Bottlerocket is `bottlerocket@<version>`, and the disk layout is not `/dev/xvda` alone. Do not reuse the AL2023 block device mapping on it.

Subnet and security group selectors that match nothing produce NodeClaims that never become nodes. The error is on the NodeClaim, not on the pod. Tag the private subnets and the cluster security group on purpose. Do not select every subnet in the VPC. A public subnet match puts nodes on the internet.

---

## The pool

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: general
spec:
  weight: 10
  limits:
    cpu: "500"
    memory: 1000Gi
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 15m
    budgets:
      - nodes: "10%"
      - nodes: "0"
        schedule: "0 13 * * mon-fri"
        duration: 10h
        reasons:
          - Drifted
          - Underutilized
  template:
    spec:
      expireAfter: 720h
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      requirements:
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot", "on-demand"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["5"]
        - key: karpenter.k8s.aws/instance-cpu
          operator: In
          values: ["4", "8", "16"]
        - key: topology.kubernetes.io/zone
          operator: In
          values: ["us-east-1a", "us-east-1b", "us-east-1c"]
```

`limits` is the cap Karpenter will refuse to pass. Without it, a bad HorizontalPodAutoscaler and a missing cluster quota race, and the quota error is how you find out. Set the limit under the EC2 vCPU quota, not at it.

`instance-cpu` avoids the tiny instances that spend their ENIs on DaemonSets, and the 64-vCPU instances that show up because they were one cent cheaper for a single pending pod. Karpenter optimizes price against the pod's requests. If requests are missing or absurd, the instance choice is absurd. That is a scheduling problem. Karpenter will not save you from it.

`expireAfter: 720h` is 30 days, which is the default. Shortening it so every node expires the same week means a fleet replacement. Expiration has been forceful on older 1.x controllers: disruption budgets did not hold it back. Check the version you run before you depend on a business-hours budget to stop a mass expiry. I leave expiry at 30 days and use drift, on purpose, for AMI rollouts.

The weekday budget with `nodes: "0"` stops drift and consolidation during the workday in UTC. Empty-node removal can stay allowed if you omit `Empty` from `reasons`. I would rather keep an empty node until evening than drop capacity someone is about to need. Adjust the cron to the timezone you are actually on call in. The schedule is UTC.

`weight` matters when two pools can both take a pod. Higher weight wins. A spot pool at weight 50 and an on-demand pool at weight 10 prefers spot. The on-demand pool is the fallback when spot cannot fit, not a pool you taint and then forget the toleration for.

---

## Spot

Spot without an interruption queue means Karpenter learns about the interruption when the node is already going away. Create the SQS queue and the EventBridge rules from the Karpenter AWS setup for the version you installed. The queue policy and the rules are part of the install, not an optimization.

Workloads on spot need a PodDisruptionBudget that allows the drain, more than one replica, and a retry in the application if a single pod dying is user-visible. A single-replica Deployment on spot is a planned outage with extra steps.

Annotate the pod, not the node, when a specific workload must not be consolidated:

```yaml
annotations:
  karpenter.sh/do-not-disrupt: "true"
```

Use that for the singleton you have not fixed yet. Do not put it on every Deployment or consolidation never pays for itself.

---

## System pool, separate from general

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: system
spec:
  weight: 1
  limits:
    cpu: "16"
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 30m
    budgets:
      - nodes: "1"
  template:
    spec:
      expireAfter: Never
      taints:
        - key: CriticalAddonsOnly
          value: "true"
          effect: NoSchedule
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["m"]
        - key: karpenter.k8s.aws/instance-cpu
          operator: In
          values: ["2", "4"]
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
```

I still prefer the controller itself on a managed node group. This pool is for add-ons that can tolerate Karpenter, if you have moved them off that group. `expireAfter: Never` on a system pool is acceptable. `expireAfter: Never` on the general pool is how you keep a year-old AMI in production.

If both this pool and a managed group exist, do not let both be the only place CoreDNS can run and then drain both on the same day.

---

## PDBs are the other half of disruption

Karpenter drains through the Kubernetes eviction API. A PodDisruptionBudget of `minAvailable: 100%`, or `minAvailable` equal to the replica count, blocks the drain. The node stays, cordoned or not, and Karpenter waits. During an AZ event that wait is the outage.

`maxUnavailable: 1` on a Deployment with three or more replicas is the usual setting. A single replica has nothing to disrupt. Either run two, or accept that this pod blocks every drain of its node and put it on the system pool on purpose.

Read [scheduling](./pending-pods-pdbs-and-spread.md) before you tighten budgets and then wonder why drift stopped.

---

## When a pod stays Pending

```bash
kubectl describe pod -n production -l app=api | sed -n '/Events/,$p'
kubectl get nodeclaims
kubectl describe nodeclaim <name>
kubectl logs -n kube-system -l app.kubernetes.io/name=karpenter --tail=100
```

The pod event tells you which requirement failed: CPU, memory, affinity, taint, topology. The NodeClaim tells you the AWS error: insufficient capacity, vCPU quota, a subnet with no free IPs, an instance profile that does not exist, a security group selector that matched nothing.

Insufficient capacity in one zone is normal for spot and sometimes for a new on-demand type. A requirement list that allows only one family and one size will sit there. Widen `instance-category` and `instance-cpu`, or allow on-demand as a fallback pool.

Subnet IP exhaustion looks like a Karpenter failure and is a CNI and CIDR problem. The [VPC CNI note](./vpc-cni-pod-ips.md) is the next read if the instance launched and the pod is still in `ContainerCreating` with `failed to assign an IP address`.

---

## Install, briefly

Use the Karpenter Helm chart version that matches the CRDs you installed. A 1.x chart against 0.37 CRDs fails in ways that look like a bad manifest. Pin the chart. Pin the AMI alias. Pin the controller's IAM to the upstream policy for that version, scoped with the cluster's discovery tag.

The controller's own AWS identity is Pod Identity or IRSA. Same pattern as any other controller. It is not the node role. If you did put the controller on Fargate, it has to be IRSA. The Pod Identity agent is a DaemonSet, and Fargate will not run it.

After the first install:

```bash
kubectl get nodepool,ec2nodeclass
kubectl get nodeclaims
```

Scale a deployment past what the system group can hold. A NodeClaim should appear, then a node, then the pod should leave Pending. If the node appears and is `NotReady` for more than a couple of minutes, it is usually the node role, the security group, or private endpoint 443. That is the [control plane](./eks-control-plane-what-you-own.md) path, not a Karpenter setting.
