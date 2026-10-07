# CKAD Application Build, Jobs, and Exam Mechanics — Docker, CronJob Traps, API Fixes

*Last-mile points. Short tasks, strict checks. Practice these until each takes under 3 minutes.*

---

### `[Task 16]` Docker build, tag, and save · *Easy*

```
Build image from Dockerfile in /opt/app as 'img:v1'.
Tag as 'registry.local:5000/img:v1'. Save to /opt/img.tar in OCI layout where asked.
```

This appears on most current forms. Usually 4 to 7 percent of score. Miss it and you chase harder questions to compensate.

```bash
# Build
docker build -t img:v1 -f /opt/app/Dockerfile /opt/app

# Tag for registry
docker tag img:v1 registry.local:5000/img:v1

# Save, plain tar
docker save -o /opt/img.tar img:v1

# Save in OCI format when prompt specifies it
docker save --output /opt/img-oci.tar --format oci img:v1 2>/dev/null || docker save -o /opt/img.tar img:v1

# Verify
ls -lh /opt/img.tar
docker images | grep img
```

Notes from r/ckad:

- Workdir matters. Run `docker build` where Dockerfile lives or pass `-f` explicitly.
- Tag format is `registry/host/image:tag`. Typo in registry host fails push checks.
- `docker save` preserves image. `docker export` is for containers. Do not mix them.
- If daemon feels slow, check `docker ps` first. Cluster SSH nodes already have docker or nerdctl available.

---

### `[Task 17]` CronJob that must exit plus manual Job run · *Medium*

```
CronJob 'report' in 'batch' runs every 5 minutes. Current image sleeps forever
so Jobs never complete. Fix command so it exits 0, set concurrencyPolicy Forbid,
activeDeadlineSeconds 120, history 3 and 1. Trigger one manual run and verify logs.
```

March 2026 writeup flagged exactly this. Job slept forever, never completed. Fix was proper command or deadline.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: report
  namespace: batch
spec:
  schedule: "*/5 * * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  startingDeadlineSeconds: 60
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 120
      template:
        spec:
          restartPolicy: Never
          containers:
          - name: report
            image: busybox:1.35
            command: ["sh", "-c", "date; echo report done"]
            resources:
              requests:
                cpu: "100m"
                memory: "64Mi"
              limits:
                cpu: "200m"
                memory: "128Mi"
```

```bash
# Fast path, generate then patch
kubectl create cronjob report --image=busybox:1.35 --schedule="*/5 * * * *" -n batch --dry-run=client -o yaml > cron.yaml
# edit cron.yaml, apply
kubectl apply -f cron.yaml

# Do not wait 5 minutes. Trigger now.
kubectl create job --from=cronjob/report manual-001 -n batch
kubectl get jobs -n batch --watch
kubectl logs job/manual-001 -n batch
kubectl get cronjob report -n batch -o jsonpath='{.spec.concurrencyPolicy}{" "}{.spec.jobTemplate.spec.activeDeadlineSeconds}{"\n"}'
```

Field use, plain:

- `concurrencyPolicy: Forbid` skips new run while last still runs. Default `Allow` overlaps. Use Forbid for anything touching shared state.
- `startingDeadlineSeconds` on CronJob aborts late starts. `activeDeadlineSeconds` on Job kills hung runs. Know which level each lives at.
- `restartPolicy` in Job template is `Never` or `OnFailure`. `Always` is rejected on apply.
- Separator `--` matters in `kubectl create cronjob ... -- command`. Without it, command is dropped silently.

---

### `[Task 18]` Fix deprecated APIs · *Easy*

```
Manifest at /opt/old.yaml fails to apply. Fix deprecated apiVersion
and verify with dry-run. Apply and confirm rollout.
```

```bash
# Find the problem
kubectl apply --dry-run=client -f /opt/old.yaml 2>&1 | head -20
grep -n "apiVersion" /opt/old.yaml

# Common fixes
# extensions/v1beta1 Ingress becomes networking.k8s.io/v1, requires pathType and backend.service structure
# batch/v1beta1 CronJob becomes batch/v1
# autoscaling/v2beta1 becomes autoscaling/v2 where applicable

kubectl apply --dry-run=client -f /opt/old.yaml
kubectl apply -f /opt/old.yaml
kubectl rollout status deployment/<name> -n <ns>
```

Ingress conversion reference, since it appears most:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: web
spec:
  ingressClassName: nginx
  rules:
  - host: webapp.internal
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: webapp-svc
            port:
              number: 80
```

Use `kubectl explain ingress.spec.rules.http.paths.backend` on the cluster. It reflects actual version. Faster than memory at minute 90.

---

### `[Task 19]` Service selector fix and multi-container sidecar · *Medium*

```
Service 'frontend-svc' in 'web' has no endpoints. Fix selector.
Add emptyDir sidecar pattern where asked, verify traffic and logs.
```

```bash
# Endpoints empty is the signal
kubectl get endpoints -n web
kubectl describe svc frontend-svc -n web
kubectl get pods -n web --show-labels

# Fix selector to match pods
kubectl patch svc frontend-svc -n web -p '{"spec":{"selector":{"app":"frontend"}}}'

# Verify
kubectl get endpoints -n web
kubectl port-forward svc/frontend-svc 8080:80 -n web &
curl -s localhost:8080 | head -20
kill %1
```

Sidecar pattern when prompt asks for logging or proxy alongside main:

```yaml
spec:
  containers:
  - name: app
    image: nginx:1.25
    volumeMounts:
    - name: logs
      mountPath: /var/log/nginx
  - name: sidecar
    image: busybox:1.35
    command: ["sh", "-c", "tail -F /var/log/nginx/access.log"]
    volumeMounts:
    - name: logs
      mountPath: /var/log/nginx
  volumes:
  - name: logs
    emptyDir: {}
```

Check with `kubectl logs <pod> -c sidecar -n web`. Main and sidecar share `emptyDir`, separate lifecycles.

---

## Exam mechanics, what actually saves time

Collected from 67 to 99 point reports. None of this is theory.

Timebox:

- First pass, 3 to 4 minutes per question max. Flag and move on. Second pass with banked time.
- Easy order is usually Secret, Service fix, Ingress create, Docker save, CronJob trigger. Do those first.
- Leave RBAC and long NetworkPolicy debug for second pass. They need clean focus.

Terminal:

- SSH per question resets context. Set namespace per task with `-n` or `kubectl config set-context --current --namespace=NS`.
- Paste is Ctrl+Shift+V, copy is Ctrl+Shift+C in exam terminal. Practice it. Mac muscle memory will betray you.
- `:set expandtab tabstop=2 shiftwidth=2` before any YAML edit. Block indent with `Shift-V` then `>`.
- VSCodium is available in remote desktop. If Vim costs you time, switch. Decide in practice, not on exam day.

Verify before moving on:

```bash
kubectl rollout status deployment/NAME -n NS
kubectl get endpoints -n NS
kubectl describe ingress NAME -n NS
kubectl logs job/NAME -n NS
kubectl auth can-i VERB RESOURCE --as=system:serviceaccount:NS:SA -n NS
kubectl get events -n NS --sort-by=.metadata.creationTimestamp | tail -20
```

Prep stack that matches passes:

- Mumshad Udemy or KodeKloud for baseline
- [aravind4799/CKAD-Practice-Questions](https://github.com/aravind4799/CKAD-Practice-Questions) until answers are boring
- [TiPunchLabs/ckad-dojo](https://github.com/TiPunchLabs/ckad-dojo) for second angle
- Killer.sh twice under time, once open book, once closed
- Killercoda NetworkPolicy drills at [killercoda.com/omkar-shelke25](https://killercoda.com/omkar-shelke25)

Skip deep Helm, Kustomize, CRDs, StatefulSet tuning for CKAD. They appear as mentions, not core tasks. Rebalance that time to labels, logs, and imperative generation.
