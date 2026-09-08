# The kubectl Commands That Actually Get Used in Production

If you sat down and counted, you'd probably find that any given engineer uses maybe fifteen `kubectl` subcommands regularly, out of the hundred-plus that exist. The rest are documentation trivia. This is about that core fifteen — the ones that show up so often they end up as shell aliases within someone's first month on a Kubernetes-heavy team.

## describe Is Your First Move, Not logs

New engineers instinctively reach for `kubectl logs` the second something's wrong with a pod. That's usually the wrong first move. If a pod isn't even running yet — stuck in `Pending`, or crash-looping before it emits anything useful — there are no logs worth reading. `describe` is where the actual story lives.

```bash
kubectl describe pod my-app-7d9f8c6b5-xk2p9 -n production
```

The Events section at the bottom is doing most of the work here. That's where you'll see things like `FailedScheduling` because no node has enough memory, or `ImagePullBackOff` because someone forgot to push the tag your manifest is pointing to. On a team running a large multi-tenant cluster, resource-pressure scheduling failures are one of the most common pages, and they're invisible in `logs` because the container never got a chance to start.

## Getting Comfortable With -o wide and -o yaml

The default `kubectl get pods` output hides almost everything useful. Two flags fix that depending on what you need:

```bash
# Which node is this actually running on, and what's its IP?
kubectl get pods -o wide -n production

# Give me the entire resolved spec, including defaults the manifest didn't set
kubectl get pod my-app-7d9f8c6b5-xk2p9 -o yaml -n production
```

`-o wide` answers "is this pod on the node that's having disk pressure issues" without a second command. `-o yaml` matters because Kubernetes fills in a lot of defaults you never wrote — resource requests, security contexts, tolerations — and during an incident, assuming your manifest is the full story is a good way to miss the actual cause.

## Exec, But With a Habit of Checking First

`kubectl exec` is essential for live debugging, but it's worth building the habit of checking what's already running before you start poking around, especially in a shared cluster where other people's changes might be the actual cause.

```bash
kubectl exec -it my-app-7d9f8c6b5-xk2p9 -n production -- /bin/sh -c "ps aux"
```

At companies running large fleets of microservices, direct exec access into production pods is often locked down or logged for audit reasons, and for good reason — it's an easy way to accidentally make a change that never makes it into version control. The habit worth building is: exec to *observe*, not to *fix*. If a fix is needed, it goes through a deploy.

## rollout: The Command That Saves You From Panic

When a deploy goes bad, the instinct is to start troubleshooting the new version in place. Often the better first move is simply rolling back and troubleshooting calmly afterward, with the pressure off.

```bash
# What actually changed, and when?
kubectl rollout history deployment/my-app -n production

# Roll back to the previous known-good revision
kubectl rollout undo deployment/my-app -n production

# Watch it happen instead of guessing
kubectl rollout status deployment/my-app -n production
```

This is a genuinely underused pattern. Rolling back first and investigating second, rather than the other way around, is how a lot of experienced on-call engineers keep incidents short — the goal during an active incident is to restore service, not to fully understand root cause in the moment.

## A Python Wrapper Worth Having

Most teams eventually write something like this, because typing the same three-command sequence during every incident gets old fast:

```python
import subprocess
import sys

def get_crashing_pods(namespace="production"):
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", namespace,
         "--field-selector=status.phase!=Running", "-o", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Failed to query cluster:", result.stderr, file=sys.stderr)
        return []
    import json
    data = json.loads(result.stdout)
    return [pod["metadata"]["name"] for pod in data.get("items", [])]

if __name__ == "__main__":
    ns = sys.argv[1] if len(sys.argv) > 1 else "production"
    for pod in get_crashing_pods(ns):
        print(f"Not running: {pod}")
```

Small, unglamorous, and exactly the kind of script that ends up saving five minutes per incident, which adds up fast across a team fielding several pages a week.

## The Underlying Point

None of these commands are exotic. What separates an engineer who's fast in an incident from one who's slow usually isn't knowledge of obscure flags — it's having internalized *which* of these fifteen commands answers the question you actually have, without needing to think about it. That only comes from running them enough times that the choice becomes automatic.
