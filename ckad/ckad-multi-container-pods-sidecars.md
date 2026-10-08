# CKAD Multi-Container Pods and Sidecars — Patterns That Actually Appear

*The exam tests whether you understand that containers in a pod share network and can share volumes. Sidecar, adapter, and ambassador patterns all reduce to the same mechanics.*

---

## Why multi-container pods matter

A Pod is the smallest deployable unit in Kubernetes. A Pod can have multiple containers that:

- Share the same network namespace (localhost works between them)
- Can share volumes (emptyDir, configMap, secret mounts)
- Are scheduled together on the same node
- Have coupled lifecycles (pod restarts affect all containers)

The CKAD tests this with:

1. Add a sidecar container for logging, monitoring, or proxying
2. Fix a Service that has no endpoints (selector mismatch)
3. Debug which container in a multi-container pod is failing

r/ckad reports consistently mention sidecar patterns and Service selector fixes as combined or adjacent tasks.

---

## The three patterns

All three patterns are the same mechanism — multiple containers in one pod. The name describes the intent.

### Sidecar

A helper container that extends the main container's functionality without changing it.

Use cases:
- Log shipping (tail logs, send to aggregator)
- Metrics exporter
- File sync
- TLS proxy

```yaml
spec:
  containers:
  - name: app
    image: nginx:1.25
    volumeMounts:
    - name: logs
      mountPath: /var/log/nginx
  - name: log-shipper
    image: fluentd:v1.16
    volumeMounts:
    - name: logs
      mountPath: /var/log/nginx
      readOnly: true
  volumes:
  - name: logs
    emptyDir: {}
```

Both containers mount the same `emptyDir`. The app writes logs, the sidecar reads and ships them.

### Adapter

A container that transforms or standardizes the main container's output.

Use cases:
- Convert logs to a standard format
- Translate metrics to Prometheus format
- Normalize API responses

```yaml
spec:
  containers:
  - name: legacy-app
    image: old-app:v1
    # Writes logs in proprietary format to /var/log/app
  - name: adapter
    image: log-adapter:v1
    # Reads proprietary logs, outputs standard JSON
```

### Ambassador

A proxy container that handles network communication on behalf of the main container.

Use cases:
- Connection pooling
- Service discovery
- TLS termination for legacy apps

```yaml
spec:
  containers:
  - name: app
    image: myapp:v1
    # Connects to localhost:6379, thinks it's talking to Redis
  - name: redis-proxy
    image: redis-proxy:v1
    # Handles connection to actual Redis cluster
```

---

## Shared networking: localhost works

All containers in a pod share the same network namespace. They can reach each other via `localhost`.

```yaml
spec:
  containers:
  - name: web
    image: nginx:1.25
    ports:
    - containerPort: 80
  - name: monitor
    image: busybox:1.35
    command: ["sh", "-c", "while true; do wget -qO- localhost:80/health; sleep 10; done"]
```

The monitor container reaches the web container at `localhost:80`. No Service needed for intra-pod communication.

### Port conflict

Containers in the same pod cannot bind the same port:

```yaml
# This fails - both want port 80
spec:
  containers:
  - name: app1
    image: nginx:1.25
    ports:
    - containerPort: 80
  - name: app2
    image: nginx:1.25
    ports:
    - containerPort: 80   # Conflict
```

Use different ports for each container.

---

## Shared volumes: emptyDir

`emptyDir` is created when the pod starts and deleted when the pod is removed. It is the standard way to share data between containers.

```yaml
spec:
  containers:
  - name: writer
    image: busybox:1.35
    command: ["sh", "-c", "while true; do date >> /data/log.txt; sleep 5; done"]
    volumeMounts:
    - name: shared
      mountPath: /data
  - name: reader
    image: busybox:1.35
    command: ["sh", "-c", "tail -F /data/log.txt"]
    volumeMounts:
    - name: shared
      mountPath: /data
      readOnly: true
  volumes:
  - name: shared
    emptyDir: {}
```

Writer appends to `/data/log.txt`. Reader tails it in real time. Both see the same filesystem because they mount the same `emptyDir`.

### emptyDir with memory backing

For high-performance temporary storage:

```yaml
volumes:
- name: cache
  emptyDir:
    medium: Memory
    sizeLimit: 100Mi
```

This uses tmpfs (RAM-backed). Faster but limited by memory.

---

## Practical sidecar: log shipping

The most common exam pattern. Main container writes logs to a file. Sidecar tails and processes them.

### Full example

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: production
spec:
  replicas: 2
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
      - name: nginx
        image: nginx:1.25
        ports:
        - containerPort: 80
        volumeMounts:
        - name: logs
          mountPath: /var/log/nginx
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "200m"
            memory: "256Mi"
      - name: log-tailer
        image: busybox:1.35
        command: ["sh", "-c", "tail -F /var/log/nginx/access.log"]
        volumeMounts:
        - name: logs
          mountPath: /var/log/nginx
          readOnly: true
        resources:
          requests:
            cpu: "50m"
            memory: "32Mi"
          limits:
            cpu: "100m"
            memory: "64Mi"
      volumes:
      - name: logs
        emptyDir: {}
```

### Viewing logs from the sidecar

```bash
# Logs from main container
kubectl logs -n production deploy/web -c nginx

# Logs from sidecar
kubectl logs -n production deploy/web -c log-tailer

# Logs from specific pod
kubectl logs web-abc123 -c log-tailer -n production

# Follow logs
kubectl logs -f deploy/web -c log-tailer -n production
```

The `-c` flag specifies which container. Without it, kubectl prompts when multiple containers exist.

---

## Service selector fix

This appears alongside or separately from multi-container tasks. The symptom: Service exists but has no endpoints.

### Diagnosis

```bash
kubectl get endpoints -n web
# NAME          ENDPOINTS
# frontend-svc  <none>           # Problem: no endpoints

kubectl describe svc frontend-svc -n web
# Selector: app=frontend

kubectl get pods -n web --show-labels
# NAME          LABELS
# web-abc123    app=web          # Mismatch: 'web' not 'frontend'
```

The Service looks for `app=frontend` but pods have `app=web`.

### Fix option 1: Patch the Service

```bash
kubectl patch svc frontend-svc -n web -p '{"spec":{"selector":{"app":"web"}}}'
```

Now the Service selects pods with `app=web`.

### Fix option 2: Label the pods

```bash
kubectl label pods web-abc123 app=frontend -n web --overwrite
```

This relabels the pod to match the Service selector. But if pods are managed by a Deployment, the label reverts on restart.

### Fix option 3: Patch the Deployment template

```bash
kubectl patch deployment web -n web \
  -p '{"spec":{"template":{"metadata":{"labels":{"app":"frontend"}}}}}'
```

This updates the pod template. New pods get the correct label. But changing the label also changes the Deployment's selector, which is immutable. Usually you patch the Service instead.

### Verification

```bash
kubectl get endpoints -n web
# NAME          ENDPOINTS
# frontend-svc  10.244.0.5:80,10.244.0.6:80   # Pods now selected

# Test connectivity
kubectl port-forward svc/frontend-svc 8080:80 -n web &
curl localhost:8080
kill %1
```

---

## Init containers versus sidecars

Init containers run to completion before main containers start. They are not sidecars.

| Aspect | Init container | Sidecar |
|---|---|---|
| Runs when | Before main containers | Alongside main containers |
| Completes | Must exit 0 to proceed | Runs continuously (usually) |
| Use case | Setup, wait for dependency | Log shipping, proxy, adapter |

### Init container example

```yaml
spec:
  initContainers:
  - name: wait-for-db
    image: busybox:1.35
    command: ["sh", "-c", "until nc -z db-svc 5432; do sleep 2; done"]
  containers:
  - name: app
    image: myapp:v1
```

The app container does not start until the init container exits 0.

### When to use which

- Need to run setup before app starts → init container
- Need to run alongside app continuously → sidecar container

---

## Debugging multi-container pods

### Which container is failing

```bash
kubectl get pod web-abc123 -n production
# READY   STATUS
# 1/2     CrashLoopBackOff    # One container failing

kubectl describe pod web-abc123 -n production
# Look at each container's State and Last State
```

### Logs from specific container

```bash
kubectl logs web-abc123 -c nginx -n production
kubectl logs web-abc123 -c log-tailer -n production
kubectl logs web-abc123 -c log-tailer -n production --previous
```

### Exec into specific container

```bash
kubectl exec -it web-abc123 -c nginx -n production -- sh
kubectl exec -it web-abc123 -c log-tailer -n production -- sh
```

### Check volume mounts

```bash
kubectl exec web-abc123 -c nginx -n production -- ls -la /var/log/nginx
kubectl exec web-abc123 -c log-tailer -n production -- ls -la /var/log/nginx
```

Both should show the same files if the volume mount is correct.

---

## Exam task walkthrough

### Task

```
Deployment 'api' in namespace 'backend' needs a sidecar container.
Add container 'metrics-exporter' using image 'prom/node-exporter:v1.6.0'.
The main container writes metrics to /metrics/app.prom.
The sidecar should read from the same path. Use emptyDir for sharing.
Ensure the Service 'api-svc' correctly selects the pods.
```

### Solution

```bash
kubectl get deployment api -n backend -o yaml > api.yaml
```

Edit `api.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: backend
spec:
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
      - name: api
        image: myapi:v1
        volumeMounts:
        - name: metrics
          mountPath: /metrics
      - name: metrics-exporter
        image: prom/node-exporter:v1.6.0
        volumeMounts:
        - name: metrics
          mountPath: /metrics
          readOnly: true
      volumes:
      - name: metrics
        emptyDir: {}
```

Apply and verify:

```bash
kubectl apply -f api.yaml

kubectl rollout status deployment/api -n backend

kubectl get pods -n backend -l app=api
# Should show 2/2 READY

kubectl logs -n backend deploy/api -c metrics-exporter

# Check Service endpoints
kubectl get endpoints api-svc -n backend
# Should show pod IPs

# If endpoints empty, fix selector
kubectl describe svc api-svc -n backend
kubectl get pods -n backend --show-labels
kubectl patch svc api-svc -n backend -p '{"spec":{"selector":{"app":"api"}}}'
```

---

## Speed commands

```bash
# Get logs from specific container
kubectl logs POD -c CONTAINER -n NS

# Exec into specific container
kubectl exec -it POD -c CONTAINER -n NS -- sh

# Check Service endpoints
kubectl get endpoints SVC -n NS

# Fix Service selector
kubectl patch svc SVC -n NS -p '{"spec":{"selector":{"KEY":"VALUE"}}}'

# Check pod labels
kubectl get pods -n NS --show-labels
```
