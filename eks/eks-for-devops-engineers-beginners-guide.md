# Starting on EKS

Someone hands you a cluster name and a namespace. This is what to do with that, and what to leave alone until you've done it a few times.

The other notes in this folder are for when you own the cluster. You don't need them yet. If a container still feels fuzzy, read [Docker internals, part 1](../docker/docker-advanced-part-1.md) first.

---

## EKS is Kubernetes, with AWS running the brain

Kubernetes runs your containers across a bunch of machines. The brain is the control plane: the API server, the database behind it (etcd), and the scheduler. On EKS, AWS runs that for you. You don't log into it. You talk to it with `kubectl`.

The machines that run your containers are the nodes. Usually EC2. Sometimes Fargate. For your first month, the nodes are someone else's job. You work on the apps.

AWS charges for the control plane every hour, even if nothing is running. If you make a cluster to practice, delete it when you stop. A lab cluster left up for a month is an expensive empty box.

```
You, with kubectl and a YAML file in git
        │
        ▼
EKS control plane          AWS runs this
        │
        ▼
Nodes                      EC2 or Fargate. Your pods run here
        │
        ▼
Pods                       your container, actually running
```

You almost never create a pod yourself. You change a Deployment. The Deployment creates the pods, and it replaces them when you change the image.

---

## If you've used ECS, the names change

Skip this if you haven't. The ideas are the same.

| You called it | On EKS it's | Meaning |
|---|---|---|
| Cluster | Cluster | The boundary. AWS runs the control plane inside it. |
| Task definition | The pod template in a Deployment | Image, CPU, memory, env, ports. |
| Task | Pod | One running copy. |
| Service | A Deployment, plus a Service | The Deployment keeps the count. The Service is the address that doesn't change. |
| ALB and target group | A Service, then an Ingress | Inside the cluster you use a Service. From the outside, an Ingress becomes a load balancer. |
| Task role | Pod Identity or IRSA | How the container calls AWS. Not this week. |

One habit carries over. The deploy command succeeding does not mean users can hit the app. On ECS, `RUNNING` only means the process started. On EKS, `kubectl apply` only means the API stored your file. You still wait until the new pods pass their health check.

---

## Five things you'll touch

Stay inside these until someone asks you to change the cluster.

**Namespace.** A folder. `payments`, `dev`, `kube-system`. Put `-n payments` on your commands. If you forget, kubectl looks in `default`, finds nothing, and it looks like the app vanished.

**Deployment.** The file you edit to release. How many copies, which image.

**Pod.** One running copy of that file. The name looks like `api-7d9f8b-xk2zp`. The ending changes every time Kubernetes replaces the pod. Don't memorize it. Select it with a label, `app=api`.

**Service.** A stable name inside the cluster. Other apps call `api`, or `api.payments.svc.cluster.local` from another namespace. They don't call the pod IP. That IP changes. The Service only sends traffic to pods that are Ready.

**Ingress.** "Requests for `api.example.com` go to this Service." On EKS a controller turns that into a load balancer. Ignore it until the app has to be reached from a browser or from outside the cluster. The long version is the [ALB and NLB note](./aws-alb-nlb-ingress-eks-deep-dive.md).

---

## A Deployment, read once

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: payments
spec:
  replicas: 2
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
          image: 111122223333.dkr.ecr.us-east-1.amazonaws.com/api:1.4.2
          ports:
            - containerPort: 8080
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
          resources:
            requests:
              cpu: "100m"
              memory: 128Mi
            limits:
              memory: 256Mi
```

`replicas: 2` means two pods.

`selector` has to match the labels on the pod. If they don't, apply fails. You don't get a pod that's half-created. You get an error.

The number on the image is the version. Don't deploy `latest` in prod. You can't tell what's running, and you can't roll back to it, because `latest` moves.

`readinessProbe` calls `/health`. If that fails, the pod can still say `Running`, and the Service will not send it traffic. Look at the READY column. `0/1` means the process is up and the check is failing. This is the status that wastes the most time when you're new.

`requests` are how Kubernetes finds a node with room. Set them. A memory limit is the point where Kubernetes restarts your container instead of letting it fill the node. You can skip the CPU limit for now. The [scheduling note](./pending-pods-pdbs-and-spread.md) goes further, when you need it.

The Service in front of those pods:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: api
  namespace: payments
spec:
  selector:
    app: api
  ports:
    - port: 80
      targetPort: 8080
```

Other pods connect to port 80. Your app listens on 8080. The selector has to be the same labels as the pod. Get this wrong and the pods are healthy while the Service has nowhere to send traffic. That's a very ordinary first bug.

```bash
kubectl get endpoints api -n payments
```

An empty address list means no Ready pod matched.

---

## Point kubectl at the right cluster

You'll get a cluster name, a region, and a role you're allowed to use. AWS letting you call EKS is not the same as Kubernetes letting you list pods. The cluster has its own list of who's allowed in. If kubectl says `Unauthorized`, your role isn't on that list. Don't try to edit the list in your first week. Ask.

```bash
aws eks update-kubeconfig --name app --region us-east-1
kubectl get ns
kubectl config current-context
```

`current-context` is which cluster the next command will hit. Check it before you apply anything. People have deleted a deployment in prod because the context was still pointed there.

---

## Commands for a normal day

There's a longer [kubectl toolkit](../linux/kubectl-daily-toolkit.md). These cover most of the first month.

```bash
kubectl get deploy,pods,svc -n payments
kubectl get pods -n payments -o wide
kubectl describe pod -n payments -l app=api
kubectl logs -n payments -l app=api --tail=100
kubectl rollout status deploy/api -n payments
```

`-l app=api` picks pods by label, so you don't need the random name. `-o wide` adds the node and the pod IP. `describe` ends with Events. Read that before logs. If the container never started, the logs are empty and the event is the reason.

`kubectl apply` exiting 0 means the API accepted the file. `rollout status` waits until the new pods are ready, or until it gives up. There's a [short note](./kubectl-rollout-status-is-underrated.md) on using it in a pipeline.

If you want to know where a pod landed:

```bash
kubectl get pod -n payments -l app=api -o wide
kubectl describe node <node-name>
```

No node in that wide output means the pod is still Pending. It never started.

---

## Three things you'll see, and what to do

| What you see | What's going on | First move |
|---|---|---|
| `Pending` | Nothing has started it. No node fit, or it's waiting on a disk. | `kubectl describe pod`, then read Events. |
| `CrashLoopBackOff` | It started and exited. Kubernetes is waiting longer before trying again. | `kubectl logs <pod> --previous` |
| `Running`, READY `0/1` | The process is up. The health check is failing, so the Service skips it. | `describe`, then logs. Try the probe path. |

`Pending` plus `Insufficient cpu` or `Insufficient memory` means the pod doesn't fit on a node. That's not your application. Copy the event and ask whoever owns the nodes. Applying the Deployment again does nothing.

`ImagePullBackOff` means the node couldn't download the image. The tag isn't there, or the node isn't allowed to pull it. Check the image line in the Deployment before you change anything else.

Crash loops have their own notes: [part 1](./crashloopbackoff-part1-foundations.md), then [part 2](./crashloopbackoff-part2-advanced.md) if it's still unclear. The habit from part 1 is `--previous`. The pod may be sitting in the wait, so the current logs are blank. The previous run has the error.

READY `0/1` while the status says `Running` is the one that fools people. The pod looks up. Users still can't connect. I've watched someone delete the pod over and over for this, and the new one failed the same probe because `/health` was the wrong path.

---

## Leave this alone for now

If you only change Deployments and Services in the namespace you were given, the cluster will be fine.

`kube-system` is DNS and networking for every app. A bad edit there is an outage for the whole cluster, not just yours.

Deleting pods to fix a crash makes the Deployment create the same pod again. Change the file, or fix what the logs are telling you.

Don't put AWS access keys in the Deployment. When the app needs S3 or Secrets Manager, the team attaches a role to the service account. That's [Pod Identity](./eks-pod-identity.md) or [IRSA](./irsa-explained-real-eks-workloads.md). Until then, the honest answer is that the pod has no AWS permissions.

Don't grow a node group, or upgrade the cluster, because one pod is Pending. Describe the pod, paste the event, and hand it to whoever owns the cluster. The [control plane](./eks-control-plane-what-you-own.md) and [compute](./eks-compute-node-groups-fargate-auto-mode.md) notes are for when that work is yours.

---

## If you're stuck

Run these in order. Stop when one of them explains it.

```bash
kubectl config current-context
kubectl get deploy api -n payments
kubectl get pods -n payments -l app=api -o wide
kubectl describe pod -n payments -l app=api
kubectl logs -n payments -l app=api --tail=50
kubectl get endpoints api -n payments
```

Then you can say which it is: the pod is Pending, the container is exiting, the health check is failing, or the Service has no endpoints. "The app is down" is how you start. The status is what gets you a useful answer.

---

## Where to go after this

A pod keeps dying: [CrashLoopBackOff, part 1](./crashloopbackoff-part1-foundations.md).

A pipeline should wait for the new version: [`kubectl rollout status`](./kubectl-rollout-status-is-underrated.md).

The app needs to be reached from outside the cluster: [ALB, NLB, and Ingress](./aws-alb-nlb-ingress-eks-deep-dive.md). You don't need that to call another Service inside the cluster.

Pods sit Pending and the events mention CPU, memory, or a disruption budget: [Pending pods, PDBs, and spread](./pending-pods-pdbs-and-spread.md).

You own the cluster, not just a namespace: start at [what you still own on the control plane](./eks-control-plane-what-you-own.md).
