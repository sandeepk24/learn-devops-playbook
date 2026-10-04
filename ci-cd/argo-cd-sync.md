# Argo CD sync

Synced is not Healthy.

Synced means the cluster matches git, after `ignoreDifferences`. Healthy means the resource's health check passed. I have shipped a CrashLoop that was Synced and Degraded at the same time, and I once stared at a green badge while the pods ran the previous digest, because I was reading the parent app-of-apps instead of the Application that owned the Deployment.

A sync applies in phases, and inside a phase it applies in waves. Lower numbers go first, and the default is 0. Inside a wave, Argo orders built-in kinds sensibly, but ordering is not waiting. A CRD and its custom resource in the same wave still race, and the custom resource fails its dry run because the CRD is not established yet. So the CRD goes at `-1` and the custom resource stays at `0`. Argo holds each wave until the previous one is healthy.

```yaml
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: widgets.payments.example.com
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
```

The pause between waves is two seconds by default. Enough on a quiet cluster. Not enough when the API server is slow, and then the custom resource still lands before the CRD is servable. I raise `ARGOCD_SYNC_WAVE_DELAY` in that case. I leave `SkipDryRunOnMissingResource` alone unless another controller really does create the CRD on its own schedule.

## Hooks

A Job in git without a hook annotation is an ordinary resource. Job specs are immutable, so the next sync cannot change the command, and the finished Job just sits there.

A PreSync hook runs before the manifests are applied. If it fails, the sync stops before the Deployment rolls. That is the migration I want when the new code cannot boot on the old schema.

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

Omit the delete policy and Argo assumes `BeforeHookCreation` anyway. I write it down so the next reader knows why last time's Job vanishes. `HookSucceeded` clears the Job after a good sync and leaves a failed one behind for me to read.

PostSync runs after everything is applied and Healthy. I once put a smoke test there and watched it never start. The new pods were not Ready, and PostSync was waiting for them on purpose.

Hooks do not run on a selective sync. I have synced "just the Deployment" from the UI and skipped the migration without realizing it. Run the full sync.

## Fields another controller owns

`ignoreDifferences` changes the OutOfSync calculation and nothing else. The apply still sends git's value unless `RespectIgnoreDifferences=true` is set.

I learned that on an HPA. I ignored `/spec/replicas`, left the sync option off, and the next sync dropped replicas back to the number in git. The HPA corrected it. Argo synced again. They kept this up until I set both.

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

Keep the `name:`. Ignore replicas on every Deployment in the Application and you hide a hand-scale on the one the HPA does not manage. And on a first sync, with no live object to respect, git's value is what gets created. The option only matters on updates.

`ServerSideApply=true` is for manifests too large for the `last-applied-configuration` annotation. It applies with `--force-conflicts`, so Argo takes the fields. Fine for an object I own. A bad idea on a resource where another controller is meant to keep a field, because Argo wins that argument on every sync.

`FailOnSharedResource=true` fails the sync when this Application tries to adopt an object another Application already owns. I turned it on after two apps rendered the same ConfigMap and the unreviewed one synced last.

## The image

The image in git is a digest.

A tag in the Deployment is a pointer, and selfHeal will put that pointer back every time someone pins a digest from a terminal. CI commits the digest into the gitops repo and Argo syncs the commit. An image updater that writes `latest` into the manifest is the tag problem again with a controller attached, and I have removed it more than once.

The reasoning for the bytes is in [the digest note](./promote-the-image-digest.md). The allow list around this Application is [the project](./argo-cd-projects.md).
