# Argo CD

I installed it for one reason. The pipeline was holding `kubectl`, and I was tired of that.

CI still builds the image and commits the manifest. Argo CD is the loop that makes the cluster match that commit, and it does not care whether the commit came from GitHub, GitLab, or Bitbucket. I have run it on more clusters than any other GitOps controller, which says more about where I have worked than about the tool.

The unit of work is an `Application`. It names a path in git and a namespace in a cluster. Desired state is the path. Live state is the namespace. OutOfSync means they disagree.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: api
  namespace: argocd
spec:
  project: payments
  source:
    repoURL: https://github.com/org/gitops.git
    targetRevision: main
    path: apps/api/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: api
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
      - PruneLast=true
```

Write the branch name. `targetRevision: main` follows `main`, while `HEAD` follows whatever the default branch happens to be today, and I have watched a cluster follow a renamed default into a branch nobody meant it to track.

Two repos are in play. The application repo is the one CI tests. The gitops repo is the one Argo reads. I once pointed `source.path` at a directory holding a Dockerfile and spent twenty minutes wondering why the sync had nothing to apply. The path has to render into manifests. Plain YAML, Kustomize, or Helm.

## Who applies

Automated sync fires when git changes. Not always.

Set `enabled: false` and it skips the sync entirely, even with `prune` and `selfHeal` sitting right below it looking like they are doing something. I have read the prune line three times and missed the flag above it.

Prune is off by default, including under automated sync. I deleted a Deployment from git once, watched the Application go OutOfSync, and watched the Deployment keep running. Manual sync did the same until I ticked prune. `PruneLast=true` pushes the deletes to the end, after the new resources are healthy, so the old Service does not disappear before its replacement answers.

SelfHeal is off by default too. Without it, a `kubectl edit` shows up as OutOfSync and stays that way until something else triggers a sync. With it, the edit is reverted to what git says without waiting for the next commit. I turn it on for production. On a cluster where I still expect to debug by hand, I leave it off and accept that the UI will show drift I put there myself.

`CreateNamespace=true` creates `spec.destination.namespace` when it is missing. Argo does not own that namespace afterward. Add the tracking annotation and it does, which means a prune can delete it. I deleted a shared namespace exactly that way. Now I let Argo create the namespace and leave the annotation alone, unless this Application is the only tenant and the namespace should die with it.

## Two writers

Keep a pipeline that runs `kubectl apply` next to Argo and you have two controllers who each believe they own the Deployment. The next reconcile puts back whatever git says, including over the replica count you just scaled and the image tag the pipeline just pushed. So I took the cluster credentials off the deploy job. Its only credential now is write access to the gitops repo. It commits the digest and Argo applies it, the same rule as [the task definition](./promote-the-image-digest.md).

Argo polls. A push does not sync in the same second, and unless a webhook is configured the wait is a few minutes, which is a long time when you are watching.

Refresh has two modes. A normal refresh re-reads git. A hard refresh also drops the cached Helm or Kustomize render. I have clicked refresh, seen the previous commit's manifests, and been confused for a while before remembering a chart dependency had changed. That is a hard refresh. The annotation is `argocd.argoproj.io/refresh: hard`, and the controller removes it when it finishes.

Who may point an Application at a cluster is [the project](./argo-cd-projects.md). The order resources come up in is [the sync](./argo-cd-sync.md).
