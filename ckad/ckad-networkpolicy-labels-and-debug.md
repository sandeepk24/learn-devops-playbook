# CKAD NetworkPolicy Mastery — Labels, Create, and Debug

*Companion to Deployments Parts 1-2, Ingress, and CronJob guides in this folder. Same format. Same workflow. Generate, patch, verify.*

*Validated against Kubernetes 1.31. Exam runs 17 tasks in 2 hours. NetworkPolicy is 1-2 of them.*

---

## Why this shows up

r/ckad reports are consistent. Two patterns appear:

1. Create a policy to allow or deny traffic for a pod or deployment.
2. Three or four policies already exist. Instruction says do not modify them. You label pods so selectors match.

Second pattern is where points are lost. Candidates create new policies when the task forbids it. Read the prompt first. If it says do not change policies, touch only labels.

---

## The mental model

NetworkPolicy selects pods by label, then defines allowed ingress and egress for those pods. No selector match means no enforcement for that pod. Empty `podSelector: {}` means all pods in the namespace.

Deny is implicit. Once a policy selects a pod, everything not explicitly allowed is denied for that direction.

---

### `[Task 08]` Create a NetworkPolicy to isolate backend traffic · *Medium*

```
In namespace 'api', create a NetworkPolicy named 'api-allow-frontend' that:
- selects pods with label 'role: api'
- allows ingress on port 8080 only from pods with label 'role: frontend'
- denies all other ingress
```

```yaml
# netpol-api.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow-frontend
  namespace: api
spec:
  podSelector:
    matchLabels:
      role: api
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          role: frontend
    ports:
    - protocol: TCP
      port: 8080
```

```bash
kubectl apply -f netpol-api.yaml -n api

# Verify
kubectl get networkpolicy -n api
kubectl describe networkpolicy api-allow-frontend -n api

# Test from a frontend pod
kubectl exec -n api deploy/frontend -- sh -c "nc -zv api-svc 8080"

# Test from elsewhere, should time out or refuse
kubectl run tmp-test --image=busybox:1.35 -n api --rm -it -- sh -c "nc -zv api-svc 8080"
```

Notes from practice:

- `podSelector` under `spec` is who is protected. `podSelector` under `from` is who is allowed.
- Omit `egress` and only `Ingress` is filtered. Egress stays open.
- Port here is the pod port, not the Service port. Check containerPort.

---

### `[Task 09]` Label pods to satisfy existing policies · *Medium, high exam frequency*

```
Namespace 'prod' has 4 NetworkPolicies. Do not modify them.
Pods 'web-1' and 'db-1' cannot communicate. Inspect policies,
add correct labels to pods so traffic is allowed. Verify connectivity.
```

This is verbatim the shape described in multiple r/ckad passes. One from Jan 2026 had 4 policies deployed, candidate had to use the correct 2 by labeling pods. Another from March 2026 had the same constraint.

```bash
# Step 1, read what exists
kubectl get networkpolicy -n prod
kubectl describe networkpolicy -n prod

# Example output you will see
# Policy allow-web-to-db selects role=db, allows from role=web on 5432
# Policy allow-dns selects all, allows egress to kube-dns on 53

# Step 2, read current labels
kubectl get pods -n prod --show-labels

# NAME    LABELS
# web-1   app=web
# db-1    app=db

# Step 3, align labels to what policies expect
kubectl label pods web-1 -n prod role=web --overwrite
kubectl label pods db-1 -n prod role=db --overwrite

# If pods are owned by a Deployment, label the template so recreates keep it
kubectl patch deployment web -n prod -p '{"spec":{"template":{"metadata":{"labels":{"role":"web","app":"web"}}}}}'
kubectl patch deployment db -n prod -p '{"spec":{"template":{"metadata":{"labels":{"role":"db","app":"db"}}}}}'

# Step 4, verify
kubectl get pods -n prod --show-labels
kubectl exec -n prod web-1 -- sh -c "nc -zv db-svc 5432"
```

Rules that keep you out of trouble:

- Never edit the policy when prompt says not to. Examiners check for that.
- When pods are managed, patch the Deployment or ReplicaSet template, not just the live pod. Live pod labels vanish on restart.
- Label both sides if needed. `from.podSelector` checks source labels. `spec.podSelector` checks destination labels. Mismatch on either side blocks traffic.
- Namespace scoping matters. `podSelector` alone is same-namespace only. Cross-namespace needs `namespaceSelector` or `namespaceSelector` plus `podSelector`. Read the policy before assuming.

---

### `[Task 10]` Deny all, then allow selectively · *Hard*

```
In namespace 'secure', apply default deny for ingress and egress.
Then allow 'api' pods to resolve DNS and to reach 'db' on 5432.
```

```yaml
# 01-default-deny.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: secure
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
---
# 02-allow-api-egress.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-api-to-db-and-dns
  namespace: secure
spec:
  podSelector:
    matchLabels:
      role: api
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          role: db
    ports:
    - protocol: TCP
      port: 5432
  - to:
    - namespaceSelector:
        matchLabels:
          name: kube-system
      podSelector:
        matchLabels:
          k8s-app: kube-dns
    ports:
    - protocol: UDP
      port: 53
```

```bash
kubectl apply -f 01-default-deny.yaml -n secure
kubectl apply -f 02-allow-api-egress.yaml -n secure

# Common miss, DNS blocked
# Symptom is curl fails by name but works by IP. Always allow DNS egress when you default-deny egress.
kubectl exec -n secure deploy/api -- sh -c "nslookup db-svc; nc -zv db-svc 5432"
```

---

## Debug sequence, same order every time

```bash
NS=prod

kubectl get networkpolicy -n $NS
kubectl describe networkpolicy -n $NS

kubectl get pods -n $NS --show-labels
kubectl get endpoints -n $NS

# Direct pod-to-pod test, bypasses Service and Ingress
kubectl exec -n $NS <source-pod> -- sh -c "nc -zv <dest-ip> <port>"

# Policy events, often empty but cheap to check
kubectl get events -n $NS --sort-by=.metadata.creationTimestamp | tail -20
```

Symptom map:

| Symptom | Likely cause | Fix |
|---|---|---|
| Timeout between pods, Service endpoints populated | Policy selects dest, source label not allowed | Add source label in `from.podSelector`, or fix source pod labels |
| DNS name fails, IP works | Egress default deny without DNS allow | Add egress to kube-dns UDP 53 |
| Worked, then broke after rollout | Label patched on pod only, template still old | Patch Deployment template labels |
| Nothing matches, no policies listed | Wrong namespace | Re-run with `-n` from prompt, check `kubectl config view` |

---

## Speed commands

```bash
kubectl get networkpolicy -n NS
kubectl describe networkpolicy NAME -n NS
kubectl get pods -n NS --show-labels
kubectl label pods NAME key=value -n NS --overwrite
kubectl patch deployment NAME -n NS -p '{"spec":{"template":{"metadata":{"labels":{"role":"VALUE"}}}}}'
kubectl exec -n NS <pod> -- sh -c "nc -zv <svc> <port>"
```

## Phrase to field map

| Exam phrase | What to do |
|---|---|
| allow only X to reach Y | `spec.podSelector` selects Y, `from.podSelector` selects X |
| do not modify policies | label pods, patch Deployment templates |
| default deny | `podSelector: {}`, both `Ingress` and `Egress` in `policyTypes` |
| allow DNS | egress to `k8s-app: kube-dns` UDP 53 in `kube-system` |
