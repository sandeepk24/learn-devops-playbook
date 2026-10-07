# CKAD Secrets, SecurityContext, and Resources — Env Conversion and Hardening

*Three tasks that appear together on current forms. Replace hardcoded env with Secrets. Lock down context. Set requests, limits, and quotas correctly.*

---

### `[Task 13]` Replace hardcoded env with Secret · *Easy, do not drop points*

```
Pod 'web' in 'staging' uses hardcoded DB_USER, DB_PASS, DB_HOST.
Create Secret 'db-sec' with those values. Update workload to use
secretKeyRef. Verify without exposing values in shell history where possible.
```

Seen on 83, 97, and 99 point passes. Steps are always the same.

```bash
# Step 1, capture current values to a temp file, avoid retyping
kubectl get pod web -n staging -o jsonpath='{.spec.containers[0].env}' > /tmp/env.json

# Step 2, create Secret imperatively
kubectl create secret generic db-sec -n staging \
  --from-literal=DB_USER=admin \
  --from-literal=DB_PASS=changeme123 \
  --from-literal=DB_HOST=postgres-svc \
  --dry-run=client -o yaml | kubectl apply -f -

# Step 3, patch workload. Generate, edit, apply.
kubectl get deployment web -n staging -o yaml > web.yaml
```

```yaml
# web.yaml, env section after edit
env:
- name: DB_USER
  valueFrom:
    secretKeyRef:
      name: db-sec
      key: DB_USER
- name: DB_PASS
  valueFrom:
    secretKeyRef:
      name: db-sec
      key: DB_PASS
- name: DB_HOST
  valueFrom:
    secretKeyRef:
      name: db-sec
      key: DB_HOST
```

```bash
kubectl apply -f web.yaml -n staging
kubectl rollout status deployment/web -n staging

# Verify env resolves, values stay base64 in etcd
kubectl exec -n staging deploy/web -- sh -c "env | grep DB_ | sed 's/=.*/=set/'"
kubectl get secret db-sec -n staging -o jsonpath='{.data}' | head -c 200
```

Notes:

- `secretKeyRef.optional: false` is default. Pod stays `CreateContainerConfigError` if Secret or key is missing. Check `kubectl describe pod` first.
- Same-namespace rule applies. Secret must live where the pod lives.
- For file mounts instead of env, use `volumes.secret.secretName` plus `volumeMounts`. Exam usually asks env, not mount. Know both.

Mount variant for reference:

```yaml
volumes:
- name: sec-vol
  secret:
    secretName: db-sec
```

---

### `[Task 14]` Harden with SecurityContext · *Medium*

```
Deployment 'api' in 'secure' must run as UID 999, fsGroup 999,
drop ALL capabilities, disallow privilege escalation, read-only root fs
except /tmp which needs a writable emptyDir.
```

```yaml
spec:
  template:
    spec:
      securityContext:
        runAsUser: 999
        runAsGroup: 999
        fsGroup: 999
        seccompProfile:
          type: RuntimeDefault
      containers:
      - name: api
        image: myrepo/api:v1.4.2
        securityContext:
          allowPrivilegeEscalation: false
          readOnlyRootFilesystem: true
          runAsNonRoot: true
          capabilities:
            drop: ["ALL"]
        volumeMounts:
        - name: tmp-vol
          mountPath: /tmp
      volumes:
      - name: tmp-vol
        emptyDir: {}
```

```bash
kubectl apply -f api.yaml -n secure
kubectl rollout status deployment/api -n secure

# Verify
kubectl get pod -n secure -l app=api -o jsonpath='{.items[0].spec.securityContext}{"\n"}'
kubectl exec -n secure -l app=api -- id
kubectl exec -n secure -l app=api -- sh -c "touch /root/test 2>&1 | head -5"
```

What fails in practice:

- Setting `runAsUser: 0` or omitting `runAsNonRoot` when prompt says non-root.
- Forgetting writable `/tmp` with `readOnlyRootFilesystem: true`. App starts then crashes on write.
- Capabilities syntax. It is `drop: ["ALL"]` under container `securityContext`, not pod level.

---

### `[Task 15]` Requests, limits, and ResourceQuota · *Medium*

```
Deployment 'worker' in 'jobs' must request 100m CPU and 128Mi,
limit 500m CPU and 512Mi. Namespace 'jobs' has quota
cpu: 2, memory: 2Gi, pods: 10. Ensure deployment fits and does not exceed quota.
```

```bash
# Read quota before scaling, saves a failed rollout
kubectl get resourcequota -n jobs
kubectl describe resourcequota compute-quota -n jobs

# used versus hard tells you headroom
# hard: cpu 2, memory 2Gi, pods 10

kubectl get deployment worker -n jobs -o yaml > worker.yaml
```

```yaml
resources:
  requests:
    cpu: "100m"
    memory: "128Mi"
  limits:
    cpu: "500m"
    memory: "512Mi"
```

```bash
kubectl apply -f worker.yaml -n jobs
kubectl top pods -n jobs
kubectl describe resourcequota compute-quota -n jobs | grep -A10 Used

# Scale check, math first
# 6 replicas at 100m request equals 600m, fits in 2 CPU
kubectl scale deployment worker --replicas=6 -n jobs
kubectl rollout status deployment/worker -n jobs
```

Rules:

- Requests affect scheduling and quota. Limits affect runtime throttling and OOMKill.
- Memory units are `Mi` and `Gi`. `GB` is rejected. CPU is `100m` or `0.1` or `1`.
- If quota blocks you, either lower requests or ask for fewer replicas. Do not delete quota unless prompt says to.
- LimitRange, if present, injects defaults. Check `kubectl get limitrange -n jobs` when pods get defaults you did not set.

---

## Speed commands

```bash
kubectl create secret generic NAME -n NS --from-literal=K=V --dry-run=client -o yaml | kubectl apply -f -
kubectl get secret NAME -n NS -o jsonpath='{.data}'
kubectl patch deployment NAME -n NS -p '{"spec":{"template":{"spec":{"securityContext":{"runAsUser":999}}}}}'
kubectl get resourcequota -n NS
kubectl describe resourcequota NAME -n NS
kubectl top pods -n NS
```

## Phrase to field map

| Exam phrase | Field |
|---|---|
| turn env into Secret | `valueFrom.secretKeyRef` |
| run as user, non-root | `runAsUser`, `runAsNonRoot: true` |
| drop capabilities | `securityContext.capabilities.drop: ["ALL"]` |
| read-only fs | `readOnlyRootFilesystem: true` plus writable `emptyDir` on `/tmp` |
| fits in quota | check `kubectl describe resourcequota` before scaling |
