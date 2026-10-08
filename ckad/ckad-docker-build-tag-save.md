# CKAD Docker Build, Tag, and Save — The Complete Guide

*This task appears on nearly every current exam form. 4 to 7 percent of score. Candidates who skip container image practice lose easy points chasing harder Kubernetes questions.*

---

## Why this matters on the CKAD

The CKAD curriculum includes "Define, build and modify container images" under Application Design and Build. Unlike the CKA which focuses on cluster administration, the CKAD tests whether you can work with application containers end-to-end.

r/ckad reports from 2025-2026 consistently mention a Docker or container image task. The pattern is always the same: build from a Dockerfile, tag for a registry, save to a tar file. Sometimes OCI format is specified. The task takes under 3 minutes if practiced, but candidates who have only worked with pre-built images struggle with the syntax.

---

## The mental model

Container images are layered filesystems with metadata. When you `docker build`, Docker reads the Dockerfile, executes each instruction, and creates layers. The final image gets a name and tag. When you `docker tag`, you create an alias pointing to the same image ID. When you `docker save`, you export the image layers and metadata to a tar archive that can be loaded elsewhere.

```
Dockerfile → docker build → Image (local) → docker tag → Registry-qualified name
                                          → docker save → .tar file
                                          → docker push → Remote registry
```

The exam tests build, tag, and save. Push is rare because it requires registry authentication.

---

## Dockerfile fundamentals

Before building, you need to read a Dockerfile. The exam may provide one, or ask you to write simple modifications.

```dockerfile
# Base image, always first instruction
FROM python:3.11-slim

# Set working directory for subsequent commands
WORKDIR /app

# Copy files from build context into image
COPY requirements.txt .
COPY src/ ./src/

# Run commands during build, each creates a layer
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables baked into image
ENV APP_ENV=production

# Document the port the app listens on
EXPOSE 8080

# Default command when container starts
CMD ["python", "src/main.py"]
```

Key instructions and what they do:

| Instruction | Purpose | Layer created |
|---|---|---|
| `FROM` | Base image to build on | No, sets base |
| `WORKDIR` | Set working directory | No, metadata only |
| `COPY` | Copy files from build context | Yes |
| `ADD` | Copy files, can extract archives and fetch URLs | Yes |
| `RUN` | Execute command during build | Yes |
| `ENV` | Set environment variable | No, metadata only |
| `EXPOSE` | Document port | No, metadata only |
| `CMD` | Default command | No, metadata only |
| `ENTRYPOINT` | Fixed command, CMD becomes arguments | No, metadata only |

---

## Building images

### Basic build

```bash
# Build from Dockerfile in current directory
docker build -t myapp:v1 .

# The -t flag sets name:tag
# The . is the build context (where COPY sources files from)
```

### Build with explicit Dockerfile path

When the Dockerfile is not in the current directory or has a different name:

```bash
# Dockerfile at /opt/app/Dockerfile, build context is /opt/app
docker build -t myapp:v1 -f /opt/app/Dockerfile /opt/app

# Dockerfile named Dockerfile.prod in current directory
docker build -t myapp:v1 -f Dockerfile.prod .
```

The `-f` flag specifies the Dockerfile path. The final argument is always the build context directory.

### Build with build arguments

```bash
# Pass variables into the build
docker build -t myapp:v1 --build-arg VERSION=1.4.2 .
```

The Dockerfile uses `ARG VERSION` to receive this value.

### Exam-style build task

```
Build an image from the Dockerfile at /opt/code/Dockerfile.
Name it 'webapp' with tag 'v2'. The build context is /opt/code.
```

```bash
cd /opt/code
docker build -t webapp:v2 -f /opt/code/Dockerfile /opt/code

# Or equivalently
docker build -t webapp:v2 -f Dockerfile .

# Verify the image exists
docker images | grep webapp
```

---

## Tagging images

Tags are aliases. Multiple tags can point to the same image ID.

### Basic tagging

```bash
# Tag an existing image for a different registry
docker tag webapp:v2 registry.local:5000/webapp:v2

# Tag with a different name
docker tag webapp:v2 mycompany/webapp:v2

# Tag as latest (common but avoid in production)
docker tag webapp:v2 webapp:latest
```

### Registry tag format

```
[registry-host[:port]/][namespace/]image-name:tag

Examples:
  nginx:1.25                          # Docker Hub official
  myuser/myapp:v1                     # Docker Hub user namespace
  registry.local:5000/myapp:v1        # Private registry with port
  gcr.io/my-project/myapp:v1          # Google Container Registry
  123456789.dkr.ecr.us-east-1.amazonaws.com/myapp:v1  # AWS ECR
```

### Exam trap: typos in registry host

The exam checks the exact tag. `registry.local:5000` is not the same as `registry:5000`. Copy the registry name from the prompt exactly.

```bash
# Wrong, will fail verification
docker tag webapp:v2 registry:5000/webapp:v2

# Correct, matches prompt
docker tag webapp:v2 registry.local:5000/webapp:v2
```

---

## Saving images to tar files

`docker save` exports an image to a tar archive. This is how you transfer images without a registry.

### Basic save

```bash
# Save to tar file
docker save -o /tmp/webapp.tar webapp:v2

# Or using redirection
docker save webapp:v2 > /tmp/webapp.tar
```

### Save multiple images

```bash
# Save multiple images to one archive
docker save -o /tmp/images.tar webapp:v2 nginx:1.25 busybox:1.35
```

### Save with specific tag

```bash
# Save the registry-qualified tag
docker save -o /tmp/webapp.tar registry.local:5000/webapp:v2
```

### OCI format

Some exam prompts specify OCI format. Docker 20.10+ supports this:

```bash
# Save in OCI format (if supported)
docker save --output /tmp/webapp-oci.tar webapp:v2

# Check Docker version for OCI support
docker version
```

If the `--format oci` flag is not available in your Docker version, the default format is Docker's own archive format, which is widely compatible.

### Loading saved images

```bash
# Load from tar file
docker load -i /tmp/webapp.tar

# Or using stdin
docker load < /tmp/webapp.tar
```

---

## docker save versus docker export

This distinction appears in exam questions and trips candidates.

| Command | Works on | Contains | Use case |
|---|---|---|---|
| `docker save` | Images | All layers, metadata, tags | Transfer images between hosts |
| `docker export` | Containers | Single-layer filesystem snapshot | Create a filesystem tarball from running container |

```bash
# Save an IMAGE
docker save -o image.tar myapp:v1

# Export a CONTAINER
docker export -o container.tar my-running-container
```

The exam asks for `docker save`. Using `docker export` on an image name fails. Using `docker export` on a container produces a different artifact.

---

## Complete exam workflow

### Task

```
1. Build an image from /opt/app/Dockerfile, name it 'processor:v1'
2. Tag it as 'registry.internal:5000/processor:v1'
3. Save the tagged image to /opt/processor.tar
```

### Solution

```bash
# Step 1: Build
docker build -t processor:v1 -f /opt/app/Dockerfile /opt/app

# Step 2: Tag
docker tag processor:v1 registry.internal:5000/processor:v1

# Step 3: Save
docker save -o /opt/processor.tar registry.internal:5000/processor:v1

# Verify each step
docker images | grep processor
ls -lh /opt/processor.tar
tar -tvf /opt/processor.tar | head -20
```

### Verification commands

```bash
# List images
docker images
docker images | grep NAME

# Inspect image details
docker inspect IMAGE:TAG

# Check tar contents
tar -tvf /path/to/file.tar | head -20

# Check tar file size
ls -lh /path/to/file.tar
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `unable to prepare context: unable to evaluate symlinks` | Build context path wrong | Check the path after `-f` and the final context argument |
| `COPY failed: file not found` | File not in build context | Ensure source files are in the context directory |
| `invalid reference format` | Tag syntax wrong | Check for spaces, invalid characters in tag |
| `No such image` on save | Image name typo or not built | Run `docker images` to verify exact name |
| Tar file is 0 bytes | Save command failed silently | Check for errors, ensure image exists |
| Permission denied on save | Path not writable | Use `/tmp` or a path you own |

---

## Speed commands for exam

```bash
# Build
docker build -t NAME:TAG -f /path/Dockerfile /path/context

# Tag
docker tag NAME:TAG registry.host:port/NAME:TAG

# Save
docker save -o /path/file.tar NAME:TAG

# Verify
docker images | grep NAME
ls -lh /path/file.tar

# Load (if needed)
docker load -i /path/file.tar
```

---

## What the exam does not ask

- Writing complex multi-stage Dockerfiles
- Docker Compose
- Docker networking or volumes
- Container runtime configuration
- Pushing to authenticated registries

The scope is build, tag, save. Practice those three commands until they are muscle memory.
