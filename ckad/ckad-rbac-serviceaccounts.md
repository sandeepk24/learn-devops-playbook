# CKAD RBAC and ServiceAccounts — Log-Driven Fixes

*The question candidates flag most. Read logs, find the missing verb, bind the right role, set the ServiceAccount. Verify.*

*Validated against Kubernetes 1.31. One RBAC task is standard on current forms.*

---

## What r/ckad keeps reporting

Pattern from Nov 2025, Jan 2026, March 2026 forms:

- A pod runs with the wrong ServiceAccount or default.
- `kubectl logs` shows Forbidden or cannot list or get a resource.
- You create a ServiceAccount, bind the correct Role or ClusterRole, set it on the workload.

One 83 percent pass called this the question they failed because they stayed too long. One 97 percent pass called the aravind4799 repo plus ckad-dojo the difference for exactly this type. Move methodically, flag it if logs are unclear, come back with fresh time.

---

### `[Task 11]` Fix a pod that cannot read ConfigMaps · *Medium*

```
Pod 'reader' in namespace 'team-a' is CrashLooping. Logs show it cannot
read ConfigMaps. Create ServiceAccount 'reader-sa', grant read-only access
to ConfigMaps in 'team-a', set the pod to use it.
```

```bash
# Step 1, read the error, do not guess
kubectl get pods -n team-a
kubectl logs reader -n team-a
# typical line: configmaps "app-config" is forbidden: User "system:serviceaccount:team-a:default" cannot get resource "configmaps"

# Step 2, see what roles exist
kubectl get roles,clusterroles -n team-a
kubectl describe role config-reader -n team-a

# Step 3, create the ServiceAccount imperatively
kubectl create serviceaccount reader-sa -n team-a

# Step 4, bind it. Prefer existing Role if it fits.
kubectl create rolebinding reader-bind \
  --role=config-reader \
  --serviceaccount=team-a:reader-sa \
  -n team-a

# If no suitable Role exists, create least-privilege Role
kubectl create role config-reader \
  --verb=get,list,watch \
  --resource=configmaps \
  -n team-a --dry-run=client -o yaml | kubectl apply -f -

kubectl create rolebinding reader-bind \
  --role=config-reader \
  --serviceaccount=team-a:reader-sa \
  -n team-a

# Step 5, attach to workload
kubectl set serviceaccount deployment/reader reader-sa -n team-a
# For a bare pod, delete and recreate, ServiceAccount is immutable on pods
# kubectl get pod reader -n team-a -o yaml > pod.yaml, edit serviceAccountName, recreate

# Step 6, verify
kubectl rollout status deployment/reader -n team-a
kubectl logs -n team-a -l app=reader --tail=20
kubectl auth can-i get configmaps --as=system:serviceaccount:team-a:reader-sa -n team-a
# expected: yes
```

---

### `[Task 12]` Create Role and RoleBinding from scratch · *Medium*

```
Create ServiceAccount 'deployer' in 'ci'. Create Role 'deploy-manager'
that can get, list, update, patch deployments and get pods. Bind it to
'deployer' in 'ci' only.
```

```yaml
# role.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deploy-manager
  namespace: ci
rules:
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "patch", "update"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: deployer
  namespace: ci
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: deployer-bind
  namespace: ci
subjects:
- kind: ServiceAccount
  name: deployer
  namespace: ci
roleRef:
  kind: Role
  name: deploy-manager
  apiGroup: rbac.authorization.k8s.io
```

```bash
kubectl apply -f role.yaml

# Verify scope, RoleBinding stays namespaced
kubectl auth can-i patch deployments --as=system:serviceaccount:ci:deployer -n ci
# expected: yes
kubectl auth can-i patch deployments --as=system:serviceaccount:ci:deployer -n default
# expected: no, correct for Role, not ClusterRole
```

---

## Role versus ClusterRole, decision rule

| Need | Use |
|---|---|
| Access in one namespace | Role plus RoleBinding |
| Access across namespaces or cluster resources like nodes | ClusterRole plus ClusterRoleBinding |
| Exam says in namespace X | Role plus RoleBinding in X, nothing cluster scoped |

Common fault: creating ClusterRoleBinding when prompt says namespace only. That grants too much and automated checks mark it wrong. Match scope exactly.

---

## Debug sequence

```bash
NS=team-a
POD=reader

kubectl logs $POD -n $NS
kubectl logs $POD -n $NS --previous
kubectl get pod $POD -n $NS -o jsonpath='{.spec.serviceAccountName}{"\n"}'
kubectl get roles,rolebindings,clusterroles,clusterrolebindings -n $NS
kubectl auth can-i --list --as=system:serviceaccount:$NS:reader-sa -n $NS
kubectl get events -n $NS --sort-by=.metadata.creationTimestamp | tail -20
```

Symptom map:

| Log or symptom | Cause | Fix |
|---|---|---|
| Forbidden, cannot get or list | Missing verb on resource | Add verb to Role, or bind correct Role |
| serviceaccount not found | Typo or wrong namespace | `kubectl get sa -n NS`, recreate |
| Still fails after binding | Pod still uses old SA | `kubectl set serviceaccount`, or recreate bare pod |
| Works in one NS, fails in another | RoleBinding is namespaced | Create binding in each required NS, or use ClusterRole if prompt allows |

---

## Speed commands

```bash
kubectl create serviceaccount NAME -n NS --dry-run=client -o yaml | kubectl apply -f -
kubectl create role NAME --verb=get,list --resource=configmaps -n NS --dry-run=client -o yaml > role.yaml
kubectl create rolebinding NAME --role=ROLE --serviceaccount=NS:SA -n NS
kubectl set serviceaccount deployment/NAME SA -n NS
kubectl auth can-i VERB RESOURCE --as=system:serviceaccount:NS:SA -n NS
kubectl logs POD -n NS --previous
```

## Phrase to field map

| Exam phrase | Action |
|---|---|
| check logs, fix SA so it can run | logs first, then `auth can-i`, then bind |
| grant read-only in namespace | Role with get, list, watch, plus RoleBinding |
| use ServiceAccount X | `serviceAccountName: X` in podSpec, or `kubectl set serviceaccount` |
