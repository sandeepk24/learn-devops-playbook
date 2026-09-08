# Part 5: Production DevOps Readiness — CI/CD, Observability, and the 3 AM Runbook

## Where this part sits

Everything so far has been sandbox work — scaffold, run locally, deploy by hand, tear down. This part is about the gap between "I can deploy this" and "I'd stake my on-call rotation on this." That gap is CI/CD discipline, observability you actually wired up rather than assumed exists, a rollback strategy you've tested rather than hoped works, and a runbook that doesn't start with "page Sandeep."

## CI/CD: getting `deploy` off laptops

If `agentcore deploy` runs from a developer's machine today, that's fine for the sandbox lab in Part 4 and not fine for anything after that. No audit trail, no consistent credentials, no gate between "I think this is ready" and "this is live."

The pipeline shape, adapted from CI/CD you already run for ECS:

```yaml
# .github/workflows/agentcore-deploy.yml — illustrative, adapt to your actual CI
name: AgentCore Deploy

on:
  pull_request:
    paths: ["agentcore/**", "app/**"]
  push:
    branches: [main]
    paths: ["agentcore/**", "app/**"]

permissions:
  id-token: write   # required for OIDC role assumption — no long-lived keys
  contents: read

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: npm install -g @aws/agentcore
      - run: agentcore validate

  plan:
    needs: validate
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AGENTCORE_DEPLOYER_ROLE_ARN }}
          aws-region: us-west-2
      - run: agentcore deploy --plan   # posted as a PR comment for human review

  deploy:
    needs: validate
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production   # your existing environment-protection gate
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AGENTCORE_DEPLOYER_ROLE_ARN }}
          aws-region: us-west-2
      - run: agentcore deploy -y
```

Same shape translates directly to Bamboo if that's your existing pipeline tool — a validate stage, a plan stage gated on PR review, a deploy stage gated on branch and environment approval. The specific mechanics of pulling secrets and assuming roles will differ, but the three-stage structure (validate → plan-and-review → deploy) is the part worth keeping regardless of which CI system it runs in.

Three things this pipeline is doing that a laptop-run deploy can't:

1. **`agentcore validate` as a required check** catches schema errors before anyone burns a CDK synth cycle on them — cheap and fast, same reason you'd lint a task-def JSON before submitting it.
2. **`deploy --plan` on every PR, gated on human review** — this is your changeset review. Nobody should merge a change to `agentcore.json` without someone having read what it's about to provision, same discipline as any Terraform plan review.
3. **OIDC role assumption, not static credentials** — if you're already doing this for ECS deploys, reuse the same trust relationship pattern, just scoped to a distinct deployer role for AgentCore (see the IAM section in Part 4 — deployer role and execution role are different roles, and your CI secret should only ever hold the deployer role ARN).

## Environment promotion

`aws-targets.json` is your promotion mechanism, and endpoint qualifiers (`DEFAULT`, `DEV`, `PROD`) give you the blue/green-adjacent behavior you're used to from target group swaps. The pattern:

- Separate `aws-targets.json` values per environment — generated from a template at pipeline time, or maintained as environment-specific branches/overlays, not hand-edited before each prod push
- Deploy to a `DEV` qualifier first, smoke test against it, then promote to `PROD` — this is your canary-adjacent step, and it should be a distinct pipeline stage with its own gate, not a single deploy that goes straight to the qualifier your users actually hit
- Treat qualifier promotion the way you'd treat re-pointing an ALB listener to a new target group — it's the moment traffic actually shifts, and it deserves its own explicit approval step even if the underlying deploy already happened

## Rollback: what the unit actually is

This is where CodeZip vs. Container from Part 4 comes back with operational teeth. Your rollback unit is whatever you can pin and redeploy deterministically:

- **Container builds** roll back to an image digest — pin by digest, not tag, in whatever deploy record you keep, exactly like you already do (or should) for ECS task definitions.
- **CodeZip builds** roll back by redeploying a previous artifact version from S3 — make sure your pipeline retains prior zip artifacts with enough versioning that "redeploy the last known-good build" is a command, not an archaeology project.

Either way, the actual rollback mechanic is: redeploy the prior artifact against the same manifest version that shipped it, then re-run `agentcore deploy`. Test this in your sandbox before you need it in prod — "we have a rollback plan" that's never been executed is not a rollback plan, it's a guess.

## Observability: what to wire up before launch, not after

CloudWatch Transaction Search needs to be explicitly enabled — it is not on by default the way basic ECS Container Insights logging is. Do this in Part 4's sandbox, not for the first time during your first production incident.

What to actually capture per invocation:

- **Trace ID correlation across the full path** — frontend request → agent invocation → tool calls → model calls. If your platform already has this pattern from other services (and per your platform's compliance audit pipeline architecture, distributed event tracing is a pattern you've built before), extend the same trace ID propagation into the agent invocation rather than inventing a second correlation scheme.
- **Token counts and per-invocation cost** — this is the metric ECS never made you think about. A single agent invocation can fan out into several model calls depending on tool-calling depth, and your cost per request is not fixed the way a Fargate task's CPU-second cost is. Emit this as a metric from day one; retrofitting cost attribution after a surprise bill is a bad way to learn this lesson.
- **Tool-call spans** — which tools were called, how long each took, whether they errored. This is your equivalent of downstream dependency latency in a traditional service — the same instinct that makes you track your database call latency in a normal API applies here, just aimed at tool invocations instead.
- **Proxy signals for quality, not just availability** — "the agent returned HTTP 200" tells you nothing about whether the answer was any good. Decide what you can cheaply measure as a quality proxy (tool-call success rate, conversation length before user disengagement, explicit thumbs-down if your frontend captures it) and alert on that too, not just on 5xx rates.

## Drift: the thing that will bite you if you don't decide this now

Revisit the open question from your team's design review: what happens when `manifest_instance` (tools, skills) gets edited post-deploy, outside the normal `agentcore.json` → `deploy` flow? If your platform allows that path, you now have two sources of truth, and the manifest genuinely stops being authoritative the moment someone uses the other one.

The clean answer, and the one worth pushing for in your next review: **all changes flow through the manifest and the pipeline, full stop.** If there's a legitimate operational need for fast post-deploy edits (an incident requiring an immediate tool disable, say), build that as an explicit, logged, reconciled-back-into-the-manifest emergency path — not a quietly-tolerated side door. The moment "editable post-deploy" becomes "and nobody updates the manifest afterward," you've lost the property that made this whole model appealing over hand-managed ECS services in the first place.

## Model version pinning

Decide explicitly whether your `--model-provider Bedrock` configuration floats to the latest model version or pins to a specific one. Floating means your agent's behavior can shift under you with no code change and no deploy — the AI-equivalent of a base image with no version pin silently getting a security patch that changes behavior. Pin the model version in your manifest, and treat a model version bump as a deliberate, tested, deployed change — same rigor you'd apply to bumping a base image.

## The runbook

This is the artifact your on-call rotation actually needs. Adapt it, but don't skip building it.

**Agent is returning errors or timing out:**
1. `agentcore status` — confirm the Runtime and any Memory/Gateway resources show healthy
2. `agentcore logs` — tail live logs for the actual exception
3. `agentcore traces list` — find the specific failing invocation, inspect the trace for where in the tool-call chain it broke
4. Check CloudWatch for the execution role's downstream call failures (Bedrock throttling, tool endpoint failures) before assuming it's agent code

**Agent is slow (high latency, not errors):**
1. Check whether this correlates with a cold-start pattern (traffic resuming after a quiet period) versus sustained load — the fix is different for each
2. Check tool-call span durations in traces — a slow downstream tool will look like agent latency if you're not decomposing the trace
3. If on Container build type, confirm this isn't an image-pull-related cold start before chasing agent logic

**Suspected bad deploy:**
1. Confirm via `agentcore status` and the CloudFormation stack's event history what actually changed
2. Roll back per the rollback section above — redeploy the prior artifact against its known-good manifest version
3. Do not hotfix directly against the deployed resource — fix goes through the manifest and the pipeline, even under incident pressure, or you've just created the drift problem described above during the worst possible moment to introduce it

**Cost spike:**
1. Check token-count metrics per invocation for anomalies — a tool-calling loop that isn't converging (Part 3's failure mode) will show up here before it shows up as a user complaint
2. Correlate against traffic volume — rule out "we just have more legitimate traffic" before treating it as a bug

## Closing checklist before your first real production deploy

- [ ] CI pipeline runs `validate` and `deploy --plan` on every PR touching `agentcore/`
- [ ] Deployer role and execution role are distinct, both least-privilege, both reviewed
- [ ] Rollback has been executed at least once in a non-production environment
- [ ] CloudWatch Transaction Search is enabled and trace correlation is verified end-to-end
- [ ] Token/cost metrics are emitting and someone owns the dashboard
- [ ] Model version is explicitly pinned in the manifest
- [ ] There is one documented, agreed answer to "how do post-deploy manifest edits happen" — and it isn't "ask around in Slack"
- [ ] The runbook above (or your team's version of it) is somewhere your on-call rotation will actually find it at 3 AM

That last one matters more than it sounds. A correct architecture with no runbook is still a bad night for whoever's holding the pager.

---

*Part of the [AgentCore for DevOps Engineers](README.md) series — [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook).*
