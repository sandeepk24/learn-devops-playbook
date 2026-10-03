# Argo CD sync

Synced means the cluster matches git, after `ignoreDifferences`. Healthy means the resource's health check passed. I have shipped a CrashLoop that was Synced and Degraded, and I have stared at a green Synced badge while the pods were the previous digest because I was looking at the parent app-of-apps. I read the Application that owns the Deployment.

A sync applies in phases, and inside a phase it applies in waves. Lower wave numbers go first. The default wave is 0. Namespaces and other built-in kinds are ordered inside a wave, and that order is not a wait. A CRD and its CR in wave 0 still race. The CR's dry run fails because the CRD is not established. I put the CRD at `-1` and leave the CR at `0`. The next wave waits until the previous one is healthy.

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: widgets.payments.example.com
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
```

Two seconds between waves is the default delay. It is enough for the CRD to register on a quiet cluster and not enough when the API is slow. I raise `ARGOCD_SYNC_WAVE_DELAY` when the CR still lands before the CRD is servable. I do not paper over it with `SkipDryRunOnMissingResource` unless the CRD is genuinely owned by another controller and will appear on its own.

## Hooks

A Job in git, with no hook annotation, is a normal resource. The Job spec is immutable. The next sync cannot change the command, and the completed Job sits there. A PreSync hook runs before the manifests, and a failed PreSync fails the sync before the Deployment rolls. That is the migration I want when the new code cannot boot on the old schema.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: 123456789012.dkr.ecr.us-east-1.amazonaws.com/api@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
          command: ["./migrate"]
```

If I omit `hook-delete-policy`, Argo uses `BeforeHookCreation`. I set it anyway so the next reader sees why the previous Job disappears. `HookSucceeded` deletes it after a good sync and leaves a failed one for me to read. PostSync runs after the sync is applied and the resources are Healthy. I have put a smoke test there and watched it never start, because the new pods were not Ready and PostSync was waiting on purpose.

Hooks do not run on a selective sync of one resource. I have "synced just the Deployment" from the UI and skipped the migration. The full sync is the one that runs the hook.

## Fields another controller owns

`ignoreDifferences` changes the OutOfSync calculation. The apply still sends git's value unless `RespectIgnoreDifferences=true`. I ignored `/spec/replicas` on a Deployment the HPA manages, left the sync option off, and the next sync set replicas back to the number in git. The HPA corrected it. Argo synced again. The Deployment oscillated until I set both.

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      name: api
      jsonPointers:
        - /spec/replicas
  syncPolicy:
    syncOptions:
      - RespectIgnoreDifferences=true
```

The `name:` matters. Ignoring replicas on every Deployment in the Application hides a hand scale on the one the HPA does not own. On the first sync, with no live object yet, the git value is what gets created. RespectIgnoreDifferences applies on the update.

`ServerSideApply=true` is how I sync a manifest that does not fit in the `last-applied-configuration` annotation. The apply uses `--force-conflicts`. Argo takes the fields. I use it when the object is too large for client-side apply. I leave it off a resource where another controller is supposed to keep a field, because force-conflicts is Argo winning that argument on every sync.

`FailOnSharedResource=true` fails the sync when this Application tries to adopt an object another Application already owns. I turned it on after two apps rendered the same ConfigMap and the later sync was the one I had not reviewed.

## The image

The container image in git is the digest. A tag in the Deployment is a pointer, and selfHeal will put that pointer back every time someone tries to pin a digest from the command line. CI commits the digest into the gitops repo. Argo syncs the commit. An image updater that writes `latest` into the manifest is the tag problem with a controller attached. I have removed it. The bytes are [the digest note](./promote-the-image-digest.md). The allow list around this Application is [the project](./argo-cd-projects.md).
