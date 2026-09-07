# Part 1: AgentCore Foundations — What Actually Changes When You Come From ECS

## The problem with how AgentCore gets introduced

Most AgentCore material starts with "agents are the future" and works backward into the CLI. If you're the engineer who has to actually run this in production, that ordering is useless to you. You don't need convincing that agents matter — someone already decided that. You need to know what you're accountable for on Tuesday when the on-call pager goes off.

So this part starts from the thing you already know — ECS — and maps forward.

## The core substitution

Here's the honest version of what changed:

```
ECS World                              AgentCore World
──────────                             ───────────────
Task Definition          ──────────►   agentcore.json
ECS Service               ──────────►   AgentCore Runtime (managed)
ALB + Target Group        ──────────►   InvokeAgentRuntime API
Blue/green target groups  ──────────►   Endpoint qualifiers (DEFAULT/DEV/PROD)
ECR image                 ──────────►   ECR image OR S3 zip (build-type dependent)
Fargate platform version  ──────────►   Managed runtime, ARM64 only
Task role / execution role──────────►   Same split, different provisioning path
Sticky sessions (ALB)     ──────────►   Built-in session isolation (native)
CloudWatch Container      ──────────►   CloudWatch Transaction Search +
  Insights                              GenAI Observability
Manual autoscaling policy ──────────►   No knob — AWS manages it
```

Two rows deserve a callout because they're where new engineers get burned.

**"Deployment" now means something narrower.** In ECS, a deployment is you: register a task def revision, update the service, watch the rolling replacement, maybe roll back by re-pointing to the previous revision. In AgentCore, `agentcore deploy` hands the packaging and provisioning to CDK/CloudFormation. You still write the pipeline that calls it, but the mechanics of "how does a new version become live" are AWS's implementation, not yours. This is good — one less category of 3 AM bug — but it means the debugging skills you built for "why is my ECS service stuck at 1/2 healthy tasks" don't transfer directly. You'll be reading CloudFormation events instead.

**You lose autoscaling as a lever, and you should be glad.** No target tracking policies, no scheduled scaling, no min/max task count tuning. AgentCore's runtime is serverless in the way Lambda is serverless — you don't provision capacity, you pay per invocation. If your team's current AgentCore-based platform (see the DynamoDB on-demand decision from your production agentic AI work) already treats traffic as spiky and unpredictable, this is a feature, not a gap. The tradeoff is you also lose the ability to pre-warm capacity ahead of a known traffic spike — cold starts are AWS's problem to optimize, not yours to configure.

## What's actually managed vs. what's still yours

This is the single most important table in the series, because it's the one people get wrong in design reviews.

| Concern | Managed by AWS | Still yours |
|---|---|---|
| Compute provisioning, scaling | ✅ | |
| Session isolation | ✅ | |
| Cold start optimization | ✅ (bounded) | Partially — build type affects this |
| Container/artifact build | | ✅ (you choose CodeZip vs. Container) |
| IAM role design | | ✅ |
| Agent code correctness | | ✅ |
| Tool/skill permissions | | ✅ |
| CI/CD pipeline | | ✅ |
| Observability instrumentation | Infra provided | ✅ (you wire it) |
| Cost per invocation | | ✅ (you can architect it wastefully) |
| Model selection & version pinning | | ✅ |
| Secrets management | Storage provided (Secrets Manager) | ✅ (rotation, injection) |
| Rollback strategy | Mechanism provided (qualifiers) | ✅ (you decide when/how) |
| Manifest as source of truth | | ✅ — and this is the sharpest edge |

That last row is worth sitting with. `agentcore.json` and `aws-targets.json` are declarative — running `agentcore deploy` again reconciles AWS to match the file, and `agentcore remove all` followed by `deploy` tears down what you removed from config. That's a genuinely nice property. It's also a trap if your team's process allows editing deployed resources out-of-band (say, hand-tweaking a tool definition post-deploy, which is exactly the `manifest_instance <br> (editable post-deploy)` box that shows up on a lot of first-draft AgentCore architecture diagrams). The moment you allow an edit path that doesn't flow back through the manifest, you've reintroduced the drift problem ECS/Terraform taught you to hate — just with a different file extension.

## The four services, briefly

AgentCore isn't one thing — it's a family of modular services you opt into. You don't need all of them for a first deployment, but you need to know they exist so you're not surprised when a teammate mentions one.

- **Runtime** — the actual hosting layer. Serverless, session-isolated, purpose-built for agent workloads. This is the part that replaces your ECS service.
- **Gateway** — turns existing APIs, Lambda functions, or services into agent-callable tools without you writing a bespoke tool-calling layer for each one.
- **Memory** — short-term (conversation-scoped) and long-term (cross-session) memory, provisioned declaratively (`--memory none | shortTerm | longAndShortTerm`). Long-term memory takes a few minutes to provision after deploy — don't panic if `agentcore status` shows it as pending immediately after a fresh deploy.
- **Identity** — inbound auth (who can invoke your agent) and outbound auth (what your agent can call on a user's behalf), including OAuth flows. This is where the IAM-adjacent thinking from ECS task roles gets more nuanced, because now you're reasoning about the agent's identity *and* the end user's delegated identity.

You'll meet Runtime and Identity in every deployment. Gateway and Memory are opt-in — add them later with `agentcore add memory` / `agentcore add credential` rather than front-loading complexity into your first project.

## When AgentCore is the wrong tool

Worth saying plainly, because "just use the new thing" is not an engineering decision: if what you're building is a standard request/response API with no need for conversational state, tool orchestration, or LLM reasoning loops, ECS is still the right answer and will be cheaper to operate. AgentCore earns its complexity when the workload is genuinely agentic — multi-turn, tool-calling, session-aware. If your team is introducing it for a workload that's really just "call an LLM once and return," push back in the design review before you build five parts of tooling around it.

## What's next

Part 2 opens the project AgentCore scaffolds for you and goes file by file — what `agentcore.json` controls, what `aws-targets.json` controls, and which of the CLI's flags at `create` time you cannot cheaply change later.

---

*Part of the [AgentCore for DevOps Engineers](README.md) series — [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook).*
