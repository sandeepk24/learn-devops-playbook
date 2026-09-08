# Docker Fundamentals for the Advanced DevOps Engineer
## Part 3 of 3 — Networking, Security, Signals & Production Debugging

> *Understanding the security model and failure modes is what separates an operator from a practitioner.*

**Series:** Docker Internals · Part 3 of 3  
**Tags:** `Docker` `Security` `Networking` `cgroups` `Debugging` `Production` `Signals`  

---

**What's in this series**

| Part | Topic | Focus |
|---|---|---|
| Part 1 — Previous | Execution Stack, Namespaces, cgroups | How Docker works at the kernel level |
| Part 2 — Previous | OverlayFS, OCI Standard, BuildKit | Storage, open standards, build engine |
| **Part 3 — Today** | Networking, Security, Signals, Production Debugging | Running and operating Docker safely |

---

**From Parts 1 & 2 — foundations to carry forward**

- Docker is a 5-layer stack: CLI → dockerd → containerd → shim → runc
- Namespaces isolate visibility; cgroups limit consumption; both are kernel filesystems
- OverlayFS shares read-only image layers; container writes go to a per-container UpperDir
- `RUN rm` cannot remove secrets from lower layers — use BuildKit `--mount=type=secret`
- Multi-stage builds with cache mounts are the standard for production image size discipline

---

## Section 7 — Container Networking: Under the Bridge

Docker networking is a full network virtualization stack built out of tools the Linux kernel already provides. When you start a container on the default bridge network, Docker creates an entire virtual network infrastructure on the host using tools that have existed in the Linux kernel since 2.6.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           LINUX HOST                                     │
│                                                                          │
│  ┌────────────┐                                   ┌────────────────────┐ │
│  │ Container A│                                   │   Container B      │ │
│  │            │                                   │                    │ │
│  │ eth0       │◄──────── same L2 segment ────────►│ eth0               │ │
│  │ 172.17.0.2 │                                   │ 172.17.0.3         │ │
│  └─────┬──────┘                                   └──────────┬─────────┘ │
│        │ veth pair                                           │ veth pair  │
│        │ (one end in container                               │            │
│        │  ns, one end on host)                               │            │
│  ┌─────▼─────────────────────────────────────────────────────▼────────┐  │
│  │                     docker0 (Linux bridge)                          │  │
│  │                     172.17.0.1 — the container gateway              │  │
│  └────────────────────────────────┬─────────────────────────────────── ┘  │
│                                   │ iptables MASQUERADE (SNAT)             │
│                                   │ containers appear as host IP outbound  │
│                                   ▼                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │           eth0 / ens3 (physical NIC)  e.g. 192.168.1.100           │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### Seeing the network plumbing from the host

```bash
# The bridge Docker created
ip link show docker0
# 3: docker0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue
#     link/ether 02:42:9a:3b:1c:4d brd ff:ff:ff:ff:ff:ff

# The veth pairs — one per running container
ip link show | grep veth
# 5: veth3a8e2c1@if4: <BROADCAST,MULTICAST,UP,LOWER_UP> ...
# 7: veth9f2b1d3@if6: <BROADCAST,MULTICAST,UP,LOWER_UP> ...

# The iptables NAT rules Docker manages
iptables -t nat -L DOCKER -n --line-numbers
# The rule for -p 8080:80:
# DNAT tcp -- 0.0.0.0/0  0.0.0.0/0  tcp dpt:8080 to:172.17.0.2:80
# Translation: incoming TCP to host port 8080 → container at 172.17.0.2:80
```

### Default bridge vs user-defined networks: a critical difference

On the default `bridge` network (`docker0`), containers communicate by IP address only — there is no DNS resolution. On a user-defined bridge network, Docker embeds an internal DNS resolver at `127.0.0.11` that resolves container names to their current IP addresses. This is why production `docker-compose.yml` files always use named networks.

```bash
# Create a user-defined network
docker network create mynet

# Start two containers on it
docker run -d --name api    --network mynet nginx:alpine
docker run -d --name worker --network mynet nginx:alpine

# From inside worker, 'api' resolves to the container's IP
docker exec worker wget -qO- http://api/
# Works — because Docker runs an embedded DNS server

# Prove the DNS server exists
docker exec worker nslookup api
# Server:  127.0.0.11      ← embedded DNS at this address
# Address: 127.0.0.11:53
# Name:    api
# Address: 172.18.0.2
```

### Host network: eliminating NAT for high-throughput workloads

`--network=host` removes the entire virtual networking stack and attaches the container directly to the host's network namespace. No veth pairs, no bridge, no iptables NAT rules.

```bash
# Container shares the host network stack directly
docker run --network=host nginx
# nginx binds directly to host port 80 — no port mapping required

# Trade-offs:
# ✓ Zero NAT overhead — network latency identical to a bare-metal process
# ✓ No port mapping required — container uses host ports directly
# ✓ Essential for network monitoring tools that need to see host interfaces
# ✗ No network isolation — container can see ALL host interfaces and ports
# ✗ Port conflicts — container cannot use a port already bound on the host

# Verify: from inside a host-network container, you see host interfaces
docker run --rm --network=host alpine ip link show
# Same output as running 'ip link show' on the host itself
```

---

## Section 8 — Security: The Layers Between a Container and the Host

Container security is not binary. It is a set of overlapping defense-in-depth mechanisms. Understanding each layer lets you make informed trade-offs between security and functionality.

```
┌────────────────────────────────────────────────────────────────────────┐
│               CONTAINER SECURITY LAYERS (outermost → innermost)         │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  USER NAMESPACES — rootless Docker                               │  │
│  │  UID 0 inside the container maps to UID 1000+ on the host.       │  │
│  │  Root exploits inside the container cannot escalate on host.     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  LINUX CAPABILITIES — decompose root privilege                   │  │
│  │  Drop all ~40 capabilities, add back only what's explicitly      │  │
│  │  needed. Default drops: SYS_ADMIN, SYS_PTRACE, NET_ADMIN...     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  SECCOMP — syscall firewall                                      │  │
│  │  Docker's default profile blocks ~44 of 300+ Linux syscalls.     │  │
│  │  Blocked: ptrace, kexec_load, mount, reboot, pivot_root...      │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  APPARMOR / SELINUX — mandatory access control                  │  │
│  │  Kernel-enforced policy that overrides Unix permissions.         │  │
│  │  Even root cannot violate an AppArmor policy.                    │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  READ-ONLY ROOTFS + NO-NEW-PRIVILEGES                           │  │
│  │  Container cannot write to rootfs; processes cannot gain         │  │
│  │  capabilities beyond what they started with.                     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
```

### Linux capabilities: root is not binary

Linux capabilities decompose the traditional all-or-nothing root privilege into ~40 discrete permissions. Docker drops a significant set by default. The engineer's job is to understand which capabilities a given workload legitimately needs.

```bash
# See the capabilities a container has by default
docker run --rm alpine \
  sh -c "apk add -q libcap && capsh --print 2>/dev/null | grep Current"

# Current: cap_chown, cap_dac_override, cap_fowner, cap_fsetid,
#          cap_kill, cap_setgid, cap_setuid, cap_setpcap,
#          cap_net_bind_service, cap_net_raw, cap_sys_chroot,
#          cap_mknod, cap_audit_write, cap_setfcap

# Hardened: drop ALL capabilities, add back only what's needed
docker run --rm \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \     # allow binding ports < 1024
  nginx:alpine

# --privileged grants ALL capabilities and disables seccomp + AppArmor
# This is functionally equivalent to running as root on the host
# Never use in production — only in tooling that explicitly accepts the risk
docker run --privileged nginx:alpine  # ← DO NOT DO THIS IN PRODUCTION
```

### seccomp: the syscall firewall

The default Docker seccomp profile blocks syscalls that could break container isolation. When you see "Operation not permitted" for a system call inside a container, seccomp is likely the cause.

```bash
# Run with no seccomp restriction (dangerous — for debugging only)
docker run --rm --security-opt seccomp=unconfined alpine sh

# Apply a minimal custom seccomp profile for a simple application
cat > minimal-seccomp.json << 'EOF'
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    {
      "names": [
        "read", "write", "open", "openat", "close", "stat", "fstat",
        "lstat", "mmap", "mprotect", "munmap", "brk", "rt_sigaction",
        "rt_sigprocmask", "exit", "exit_group", "futex", "clone",
        "execve", "wait4", "arch_prctl", "set_tid_address", "set_robust_list"
      ],
      "action": "SCMP_ACT_ALLOW"
    }
  ]
}
EOF

docker run --rm \
  --security-opt seccomp=minimal-seccomp.json \
  alpine echo "running with minimal syscall surface"
```

### The hardened production container: all layers applied

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.19 AS base

# Create a non-root user at image build time
RUN addgroup -S appgrp && adduser -S appuser -G appgrp

FROM base AS production
WORKDIR /app
COPY --chown=appuser:appgrp dist/ ./dist/

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1

# Exec form ensures PID 1 = your application (not a shell)
ENTRYPOINT ["./dist/server"]
```

```bash
docker run -d \
  --name api \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  --read-only \                         # rootfs is immutable
  --tmpfs /tmp:size=64m,noexec \        # writable but non-executable temp
  --security-opt no-new-privileges \    # processes cannot gain capabilities
  --security-opt seccomp=./profile.json \
  -p 8080:8080 \
  my-app:hardened
```

---

## Section 9 — The Signals Problem: Why Your Containers Take 10 Seconds to Stop

This is one of the most common production problems engineers don't realise is Docker-related. It causes slow deploys, in-flight request failures during rolling updates, and inexplicable latency during scale-down events.

```
docker stop my-container
       │
       ▼
SIGTERM sent to PID 1 in the container namespace
       │
       ├── PID 1 = /bin/sh (shell form Dockerfile)
       │   The shell does NOT forward SIGTERM to child processes
       │   Shell ignores SIGTERM by default
       │   → 10 second timeout → SIGKILL → abrupt termination
       │   → in-flight requests fail, connections dropped
       │
       └── PID 1 = your application (exec form Dockerfile)
           Application receives SIGTERM directly
           → Application drains connections
           → Application exits cleanly
           → Fast, graceful shutdown
```

### Shell form vs exec form — the difference that matters

```dockerfile
# SHELL FORM — spawns /bin/sh -c "node server.js"
# PID 1 = /bin/sh, not node
# node never receives SIGTERM — it gets SIGKILL after 10 seconds
CMD node server.js

# EXEC FORM — runs node directly as PID 1
# node receives SIGTERM and can shut down gracefully
CMD ["node", "server.js"]

# ENTRYPOINT + CMD exec form — the preferred production pattern
ENTRYPOINT ["node"]
CMD ["dist/server.js"]
```

```bash
# Verify what PID 1 is in your running container
docker exec my-container cat /proc/1/cmdline | tr '\0' ' '

# BAD output: /bin/sh -c node server.js
# GOOD output: node dist/server.js
```

### The init process solution for multi-process containers

If your container legitimately needs multiple processes — main application plus a metrics sidecar, log forwarder, or local agent — PID 1 should be a proper init process that forwards signals and reaps zombie processes.

```bash
# Docker's built-in tini init process (--init flag)
docker run --init my-app
# PID 1 = /sbin/docker-init (tini)
# tini forwards signals to all children and reaps zombies

# Or embed tini directly in the Dockerfile for portability
FROM alpine:3.19
RUN apk add --no-cache tini
COPY app /app
ENTRYPOINT ["/sbin/tini", "--", "/app/server"]
CMD ["--config", "/etc/app/config.yaml"]
```

---

## Section 10 — The Production Debugging Toolkit

When something breaks, knowing exactly which tool reaches into which layer of the stack determines how fast you find it.

```
Container not starting?
├── docker inspect <id>
│   Check: State.Status, State.ExitCode, State.OOMKilled, State.Error
├── docker logs <id> --tail=50
│   Check: application stderr/stdout from the last N lines
└── docker events --filter container=<id>
    Check: what the Docker daemon did and when

Container starting but behaving wrong?
├── docker exec <id> /bin/sh       — enter the container namespace
├── docker top <id>                 — processes and their PIDs inside
└── docker stats <id>               — live CPU/memory/net/block I/O

Resource anomalies?
├── docker stats --no-stream       — point-in-time snapshot
├── /sys/fs/cgroup/.../cpu.stat    — kernel throttle data (throttled_usec)
└── /sys/fs/cgroup/.../memory.events — OOM event count (oom_kill)

Network issues?
├── docker network inspect <net>   — containers, IPs, gateways
├── nsenter --net --target <pid>   — enter container net NS, run ip/ss/netstat
└── iptables -t nat -L -n          — port mapping and masquerade rules

Image / build issues?
├── docker history --no-trunc <img>  — full layer history with commands
├── docker inspect <img>             — complete image metadata and config
└── dive <img>                       — interactive layer explorer with waste analysis
```

### Commands that reach below the Docker abstraction

These are the tools that matter when `docker` commands fail or when the abstraction isn't giving you enough signal.

```bash
# Enter a container's namespaces WITHOUT docker exec
# Critical when: dockerd is unresponsive but the container is still serving traffic
# (The shim keeps the container alive even when dockerd is down)
CONTAINER_PID=$(docker inspect --format '{{.State.Pid}}' my-container)
nsenter \
  --target ${CONTAINER_PID} \
  --mount --uts --ipc --net --pid \
  -- /bin/bash
# You are now inside the container's namespaces

# Trace all syscalls a container process makes
# Useful for: debugging mysterious "Operation not permitted" errors
strace -p ${CONTAINER_PID} -f -e trace=network,file 2>&1 | head -50

# Read cgroup resource usage directly — bypasses docker stats entirely
CONTAINER_ID=$(docker inspect --format '{{.Id}}' my-container)

# CPU throttle data — the thing docker stats doesn't show you
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/cpu.stat

# Memory breakdown — more accurate than docker stats Working Set
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/memory.stat

# OOM event counter — confirms if OOM kills have occurred
cat /sys/fs/cgroup/system.slice/docker-${CONTAINER_ID}.scope/memory.events

# Inspect a running container's OverlayFS UpperDir
# See exactly what the container has written since it started
UPPER=$(docker inspect my-container \
  --format '{{.GraphDriver.Data.UpperDir}}')
find ${UPPER} -type f -newer /proc/1 2>/dev/null | head -20

# Check for SUID binaries in your image (potential privilege escalation path)
docker run --rm my-image:latest find / -perm /4000 -type f 2>/dev/null

# Inspect an image's manifest and layer structure without pulling it
# (requires crane from google/go-containerregistry)
crane manifest nginx:latest | python3 -m json.tool
```

---

## Section 11 — Ten Truths Senior Engineers Know That Articles Skip

These are the things you learn from production incidents, not tutorials.

**1. The Docker socket is a root backdoor.**
Mounting `-v /var/run/docker.sock:/var/run/docker.sock` gives that container full root access to the host. Any process inside can spawn a `--privileged` container, mount the host filesystem at `/`, and read or write anything. Never do this in production. CI tools that need this (like Docker-in-Docker) should use explicit rootless alternatives or socket proxies.

**2. `ENV` variables are visible to every process and in `docker inspect`.**
`docker inspect my-container` shows all environment variables in plaintext to anyone with Docker daemon access. Never put secrets in `ENV`. Use `--mount=type=secret` during build and runtime secret managers (Vault, AWS Secrets Manager, Kubernetes Secrets) at runtime.

**3. Layer order is a cache strategy, not a style preference.**
Instructions that change rarely go first. Instructions that change frequently go last. Changing any instruction invalidates all layers below it in the cache. `COPY . .` before `RUN pip install` means every code change re-downloads all packages. Inverting the order means incremental builds cost almost nothing.

**4. `docker cp` and `docker exec` use different mechanisms.**
`docker cp` extracts from the container's MergedDir (the OverlayFS union view) — it works even if the container has no shell. `docker exec` uses `setns()` to join the container's namespaces and then executes a process. Neither requires the container to have bash, sh, or any shell installed.

**5. Containers share the host kernel — kernel exploits affect all containers on the host.**
If a kernel vulnerability allows namespace escape (CVE-2019-5736 in runc is the canonical example), all containers on the host are potentially compromised simultaneously. This is exactly why AWS Lambda uses Firecracker microVMs and Google Cloud Run uses gVisor — they provide VM-level kernel isolation that containers cannot.

**6. `docker stats` memory reporting is misleading without context.**
`docker stats` reports Working Set memory, which includes page cache (filesystem buffer cache). The kernel can reclaim page cache under pressure. A container showing 400MB in `docker stats` might only have 150MB of private memory that actually matters. Use `memory.stat` in the cgroup for accurate breakdown — specifically `anon` for private memory.

**7. The `latest` tag is not a version — it is a moving target.**
Two `docker pull nginx:latest` commands executed hours apart may return different images with different layer hashes and different CVE profiles. In production, always pin to a specific digest: `nginx@sha256:abc123def456...`. The digest is content-addressed and immutable — it cannot be overwritten.

**8. Bind mounts and volumes have different performance profiles depending on the platform.**
On Docker Desktop (macOS, Windows), bind mounts cross a hypervisor boundary and are significantly slower than volumes, which live inside the Docker VM. On Linux, both bypass OverlayFS and are equivalent. Use volumes for production data, bind mounts for local development on Linux. Use volumes for everything on Docker Desktop.

**9. `docker build` sends the entire build context to the daemon before a single instruction runs.**
Every file not excluded by `.dockerignore` is archived and sent over the Unix socket to dockerd. A build directory containing `node_modules` (200MB+) or build artifacts will transfer all of that before layer caching even begins. The build appears to "hang" for minutes before showing any output. Always write `.dockerignore` before writing a `Dockerfile`.

```bash
# Check what your build context will send BEFORE running docker build
du -sh --exclude=.git --exclude=node_modules .
# If this number is > 50MB, your .dockerignore needs work

# A comprehensive .dockerignore
cat > .dockerignore << 'EOF'
.git
.gitignore
node_modules
__pycache__
*.pyc
dist/
build/
*.egg-info/
.env
.env.*
*.pem
*.key
.vscode/
.idea/
.DS_Store
Thumbs.db
tests/
*.test.js
*.spec.js
coverage/
.nyc_output/
Dockerfile*
docker-compose*
.dockerignore
README.md
docs/
EOF
```

**10. Containers that write logs to files inside the container are doing it wrong.**
Logs written to files in the container go to the OverlayFS UpperDir. They consume host disk, they don't rotate automatically (the container has no logrotate), and they're not accessible via `docker logs` — because `docker logs` reads from the container's stdout/stderr streams captured by containerd. Twelve-factor containers write everything to stdout and stderr. Docker routes these to a configurable logging driver (json-file, awslogs, fluentd, journald) without any application-level change.

---

## Architecture Summary: The Full Mental Model

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     DOCKER EXECUTION MODEL — COMPLETE                     │
│                                                                            │
│  CLI ──REST──► dockerd ──gRPC──► containerd ──fork──► containerd-shim    │
│                  │                    │                       │            │
│                  │              [image store]         [per-container       │
│                  │              [snapshots ]           keeper process]     │
│                  │                    │                       │            │
│             [libnetwork]              └────exec──► runc   (ephemeral)     │
│             [volumes]                                  │                   │
│             [build/push]                         [syscalls to kernel]      │
│                                                        │                   │
│                                   ┌────────────────────┼──────────────┐   │
│                                   │                    │              │   │
│                             [Namespaces]         [cgroups v2]   [OverlayFS]│
│                             pid net mnt           cpu memory    lowerdir  │
│                             uts ipc user          io pids       upperdir  │
│                             cgroup time           hierarchy     mergeddir │
│                                   │                    │              │   │
│                             [Capabilities]       [seccomp]    [AppArmor]  │
│                             (what root            (syscall     (MAC        │
│                              can do)               filter)      policy)   │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Further Depth

For engineers who want to go to the source:

**Linux namespaces and cgroups** — `man 7 namespaces`, `man 7 cgroups`, and the authoritative kernel docs at `kernel.org/doc/html/latest/admin-guide/cgroup-v2.html`

**OCI specifications** — the actual specs that define the image format and runtime contract: `github.com/opencontainers/runtime-spec` and `github.com/opencontainers/image-spec`

**containerd architecture** — `github.com/containerd/containerd/blob/main/docs/architecture.md`

**BuildKit internals** — `github.com/moby/buildkit/blob/master/docs/architecture.md`

**Running runc manually** — `github.com/opencontainers/runc/blob/main/docs/` — the most direct path to understanding what Docker does at the kernel boundary

**gVisor** — `gvisor.dev/docs/architecture_guide/` — an alternative "kernel" for containers that intercepts syscalls in userspace, providing stronger isolation than standard Linux namespaces

**Firecracker** — `github.com/firecracker-microvm/firecracker` — the microVM technology behind AWS Lambda that provides full VM isolation with container-like startup times

---

*All commands validated against Docker Engine 26.x, containerd 1.7.x, runc 1.1.x, Linux kernel 6.x with cgroups v2. Cgroup paths use the systemd cgroup driver, which is the default on Ubuntu 22.04+, Debian 11+, RHEL 9+, and Amazon Linux 2023. For cgroupfs driver (older systems), paths differ — check `docker info | grep "Cgroup Driver"` to confirm.*
