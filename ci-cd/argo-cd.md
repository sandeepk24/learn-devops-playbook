# Argo CD

I installed this when the deploy target was a cluster and I was tired of the pipeline holding `kubectl`. The CI system still builds the image and commits the manifest. Argo CD is the loop that makes the cluster match that commit. I have it on more clusters than the other GitOps controllers. The build is still GitHub, GitLab, or Bitbucket.

The unit of work is an `Application`. It names a path in git and a namespace in a cluster. Desired state is the path. Live state is the namespace. OutOfSync means those two disagree.

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

`targetRevision: main` follows that branch. `HEAD` follows whatever the default branch is today. I have had `HEAD` move to a branch I did not mean after someone renamed the default, and the cluster followed it. I write the branch name.

The gitops repo is the one Argo reads. The application repo is the one CI tests. I have pointed `source.path` at a Dockerfile directory and then wondered why the sync had nothing to apply. The path has to render into manifests: plain YAML, Kustomize, or a Helm chart.

## Who applies

Automated sync runs when git changes. It does not run because I set `prune` or `selfHeal` on a policy that has `enabled: false`. That flag skips the sync and leaves the other two sitting there looking intentional. I have read the prune line and missed `enabled`.

`prune` defaults off, even with automated sync. I deleted a Deployment from git, the Application went OutOfSync, and the Deployment kept running. A manual sync did the same until I checked prune. `PruneLast=true` deletes after the new resources are healthy, so I am not dropping the old Service before the new one is up.

`selfHeal` defaults off. A `kubectl edit` shows OutOfSync and stays until something else syncs. With `selfHeal: true` the edit goes back to git without waiting for the next commit. I turn it on for production. I leave it off on a cluster where I still expect to debug by hand, and I know the UI is telling the truth about that choice.

`CreateNamespace=true` creates `spec.destination.namespace` when it is missing. That namespace is not owned by the Application. Owning a namespace Argo created, by adding the tracking annotation, means a prune can delete it. I have deleted a shared namespace that way. I let Argo create it. I do not hand it the tracking id unless this Application is the only thing in that namespace and I have already decided the namespace should die with the app.

## Two writers

The pipeline that still runs `kubectl apply`, and Argo, both think they own the Deployment. The next reconcile puts back whatever is in git, including the replica count I had just scaled, and including an image tag the pipeline pushed that git does not mention. I took cluster credentials off the deploy job. The job's credential is write access to the gitops repo. It commits the digest. Argo applies. The digest rule is [the same one as the task definition](./promote-the-image-digest.md).

Argo polls. A push does not sync in the same second. I have refreshed the Application from the UI and still seen the previous render, because a normal refresh re-reads git and a hard refresh drops the cached Helm or Kustomize output. I use the hard refresh when a chart dependency changed and the manifests on screen were from the previous commit. The annotation is `argocd.argoproj.io/refresh: hard`. The controller removes it after the refresh.

Who is allowed to point that Application at a cluster is [the project](./argo-cd-projects.md). The order resources come up in is [the sync](./argo-cd-sync.md).
