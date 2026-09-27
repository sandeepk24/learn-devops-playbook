# Storage choices on EKS

**Author:** Sandeep K | `sandeepk24/learn-devops-playbook`
**Tags:** `#EKS` `#EBS` `#EFS`

A pod's filesystem is empty when the container starts, unless you mounted something. Most pods should stay that way. Persistent storage is a second system, with its own failure domain, and on EKS that failure domain is usually an Availability Zone.

The long walkthrough of the EBS driver, volume types, and snapshots is [EBS volumes on EKS](../aws/ebs-volumes-on-eks-the-complete-guide-for-devops-engineers.md). This note is the choice in front of that, and the two mistakes that make a volume look like a scheduler bug.

---

## What the pod actually needs

| Need | Use |
|---|---|
| Scratch that can die with the pod | `emptyDir`. Memory-backed only for a small cache you have sized. |
| One writer, data must survive a restart, loss of the node is acceptable if the volume remains | EBS, `gp3`, CSI driver, `WaitForFirstConsumer`. |
| Many pods reading and writing the same files | EFS. You are accepting NFS latency and a throughput mode. |
| Objects, mostly read | S3 through the AWS SDK. The Mountpoint for S3 CSI driver if a process can only speak files. It is not a POSIX disk. Do not run a database on it. |
| A database | RDS or Aurora. An EBS volume under a database pod is a decision you can defend: you own failover, snapshots, and the AZ. |

`emptyDir` on a node with a small root volume fills the node and evicts pods. Size the node's disk in the launch template or the EC2NodeClass, or set a size limit on the emptyDir. The default is "until the disk is full."

---

## EBS is one zone

An EBS volume does not move between Availability Zones. Once a PersistentVolume is bound, the pod can only schedule onto nodes in that zone. Karpenter will not rescue you by launching in another zone. The event looks like affinity. The affinity was injected by the volume.

`volumeBindingMode: WaitForFirstConsumer` waits to create the volume until the scheduler has picked a node, so the volume is created in the zone where the pod can actually run. `Immediate` creates it at PVC creation time, in whichever zone the driver picked, and then the pod is stuck if that zone is full or tainted.

```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete
allowVolumeExpansion: true
parameters:
  type: gp3
  encrypted: "true"
  fsType: ext4
```

Check which class is default after you install the driver:

```bash
kubectl get storageclass
```

Two classes annotated as default is not "either one." It is a provisioner race you will not enjoy. The old in-tree `gp2` default is still lying around on clusters that have lived a while. A PVC that does not name a class gets that default. Name the class in the PVC for anything you would be unhappy to find on gp2.

`reclaimPolicy: Delete` removes the disk when the PVC goes away. That is correct for a cache you can rebuild and wrong for data you cannot. I use `Retain` when a human should have to delete the volume on purpose. Retained volumes cost money until someone notices them in the EC2 console. That is the trade.

A KMS key in the StorageClass parameters fails provisioning unless the CSI controller role can use the key. Account-default EBS encryption covers the disk without that parameter. Add a CMK when you have a reason, and test a PVC in the same change. A failed provision looks like a Pending pod with a cloud event, not like a crash.

The CSI controller's IAM role is the add-on's service account, not the node role. Installing the add-on without the role is a Pending PVC forever. The [add-on note](./eks-addons.md) has that install.

Non-root pods need `fsGroup` or they cannot write the mount. The container starts, the process gets `EACCES`, and if that process exits you are in CrashLoopBackOff with a storage problem. The [crash loop notes](./crashloopbackoff-part2-advanced.md) cover the symptom. The fix is on the pod:

```yaml
securityContext:
  runAsUser: 1000
  runAsNonRoot: true
  fsGroup: 1000
```

---

## EFS when it really is shared

EFS is ReadWriteMany. It is also a network filesystem with a throughput mode that will throttle you if you left it on bursting and the workload is a backlog of writes. Provisioned throughput when you know the rate. Bursting when you have looked at the credits and they are not the product.

One access point per application, IAM authorization on, and the CSI driver's service account holding the IAM actions. A node-wide mount of the whole file system means every pod on the node can see every other application's files. That is the node-role mistake again, in filesystem form.

Do not put a database on EFS because you wanted the pod to move zones. Use a database that already moves zones. EFS for shared uploads, a shared cache you can explain, or a legacy process that needs a directory. Not for low-latency fsync.

---

## Pending, once the scheduler was willing

If the pod is Pending and the event is `FailedScheduling` with a volume affinity message, the volume exists in a zone where you have no capacity. Either let Karpenter launch in that zone, or accept that this pod is zonal and stop spreading it with `DoNotSchedule` across three zones it cannot use.

If the pod is `ContainerCreating` and the event is `FailedAttachVolume` or `FailedMount`, the volume is in the right zone and the attach failed. The node IAM or the CSI node plugin cannot attach, the volume is already attached to a node that died and has not released, or `fsGroup` is churning on a large directory and the mount has not finished. `kubectl describe pvc` and `kubectl describe pv` before you delete anything. Deleting a PVC with reclaim `Delete` to "unstick" a pod deletes the disk.
