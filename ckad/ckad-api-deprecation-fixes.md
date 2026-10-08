# CKAD API Deprecation Fixes — Converting Old Manifests

*The exam gives you a YAML file that fails to apply. The error mentions unknown field or no kind registered. You identify the deprecated apiVersion, convert to the current version, and apply successfully.*

---

## Why this appears on the exam

Kubernetes evolves. APIs graduate from beta to stable, fields change structure, old versions get removed. Real clusters have old manifests that break on upgrade. The CKAD tests whether you can:

1. Read an error message and identify the deprecated API
2. Know the current apiVersion for common resources
3. Convert the manifest structure where required
4. Validate with dry-run before applying

r/ckad March 2026: "Deprecated API Fix — One manifest used extensions/v1beta1."

This is a straightforward task if you know the mapping. Candidates who have only written manifests from scratch struggle because they have never seen the old formats.

---

## The deprecation timeline that matters

Kubernetes 1.22 (August 2021) removed several long-deprecated APIs. The CKAD exam runs on Kubernetes 1.31 as of 2025-2026, meaning these old versions are long gone:

| Resource | Removed API | Current API |
|---|---|---|
| Ingress | `extensions/v1beta1`, `networking.k8s.io/v1beta1` | `networking.k8s.io/v1` |
| IngressClass | `networking.k8s.io/v1beta1` | `networking.k8s.io/v1` |
| CronJob | `batch/v1beta1` | `batch/v1` |
| HorizontalPodAutoscaler | `autoscaling/v2beta1`, `autoscaling/v2beta2` | `autoscaling/v2` |
| PodSecurityPolicy | `policy/v1beta1` | Removed entirely, use Pod Security Admission |
| PodDisruptionBudget | `policy/v1beta1` | `policy/v1` |
| EndpointSlice | `discovery.k8s.io/v1beta1` | `discovery.k8s.io/v1` |

The exam most commonly tests Ingress conversion because it has both apiVersion and structural changes.

---

## Identifying the problem

### The error message

When you apply a manifest with a removed API:

```bash
kubectl apply -f old-ingress.yaml
```

```
error: resource mapping not found for name: "web" namespace: "" 
from "old-ingress.yaml": no matches for kind "Ingress" in version "extensions/v1beta1"
ensure CRDs are installed first
```

Or:

```
error: unable to recognize "old-ingress.yaml": no matches for kind "Ingress" 
in version "networking.k8s.io/v1beta1"
```

The error tells you exactly which apiVersion failed.

### Quick diagnosis

```bash
# Check what version the file uses
grep -n "apiVersion" /opt/old.yaml

# Try a dry-run to see the full error
kubectl apply --dry-run=client -f /opt/old.yaml 2>&1

# Check what versions the cluster supports
kubectl api-resources | grep -i ingress
kubectl api-versions | grep networking
```

---

## Ingress conversion (most common)

Ingress has the most significant structural changes. It is not just apiVersion — the backend structure changed.

### Old format (extensions/v1beta1 or networking.k8s.io/v1beta1)

```yaml
apiVersion: extensions/v1beta1
kind: Ingress
metadata:
  name: web
  namespace: web
spec:
  rules:
  - host: webapp.internal
    http:
      paths:
      - path: /
        backend:
          serviceName: webapp-svc
          servicePort: 80
```

### New format (networking.k8s.io/v1)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: web
spec:
  ingressClassName: nginx              # Required or uses default class
  rules:
  - host: webapp.internal
    http:
      paths:
      - path: /
        pathType: Prefix               # Required: Prefix, Exact, or ImplementationSpecific
        backend:
          service:                     # New structure
            name: webapp-svc
            port:
              number: 80               # Or name: http
```

### Key structural changes

| Old field | New field |
|---|---|
| `backend.serviceName` | `backend.service.name` |
| `backend.servicePort` | `backend.service.port.number` or `backend.service.port.name` |
| (none) | `pathType` is now required |
| `kubernetes.io/ingress.class` annotation | `spec.ingressClassName` |

### pathType values

- `Prefix` — matches the path and anything under it (`/api` matches `/api`, `/api/`, `/api/users`)
- `Exact` — matches only the exact path (`/api` matches only `/api`)
- `ImplementationSpecific` — behavior defined by the Ingress controller

Use `Prefix` in most cases. Use `Exact` when explicitly required.

### Complete conversion example

Old manifest at `/opt/old-ingress.yaml`:

```yaml
apiVersion: extensions/v1beta1
kind: Ingress
metadata:
  name: api-ingress
  namespace: production
  annotations:
    kubernetes.io/ingress.class: nginx
spec:
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /v1
        backend:
          serviceName: api-v1-svc
          servicePort: 8080
      - path: /v2
        backend:
          serviceName: api-v2-svc
          servicePort: 8080
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls
```

Fixed manifest:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: api-ingress
  namespace: production
spec:
  ingressClassName: nginx
  rules:
  - host: api.example.com
    http:
      paths:
      - path: /v1
        pathType: Prefix
        backend:
          service:
            name: api-v1-svc
            port:
              number: 8080
      - path: /v2
        pathType: Prefix
        backend:
          service:
            name: api-v2-svc
            port:
              number: 8080
  tls:
  - hosts:
    - api.example.com
    secretName: api-tls
```

Changes made:
1. `apiVersion: extensions/v1beta1` → `apiVersion: networking.k8s.io/v1`
2. Annotation `kubernetes.io/ingress.class: nginx` → `spec.ingressClassName: nginx`
3. Added `pathType: Prefix` to each path
4. Changed `backend.serviceName` → `backend.service.name`
5. Changed `backend.servicePort` → `backend.service.port.number`

---

## CronJob conversion

CronJob is simpler. Only the apiVersion changes, no structural differences.

### Old format

```yaml
apiVersion: batch/v1beta1
kind: CronJob
metadata:
  name: cleanup
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: busybox:1.35
            command: ["sh", "-c", "echo cleaning"]
          restartPolicy: OnFailure
```

### New format

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup
spec:
  schedule: "0 3 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cleanup
            image: busybox:1.35
            command: ["sh", "-c", "echo cleaning"]
          restartPolicy: OnFailure
```

Only change: `batch/v1beta1` → `batch/v1`

---

## HorizontalPodAutoscaler conversion

### Old format (autoscaling/v2beta1 or v2beta2)

```yaml
apiVersion: autoscaling/v2beta2
kind: HorizontalPodAutoscaler
metadata:
  name: web-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

### New format (autoscaling/v2)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

Only change: `autoscaling/v2beta2` → `autoscaling/v2`

---

## Using kubectl explain

When unsure about field structure, use `kubectl explain` on the cluster:

```bash
# Check Ingress backend structure
kubectl explain ingress.spec.rules.http.paths.backend
kubectl explain ingress.spec.rules.http.paths.backend.service
kubectl explain ingress.spec.rules.http.paths.backend.service.port

# Check required fields
kubectl explain ingress.spec.rules.http.paths --recursive | head -30
```

The output reflects the actual cluster version. Use it freely during the exam.

---

## Exam task walkthrough

### Task

```
Manifest at /opt/legacy.yaml fails to apply with API version error.
Fix the manifest and apply it. Verify the resource is created correctly.
```

### Solution

```bash
# Step 1: Identify the problem
kubectl apply --dry-run=client -f /opt/legacy.yaml 2>&1
# Error shows: no matches for kind "Ingress" in version "extensions/v1beta1"

# Step 2: Check current file
cat /opt/legacy.yaml

# Step 3: Edit the file
vim /opt/legacy.yaml
```

In vim, make these changes:
- Line 1: `apiVersion: extensions/v1beta1` → `apiVersion: networking.k8s.io/v1`
- Remove `kubernetes.io/ingress.class` annotation, add `spec.ingressClassName: nginx`
- Add `pathType: Prefix` to each path
- Change `backend.serviceName` → `backend.service.name`
- Change `backend.servicePort` → `backend.service.port.number`

```bash
# Step 4: Validate
kubectl apply --dry-run=client -f /opt/legacy.yaml

# Step 5: Apply
kubectl apply -f /opt/legacy.yaml

# Step 6: Verify
kubectl get ingress -n <namespace>
kubectl describe ingress <name> -n <namespace>
```

---

## Quick reference table

| Old apiVersion | New apiVersion | Structural changes |
|---|---|---|
| `extensions/v1beta1` (Ingress) | `networking.k8s.io/v1` | Yes, backend and pathType |
| `networking.k8s.io/v1beta1` (Ingress) | `networking.k8s.io/v1` | Yes, backend and pathType |
| `batch/v1beta1` (CronJob) | `batch/v1` | No |
| `autoscaling/v2beta1` (HPA) | `autoscaling/v2` | Minor |
| `autoscaling/v2beta2` (HPA) | `autoscaling/v2` | No |
| `policy/v1beta1` (PDB) | `policy/v1` | No |

---

## Speed commands

```bash
# Check what failed
kubectl apply --dry-run=client -f FILE 2>&1

# Check supported API versions
kubectl api-versions | grep KEYWORD

# Check resource API group
kubectl api-resources | grep RESOURCE

# Explore field structure
kubectl explain RESOURCE.spec.FIELD

# Validate after editing
kubectl apply --dry-run=client -f FILE
```

The exam does not expect you to memorize every deprecated API. It expects you to read the error, identify the issue, and fix it using cluster tools like `kubectl explain`.
