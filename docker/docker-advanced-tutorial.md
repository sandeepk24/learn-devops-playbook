# 🐳 Docker Advanced Commands: The Complete Field Guide

> **Audience:** Developers and DevOps engineers who are comfortable with basic Docker operations (`docker run`, `docker ps`, `docker build`) and are ready to move into production-grade workflows, orchestration, and operational mastery.

---

## Table of Contents

1. [Docker Compose Orchestration](#1-docker-compose-orchestration)
2. [Image Portability: Save, Load, Export & Import](#2-image-portability-save-load-export--import)
3. [System Health & Disk Management](#3-system-health--disk-management)
4. [Registry Operations: Tag, Push, Login & Logout](#4-registry-operations-tag-push-login--logout)
5. [Docker Swarm: Container Clustering at Scale](#5-docker-swarm-container-clustering-at-scale)
6. [Stack Deployments in Swarm Mode](#6-stack-deployments-in-swarm-mode)
7. [Container Checkpointing: Freeze & Restore](#7-container-checkpointing-freeze--restore)
8. [Real-World Workflow Patterns](#8-real-world-workflow-patterns)
9. [Quick Reference Cheat Sheet](#9-quick-reference-cheat-sheet)

---

## Why "Advanced" Docker Matters

Anyone can spin up a container. What separates a proficient Docker user from a seasoned practitioner is the ability to manage **multi-service architectures**, orchestrate **distributed workloads**, maintain **clean and efficient systems**, and **move images safely** between environments. The 21 commands covered in this guide represent the operational toolkit you reach for when the basics are no longer enough.

---

## 1. Docker Compose Orchestration

Docker Compose is not just a convenience wrapper — it is the declarative interface for defining, running, and managing multi-container applications. Think of a `docker-compose.yml` file as the single source of truth for your application's topology.

### 1.1 `docker-compose up` — Bringing Services to Life

```bash
docker-compose up
```

This command reads your `docker-compose.yml`, creates the necessary networks and volumes, pulls or builds images, and starts all defined services **in dependency order**. Add the `-d` (detached) flag to run everything in the background:

```bash
docker-compose up -d
```

**What it really does under the hood:**
- Creates a dedicated bridge network (e.g., `myapp_default`)
- Resolves service dependencies specified by `depends_on`
- Mounts volumes declared in the file
- Streams aggregated logs from all containers to stdout (unless `-d` is used)

**Pro tip:** Use `--build` to force a rebuild of images even if they already exist:

```bash
docker-compose up --build -d
```

### 1.2 `docker-compose down` — Tearing Down Cleanly

```bash
docker-compose down
```

This is the mirror of `up`. It stops all running containers, removes them, and deletes the associated networks. It does **not** remove named volumes or images by default — a deliberate safety measure.

To also remove volumes (⚠️ destroys persistent data):

```bash
docker-compose down -v
```

To also remove locally built images:

```bash
docker-compose down --rmi local
```

**When to use this vs. `docker-compose stop`:** Use `down` when you want a complete teardown of the application stack. Use `stop` when you just want to pause services without removing containers — useful during development when you want to restart quickly without re-creating containers.

### 1.3 `docker-compose logs` — Diagnosing Your Stack

```bash
docker-compose logs
```

This aggregates and streams logs from all services defined in your Compose file. This is really useful for debugging startup race conditions and inter-service communication errors.

Useful flags:

```bash
# Follow logs in real-time (like tail -f)
docker-compose logs -f

# Limit output to a specific service
docker-compose logs -f web

# Show the last 50 lines
docker-compose logs --tail=50
```

**Pro tip:** Pair `logs -f` with a specific service name during active development. You'll catch errors much faster than grepping through individual container logs.

### 1.4 `docker-compose exec` — Running Commands Inside Services

```bash
docker-compose exec service_name bash
```

This is the Compose-aware equivalent of `docker exec`. It targets a service by **name** (as defined in your `docker-compose.yml`) rather than by container ID or name — a critical distinction because container names can change on restarts.

Common real-world uses:

```bash
# Open a shell in your web service
docker-compose exec web bash

# Run a Django management command
docker-compose exec web python manage.py migrate

# Inspect your database
docker-compose exec db psql -U postgres -d mydb

# Run a one-off Node.js script
docker-compose exec api node scripts/seed.js
```

**Why this matters:** In a Compose environment, you should almost always prefer `docker-compose exec` over `docker exec` because it respects the service abstraction and always connects to the correct container even if you have scaled services.

---

## 2. Image Portability: Save, Load, Export & Import

Understanding the difference between these four commands is one of the most misunderstood areas of Docker. They solve different problems and operate on different underlying objects — images vs. containers.

| Command | Operates On | Preserves Layers/History | Primary Use Case |
|---|---|---|---|
| `docker save` | **Image** | ✅ Yes | Move images between registries/hosts |
| `docker load` | **Image** (from tar) | ✅ Yes | Restore a saved image |
| `docker export` | **Container** | ❌ No | Snapshot a running container's filesystem |
| `docker import` | **Filesystem tar** | ❌ No | Create a minimal base image |

### 2.1 `docker save` — Exporting an Image to a Tar Archive

```bash
docker save -o my_image.tar my_image:tag
```

This serializes a Docker image — along with all its intermediate layers, metadata, and history — into a single `.tar` file. This is the right tool when you need to:
- Transfer an image to an air-gapped machine with no registry access
- Archive a specific version of an image for compliance or disaster recovery
- Share a private image with a colleague without setting up a registry

Save multiple images into a single archive:

```bash
docker save -o app_bundle.tar frontend:1.0 backend:2.1 nginx:alpine
```

### 2.2 `docker load` — Restoring an Image from a Tar Archive

```bash
docker load < my_image.tar
```

This is the exact inverse of `docker save`. It reads a tar archive and restores the full image — layers, tags, and all — into your local Docker image store.

Alternative syntax (equivalent):

```bash
docker load -i my_image.tar
```

Upon success, Docker will report the image ID and any tags that were restored.

### 2.3 `docker export` — Snapshotting a Container's Filesystem

```bash
docker export container_name > container.tar
```

This exports the **live filesystem** of a running or stopped container as a flat tar archive. It captures the current state of the writable layer merged with all image layers — but critically, **it strips all metadata**: no Dockerfile history, no environment variables, no exposed ports, no entrypoints.

**When would you use this?** Primarily for creating minimal base images by exporting a container that was built with custom tooling, or for forensic inspection of a container's filesystem at a point in time.

### 2.4 `docker import` — Creating an Image from a Filesystem Tar

```bash
docker import container.tar my_new_image
```

This creates a new Docker image from a flat tar archive (typically produced by `docker export`). Because there's no layer history, the resulting image has a single layer and no inherited configuration.

You can specify a CMD at import time:

```bash
docker import container.tar my_new_image -- /bin/bash
```

**The `save/load` vs. `export/import` distinction summarized:** Think of `save/load` as a full backup-and-restore of an image (layers intact). Think of `export/import` as a filesystem snapshot that produces a new, minimal, single-layer image with no history.

---

## 3. System Health & Disk Management

Docker objects accumulate quietly. Images, stopped containers, unnamed volumes, and dangling build caches can consume significant disk space over time. These two commands are your primary tools for visibility and cleanup.

### 3.1 `docker system df` — Understanding Your Docker Disk Footprint

```bash
docker system df
```

This provides a breakdown of disk usage across all Docker object types:

```
TYPE            TOTAL     ACTIVE    SIZE      RECLAIMABLE
Images          23        11        4.2GB     2.1GB (50%)
Containers      5         2         120MB     80MB (67%)
Local Volumes   8         3         1.5GB     600MB (40%)
Build Cache     –         –         800MB     800MB
```

For a verbose listing showing individual objects:

```bash
docker system df -v
```

**Pro tip:** Run this before and after a `prune` operation to understand exactly what was reclaimed. It's also a great command to run when CI/CD build agents start failing with "no space left on device" errors.

### 3.2 `docker system prune` — Reclaiming Disk Space

```bash
docker system prune
```

This is the nuclear option for disk reclamation. By default it removes:
- All **stopped containers**
- All **dangling images** (untagged, not referenced by any container)
- All **unused networks**
- All **dangling build cache** entries

To also remove unused volumes (⚠️ can destroy data):

```bash
docker system prune --volumes
```

To remove **all** unused images (not just dangling ones):

```bash
docker system prune -a
```

To skip the confirmation prompt (useful in CI/CD scripts):

```bash
docker system prune -f
```

**A word of caution:** `docker system prune -a --volumes -f` is a perfectly reasonable command to run on a CI build agent between jobs. On a development machine or production host, always review what will be removed first.

---

## 4. Registry Operations: Tag, Push, Login & Logout

Working with Docker registries — Docker Hub, AWS ECR, Google Artifact Registry, or a private Harbor instance — requires understanding the tag convention and the authentication flow.

### 4.1 `docker tag` — Naming Images for Registry Distribution

```bash
docker tag old_image_name new_image_name
```

Tags are not copies — they are aliases. Both names point to the same image layers. The tag is how Docker knows **which registry** to push to and **what version** to use.

The full tag format is: `[registry_host:port/][namespace/]repository[:tag]`

Real-world examples:

```bash
# Tag for Docker Hub under your username
docker tag my_app:latest yourusername/my_app:1.0.0

# Tag for AWS ECR
docker tag my_app:latest 123456789.dkr.ecr.us-east-1.amazonaws.com/my_app:1.0.0

# Tag for GitHub Container Registry
docker tag my_app:latest ghcr.io/yourorg/my_app:1.0.0

# Always tag both a versioned tag AND latest
docker tag my_app:1.0.0 yourusername/my_app:latest
```

**Best practice:** Always maintain both a semantic version tag (`1.0.0`) and a `latest` tag. The version tag is immutable reference; `latest` is your mutable pointer.

### 4.2 `docker push` — Publishing Images to a Registry

```bash
docker push my_image:tag
```

This uploads your local image layers to the configured registry. Docker is smart about this — it compares layer digests and only uploads layers that don't already exist in the registry, making repeated pushes of similar images very efficient.

```bash
# Push to Docker Hub
docker push yourusername/my_app:1.0.0

# Push to ECR (after tagging)
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/my_app:1.0.0

# Push all tags for an image
docker push --all-tags yourusername/my_app
```

### 4.3 `docker login` — Authenticating to a Registry

```bash
docker login
```

Without arguments, this authenticates to Docker Hub. You'll be prompted for username and password. Credentials are stored in your Docker credential store (or `~/.docker/config.json` if no credential helper is configured).

For private or cloud registries:

```bash
# Login to GitHub Container Registry
docker login ghcr.io

# Login to AWS ECR (using AWS CLI to generate a token)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  123456789.dkr.ecr.us-east-1.amazonaws.com
```

**Security note:** Avoid passing passwords directly via `-p` on the command line — they appear in shell history and process lists. Use `--password-stdin` instead.

### 4.4 `docker logout` — Clearing Registry Credentials

```bash
docker logout
```

This removes stored credentials for the specified registry from your credential store. Always run this on shared machines or CI/CD runners after a push operation.

```bash
# Logout from a specific registry
docker logout ghcr.io
docker logout 123456789.dkr.ecr.us-east-1.amazonaws.com
```

---

## 5. Docker Swarm: Container Clustering at Scale

Docker Swarm turns a pool of Docker hosts into a single, unified cluster. While Kubernetes dominates the enterprise orchestration conversation, Swarm remains a compelling choice for teams that want Kubernetes-like orchestration without the operational overhead.

### 5.1 `docker swarm init` — Bootstrapping a Swarm Cluster

```bash
docker swarm init
```

This command turns the current Docker host into a **Swarm manager node** and prints a `docker swarm join` token that worker nodes can use to join the cluster.

On a multi-interface host, specify the advertise address:

```bash
docker swarm init --advertise-addr 192.168.1.100
```

After initialization, Docker outputs a join command like:

```
To add a worker to this swarm, run the following command:
    docker swarm join --token SWMTKN-1-xxx... 192.168.1.100:2377
```

**Key Swarm concepts to understand before proceeding:**
- **Manager nodes** handle cluster state, scheduling, and the Raft consensus algorithm
- **Worker nodes** run tasks but don't participate in cluster management decisions
- A cluster should have an **odd number of managers** (1, 3, 5) to maintain quorum

### 5.2 `docker service create` — Deploying a Replicated Service

```bash
docker service create --name my_service nginx
```

In Swarm mode, you don't run containers directly — you declare **services**. A service is a desired state: "I want 3 replicas of this image running at all times." The Swarm manager reconciles reality toward that state continuously.

Real-world example with full configuration:

```bash
docker service create \
  --name web \
  --replicas 3 \
  --publish published=80,target=80 \
  --update-parallelism 1 \
  --update-delay 10s \
  --restart-condition on-failure \
  --constraint 'node.role == worker' \
  nginx:alpine
```

Scaling a service up or down:

```bash
docker service scale web=5
```

Inspecting service status:

```bash
docker service ls
docker service ps web
docker service logs web
```

---

## 6. Stack Deployments in Swarm Mode

Stacks bring the declarative, multi-service model of Docker Compose into the Swarm world. A stack is essentially a Compose file deployed across a cluster.

### 6.1 `docker stack deploy` — Deploying a Multi-Service Stack

```bash
docker stack deploy -c docker-compose.yml my_stack
```

This command reads a Compose file (version 3.x) and deploys all defined services as a Swarm stack. It's idempotent — run it again to update a running stack with new configuration.

Example `docker-compose.yml` for stack deployment:

```yaml
version: "3.8"
services:
  web:
    image: nginx:alpine
    deploy:
      replicas: 3
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure
    ports:
      - "80:80"

  redis:
    image: redis:alpine
    deploy:
      replicas: 1
      placement:
        constraints:
          - node.role == manager
```

Deploy and then verify:

```bash
docker stack deploy -c docker-compose.yml my_stack
docker stack services my_stack
docker stack ps my_stack
```

### 6.2 `docker stack rm` — Removing a Stack

```bash
docker stack rm my_stack
```

This removes all services, networks, and secrets associated with the named stack. It does **not** remove volumes — another deliberate safety measure to protect persistent data.

Verify removal:

```bash
docker stack ls
```

---

## 7. Container Checkpointing: Freeze & Restore

Docker's checkpoint feature uses **CRIU (Checkpoint/Restore In Userspace)** to freeze a running container's state to disk and restore it later — potentially on a different host. This is a powerful but experimental feature that requires CRIU to be installed on the host.

> ⚠️ **Note:** Checkpoint support requires a Docker daemon built with experimental features enabled and CRIU installed (`apt install criu` on Ubuntu/Debian). This feature is primarily available on Linux.

### 7.1 `docker checkpoint create` — Freezing a Container's State

```bash
docker checkpoint create container_name checkpoint_name
```

This captures the **complete runtime state** of a container: memory contents, open file descriptors, network connections, and process state — everything needed to restore execution exactly where it left off.

```bash
# Create a checkpoint and leave the container running
docker checkpoint create --leave-running=true my_container checkpoint_v1

# Create a checkpoint and stop the container
docker checkpoint create my_container checkpoint_v1
```

**Use cases:**
- **Live migration:** Checkpoint a container on host A, transfer the checkpoint files, restore on host B — with near-zero downtime
- **Snapshotting long-running computations:** Save state before a risky operation
- **Fast container startup:** Pre-warm application state and restore instead of cold-starting

### 7.2 `docker checkpoint ls` — Listing Available Checkpoints

```bash
docker checkpoint ls container_name
```

Lists all checkpoints created for the specified container. Checkpoints are stored in `/var/lib/docker/containers/<id>/checkpoints/` by default.

### 7.3 `docker checkpoint rm` — Removing a Checkpoint

```bash
docker checkpoint rm container_name checkpoint_name
```

Deletes a specific checkpoint. Checkpoints can be large (proportional to container memory usage) so regular cleanup is important.

To restore from a checkpoint:

```bash
docker start --checkpoint checkpoint_name container_name
```

---

## 8. Real-World Workflow Patterns

### Pattern 1: Zero-Downtime Deployment with Swarm

```bash
# 1. Build and tag new image
docker build -t myapp:2.0.0 .
docker tag myapp:2.0.0 registry.example.com/myapp:2.0.0

# 2. Push to registry
docker login registry.example.com
docker push registry.example.com/myapp:2.0.0

# 3. Update the service in Swarm (rolling update)
docker service update \
  --image registry.example.com/myapp:2.0.0 \
  --update-parallelism 1 \
  --update-delay 30s \
  myapp_service
```

### Pattern 2: Migrating Images Without a Registry

```bash
# On source host — save image
docker save -o myapp_2.0.0.tar myapp:2.0.0

# Transfer to destination host
scp myapp_2.0.0.tar user@destination:/tmp/

# On destination host — load image
docker load -i /tmp/myapp_2.0.0.tar

# Verify
docker images | grep myapp
```

### Pattern 3: CI/CD Cleanup on Build Agents

```bash
#!/bin/bash
# Run at the end of each CI job to keep agents clean

echo "=== Docker disk usage before cleanup ==="
docker system df

echo "=== Pruning unused resources ==="
docker system prune -f

echo "=== Docker disk usage after cleanup ==="
docker system df
```

### Pattern 4: Local Development Compose Workflow

```bash
# Start your stack
docker-compose up -d

# Tail logs from the API service
docker-compose logs -f api

# Run migrations
docker-compose exec api python manage.py migrate

# Check system resource usage
docker system df

# Tear down completely when done for the day
docker-compose down -v
```

---

## 9. Quick Reference Cheat Sheet

```
┌─────────────────────────────────────────────────────────────────────┐
│                     DOCKER COMPOSE                                  │
├──────────────────────────┬──────────────────────────────────────────┤
│ docker-compose up -d     │ Start stack in background               │
│ docker-compose down -v   │ Stop stack, remove volumes              │
│ docker-compose logs -f   │ Stream all service logs                 │
│ docker-compose exec s sh │ Open shell in service s                 │
├─────────────────────────────────────────────────────────────────────┤
│                     IMAGE PORTABILITY                               │
├──────────────────────────┬──────────────────────────────────────────┤
│ docker save -o f.tar i:t │ Export image (with layers) to tar       │
│ docker load < f.tar      │ Import image from tar                   │
│ docker export c > f.tar  │ Export container filesystem to tar      │
│ docker import f.tar name │ Create image from filesystem tar        │
├─────────────────────────────────────────────────────────────────────┤
│                     SYSTEM MANAGEMENT                               │
├──────────────────────────┬──────────────────────────────────────────┤
│ docker system df         │ Show disk usage summary                 │
│ docker system prune -a   │ Remove all unused resources             │
├─────────────────────────────────────────────────────────────────────┤
│                     REGISTRY OPERATIONS                             │
├──────────────────────────┬──────────────────────────────────────────┤
│ docker tag src dst       │ Alias an image with a new tag           │
│ docker push image:tag    │ Upload image to registry                │
│ docker login [registry]  │ Authenticate to registry                │
│ docker logout [registry] │ Remove stored credentials               │
├─────────────────────────────────────────────────────────────────────┤
│                     SWARM & STACKS                                  │
├──────────────────────────┬──────────────────────────────────────────┤
│ docker swarm init        │ Initialize a Swarm manager node         │
│ docker service create    │ Deploy a replicated service             │
│ docker service scale s=n │ Scale service to n replicas             │
│ docker stack deploy -c f │ Deploy a Compose file as a stack        │
│ docker stack rm name     │ Remove a deployed stack                 │
├─────────────────────────────────────────────────────────────────────┤
│                     CHECKPOINTING (Experimental)                    │
├──────────────────────────┬──────────────────────────────────────────┤
│ docker checkpoint create │ Freeze container state to disk          │
│ docker checkpoint ls     │ List checkpoints for a container        │
│ docker checkpoint rm     │ Delete a checkpoint                     │
└──────────────────────────┴──────────────────────────────────────────┘
```

---

## Closing Thoughts

Mastering these 21 commands takes your Docker practice from running isolated containers to orchestrating production systems. The patterns here — declarative Compose files, registry-based image distribution, Swarm services with rolling updates, systematic disk management — are the foundations that real-world containerized architectures are built on.

The deeper principle connecting all of these commands is **immutability and declarativeness**: define the desired state, let Docker reconcile reality to it, and use tags + registries to make that desired state portable and auditable across environments.

---

*References: [Docker Official Documentation](https://docs.docker.com) · [CRIU Project](https://criu.org) · [Compose File Reference](https://docs.docker.com/compose/compose-file/)*
