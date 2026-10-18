# Storage Systems

Three storage primitives underpin most of what runs in the cloud: block storage, object storage, and file systems. They're not interchangeable. Using the wrong one for a workload produces failures that look like application bugs until you trace them back to I/O semantics.

The choice isn't "which one is best." It's which one matches the access pattern of the workload.

## Fundamentals

### Block storage

Raw storage presented as a device. No filesystem semantics at the storage layer — the OS mounts it and handles the filesystem. Reads and writes at byte offsets. Low latency. High throughput. Suitable for anything that needs random access to structured data: databases, virtual machine disks, write-ahead logs.

A database needs to write a specific page at a specific offset, fsync it to disk, and read it back during crash recovery. That's a block storage workload. It requires low latency, random access, and durability guarantees at the I/O level. Object storage can't do this. Neither can a network file system without significant performance degradation.

Block storage attaches to one instance at a time (with exceptions — some shared block storage exists but is niche). If the instance dies, the block device can be detached and reattached to another instance. The data persists independently of the instance lifecycle.

### Object storage

Flat namespace of key-value pairs where the value is a binary blob. No directories (the `/` in a key name is convention, not hierarchy). No append in place — you write the full object or you don't. No random byte-offset access. Reads are always the full object or a byte-range request.

What you get in exchange: effectively unlimited scale, eleven-nines durability without any configuration, cheap storage per GB, global accessibility via HTTP, and no instance attachment required. Any service, anywhere, can read from or write to object storage given appropriate credentials.

Object storage is the right choice for: user-uploaded files, static web assets, data lake raw storage, backup archives, CloudFront origins, machine learning training data, log archives. It's the wrong choice for: anything that needs to be mounted as a filesystem, anything requiring in-place updates, anything where append performance matters.

The access pattern distinction:

```
Block storage (EBS):                  Object storage (S3):

db_file.seek(offset=4096)             s3.get_object(key="file.parquet")
db_file.write(8 bytes)                → returns full object (or byte range)
db_file.flush()
                                      s3.put_object(key="file.parquet", body=...)
(random read/write at byte offsets)   → replaces entire object
```

### File systems

Shared file systems present a familiar directory hierarchy accessible from multiple instances simultaneously. POSIX semantics: open, read, write, seek, close, with file locking. The expectation: multiple processes on multiple machines can read and write the same file with coherent results.

Useful for: shared configuration files that multiple services read, content management systems where the application server writes files and a CDN origin reads them, HPC workloads that need shared scratch space, legacy applications that assume a local filesystem but need to run at scale.

The trade-off: network file systems are slower than local block storage, always. A database running on NFS will perform worse than the same database on a local SSD, because every I/O crosses a network hop. Workloads that don't need sharing should not use a shared file system.

### Durability vs availability

Durability: the probability a stored object survives. S3's eleven-nines durability means losing one object per ten million per ten thousand years. EBS snapshots replicated across an AZ achieve similar durability. In-memory caches have zero durability — a restart loses the data.

Availability: the probability a stored object can be retrieved right now. A durable but unavailable system has the data, but you can't access it. These are distinct axes and need to be designed for separately.

## Operations

### IOPS, throughput, and latency

Block storage performance has three dimensions that matter depending on the workload type.

**IOPS (I/O operations per second).** Counts of read or write operations, independent of size. A transactional database doing many small random reads is IOPS-bound. Eight KB page reads at 10,000 IOPS is 80 MB/s throughput, but the constraint is the operation count, not the bandwidth.

**Throughput (MB/s).** Data volume per second. Analytic workloads doing large sequential scans are throughput-bound. Reading a 50 GB Parquet file sequentially doesn't need high IOPS — it needs high sequential read bandwidth.

**Latency.** Time per operation. Write-ahead log flushes on a database are latency-sensitive. Each transaction commit waits for the log flush to complete. A disk with high IOPS but variable latency will produce variable commit times, which surfaces as p99 latency spikes in the application.

Provisioned IOPS, throughput-optimized, and general purpose SSD are different points in this space. Know which dimension your workload is constrained by before choosing a volume type.

### The AZ pinning problem

Block storage is AZ-scoped. An EBS volume in us-east-1a cannot be attached to an instance in us-east-1b. The volume and the instance must be in the same AZ.

This creates a constraint in autoscaling groups: instances can only use EBS volumes from their AZ. Stateful workloads on EBS in an autoscaling fleet need per-AZ volume management. EBS snapshots can be copied across AZs or regions to restore in a different AZ, but that's a recovery operation, not transparent access.

Kubernetes inherits this fully. A PersistentVolume backed by EBS is pinned to one AZ. A pod that requests that PVC will be scheduled into that AZ. If the node in that AZ is replaced, the new node must also be in the same AZ. Topology-aware scheduling handles this, but it's a constraint to design around — not all workloads that seem stateless actually are.

### S3 consistency model

S3 provides strong read-after-write consistency for all operations as of 2020. Before that, there was an eventual consistency window for certain operations that caused real production bugs. Knowing the change matters because pre-2020 advice (add a delay after write, don't read immediately after delete) is now outdated.

What hasn't changed: S3 is eventually consistent across replication regions in S3 Cross-Region Replication. A write in us-east-1 is not immediately visible in eu-west-1 via CRR. Design accordingly.

### Data lifecycle and cost

Object storage cost accumulates over time unless lifecycle policies manage it. Logs written to S3 stay forever unless a lifecycle rule moves them to cheaper storage classes or expires them. Incomplete multipart uploads accumulate without a cleanup rule. Versioning enabled without a noncurrent version expiration policy doubles storage costs every time an object is overwritten.

Set lifecycle policies at bucket creation. Not retroactively when the bill arrives.

## Deep Dive: storage on AWS

**EBS (Elastic Block Store).** Block storage for EC2 instances. Four volume types in common use:

- `gp3`: general purpose SSD. Baseline 3,000 IOPS and 125 MB/s, independently configurable up to 16,000 IOPS and 1,000 MB/s. The default for most workloads. Cheaper than gp2 for equivalent performance.
- `io2 Block Express`: provisioned IOPS SSD. Up to 256,000 IOPS per volume. For high-performance databases where IOPS is the binding constraint. Significantly more expensive.
- `st1`: throughput-optimized HDD. Sequential read/write workloads. Data warehouses, log processing, large sequential scans. Not for random access.
- `sc1`: cold HDD. Infrequent access, large volumes, minimum cost.

EBS Multi-Attach: attach the same `io2` volume to up to 16 Nitro instances in the same AZ simultaneously. Applications must handle concurrent writes — this is not a transparent shared filesystem. Use it for clustered databases that manage their own I/O coordination (Oracle RAC, certain shared-disk databases), not for general file sharing.

**S3 (Simple Storage Service).** Six storage classes:

- Standard: frequent access, millisecond retrieval, highest cost per GB.
- Intelligent-Tiering: automatic movement between tiers based on access patterns. No retrieval fee. Small monitoring charge per object. The right default when access patterns are unknown or variable.
- Standard-IA and One Zone-IA: infrequent access, lower storage cost, retrieval fee per GB. One Zone-IA trades AZ redundancy for lower cost — appropriate for data that can be recreated.
- Glacier Instant Retrieval / Flexible Retrieval / Deep Archive: cold storage at progressively lower cost and higher retrieval latency. Deep Archive retrieval can take 12 hours.

S3 Transfer Acceleration: routes uploads through CloudFront edge nodes to reach S3 faster from distant regions. Useful for globally distributed file uploads to a central bucket.

**EFS (Elastic File System).** POSIX-compliant managed NFS. Multiple instances across multiple AZs mount the same filesystem simultaneously. Performance scales automatically with storage. Two modes: General Purpose (lower latency, most workloads) and Max I/O (higher throughput, higher latency, parallel workloads). Bursting throughput is provisioned; baseline drops as storage drops below 1 TB unless provisioned throughput is purchased.

EFS is significantly more expensive per GB than EBS or S3. It's the right choice when the workload requires shared file access. If sharing isn't required, EBS is faster and cheaper.

**FSx family.** Managed implementations of specific filesystems: FSx for Lustre (high-performance computing, ML training data), FSx for Windows File Server (SMB protocol, Active Directory integration), FSx for NetApp ONTAP (NAS semantics on AWS), FSx for OpenZFS. Use when a specific filesystem protocol or feature set is required and EFS doesn't fit.

| | EBS | S3 | EFS | FSx for Lustre |
|---|---|---|---|---|
| Access model | Block (single instance) | Object (HTTP) | File (multi-instance NFS) | File (parallel HPC) |
| Latency | Sub-millisecond | Milliseconds | Low milliseconds | Sub-millisecond |
| Sharing | No (single attach, or Multi-Attach io2) | Yes (any client) | Yes (multi-AZ NFS) | Yes (parallel) |
| Use case | Databases, OS volumes | Static assets, data lakes, backups | Shared app files, CMS | ML training, HPC |
| Durability | 99.999% within AZ | 99.999999999% | 99.999999999% | Varies |

## What's next

Day 23: network security — defense in depth across the network layer, what security groups and NACLs actually enforce, and how zero trust changes the model when the network perimeter disappears.

---

*Part of the [System Design for DevOps & Cloud Engineers](README.md) series — 75 days, one concept at a time.*
