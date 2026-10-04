# Argo CD projects

Leave `spec.project` empty and the Application lands in `default`. That project, as created, allows any source repo, any cluster, any namespace, and any cluster-scoped kind.

I shipped a team's first app on it because the sync worked. That Application could have created a ClusterRole. Nobody noticed, including me.

The project is the allow list. The Application is just a pointer.

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

`sourceRepos` is the git this project may read. Anything else is rejected. I watched a pull request swap `repoURL` for a fork once, and the project stopped it even though the Application YAML was perfectly valid.

`destinations` covers where namespaced resources may land. `namespace: payments` keeps Deployments out of `kube-system`. Copy the server URL from the cluster secret exactly, because one stray character makes it a different destination, and the error reads like a permissions problem.

`clusterResourceWhitelist` holds only what I typed into it. A Namespace is cluster-scoped, so the destination entry does not cover it, and the `name: payments` here is what stops the project creating `kube-system` or anything else. CRDs, ClusterRoles, and webhook configurations stay off the list. They live in a platform project that I review. Namespaced kinds are allowed until denied, and I have denied `ResourceQuota` on a team project after a sync overwrote the quota the platform chart set.

`destinationServiceAccounts` is the identity the sync runs as. It takes effect only after sync impersonation is switched on with `application.sync.impersonation.enabled: "true"` in `argocd-cm`. Skip that and the field sits there doing nothing, which is an easy thing to believe is a control. Once it is on, `payments-deployer` can update Deployments in `payments` and cannot bind cluster roles. I create that ServiceAccount in the platform repo before the first team app syncs. A forbidden error on sync is usually this account missing a RoleBinding. The fix is the RoleBinding. A wider project is the wrong answer.

`sourceNamespaces` says where Applications for this project may live. Nothing happens until `application.namespaces` is set in `argocd-cmd-params-cm` and the server and application controller are restarted. After that, the payments team keeps its Applications in its own namespace. I stopped finding team apps dropped into `argocd` next to the platform ones.

## One Application per directory

I started with app-of-apps. One parent Application, whose path was a folder of child Application manifests. The parent went Synced once the child objects existed. The children could be Degraded and the parent stayed green.

I was reading the parent.

An ApplicationSet generates the Applications from the repo instead. The project in the template is a fixed name. I never template `spec.project`, because a generator that lets a directory pick its own project lets a pull request pick the permissive one. The docs warn about exactly that, and I have seen the pull request.

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
      finalizers:
        - resources-finalizer.argocd.argoproj.io
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

`goTemplate: true` is what expands `{{.path.basenameNormalized}}`. Leave it out and the braces become the Application name, which I have committed more than once. The normalized form swaps out characters Kubernetes will not accept in a name.

Add a directory under `apps/payments/` and an Application appears on the next reconcile. Remove one and the Application object is deleted. What happens to the workload depends on the finalizer. With `resources-finalizer.argocd.argoproj.io` the Deployment goes with it, and without it the Deployment keeps running with nothing managing it. I set the finalizer deliberately, and I point the generator at a folder that holds only apps I am willing to lose.

I review the ApplicationSet file itself. Teams add directories. A change to `project` or `destination.server` on the template gets a real read.

How the generated Application orders its resources is [the sync note](./argo-cd-sync.md). What sits inside each directory is still [an Application](./argo-cd.md).
