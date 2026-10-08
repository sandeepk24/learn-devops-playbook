# CKAD Exam Strategy and Mechanics — What Actually Saves Time

*Collected from candidates who scored 67 to 99 percent. This is not theory. This is what works on exam day.*

---

## The exam format

- 2 hours, 17 questions
- 66 percent passing score (roughly 11 of 17 correct)
- Performance-based, all terminal work
- Kubernetes 1.31 as of 2025-2026
- SSH per question into different cluster nodes
- Kubernetes documentation allowed (kubernetes.io/docs)
- `kubectl explain` available and reflects cluster version
- PSI Secure Browser with remote desktop option

---

## Time management

### The math

- 2 hours = 120 minutes
- 17 questions = ~7 minutes average per question
- But questions are weighted differently
- Some take 2 minutes, some take 12

### The strategy that works

First pass: 3-4 minutes per question maximum.

- Read the question
- If you know how to solve it, do it
- If stuck after 2 minutes, flag and move on
- Do not stay on any question beyond 4 minutes in first pass

Second pass: Use banked time on flagged questions.

- By moving fast on easy questions, you bank time
- Come back to hard questions with 20-30 minutes remaining
- Fresh eyes often see the solution

### What candidates report

r/ckad Jan 2026 (99%): "Finished with about 20 minutes left to review."

r/ckad Nov 2025 (83%): "Dont stay on it in order to fix it. There are easier questions ahead from which you can score if you have enough time."

r/ckad March 2026 (97%): "Flag difficult questions and move on. Came back to them later with fresh eyes and more time in the bank."

### Question ordering

Easy questions tend to be:
- Secret creation and mounting
- Service selector fix
- Ingress creation
- Docker build/tag/save
- CronJob manual trigger

Hard questions tend to be:
- RBAC with log-driven diagnosis
- NetworkPolicy with multiple existing policies
- Multi-step debugging

Do easy questions first. Bank time. Return to hard questions.

---

## Terminal mechanics

### SSH per question

Each question SSHs you into a different cluster node. Your context resets.

```bash
# At the start of each question, you run something like:
ssh node01
```

Your shell history from previous questions is gone. Your aliases are gone (except `k=kubectl` which is preset).

### Namespace handling

Every task specifies a namespace. Getting it wrong means zero points.

Option 1: Use `-n` on every command

```bash
kubectl get pods -n staging
kubectl apply -f file.yaml -n staging
kubectl logs pod-name -n staging
```

Option 2: Set context namespace at start of each task

```bash
kubectl config set-context --current --namespace=staging
```

Then commands default to that namespace. But you must remember to do this per task.

Recommendation: Use `-n` explicitly. It is one extra flag but removes the risk of forgetting to set context.

### Copy and paste

- Copy: `Ctrl+Shift+C`
- Paste: `Ctrl+Shift+V`

This is different from Mac conventions (`Cmd+C`, `Cmd+V`). Practice before exam day or muscle memory will betray you.

r/ckad July 2025: "The main challenge I encountered was with copy-paste commands. On killer.sh, I was able to use Cmd+C and Cmd+V for copying and pasting, but in the exam portal, I had to use Ctrl+Shift+C and Ctrl+Shift+V."

---

## Vim setup

Vim is the default editor. YAML requires exact indentation. A single tab character breaks everything.

### First thing in every session

```bash
vim ~/.vimrc
```

Add:

```
set expandtab
set tabstop=2
set shiftwidth=2
set autoindent
```

Or set inline when opening a file:

```
:set expandtab tabstop=2 shiftwidth=2 autoindent
```

### Essential vim commands

| Command | Action |
|---|---|
| `i` | Insert mode |
| `Esc` | Exit insert mode |
| `:w` | Save |
| `:q` | Quit |
| `:wq` | Save and quit |
| `:q!` | Quit without saving |
| `dd` | Delete line |
| `yy` | Copy line |
| `p` | Paste below |
| `P` | Paste above |
| `u` | Undo |
| `Ctrl+r` | Redo |
| `/pattern` | Search forward |
| `n` | Next search result |
| `:%s/old/new/g` | Replace all |
| `Shift+V` | Visual line mode |
| `>` | Indent selected lines |
| `<` | Unindent selected lines |
| `:set paste` | Paste mode (preserves indentation) |
| `:set nopaste` | Exit paste mode |

### Block indentation

When you paste YAML at wrong indentation:

1. Position cursor at first line of block
2. `Shift+V` to enter visual line mode
3. Move down to select all lines
4. `>` to indent one level, or `<` to unindent
5. Repeat `>` or `<` as needed

This fixes indentation in two keystrokes instead of editing every line.

### VSCodium alternative

The exam environment includes a remote desktop with VSCodium. If Vim slows you down, use VSCodium.

r/ckad Jan 2026: "I strongly recommend use VSCodium to take the exam since it's much easier to edit the yaml and use the terminal at the same time."

Decide in practice, not on exam day. If you choose VSCodium, practice with it.

---

## Imperative commands

Typing YAML from scratch is slow and error-prone. Generate it.

### Generate, edit, apply

```bash
# Generate YAML without applying
kubectl create deployment web --image=nginx:1.25 --replicas=3 \
  --dry-run=client -o yaml > web.yaml

# Edit to add resources, probes, etc.
vim web.yaml

# Apply
kubectl apply -f web.yaml
```

### What kubectl generates

```bash
kubectl create deployment NAME --image=IMG --replicas=N
```

Generates: apiVersion, kind, metadata, spec.selector, spec.template with basic container.

Does NOT generate: resources, probes, env, volumeMounts, volumes, extra labels.

Those are what you add manually.

### Common generators

```bash
# Deployment
kubectl create deployment NAME --image=IMG --replicas=N --dry-run=client -o yaml

# Service
kubectl expose deployment NAME --port=80 --target-port=8080 --dry-run=client -o yaml

# ConfigMap
kubectl create configmap NAME --from-literal=key=value --dry-run=client -o yaml

# Secret
kubectl create secret generic NAME --from-literal=key=value --dry-run=client -o yaml

# Job
kubectl create job NAME --image=IMG --dry-run=client -o yaml -- command args

# CronJob
kubectl create cronjob NAME --image=IMG --schedule="*/5 * * * *" --dry-run=client -o yaml -- command

# Ingress
kubectl create ingress NAME --rule="host/path=service:port" --class=nginx --dry-run=client -o yaml

# ServiceAccount
kubectl create serviceaccount NAME --dry-run=client -o yaml

# Role
kubectl create role NAME --verb=get,list --resource=pods --dry-run=client -o yaml

# RoleBinding
kubectl create rolebinding NAME --role=ROLE --serviceaccount=NS:SA --dry-run=client -o yaml
```

### The -- separator

For Jobs and CronJobs, `--` separates kubectl flags from the container command:

```bash
# Wrong: command is lost
kubectl create job test --image=busybox sh -c "echo hello"

# Correct: command is captured
kubectl create job test --image=busybox -- sh -c "echo hello"
```

---

## kubectl explain

Use it freely. It reflects the actual cluster version.

```bash
# What fields exist on a Deployment spec
kubectl explain deployment.spec

# Drill down
kubectl explain deployment.spec.strategy
kubectl explain deployment.spec.strategy.rollingUpdate

# Show all fields recursively
kubectl explain deployment.spec --recursive | head -50

# Specific field
kubectl explain pod.spec.containers.resources
```

When unsure about field names or structure, `kubectl explain` is faster than the docs.

---

## Verification

A task you think you finished but did not is worse than a task you skipped. You will not come back to it.

### Verify every task before moving on

```bash
# Deployment rollout
kubectl rollout status deployment/NAME -n NS

# Service endpoints
kubectl get endpoints -n NS

# Ingress
kubectl describe ingress NAME -n NS

# Job completion
kubectl get job NAME -n NS
kubectl logs job/NAME -n NS

# CronJob
kubectl get cronjob NAME -n NS

# RBAC
kubectl auth can-i VERB RESOURCE --as=system:serviceaccount:NS:SA -n NS

# Events (catches things describe misses)
kubectl get events -n NS --sort-by=.metadata.creationTimestamp | tail -20
```

### Quick verification commands

```bash
# Does the resource exist
kubectl get RESOURCE NAME -n NS

# Is the pod running
kubectl get pods -n NS | grep NAME

# Are endpoints populated
kubectl get endpoints SVC -n NS

# Any errors in events
kubectl get events -n NS --sort-by=.metadata.creationTimestamp | grep -i error
```

---

## Common mistakes

| Mistake | Consequence | Prevention |
|---|---|---|
| Wrong namespace | Zero points | Use `-n` on every command |
| Selector mismatch | Pod not managed, Service has no endpoints | Verify with `kubectl describe` |
| Tab in YAML | Parse error | Set `expandtab` in vim |
| Forgot `--` in job/cronjob | Command dropped | Always use `-- command` for jobs |
| apiVersion wrong | Resource rejected | `apps/v1` for Deployments, `batch/v1` for Jobs |
| Stayed too long on hard question | Ran out of time for easy questions | Flag at 4 minutes, move on |
| Did not verify | Assumed success, actually failed | Always verify before moving on |

---

## Prep stack that works

Based on candidates who passed with 83-99%:

1. **Baseline course**: Mumshad Mannambeth Udemy or KodeKloud
2. **Practice questions**: [aravind4799/CKAD-Practice-Questions](https://github.com/aravind4799/CKAD-Practice-Questions) — do until answers are boring
3. **Second angle**: [TiPunchLabs/ckad-dojo](https://github.com/TiPunchLabs/ckad-dojo)
4. **Timed simulation**: Killer.sh twice — once open book, once closed
5. **NetworkPolicy drills**: [killercoda.com/omkar-shelke25](https://killercoda.com/omkar-shelke25)

### What to deprioritize

- Deep Helm, Kustomize, CRDs — mentioned, not core tasks
- StatefulSets, DaemonSets — rarely appear
- Complex multi-stage Dockerfiles — just build/tag/save
- Persistent Volumes in depth — basic understanding is enough

Rebalance that time to labels, logs, imperative generation, and verification.

---

## Day of exam

- Test your webcam, mic, and ID before the session
- Clear your desk per PSI requirements
- Have water within reach (ask proctor if unsure)
- Arrive 15 minutes early for check-in
- Breathe. You have practiced this.

### First 5 minutes

1. Set vim defaults in `~/.vimrc`
2. Verify `k=kubectl` alias works
3. Skim the question list to identify easy ones
4. Start with an easy question to build confidence

### During the exam

- Read the full question before starting
- Note the namespace and any specific names
- Generate, edit, apply, verify
- Flag and move on at 4 minutes
- Do not panic if one question is unfamiliar

### Last 20 minutes

- Return to flagged questions
- Prioritize partial credit: if you can get 50% of a question, do it
- Re-verify anything you were unsure about
- Do not add new changes in the last 5 minutes
