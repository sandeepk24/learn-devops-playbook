# Argo CD projects

An Application with no `spec.project` lands in `default`. The default project, the day it is created, allows any source repo, any cluster, any namespace, and any cluster-scoped kind. I have shipped a team's first app on `default` because the sync worked. That Application could create a ClusterRole. The project is the allow list. The Application is just a pointer.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: payments
  namespace: argocd
spec:
  description: Payments services
  sourceRepos:
    - https://github.com/org/gitops.git
  destinations:
    - namespace: payments
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace
      name: payments
  sourceNamespaces:
    - payments
  destinationServiceAccounts:
    - server: https://kubernetes.default.svc
      namespace: payments
      defaultServiceAccount: payments-deployer
```

`sourceRepos` is the git Argo may read for this project. A second repo URL in an Application is rejected. I have watched a pull request change `repoURL` to a fork. The project stopped it. The Application YAML was valid.

`destinations` is where namespaced resources may go. `namespace: payments` keeps Deployments out of `kube-system`. I keep the server URL identical to the one on the cluster secret. A trailing character difference is a destination the project refuses, and the error looks like a permissions problem.

`clusterResourceWhitelist` is empty of anything I did not type. A Namespace is cluster-scoped, so the destination entry does not cover it. The `name: payments` on that whitelist is what keeps the project from creating `kube-system` or any other namespace. A CRD, a ClusterRole, or a MutatingWebhookConfiguration stays off this list and lives in a platform project I review. Namespaced kinds are allowed until I blacklist one. I have blacklisted `ResourceQuota` on a team project after a sync replaced the quota the platform chart had set.

`destinationServiceAccounts` is the identity the sync uses in that namespace. The Application controller is not cluster-admin for every app once this is set. `payments-deployer` can update Deployments in `payments`. It cannot bind cluster roles. I create that ServiceAccount in the platform repo, before the first team app syncs. An Application that fails with a forbidden error is usually this account, and the fix is the RoleBinding, not a wider project.

`sourceNamespaces` lists where Applications for this project may live. It does nothing until `argocd-cm` allows those namespaces in `application.namespaces`. After that, the payments team creates Applications in the `payments` namespace, and those Applications can only join a project that lists `payments`. I stopped finding team Applications dropped into the `argocd` namespace next to the platform ones.

## One Application per directory

I started with an app-of-apps: one parent Application whose path was a directory of child Application manifests. The parent went Synced when the child Application objects existed. The children could be Degraded and the parent was still green. I read the parent.

An ApplicationSet generates the Applications from the repo. The project on the template is a fixed name. I do not template `spec.project`. A generator that lets the directory choose the project will let a pull request choose the permissive one. The docs call that out, and I have seen the pull request.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: payments
  namespace: argocd
spec:
  goTemplate: true
  goTemplateOptions: ["missingkey=error"]
  generators:
    - git:
        repoURL: https://github.com/org/gitops.git
        revision: main
        directories:
          - path: apps/payments/*
  template:
    metadata:
      name: "{{.path.basenameNormalized}}"
    spec:
      project: payments
      source:
        repoURL: https://github.com/org/gitops.git
        targetRevision: main
        path: "{{.path.path}}"
      destination:
        server: https://kubernetes.default.svc
        namespace: payments
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

`goTemplate: true` is what makes `{{.path.basenameNormalized}}` expand. Without it I have committed the braces as the Application name. `basenameNormalized` replaces characters Kubernetes will not accept in a name. A new directory under `apps/payments/` becomes an Application on the next reconcile. Deleting the directory prunes that Application only if prune is on. I keep prune on here, and I keep the directory generator pointed at a folder that contains nothing except apps I am willing to delete.

The ApplicationSet file is one I review. The team adds a directory under `apps/payments/`. A pull request that changes `project` or `destination.server` on the template is the one I do not let through on a rubber stamp. How that generated Application orders its resources is [the sync note](./argo-cd-sync.md). The thing inside the directory is still [an Application](./argo-cd.md).
