# ECS Deployment Circuit Breakers: What They Are and Why You Want Them

*Notes from AWS "Containers from the Couch" — Adam Keller walks Brent through deployment circuit breakers end to end.*

---

## So what's a deployment circuit breaker, anyway?

First thing to clear up: this isn't the service-mesh circuit breaker you might be thinking of. It's not about stopping traffic to a failing downstream service. It's scheduler logic. It lives in the ECS control plane, and its job is to detect when a deployment is going sideways — then optionally roll it back automatically.

Here's the problem it solves. Before this existed, a broken deployment would just... flap. Your container starts, crashes immediately, ECS replaces it, the replacement crashes, and you're stuck in this loop. CloudFormation can't see inside containers, so it has no idea anything's wrong. It just sits there waiting for its timeout — sometimes hours — before it finally gives up and marks the stack as failed.

That's painful enough when you're watching the console. But in an automated pipeline? Teams were building their own remediation logic, or they'd get paged at 2am to fix something manually. Not great.

The circuit breaker moves that failure detection into ECS itself. ECS can now notice that your tasks keep dying, mark the deployment as failed, and — if you turn on rollback — automatically flip back to the last working task definition. The whole time, your old tasks keep serving traffic. That's the key part.
