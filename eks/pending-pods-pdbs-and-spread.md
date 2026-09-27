# Pending pods, PDBs, and spread

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#Scheduling` `#Karpenter`

Most "the deploy is stuck" pages are one of three things: the scheduler will not place the pod, the CNI will not give it an IP, or a drain will not finish because a PodDisruptionBudget says no. This is the first and the third. IPs are in the [VPC CNI note](./vpc-cni-pod-ips.md). Crash loops are the other two notes in this folder.

---

## Requests are what the scheduler believes

The scheduler and Karpenter look at requests. Limits are a cgroup. A pod with no requests and no limits is BestEffort. Under memory pressure it is first in line to die, and Karpenter has nothing honest to bin-pack.

| You set | What happens |
|---|---|
| Neither | BestEffort. Cheap to schedule. First to be evicted. |
| CPU request, no CPU limit | Guaranteed the request. Can burst. Does not get CFS-throttled at a ceiling. |
| CPU limit and no request | Kubernetes sets the request equal to the limit. You schedule the ceiling, and you still throttle at it. |
| Memory request and a higher memory limit | Normal. The limit is the point where you would rather restart the container than have the node OOM killer choose a victim. |
| Memory limit and no request | Request is copied from the limit. Pending pods, because every replica demands the ceiling. |

I set CPU requests from what the process uses at the load I care about, and I leave CPU limits off on request-path services. A CPU limit shows up as latency, not as an error, and the HPA may not be looking at throttle. I set memory limits. A container with no memory limit is how one leak takes the node, and then every other pod on it.

If the HorizontalPodAutoscaler target is 70% CPU and the request is 10m while the process sits at 500m, the autoscaler thinks the pod is on fire. Fix the request before you add replicas.

```yaml
resources:
  requests:
    cpu: "500m"
    memory: 512Mi
  limits:
    memory: 1Gi
```

Workers that block on a queue are not a CPU story. Scale them on queue depth. The KEDA sketch in the [IRSA note](./irsa-explained-real-eks-workloads.md) is that pattern. A CPU HPA on a worker that is idle in `ReceiveMessage` will scale to minimum and stay there while the queue grows.

---

## A PDB that allows one to leave

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api
  namespace: payments
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: api
```

You set `maxUnavailable` or `minAvailable`. The API rejects both. `minAvailable` equal to the replica count, or `minAvailable: 100%`, means a voluntary eviction never succeeds. Karpenter waits. The managed node group update waits. `kubectl drain` waits. The node sits cordoned until someone deletes the PDB in an incident and calls that an upgrade.

`maxUnavailable: 1` on three or more replicas is what I want for a service behind a load balancer that already has a readiness probe. The probe is what takes the pod out of traffic. The PDB is what stops you removing the last one.

A single replica has no disruption budget that is both safe and drainable. Run two, or accept that this pod blocks every drain of its node and place it on a node you do not roll casually. PDBs do nothing when the node disappears. They only gate the operations you start: drain, consolidation, upgrade.

Check before a node roll:

```bash
kubectl get pdb -A
kubectl get deploy -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,REPLICAS:.spec.replicas
```

Any PDB whose `ALLOWED DISRUPTIONS` is 0 will block. Any Deployment at one replica that owns a `minAvailable: 1` PDB is the usual reason.

---

## Spread

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app: api
```

`DoNotSchedule` means the pod stays Pending rather than land in a zone that already has its share. That is what you want for an API that has to survive a zone, and only if something can launch capacity in the empty zone. Karpenter with all three zones in the NodePool requirements can. A node group pinned to two subnets cannot. The pod will wait forever and the event will say topology, which is accurate and useless until you look at the NodePool.

`ScheduleAnyway` records the skew and places the pod. I use it for batch, and for a second constraint on `kubernetes.io/hostname` so three replicas do not all land on the one large node that satisfied the zone rule.

`labelSelector` has to match the pods you think you are spreading. A selector that matches nothing does not spread. A selector that matches every pod in the namespace spreads them as one set and Pending shows up in places you did not expect.

Topology spread is a scheduler rule. It does not move running pods. A deploy that rolls will rebalance. A cluster that has been skewed for a month stays skewed until something recreates the pods.

---

## Priority for the things the cluster needs

Application pods at the default priority of zero will not preempt a system pod that is higher. The failure is the other way: system pods also at zero, nodes full, CoreDNS Pending, everything in the cluster starts failing DNS and you scale the application because that is what the graph shows.

```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: platform-critical
value: 1000000
preemptionPolicy: PreemptLowerPriority
```

CoreDNS and the Karpenter controller get that class. Application Deployments do not. Preemption is a sharp tool. I use it so a burst of batch pods cannot keep DNS off the cluster. I do not use it so one team can evict another team's pods. That is a resource quota conversation, not a priority of 1000000000.

The system node group taint `CriticalAddonsOnly=true:NoSchedule` is the other half. Priority decides who wins on a full node. The taint decides who was allowed there. Application pods do not get the toleration. The [compute note](./eks-compute-node-groups-fargate-auto-mode.md) sets the taint.

---

## Reading Pending

```bash
kubectl describe pod -n payments <pod>
kubectl get events -n payments --sort-by='.lastTimestamp'
```

The Events block is the scheduler telling you which predicate failed. Work down it. Do not start with the application log. The application has not started.

| Event | What it actually is |
|---|---|
| `Insufficient cpu` or `Insufficient memory` | Requests do not fit what is left on any node. Karpenter should be launching, or it hit its `limits`, or EC2 quota, or the instance types in the pool are smaller than this pod. |
| `untolerated taint` | The pod has no toleration for a taint that is on every node that would otherwise fit. Spot taints, system taints, and a taint someone added during an incident and left. |
| `didn't match Pod's node affinity/selector` | `nodeSelector` or affinity names a label no node has. Auto Mode labels are `eks.amazonaws.com/...`. Self-managed Karpenter labels are `karpenter.k8s.aws/...`. A manifest copied from the other one sits here. |
| `did not tolerate topology spread constraint` or a topology message | `DoNotSchedule` and the skew is already maxed, or the empty zone cannot get a node. |
| `0/N nodes are available` with several of the above | Read all of them. The first one is not always the one that is true for every node. |
| Pod is `ContainerCreating`, not Pending | It is scheduled. IP, volume, or image. CNI note, [storage](./eks-storage-choices.md), or `kubectl describe` for `FailedMount` and image pull. |

Image pull timeouts are the VPC path to ECR. Image pull 403 is the node role or the repository policy. `exec format error` is the architecture. Graviton nodes running an amd64 image fail this way after scheduling succeeded.

A pod that is Pending with `FailedScheduling` and a NodeClaim in `NotReady` or never appearing is Karpenter, and the NodeClaim events have the AWS error. Quota and "insufficient capacity" are the common ones. Widen the instance categories, or wait, or fall back to on-demand. The [Karpenter note](./karpenter-on-eks.md) has the commands.

---

## Eviction when memory is the problem

If the node is under memory pressure, kubelet evicts BestEffort first, then Burstable pods using more than their request, then Guaranteed last. A Deployment with no memory request will be the one that dies, and it will look like a restart storm in the application. Set the request. If the node is still thrashing, the limit is too high for the instance or too many pods were scheduled because their requests were tiny and their usage is not.

`kubectl describe node <node>` and the Allocated resources block are the numbers. Compare requests to capacity before you compare usage graphs. The scheduler never saw the usage.
