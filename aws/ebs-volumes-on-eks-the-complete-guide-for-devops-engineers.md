# Your App Needs a Hard Drive in the Cloud — Here's How EBS + EKS Actually Works 💾

> **Plain English. Real Diagrams. Zero Handwaving.**  
> What a Senior Cloud Engineer actually sets up when a development team says _"we need persistent storage on Kubernetes."_  
> From "what even is a volume?" to production-grade EBS on EKS — one document.

---

## 📋 Table of Contents

1. [The Plain English Foundation — What Problem Does EBS Solve?](#1-the-plain-english-foundation)
2. [What is EBS — Really?](#2-what-is-ebs-really)
3. [EBS Volume Types — Choosing the Right Disk](#3-ebs-volume-types)
4. [How EBS Works with EC2 — The Foundation](#4-how-ebs-works-with-ec2)
5. [Kubernetes Storage — The Concept Stack](#5-kubernetes-storage-the-concept-stack)
6. [The Full Picture — EBS + EKS Together](#6-the-full-picture-ebs--eks-together)
7. [The EBS CSI Driver — The Magic Glue](#7-the-ebs-csi-driver)
8. [StorageClass — The Disk Ordering Menu](#8-storageclass)
9. [PersistentVolume & PersistentVolumeClaim — Request and Fulfillment](#9-pv-and-pvc)
10. [Real-World Example — PostgreSQL on EKS with EBS](#10-real-world-example)
11. [The Availability Zone Problem — The #1 Gotcha](#11-the-availability-zone-problem)
12. [What the Sr. Cloud Engineer Sets Up — Step by Step](#12-what-the-sr-cloud-engineer-sets-up)
13. [Snapshots, Backups & Disaster Recovery](#13-snapshots-backups--disaster-recovery)
14. [Monitoring & Alerting for EBS on EKS](#14-monitoring--alerting)
15. [Cost Optimization](#15-cost-optimization)
16. [Common Failures & How to Debug](#16-common-failures--debugging)
17. [Quick Reference Cheat Sheet](#17-quick-reference-cheat-sheet)

---

## 1. The Plain English Foundation

### Start Here: Think of Your Laptop

When you open VS Code and save a file, where does it go? Your laptop's hard drive (SSD). The data stays there even when you close the laptop, restart it, or open it again three days later.

Now think about what happens when you run an app in a Docker container or a Kubernetes pod:

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Pod                        │
│                                                          │
│   Your App  →  writes file to /data/logs/app.log        │
│                           ↓                             │
│              Container Filesystem                        │
│              (lives in RAM + temp disk)                  │
│                                                          │
│   Pod gets DELETED or CRASHED                           │
│              ↓                                          │
│   EVERYTHING INSIDE IS GONE 💥                          │
│   app.log = gone                                        │
│   database rows = gone                                  │
│   uploaded files = gone                                 │
└─────────────────────────────────────────────────────────┘
```

This is the **ephemeral container problem**. Containers are designed to be disposable. When they die, everything inside dies too. That's great for stateless apps (APIs that just compute things), but catastrophic for:

- Databases (PostgreSQL, MySQL, MongoDB)
- File uploads (user avatars, documents, media)
- Application logs that need to survive restarts
- ML model artifacts, training checkpoints
- Message queue data (Kafka, RabbitMQ)

**EBS solves this.** It's a network-attached hard drive that exists independently of any container or server. Data lives on the drive — not inside the container.

```
┌─────────────────────────────────────────────────────────┐
│                    Kubernetes Pod                        │
│                                                          │
│   Your App  →  writes file to /data/logs/app.log        │
│                           ↓                             │
│              Volume Mount (/data)                       │
│              ↓                                          │
└──────────────╋──────────────────────────────────────────┘
               ║  (network connection)
┌──────────────╋──────────────────────────────────────────┐
│              ║                                           │
│    EBS Volume (acts like a hard drive)                  │
│    /dev/nvme1n1 → formatted as ext4 or xfs              │
│    Data PERSISTS even when pod dies ✅                   │
└─────────────────────────────────────────────────────────┘
```

---

## 2. What Is EBS — Really?

**EBS = Elastic Block Store**

The word "block" is the technical term. Let's break it down:

```
BLOCK STORAGE
─────────────────────────────────────────────────────────

Think of your hard drive as a giant grid of equally sized boxes.
Each box = 1 block (typically 512 bytes or 4KB).

┌────┬────┬────┬────┬────┬────┬────┬────┐
│ B0 │ B1 │ B2 │ B3 │ B4 │ B5 │ B6 │ B7 │  ← Blocks
└────┴────┴────┴────┴────┴────┴────┴────┘

When you save a file, the OS writes it to specific block addresses.
The OS + filesystem (ext4, xfs) manage which blocks belong to which files.

Block storage = raw disk. Your OS formats it and manages files on top.

vs. Object Storage (S3):  files stored as objects with metadata
                           no filesystem — accessed via API
vs. File Storage (EFS):   network filesystem, shared across many servers
                           NFS protocol
```

### The "Elastic" Part

```
Traditional data center:
  "We need more disk"
  → Order physical drives
  → Wait 2 weeks for delivery
  → Rack and stack in datacenter
  → Configure storage array
  → Mount to server

AWS EBS:
  aws ec2 create-volume --size 500 --volume-type gp3
  → Provisioned in < 60 seconds
  → Attach to any EC2 instance in the same AZ
  → Resize on the fly without downtime
  → Change performance tier without recreating
```

### The Physical Reality (Simplified)

EBS volumes don't live on your EC2 instance. They live on dedicated AWS storage hardware in the same Availability Zone, connected via a **high-speed network**.

```
AWS Availability Zone (e.g., us-east-1a)
┌─────────────────────────────────────────────────────────────┐
│                                                              │
│  ┌──────────────────┐           ┌────────────────────────┐  │
│  │   EC2 Instance   │           │   EBS Storage Fleet    │  │
│  │  (your K8s node) │           │   (dedicated hardware) │  │
│  │                  │           │                         │  │
│  │   Your App       │◄─ NVMe ──▶│  Volume: vol-0abc123    │  │
│  │   Container      │  over     │  Size: 100GB gp3        │  │
│  │                  │  network  │  3000 IOPS, 125 MB/s    │  │
│  └──────────────────┘           │                         │  │
│                                 │  Replicated 2x within   │  │
│                                 │  the AZ automatically   │  │
│                                 └────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

Key facts:
✅ EBS volume survives EC2 instance termination
✅ EBS data replicated within the AZ (protects against disk failure)
❌ EBS volume is AZ-SPECIFIC — cannot attach to instance in different AZ
❌ Only ONE EC2 instance at a time (by default — io2 Block Express supports multi-attach)
```

---

## 3. EBS Volume Types — Choosing the Right Disk

This is what a Sr. Cloud Engineer evaluates when a team says "we need storage."

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     EBS VOLUME TYPE DECISION TREE                        │
│                                                                           │
│  What are you storing?                                                    │
│         │                                                                 │
│   ┌─────┴──────┐                                                          │
│   │            │                                                          │
│ General      High Performance                                             │
│ Purpose      Workloads                                                    │
│   │            │                                                          │
│  gp3         ┌─┴────────────────┐                                        │
│  gp2         │                  │                                         │
│ (default)  io2/io2              sc1/st1                                   │
│           Block Express         (Cold/Throughput HDD)                    │
│           (databases,           (big data, archives)                     │
│            high IOPS)                                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

### The Full Comparison

| Type | Name | IOPS | Throughput | Size | Use Case | EKS Use |
|------|------|------|------------|------|----------|---------|
| **gp3** | General Purpose SSD | 3,000–16,000 | 125–1,000 MB/s | 1GB–16TB | Default choice for almost everything | ✅ PostgreSQL, app logs, most workloads |
| **gp2** | General Purpose SSD (old) | Up to 16,000 | 250 MB/s | 1GB–16TB | Legacy — migrate to gp3 | ⚠️ Prefer gp3 |
| **io2** | Provisioned IOPS SSD | Up to 64,000 | 1,000 MB/s | 4GB–16TB | High-perf databases | ✅ Critical MySQL, Oracle, SAP |
| **io2 Block Express** | Highest Perf SSD | Up to 256,000 | 4,000 MB/s | 4GB–64TB | Largest databases | ✅ SAP HANA, huge Cassandra |
| **st1** | Throughput HDD | 500 | 500 MB/s | 125GB–16TB | Sequential large files | ✅ Kafka, log storage, ETL |
| **sc1** | Cold HDD | 250 | 250 MB/s | 125GB–16TB | Infrequent access | ✅ Archives, backups |

### Plain English: gp3 vs io2

```
gp3 — Think of it as a fast SSD laptop drive
────────────────────────────────────────────
Cost:       ~$0.08/GB/month
IOPS:       3,000 baseline FREE, buy more up to 16,000 independently
Best for:   Web apps, APIs, small-medium databases, EKS general use
Analogy:    A MacBook Pro SSD — fast for most tasks, great value

io2 — Think of it as a server-grade NVMe RAID array
────────────────────────────────────────────────────
Cost:       ~$0.125/GB/month + $0.065/IOPS/month
IOPS:       Consistent, guaranteed — no bursting
Best for:   Critical production databases, financial systems
Analogy:    Enterprise SAN storage — consistent, never bursts, never throttles
When to use: Your DBA says "we need guaranteed 20,000 IOPS minimum at all times"
```

### IOPS — What It Actually Means

```
IOPS = Input/Output Operations Per Second

Each database read or write = 1 I/O operation

A typical PostgreSQL row read = ~8KB (1-2 IOPS)
A typical web app PostgreSQL instance:
  → 50 concurrent users × 20 queries/second = 1,000 IOPS needed
  → gp3 baseline of 3,000 IOPS is MORE than enough ✅

A high-traffic financial database:
  → 500 concurrent users × 100 queries/second = 50,000 IOPS needed
  → gp3 max of 16,000 IOPS is NOT enough ❌
  → io2 with 64,000 IOPS ✅

Rule of thumb for EKS:
  Dev/staging PostgreSQL:      gp3 20GB, 3000 IOPS (default)
  Production PostgreSQL:       gp3 100GB, 6000 IOPS
  High-traffic production DB:  io2 500GB, 20000 IOPS
```

---

## 4. How EBS Works with EC2 — The Foundation

Before EKS, understand how EBS attaches to a regular EC2 instance. EKS uses this same mechanism under the hood.

```
STEP 1: Create a volume
─────────────────────────────────────────────────────────────
aws ec2 create-volume \
  --availability-zone us-east-1a \    ← MUST match your EC2's AZ
  --size 100 \                         ← GB
  --volume-type gp3 \
  --iops 3000 \
  --throughput 125                     ← MB/s

→ Returns: vol-0a1b2c3d4e5f6a7b8

STEP 2: Attach to EC2
─────────────────────────────────────────────────────────────
aws ec2 attach-volume \
  --volume-id vol-0a1b2c3d4e5f6a7b8 \
  --instance-id i-1234567890abcdef0 \
  --device /dev/xvdf               ← Linux device name

STEP 3: Format (first time only)
─────────────────────────────────────────────────────────────
# SSH into EC2 instance:
lsblk                              # See the new disk: nvme1n1 (100GB)
mkfs -t xfs /dev/nvme1n1          # Format with XFS filesystem

STEP 4: Mount
─────────────────────────────────────────────────────────────
mkdir -p /data
mount /dev/nvme1n1 /data

# Now: any files written to /data persist on EBS
echo "I survive reboots" > /data/test.txt

# Add to /etc/fstab for automatic mount on reboot
echo "/dev/nvme1n1 /data xfs defaults,nofail 0 2" >> /etc/fstab

STEP 5: Detach and re-attach to different instance
─────────────────────────────────────────────────────────────
umount /data
aws ec2 detach-volume --volume-id vol-0a1b2c3d4e5f6a7b8
aws ec2 attach-volume \
  --volume-id vol-0a1b2c3d4e5f6a7b8 \
  --instance-id i-newinstance \
  --device /dev/xvdf
mount /dev/nvme1n1 /data
# ALL your data is still there ✅
```

**EKS automates ALL of the above** — creating, attaching, formatting, mounting, and unmounting volumes as pods move between nodes.

---

## 5. Kubernetes Storage — The Concept Stack

Before we get to EBS + EKS specifically, understand the 4-layer Kubernetes storage abstraction. This is what makes Kubernetes storage portable across AWS, GCP, Azure, and on-prem.

```
┌───────────────────────────────────────────────────────────────────┐
│                    KUBERNETES STORAGE STACK                        │
│                                                                    │
│  Layer 4 (App)      POD                                           │
│                     └── volumeMounts:                             │
│                           - name: data                            │
│                             mountPath: /var/lib/postgresql/data   │
│                     └── volumes:                                  │
│                           - name: data                            │
│                             persistentVolumeClaim:                │
│                               claimName: postgres-pvc  ──────┐   │
│                                                               │   │
│  Layer 3 (Request)  PERSISTENTVOLUMECLAIM (PVC)  ◄────────────┘   │
│                     "I need 50GB of fast storage"                 │
│                     storageClassName: ebs-gp3                     │
│                     accessModes: ReadWriteOnce           ─────┐   │
│                     resources: 50Gi                            │   │
│                                                                │   │
│  Layer 2 (Fulfillment) PERSISTENTVOLUME (PV)  ◄────────────────┘   │
│                     "Here is vol-0abc123 (50GB EBS)"              │
│                     Auto-created by StorageClass                  │
│                                                                    │
│  Layer 1 (Policy)   STORAGECLASS                                  │
│                     "When someone asks for ebs-gp3,               │
│                      create a gp3 EBS volume in their AZ"         │
│                     provisioner: ebs.csi.aws.com                  │
│                                                                    │
│  Layer 0 (Driver)   EBS CSI DRIVER                               │
│                     "I know how to talk to AWS APIs               │
│                      to create/attach/detach EBS volumes"         │
└───────────────────────────────────────────────────────────────────┘
```

### Each Layer in Plain English

```
STORAGECLASS = The menu at a restaurant
──────────────────────────────────────────────────────
"We offer: gp3 SSD, io2 High Performance, sc1 Archive"
Defined by the Sr. Cloud Engineer once.
Dev teams choose from this menu when requesting storage.

PERSISTENTVOLUMECLAIM (PVC) = Your order from the menu
──────────────────────────────────────────────────────
"I'll have 50GB of gp3 please"
Created by the developer or DevOps engineer in their app YAML.
Kubernetes sees this and automatically provisions the storage.

PERSISTENTVOLUME (PV) = The actual table you're seated at
──────────────────────────────────────────────────────────
The real EBS volume that was created to fulfill the order.
Usually auto-created (dynamic provisioning) — you rarely touch this.

POD VOLUME MOUNT = Using the table
──────────────────────────────────────────────────────────
Your app container can now read/write to /var/lib/postgresql/data
and it goes to the real EBS volume.
```

---

## 6. The Full Picture — EBS + EKS Together

Here's the complete architecture. Read this diagram carefully — this is what a Sr. Cloud Engineer builds.

```
AWS CLOUD
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                           │
│  VPC (10.0.0.0/16)                                                        │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                                                                     │   │
│  │  AZ: us-east-1a                    AZ: us-east-1b                  │   │
│  │  ┌────────────────────────────┐    ┌────────────────────────────┐  │   │
│  │  │    Private Subnet          │    │    Private Subnet          │  │   │
│  │  │    10.0.1.0/24             │    │    10.0.2.0/24             │  │   │
│  │  │                            │    │                            │  │   │
│  │  │  EKS Node Group            │    │  EKS Node Group            │  │   │
│  │  │  ┌──────────────────────┐  │    │  ┌──────────────────────┐  │  │   │
│  │  │  │  EC2 (m5.xlarge)     │  │    │  │  EC2 (m5.xlarge)     │  │  │   │
│  │  │  │  ┌───────────────┐   │  │    │  │  ┌───────────────┐   │  │  │   │
│  │  │  │  │ postgres pod  │   │  │    │  │  │  api pod      │   │  │  │   │
│  │  │  │  │ /var/lib/pg   │   │  │    │  │  │  (stateless)  │   │  │  │   │
│  │  │  │  └───────┬───────┘   │  │    │  │  └───────────────┘   │  │  │   │
│  │  │  │          │ mounted   │  │    │  │                       │  │  │   │
│  │  │  └──────────╋──────────┘  │    │  └──────────────────────┘  │  │   │
│  │  │             ║             │    │                             │  │   │
│  │  │  ┌──────────╋──────────┐  │    │                             │  │   │
│  │  │  │ EBS Volume          │  │    │  EBS CAN'T cross AZ ❌      │  │   │
│  │  │  │ vol-0abc123         │  │    │  (postgres pod MUST stay    │  │   │
│  │  │  │ 100GB gp3           │  │    │   in us-east-1a)            │  │   │
│  │  │  │ 3000 IOPS           │  │    │                             │  │   │
│  │  │  └─────────────────────┘  │    └────────────────────────────┘  │   │
│  │  └────────────────────────────┘                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  IAM Role ──────────────────────────────────────────────────────────────┐  │
│  (EBS CSI Driver needs permission to:                                   │  │
│   CreateVolume, AttachVolume, DetachVolume,                             │  │
│   DeleteVolume, DescribeVolumes, DescribeSnapshots...)                  │  │
└─────────────────────────────────────────────────────────────────────────┘
```

### What Happens When a Pod Gets Scheduled

```
SCENARIO: Postgres pod is scheduled by Kubernetes on a node

Step 1: Kubernetes Scheduler picks a node
        "Node in us-east-1a has capacity, schedule postgres there"

Step 2: kubelet on that node sees the pod has a PVC
        "This pod needs PVC: postgres-pvc"

Step 3: EBS CSI Driver checks if PV exists
        PVC already bound to vol-0abc123?
          → YES: proceed to attach
          → NO:  create new EBS volume in THIS node's AZ first

Step 4: EBS CSI Driver calls AWS API
        ec2:AttachVolume(vol-0abc123, i-nodeid, /dev/xvdf)
        ← Typical attach time: 15-30 seconds

Step 5: kubelet mounts the volume into the pod
        mount /dev/nvme1n1 /var/lib/postgresql/data
        (formats if first time using xfs or ext4)

Step 6: Pod starts
        PostgreSQL starts, finds existing data (or empty volume)
        App is running ✅

SCENARIO: Pod crashes and gets rescheduled

Step 1: Pod dies on Node A (us-east-1a)
Step 2: Kubernetes reschedules it
        — If another node in us-east-1a exists → go there
        — If no nodes in us-east-1a → STUCK (AZ mismatch problem!)
Step 3: EBS CSI Driver detaches from Node A
Step 4: EBS CSI Driver attaches to Node B
Step 5: Same data, different node — transparent to the app ✅
```

---

## 7. The EBS CSI Driver — The Magic Glue

CSI = Container Storage Interface. It's a standard API that lets Kubernetes talk to ANY storage provider without knowing the specifics.

### What It Is

```
Without CSI Driver:
  Kubernetes has NO idea how to create an EBS volume.
  It knows nothing about AWS APIs.

With EBS CSI Driver:
  A set of pods running in kube-system that:
  1. Watch for PVC creation events
  2. Call AWS APIs to create EBS volumes
  3. Call AWS APIs to attach volumes to EC2 nodes
  4. Tell kubelet where to mount the device
  5. Detach volumes when pods are deleted
  6. Delete volumes when PVCs are deleted (if reclaimPolicy: Delete)

The CSI driver pods run as a DaemonSet (one per node)
+ a controller Deployment (manages creation/deletion)
```

### Installing the EBS CSI Driver on EKS

```bash
# Option 1: EKS Managed Add-on (RECOMMENDED — Sr. Cloud Engineers use this)
# ─────────────────────────────────────────────────────────────────────────

# Step 1: Create the IAM Role for the CSI Driver (needs AWS permissions)
# The driver needs to call ec2:CreateVolume, ec2:AttachVolume, etc.

eksctl create iamserviceaccount \
  --name ebs-csi-controller-sa \
  --namespace kube-system \
  --cluster my-eks-cluster \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --role-only \
  --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy \
  --approve

# Step 2: Install the add-on
aws eks create-addon \
  --cluster-name my-eks-cluster \
  --addon-name aws-ebs-csi-driver \
  --service-account-role-arn arn:aws:iam::ACCOUNT_ID:role/AmazonEKS_EBS_CSI_DriverRole

# Verify it's running:
kubectl get pods -n kube-system | grep ebs-csi
# ebs-csi-controller-7d6d8c9b4b-xxxxx   6/6   Running   0   2m
# ebs-csi-node-xxxxx                    3/3   Running   0   2m  (one per node)

# Option 2: Helm (for more control)
# ─────────────────────────────────────────────────────────────────────────
helm repo add aws-ebs-csi-driver https://kubernetes-sigs.github.io/aws-ebs-csi-driver
helm repo update

helm upgrade --install aws-ebs-csi-driver \
  aws-ebs-csi-driver/aws-ebs-csi-driver \
  --namespace kube-system \
  --set controller.serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=\
    arn:aws:iam::ACCOUNT_ID:role/AmazonEKS_EBS_CSI_DriverRole
```

### What the CSI Driver Components Do

```
EBS CSI Controller (Deployment — runs on any node)
├── csi-provisioner   : Watches for PVC → creates EBS volume
├── csi-attacher      : Attaches EBS to EC2 node
├── csi-snapshotter   : Creates EBS snapshots
├── csi-resizer       : Expands volumes
└── liveness-probe    : Health monitoring

EBS CSI Node (DaemonSet — runs on EVERY node)
├── node-driver-registrar : Registers driver with kubelet
└── ebs-plugin            : Handles actual mount/unmount on THIS node
```

---

## 8. StorageClass — The Disk Ordering Menu

The StorageClass is defined ONCE by the Sr. Cloud Engineer and used by ALL dev teams.

### Default EKS StorageClass

```bash
# Check what StorageClasses exist in your cluster:
kubectl get storageclass
# NAME            PROVISIONER             RECLAIMPOLICY  VOLUMEBINDINGMODE
# gp2 (default)   kubernetes.io/aws-ebs   Delete         WaitForFirstConsumer
# gp3             ebs.csi.aws.com         Delete         WaitForFirstConsumer

# EKS ships with gp2 as default — but Sr. Cloud Engineers switch to gp3
# gp3 is cheaper and faster than gp2 for the same baseline
```

### StorageClass Definitions — What a Sr. Cloud Engineer Creates

```yaml
# storageclass-gp3.yaml
# ── General Purpose — Default for most workloads ──────────────────
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ebs-gp3
  annotations:
    # Make this the default SC (replaces gp2)
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com   # The EBS CSI driver
volumeBindingMode: WaitForFirstConsumer
#  ↑ CRITICAL: Don't create volume until pod is scheduled to a node
#  This ensures the volume is created in the SAME AZ as the node
#  Without this: volume might be in wrong AZ!

reclaimPolicy: Delete
#  ↑ When PVC is deleted, DELETE the EBS volume too
#  Change to "Retain" for critical data you want to keep after deletion

allowVolumeExpansion: true
#  ↑ Allow resizing volumes without deleting them

parameters:
  type: gp3
  fsType: ext4            # Or xfs (xfs is faster for large sequential writes)
  iops: "3000"            # Baseline IOPS (free with gp3)
  throughput: "125"       # MB/s (free with gp3)
  encrypted: "true"       # ALWAYS encrypt EBS volumes
  # kmsKeyId: "arn:aws:kms:..."  # Optional: use custom KMS key

---
# storageclass-gp3-high-iops.yaml
# ── High Performance — For production databases ────────────────────
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ebs-gp3-high-iops
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain          # Retain data even if PVC deleted
allowVolumeExpansion: true
parameters:
  type: gp3
  fsType: xfs                  # XFS for high-perf databases
  iops: "6000"                 # 2x baseline — good for production Postgres
  throughput: "250"            # 2x baseline throughput
  encrypted: "true"

---
# storageclass-io2.yaml
# ── Mission Critical — For financial/critical databases ────────────
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ebs-io2
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
parameters:
  type: io2
  fsType: xfs
  iopsPerGB: "50"              # 50 IOPS per GB → 100GB = 5,000 IOPS
  encrypted: "true"

---
# storageclass-sc1.yaml
# ── Cold Storage — For archives, backups ───────────────────────────
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ebs-sc1-cold
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
parameters:
  type: sc1
  fsType: ext4
  encrypted: "true"
```

```bash
# Apply all StorageClasses:
kubectl apply -f storageclass-gp3.yaml
kubectl apply -f storageclass-gp3-high-iops.yaml
kubectl apply -f storageclass-io2.yaml

# Remove default annotation from old gp2:
kubectl patch storageclass gp2 \
  -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "false"}}}'

# Verify:
kubectl get storageclass
# NAME                   PROVISIONER          DEFAULT
# ebs-gp3                ebs.csi.aws.com      ✅ (default)
# ebs-gp3-high-iops      ebs.csi.aws.com
# ebs-io2                ebs.csi.aws.com
# ebs-sc1-cold           ebs.csi.aws.com
# gp2                    kubernetes.io/aws-ebs (no longer default)
```

---

## 9. PV and PVC — Request and Fulfillment

### PersistentVolumeClaim — What Developers Write

This is what goes in the application's Kubernetes manifests:

```yaml
# postgres-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
  namespace: production
  labels:
    app: postgres
    team: backend
spec:
  accessModes:
    - ReadWriteOnce     # Only ONE pod can read/write at a time
    #  ↑ For EBS, this is ALWAYS ReadWriteOnce (EBS = 1 instance at a time)
    #  ReadWriteMany = EFS (shared filesystem, multiple pods)
    #  ReadOnlyMany  = for read-only data shared across pods

  storageClassName: ebs-gp3-high-iops   # Which menu item to order
  # omit storageClassName to use the default (ebs-gp3)

  resources:
    requests:
      storage: 100Gi      # Request 100GB
      # EBS sizes: 1GB minimum, 16TB maximum for gp3
```

### PersistentVolume — What Kubernetes Creates Automatically

```yaml
# You don't write this — Kubernetes creates it automatically!
# But understanding it helps you debug.

apiVersion: v1
kind: PersistentVolume
metadata:
  name: pvc-a1b2c3d4-e5f6-7890-abcd-ef1234567890  # Auto-generated name
  labels:
    topology.kubernetes.io/zone: us-east-1a        # Which AZ the volume is in
spec:
  capacity:
    storage: 100Gi
  accessModes:
    - ReadWriteOnce
  storageClassName: ebs-gp3-high-iops
  persistentVolumeReclaimPolicy: Delete

  # This is the actual EBS volume reference:
  csi:
    driver: ebs.csi.aws.com
    volumeHandle: vol-0a1b2c3d4e5f6a7b8  # The real AWS EBS Volume ID
    fsType: xfs
    volumeAttributes:
      storage.kubernetes.io/csiProvisionerIdentity: "..."

  # AZ constraint — ensures pods can only schedule where volume exists:
  nodeAffinity:
    required:
      nodeSelectorTerms:
        - matchExpressions:
            - key: topology.kubernetes.io/zone
              operator: In
              values:
                - us-east-1a    # This PV ONLY works in us-east-1a
```

### Checking PVC Status

```bash
# Create the PVC
kubectl apply -f postgres-pvc.yaml

# Check status — it starts as "Pending" until a pod uses it
kubectl get pvc -n production
# NAME            STATUS    VOLUME                                     CAPACITY
# postgres-data   Pending   (empty — WaitForFirstConsumer mode)        0

# After the pod that uses this PVC is created:
kubectl get pvc -n production
# NAME            STATUS   VOLUME                                      CAPACITY
# postgres-data   Bound    pvc-a1b2c3d4-e5f6-7890-abcd-ef1234567890   100Gi

# See the actual EBS volume ID:
kubectl describe pvc postgres-data -n production | grep VolumeHandle
# VolumeHandle: vol-0a1b2c3d4e5f6a7b8

# Go to AWS console or CLI to verify:
aws ec2 describe-volumes --volume-ids vol-0a1b2c3d4e5f6a7b8
```

---

## 10. Real-World Example — PostgreSQL on EKS with EBS

This is the complete, production-grade setup. Everything a Sr. Cloud Engineer would approve.

### The Full Stack

```
Team Request:  "We need PostgreSQL running on EKS with persistent storage"
Sr. Engineer:  Sets up StorageClass (done once)
DevOps/Dev:    Creates StatefulSet + PVC + Service
```

```yaml
# postgres-complete.yaml
# Everything needed to run PostgreSQL with persistent EBS storage

---
# 1. Namespace
apiVersion: v1
kind: Namespace
metadata:
  name: production

---
# 2. Secret for DB password (in real life: use Secrets Manager + External Secrets)
apiVersion: v1
kind: Secret
metadata:
  name: postgres-secret
  namespace: production
type: Opaque
stringData:
  POSTGRES_USER: appuser
  POSTGRES_PASSWORD: change-me-in-production-use-secrets-manager
  POSTGRES_DB: myapp

---
# 3. ConfigMap for PostgreSQL tuning
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-config
  namespace: production
data:
  postgresql.conf: |
    # Memory settings (tune for your pod memory limits)
    shared_buffers = 256MB
    effective_cache_size = 768MB
    work_mem = 4MB
    maintenance_work_mem = 64MB
    # Checkpoints (important for EBS — reduces write amplification)
    checkpoint_completion_target = 0.9
    wal_buffers = 16MB
    # Connections
    max_connections = 100

---
# 4. StatefulSet — NOT a Deployment for databases!
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres
  namespace: production
  labels:
    app: postgres
spec:
  serviceName: postgres-headless    # Must match headless service below
  replicas: 1                       # 1 replica for single-node Postgres
                                    # For HA: use CloudNativePG or Patroni

  selector:
    matchLabels:
      app: postgres

  template:
    metadata:
      labels:
        app: postgres

    spec:
      # ── NODE AFFINITY: Pin to a specific AZ ──────────────────────
      # CRITICAL: Ensures pod schedules in same AZ as EBS volume
      # Without this, Kubernetes might try to schedule in wrong AZ
      affinity:
        nodeAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              preference:
                matchExpressions:
                  - key: topology.kubernetes.io/zone
                    operator: In
                    values:
                      - us-east-1a    # Pin to same AZ as your EBS volume

      # ── SECURITY CONTEXT ─────────────────────────────────────────
      securityContext:
        runAsUser: 999        # postgres user in the container
        runAsGroup: 999
        fsGroup: 999          # Volume files owned by postgres group

      # ── CONTAINERS ───────────────────────────────────────────────
      containers:
        - name: postgres
          image: postgres:15-alpine
          imagePullPolicy: IfNotPresent

          # Resource limits — tune for your workload
          resources:
            requests:
              memory: "512Mi"
              cpu: "250m"
            limits:
              memory: "1Gi"
              cpu: "1000m"

          # Environment from secret
          envFrom:
            - secretRef:
                name: postgres-secret

          env:
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
              # PostgreSQL needs this subdirectory — avoids "lost+found" issue
              # when EBS volume is mounted at the parent directory

          # Ports
          ports:
            - containerPort: 5432
              name: postgres

          # Volume mounts
          volumeMounts:
            - name: postgres-data     # Matches volumeClaimTemplates name
              mountPath: /var/lib/postgresql/data
            - name: postgres-config
              mountPath: /etc/postgresql/postgresql.conf
              subPath: postgresql.conf

          # Health checks
          livenessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - pg_isready -U $POSTGRES_USER -d $POSTGRES_DB
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3

          readinessProbe:
            exec:
              command:
                - /bin/sh
                - -c
                - pg_isready -U $POSTGRES_USER -d $POSTGRES_DB
            initialDelaySeconds: 5
            periodSeconds: 5
            timeoutSeconds: 3

      volumes:
        - name: postgres-config
          configMap:
            name: postgres-config

  # ── VOLUME CLAIM TEMPLATE ──────────────────────────────────────────
  # StatefulSet creates one PVC per replica automatically
  # Named: postgres-data-postgres-0, postgres-data-postgres-1, etc.
  volumeClaimTemplates:
    - metadata:
        name: postgres-data
        labels:
          app: postgres
      spec:
        accessModes:
          - ReadWriteOnce
        storageClassName: ebs-gp3-high-iops
        resources:
          requests:
            storage: 100Gi

---
# 5. Headless Service (required for StatefulSet)
apiVersion: v1
kind: Service
metadata:
  name: postgres-headless
  namespace: production
spec:
  clusterIP: None     # Headless — returns pod IPs directly
  selector:
    app: postgres
  ports:
    - port: 5432
      targetPort: 5432

---
# 6. ClusterIP Service (for app connections)
apiVersion: v1
kind: Service
metadata:
  name: postgres
  namespace: production
spec:
  type: ClusterIP
  selector:
    app: postgres
  ports:
    - port: 5432
      targetPort: 5432
      name: postgres
```

```bash
# Deploy everything:
kubectl apply -f postgres-complete.yaml

# Watch it come up:
kubectl get pods -n production -w
# NAME         READY   STATUS     RESTARTS   AGE
# postgres-0   0/1     Pending    0          5s     ← waiting for EBS
# postgres-0   0/1     Init:0/1   0          20s    ← EBS attached, mounting
# postgres-0   1/1     Running    0          35s    ← ready!

# Verify EBS was created:
kubectl get pvc -n production
# NAME                       STATUS   VOLUME                                     CAPACITY
# postgres-data-postgres-0   Bound    pvc-xxxxx-xxxxx-xxxxx-xxxxx-xxxxxxxxxxxxx  100Gi

# Get the actual EBS Volume ID:
kubectl get pv $(kubectl get pvc postgres-data-postgres-0 -n production \
  -o jsonpath='{.spec.volumeName}') \
  -o jsonpath='{.spec.csi.volumeHandle}'
# → vol-0a1b2c3d4e5f6a7b8

# Test data persistence:
kubectl exec -it postgres-0 -n production -- psql -U appuser -d myapp -c \
  "CREATE TABLE test (id serial, msg text); INSERT INTO test(msg) VALUES ('I survive pod restarts!');"

# Delete the pod (simulates crash):
kubectl delete pod postgres-0 -n production

# Pod restarts, uses SAME EBS volume:
kubectl exec -it postgres-0 -n production -- psql -U appuser -d myapp -c \
  "SELECT * FROM test;"
# id | msg
# ────+──────────────────────────
#  1 | I survive pod restarts! ✅
```

---

## 11. The Availability Zone Problem — The #1 Gotcha

**This is the most common production incident involving EBS on EKS.**

```
THE SCENARIO:
─────────────────────────────────────────────────────────────────────
Your EBS volume was created in us-east-1a (because the pod first
scheduled on a node there).

Something happens to all nodes in us-east-1a:
  - Node group scaling event moved all nodes to us-east-1b
  - Spot instance reclamation hit all 1a nodes
  - You patched nodes and drained 1a first

NOW: Kubernetes tries to reschedule postgres-0.
     The only available nodes are in us-east-1b.

     BUT: vol-0abc123 is in us-east-1a.
     EBS CANNOT be mounted across AZs.

RESULT: Pod is stuck in "Pending" forever:
  kubectl describe pod postgres-0
  Warning  FailedScheduling: 0/3 nodes available:
  3 node(s) had volume node affinity conflict.
  → Kubernetes won't schedule the pod on nodes in the wrong AZ!
```

### Solutions

```
SOLUTION 1: Always have nodes in each AZ (RECOMMENDED)
────────────────────────────────────────────────────────
Ensure your node group spans all AZs and has at least 1 node per AZ.

# eksctl nodegroup config:
nodeGroups:
  - name: workers
    availabilityZones: [us-east-1a, us-east-1b, us-east-1c]
    minSize: 3   # At least 1 per AZ
    desiredCapacity: 6

SOLUTION 2: Pin StatefulSet pods to specific AZs
────────────────────────────────────────────────────────
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - key: topology.kubernetes.io/zone
                operator: In
                values:
                  - us-east-1a   # This pod ONLY runs in 1a where the volume is

SOLUTION 3: Use topology spread constraints
────────────────────────────────────────────────────────
For StatefulSets with multiple replicas, ensure each replica
and its EBS volume end up in different AZs:

spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app: postgres

SOLUTION 4: Use EFS instead of EBS (for multi-AZ shared data)
────────────────────────────────────────────────────────────────
EFS = Elastic File System = shared NFS mount
  ✅ Accessible from all AZs
  ✅ Multiple pods can mount simultaneously (ReadWriteMany)
  ❌ 3-5x slower than EBS for random I/O
  ❌ More expensive per GB
  → Use for: uploads, shared config files, NOT for databases
```

---

## 12. What the Sr. Cloud Engineer Sets Up — Step by Step

This is the complete, ordered checklist a Sr. Cloud Engineer follows when onboarding EBS for a new EKS cluster.

```bash
# ══════════════════════════════════════════════════════════════
# PHASE 1: PREREQUISITES
# ══════════════════════════════════════════════════════════════

# 1. Confirm EKS cluster OIDC provider exists (required for IRSA)
aws eks describe-cluster --name my-cluster \
  --query "cluster.identity.oidc.issuer" --output text
# → https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71...

# If not exists, create it:
eksctl utils associate-iam-oidc-provider \
  --cluster my-cluster \
  --approve

# 2. Create IAM Role for EBS CSI Driver (IRSA — IAM Roles for Service Accounts)
eksctl create iamserviceaccount \
  --name ebs-csi-controller-sa \
  --namespace kube-system \
  --cluster my-cluster \
  --role-name AmazonEKS_EBS_CSI_DriverRole \
  --role-only \
  --attach-policy-arn arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy \
  --approve

# ══════════════════════════════════════════════════════════════
# PHASE 2: INSTALL EBS CSI DRIVER
# ══════════════════════════════════════════════════════════════

# Install as EKS managed add-on:
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

aws eks create-addon \
  --cluster-name my-cluster \
  --addon-name aws-ebs-csi-driver \
  --service-account-role-arn \
    arn:aws:iam::${ACCOUNT_ID}:role/AmazonEKS_EBS_CSI_DriverRole

# Wait for it to be active:
aws eks wait addon-active --cluster-name my-cluster --addon-name aws-ebs-csi-driver

# Verify:
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
# ebs-csi-controller-xxxxxxxxxx-xxxxx   6/6   Running
# ebs-csi-node-xxxxx (one per node)     3/3   Running

# ══════════════════════════════════════════════════════════════
# PHASE 3: CREATE STORAGE CLASSES
# ══════════════════════════════════════════════════════════════

kubectl apply -f - <<'EOF'
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ebs-gp3
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
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: ebs-gp3-high-iops
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Retain
allowVolumeExpansion: true
parameters:
  type: gp3
  iops: "6000"
  throughput: "250"
  encrypted: "true"
  fsType: xfs
EOF

# Remove default from old gp2:
kubectl patch storageclass gp2 \
  -p '{"metadata":{"annotations":{"storageclass.kubernetes.io/is-default-class":"false"}}}'

# ══════════════════════════════════════════════════════════════
# PHASE 4: TEST THE SETUP
# ══════════════════════════════════════════════════════════════

# Create a test PVC and Pod to verify end-to-end:
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ebs-test-pvc
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: ebs-gp3
  resources:
    requests:
      storage: 5Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: ebs-test-pod
spec:
  containers:
    - name: test
      image: amazonlinux:2
      command: ["/bin/sh", "-c",
        "echo 'EBS WORKS!' > /data/test.txt && cat /data/test.txt && sleep 3600"]
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: ebs-test-pvc
EOF

# Watch PVC bind and pod start:
kubectl get pvc ebs-test-pvc -w
# ebs-test-pvc   Pending   ... (waiting for pod)
# ebs-test-pvc   Bound     ... ← EBS created!

kubectl logs ebs-test-pod
# EBS WORKS! ✅

# Cleanup:
kubectl delete pod ebs-test-pod
kubectl delete pvc ebs-test-pvc
# EBS volume deleted automatically (reclaimPolicy: Delete)

# ══════════════════════════════════════════════════════════════
# PHASE 5: HAND OFF TO TEAMS WITH DOCUMENTATION
# ══════════════════════════════════════════════════════════════
# Teams use StorageClass names: ebs-gp3 or ebs-gp3-high-iops
# in their PVC storageClassName field
```

---

## 13. Snapshots, Backups & Disaster Recovery

### EBS Snapshots Explained

```
EBS Snapshot = Point-in-time copy of your EBS volume stored in S3
               (S3-backed, but you don't manage it — AWS does)

Cost:     ~$0.05/GB/month for stored snapshot data
          Incremental: only changed blocks since last snapshot

Timeline:
Day 1:  100GB EBS volume → first snapshot = 100GB stored
Day 2:  Write 5GB of new data → second snapshot = 5GB additional stored
Day 3:  Write 3GB → third snapshot = 3GB additional stored

Restore: Create new volume from any snapshot (full 100GB)

┌─────────────────────────────────────────────────────────────┐
│  EBS Volume (live)                                          │
│  ████████████████████░░░░░░░░░░░░ 60/100GB used             │
│         ↓ snapshot                                          │
│  S3 (managed by AWS)                                        │
│  snap-0abc123 (2024-01-15 02:00 UTC)                       │
│  snap-0def456 (2024-01-16 02:00 UTC)                       │
│  snap-0ghi789 (2024-01-17 02:00 UTC)  ← restore from this  │
└─────────────────────────────────────────────────────────────┘
```

### VolumeSnapshot on EKS (Kubernetes-Native Snapshots)

```yaml
# Install VolumeSnapshot CRDs and controller first:
# kubectl apply -f https://raw.githubusercontent.com/kubernetes-csi/external-snapshotter/...

# 1. Create a VolumeSnapshotClass
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ebs-vsc
  annotations:
    snapshot.storage.kubernetes.io/is-default-class: "true"
driver: ebs.csi.aws.com
deletionPolicy: Retain    # Keep snapshot even if VolumeSnapshot object deleted
parameters:
  tagSpecification_1: "key=CreatedBy,value=kubernetes"
  tagSpecification_2: "key=Environment,value=production"

---
# 2. Create a snapshot of a PVC
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: postgres-snapshot-20240117
  namespace: production
spec:
  volumeSnapshotClassName: ebs-vsc
  source:
    persistentVolumeClaimName: postgres-data-postgres-0

---
# 3. Restore from snapshot into a new PVC
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data-restored
  namespace: production
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: ebs-gp3-high-iops
  resources:
    requests:
      storage: 100Gi
  dataSource:
    name: postgres-snapshot-20240117
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
```

### Automated Daily Snapshots with AWS Data Lifecycle Manager

```bash
# Create a DLM policy for automatic snapshots of EKS EBS volumes
aws dlm create-lifecycle-policy \
  --description "EKS Postgres Daily Backup" \
  --state ENABLED \
  --execution-role-arn arn:aws:iam::ACCOUNT_ID:role/AWSDataLifecycleManagerDefaultRole \
  --policy-details '{
    "PolicyType": "EBS_SNAPSHOT_MANAGEMENT",
    "ResourceTypes": ["VOLUME"],
    "TargetTags": [{"Key": "kubernetes.io/created-for/pvc/name", "Value": "postgres-data-postgres-0"}],
    "Schedules": [{
      "Name": "Daily snapshots",
      "CreateRule": {"Interval": 24, "IntervalUnit": "HOURS", "Times": ["02:00"]},
      "RetainRule": {"Count": 14},
      "TagsToAdd": [{"Key": "SnapshotType", "Value": "Daily"}]
    }]
  }'
```

---

## 14. Monitoring & Alerting for EBS on EKS

```bash
# ── KEY METRICS TO MONITOR ───────────────────────────────────────────

# 1. PVC Status — is any PVC stuck in Pending?
kubectl get pvc --all-namespaces | grep -v Bound
# Anything NOT "Bound" needs investigation

# 2. Volume utilization — are disks getting full?
# Inside the pod:
kubectl exec -it postgres-0 -n production -- df -h /var/lib/postgresql/data
# Filesystem      Size  Used Avail Use% Mounted on
# /dev/nvme1n1     99G   45G   54G  46% /var/lib/postgresql/data

# 3. EBS CloudWatch Metrics (via AWS Console or CLI):
aws cloudwatch get-metric-statistics \
  --namespace AWS/EBS \
  --metric-name VolumeReadOps \
  --dimensions Name=VolumeId,Value=vol-0a1b2c3d4e5f6a7b8 \
  --start-time 2024-01-17T00:00:00Z \
  --end-time 2024-01-17T01:00:00Z \
  --period 300 \
  --statistics Average

# Key EBS CloudWatch Metrics:
# VolumeReadOps     → Read IOPS consumed
# VolumeWriteOps    → Write IOPS consumed
# VolumeReadBytes   → Read throughput
# VolumeWriteBytes  → Write throughput
# VolumeTotalReadTime → Avg read latency (high = IOPS throttling)
# BurstBalance      → For gp2 (not gp3) — if hits 0, severe throttling
```

### Prometheus Alerts for EBS

```yaml
# prometheus-ebs-alerts.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ebs-alerts
  namespace: monitoring
spec:
  groups:
    - name: ebs.rules
      rules:
        # Alert: PVC approaching full
        - alert: PVCDiskUsageHigh
          expr: |
            (kubelet_volume_stats_used_bytes /
             kubelet_volume_stats_capacity_bytes) * 100 > 80
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} is {{ $value | humanize }}% full"
            description: "Volume in {{ $labels.namespace }} will be full soon. Expand or clean up."

        # Alert: PVC critically full
        - alert: PVCDiskUsageCritical
          expr: |
            (kubelet_volume_stats_used_bytes /
             kubelet_volume_stats_capacity_bytes) * 100 > 90
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} is {{ $value | humanize }}% full"

        # Alert: PVC stuck in Pending
        - alert: PVCPending
          expr: kube_persistentvolumeclaim_status_phase{phase="Pending"} == 1
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "PVC {{ $labels.persistentvolumeclaim }} stuck in Pending"
```

### Expanding an EBS Volume (Zero Downtime)

```bash
# Your disk is at 85% — time to expand
# EBS gp3 supports online expansion (no downtime!)

# Step 1: Edit the PVC (storageClass must have allowVolumeExpansion: true)
kubectl patch pvc postgres-data-postgres-0 -n production \
  -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'

# Step 2: Watch the expansion:
kubectl describe pvc postgres-data-postgres-0 -n production
# Conditions:
#   Type                      Status
#   FileSystemResizePending   True   ← EBS expanded, waiting for fs resize

# Step 3: The filesystem is resized when the pod restarts
# (or immediately if the CSI driver supports online resize — EBS does!)
kubectl rollout restart statefulset postgres -n production

# Verify:
kubectl exec -it postgres-0 -n production -- df -h /var/lib/postgresql/data
# Filesystem      Size  Used Avail Use%
# /dev/nvme1n1    197G   45G  152G  23%  ← expanded! ✅
```

---

## 15. Cost Optimization

```
COST BREAKDOWN (us-east-1, 2024 pricing):

gp3:
  Storage:    $0.08/GB/month
  IOPS:       $0.005/IOPS/month (above 3,000 baseline)
  Throughput: $0.040/MB/s/month (above 125 MB/s baseline)

  100GB, 3000 IOPS, 125 MB/s = $8/month
  100GB, 6000 IOPS, 250 MB/s = $8 + (3000 × $0.005) + (125 × $0.040)
                              = $8 + $15 + $5 = $28/month

io2:
  Storage:    $0.125/GB/month
  IOPS:       $0.065/IOPS/month

  100GB, 5000 IOPS = $12.50 + (5000 × $0.065) = $337.50/month

Snapshots:
  $0.05/GB/month (incremental after first)
  100GB volume, daily snapshots for 14 days ≈ $7–15/month extra
```

### Cost Optimization Checklist

```bash
# 1. Find unattached (orphaned) EBS volumes — you're paying for these!
aws ec2 describe-volumes \
  --filters Name=status,Values=available \
  --query 'Volumes[*].{ID:VolumeId,Size:Size,Type:VolumeType,AZ:AvailabilityZone}' \
  --output table

# 2. Find volumes with old snapshot policies that are keeping too many snapshots
aws ec2 describe-snapshots --owner-ids self \
  --query 'sort_by(Snapshots, &StartTime)[*].{ID:SnapshotId,Size:VolumeSize,Date:StartTime}' \
  --output table

# 3. Identify oversized PVCs — PVC requested 500GB but only using 20GB
kubectl get pvc --all-namespaces -o json | jq -r \
  '.items[] | [.metadata.namespace, .metadata.name, .spec.resources.requests.storage] | @tsv'

# 4. Migrate gp2 → gp3 (same performance, ~20% cheaper)
# List all gp2 volumes:
aws ec2 describe-volumes \
  --filters Name=volume-type,Values=gp2 \
  --query 'Volumes[*].VolumeId' --output text | \
  xargs -I{} aws ec2 modify-volume --volume-id {} --volume-type gp3
# No downtime — modification happens live

# 5. Right-size IOPS — don't pay for unused IOPS
# Check actual IOPS consumption in CloudWatch before setting limits
```

---

## 16. Common Failures & Debugging

### Failure 1: PVC stuck in Pending forever

```bash
kubectl describe pvc my-pvc -n production
# Events:
#   Warning  ProvisioningFailed: ... volume node affinity conflict

# Causes:
# a) No nodes in the AZ where the volume was created
# b) WaitForFirstConsumer: no pod created yet (this is normal!)
# c) StorageClass doesn't exist

# Debug:
kubectl get storageclass                     # Does the SC exist?
kubectl get nodes -L topology.kubernetes.io/zone  # What AZs have nodes?
kubectl describe pod postgres-0              # Is the pod scheduled?
kubectl logs -n kube-system \
  -l app=ebs-csi-controller -c csi-provisioner  # CSI driver logs
```

### Failure 2: Pod stuck in ContainerCreating

```bash
kubectl describe pod postgres-0 -n production
# Events:
#   Warning  FailedAttachVolume: ... error attaching volume

# Causes:
# a) Volume still attached to old (deleted) node — AWS takes 6-10 min to force-detach
# b) IAM permissions missing on CSI driver role
# c) Volume in different AZ than node

# Check IAM:
kubectl logs -n kube-system \
  -l app=ebs-csi-controller -c csi-attacher | grep -i "error\|denied"

# Force detach if old node is gone:
aws ec2 describe-volumes --volume-ids vol-0abc123
# Check if "Attachments" shows an old instance
aws ec2 detach-volume --volume-id vol-0abc123 --force
```

### Failure 3: "read-only file system" errors in pod

```bash
# Container can't write to mounted path

# Check filesystem errors:
kubectl exec -it postgres-0 -n production -- dmesg | tail -20
# Look for: "EXT4-fs error" or "XFS: ... disk quota exceeded"

# Usually means: EBS volume ran out of space
kubectl exec -it postgres-0 -n production -- df -h

# Or: inode exhaustion (many small files)
kubectl exec -it postgres-0 -n production -- df -i
# If Iuse% = 100% → no more files can be created even with space available
```

### Failure 4: EBS volume limit per instance exceeded

```bash
# EC2 instances have a maximum number of EBS volumes:
# m5, c5: up to 28 EBS volumes
# Older types: up to 40 EBS volumes

# If you're running many stateful pods per node, you'll hit this limit
# Symptom: new volumes fail to attach

# Solution 1: Use larger nodes with higher EBS limits
# Solution 2: Limit StatefulSet pods per node:
spec:
  affinity:
    podAntiAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        - labelSelector:
            matchLabels:
              app: postgres
          topologyKey: kubernetes.io/hostname
  # Ensures only 1 postgres pod per node
```

---

## 17. Quick Reference Cheat Sheet

### Key Commands

```bash
# ── EBS CSI DRIVER ───────────────────────────────────────────────
kubectl get pods -n kube-system | grep ebs-csi       # Check driver pods
kubectl logs -n kube-system -l app=ebs-csi-controller -c csi-provisioner
kubectl logs -n kube-system -l app=ebs-csi-node -c ebs-plugin

# ── PVC / PV ─────────────────────────────────────────────────────
kubectl get pvc --all-namespaces                     # All PVCs
kubectl get pv                                       # All PVs
kubectl describe pvc <name> -n <ns>                  # PVC details + events
kubectl patch pvc <name> -n <ns> \                   # Expand volume
  -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'

# ── STORAGE CLASSES ───────────────────────────────────────────────
kubectl get storageclass                             # List storage classes
kubectl describe storageclass ebs-gp3               # SC details

# ── FINDING YOUR EBS VOLUME ID ────────────────────────────────────
kubectl get pv <pv-name> -o jsonpath='{.spec.csi.volumeHandle}'

# ── AWS EBS CLI ───────────────────────────────────────────────────
aws ec2 describe-volumes --filters Name=status,Values=available   # Orphaned
aws ec2 describe-volumes --volume-ids vol-xxxxx                   # Volume details
aws ec2 modify-volume --volume-id vol-xxxxx --size 200            # Resize
aws ec2 create-snapshot --volume-id vol-xxxxx --description "manual backup"

# ── DISK USAGE INSIDE POD ─────────────────────────────────────────
kubectl exec -it <pod> -- df -h                     # Disk space
kubectl exec -it <pod> -- df -i                     # Inode usage
kubectl exec -it <pod> -- iostat -x 1 5             # I/O stats (live)
```

### Quick Decision Guide

```
WHAT DO YOU NEED?                 USE THIS
─────────────────────────────     ──────────────────────────────────────
Standard DB (dev/staging)         PVC: ebs-gp3, 20-50GB
Production DB (moderate traffic)  PVC: ebs-gp3-high-iops, 100GB+
Mission critical DB               PVC: ebs-io2, 200GB+
Shared files across pods          EFS (not EBS)
Temporary scratch space           emptyDir (no PVC needed — ephemeral)
Static assets (read-only)         ConfigMap or S3 + initContainer
Backups / Archives                PVC: ebs-sc1-cold

ACCESS MODE CHEAT SHEET
─────────────────────────────     ──────────────────────────────────────
ReadWriteOnce (RWO)               EBS — 1 pod, read+write. Use for DBs.
ReadWriteMany (RWX)               EFS — many pods, read+write. Use for uploads.
ReadOnlyMany (ROX)                Shared read-only data across pods.

STATEFULSET vs DEPLOYMENT
─────────────────────────────     ──────────────────────────────────────
StatefulSet + EBS                 Databases, message queues (Kafka)
                                  Each replica gets its own EBS volume
                                  Named predictably: data-postgres-0
Deployment + EBS                  Single-replica stateful apps
                                  (only works if replicas: 1)
Deployment + EFS                  Stateful apps that scale horizontally
```

---



---


