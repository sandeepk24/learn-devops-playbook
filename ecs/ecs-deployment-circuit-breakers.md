# ECS Deployment Circuit Breakers: What They Are and Why You Want Them

*Notes from AWS "Containers from the Couch" — Adam Keller walks Brent through deployment circuit breakers end to end.*

---

## So what's a deployment circuit breaker, anyway?

First thing to clear up: this isn't the service-mesh circuit breaker you might be thinking of. It's not about stopping traffic to a failing downstream service. It's scheduler logic. It lives in the ECS control plane, and its job is to detect when a deployment is going sideways — then optionally roll it back automatically.

Here's the problem it solves. Before this existed, a broken deployment would just... flap. Your container starts, crashes immediately, ECS replaces it, the replacement crashes, and you're stuck in this loop. CloudFormation can't see inside containers, so it has no idea anything's wrong. It just sits there waiting for its timeout — sometimes hours — before it finally gives up and marks the stack as failed.

That's painful enough when you're watching the console. But in an automated pipeline? Teams were building their own remediation logic, or they'd get paged at 2am to fix something manually. Not great.

The circuit breaker moves that failure detection into ECS itself. ECS can now notice that your tasks keep dying, mark the deployment as failed, and — if you turn on rollback — automatically flip back to the last working task definition. The whole time, your old tasks keep serving traffic. That's the key part.

---

## Where does this logic actually live?

This is important. The detection lives in the ECS control plane — not in your deployment tool. So it doesn't matter whether you're deploying with the CLI, the SDK, Terraform, CloudFormation, CDK, or some custom tooling you built yourself. The circuit breaker works the same way regardless.

It also works with both EC2-backed tasks and Fargate. No difference there.

And here's something that trips people up: there's nothing to upgrade. The ECS control plane is managed by AWS, unversioned from your perspective. The feature just... exists. The only thing with versions is the ECS agent running on your EC2 instances, and that's a separate concern.

---

## How does ECS decide when to trip the breaker?

Here's the thing — you don't configure a threshold like "roll back after 5 failures." ECS calculates the threshold based on your service's desired task count. It's managed for you.

Adam mentioned this was a first iteration when he recorded the demo, and acknowledged some edge cases might not get caught. But for the common case of "my new image is completely broken and crashes on startup," it works well.

---

## Quick refresher: task definitions vs services

If you're coming from Kubernetes, here's the mental mapping.

A **task definition** is basically your pod spec. It's the JSON that describes your containers — the image, ports, CPU and memory, environment variables, and importantly, the execution role. That execution role is what lets ECS pull your image from ECR. Without it, you get cryptic "image not found" errors even when the image definitely exists.

A **service** is what maintains your desired state. You say "I want 5 tasks running," and ECS makes sure there are always 5. Same concept as replicas in Kubernetes.

---

## Rolling deployment settings you need to understand

Two numbers control everything here:

**`minimumHealthyPercent: 100`** — This means ECS has to start new tasks *before* it stops old ones. You never dip below your desired count.

**`maximumPercent: 200`** — This allows double the tasks during rollout. So if you're going from 5 old tasks to 5 new ones, you might briefly have 10 running while the transition happens.

Together, these give you the "add before remove" behavior. Old tasks keep serving traffic until new ones are proven healthy. This is different from the default behavior where ECS might stop some old tasks first to make room.

---

## How to enable the circuit breaker

Here's the actual config:

```json
"deploymentCircuitBreaker": {
  "enable": true,
  "rollback": true
}
```

Two things to know:

1. **It's off by default.** You have to explicitly enable it.
2. **Rollback is a separate flag.** You can enable detection without automatic rollback if you want to handle failures yourself.

Adam's recommendation: unless you've already built custom rollback logic that you prefer, just turn rollback on. Let ECS handle it.

---

## New deployment observability

Once you enable the circuit breaker, deployments expose some new fields that are really useful:

- **`rolloutState`** — Can be `IN_PROGRESS`, `COMPLETED`, or `FAILED`
- **`failedTasks`** — A count of how many tasks have failed during this deployment

When a rollback happens, watch what ECS does: the PRIMARY deployment flips back to the previous task definition. You'll see it in the console — the task definition revision number changes.

If you've got rollback disabled, a failed deployment just stays in the `FAILED` state. ECS stops trying to push the broken version, but it doesn't automatically go back. You deal with it however you want.

---

## EventBridge integration

Deployment state changes get emitted to EventBridge. So you can:

- Trigger SNS alerts when a deployment fails
- Kick off Lambda automation for custom handling
- Feed deployment events into your observability pipeline

The service events tell the whole story in sequence: tasks failed to start, rolling back, rollback successful, steady state reached. Good stuff for your dashboards.

---

## Load balancers: nothing changes

If you're using an ALB or NLB, the circuit breaker just works. No configuration changes needed on the load balancer side.

One thing worth noting: unhealthy new tasks never get registered into the target group. So even while ECS is detecting failures and deciding whether to roll back, your load balancer is only sending traffic to healthy tasks — which are your old ones.

---

## IaC support

At the time Adam recorded the demo, Terraform and CloudFormation support was still pending. But that was a while ago — both support it now. You'll find `deployment_circuit_breaker` blocks in Terraform and the equivalent in CloudFormation templates.
