# Part 4: Deployment Options — CodeZip vs. Container, and What `deploy` Actually Touches

## The decision you're really making

Part 2 flagged `--build` as medium-cost to change later. Here's the full argument, because "which one should we pick" is the question your design review will actually spend time on, and it deserves more than a coin flip.

## CodeZip vs. Container, side by side

| | CodeZip (default) | Container |
|---|---|---|
| Requires Docker | No | Yes |
| Packaging | Zip archive, uploaded to S3 | Docker image, pushed to ECR |
| Custom system dependencies | No — Python deps only, via `pyproject.toml` | Yes — any OS package, custom base image |
| Build speed | Faster | Slower (image build + push) |
| Cold start | Generally faster | Generally slower, more variable |
| Reproducibility | Depends on lockfile discipline | Stronger — image digest is the reproducibility unit |
| Base image patching cadence | AWS's problem | Yours — you own the base image lifecycle |
| Image scanning / SBOM | Not your surface | Yours to wire in (ECR scanning, Trivy, whatever your org already runs on other ECR images) |
| Best fit | Pure-Python agents, no native deps, fastest iteration | Agents needing native libraries, specific runtimes, or matching an existing container security baseline |

## Why "how much overhead does Container add" is the wrong first question

If your team's whiteboard discussion left an open note asking specifically about containerization overhead, reframe it before answering: overhead in *what dimension* determines the answer, and conflating them is how these discussions go in circles.

- **Build-time overhead** — real, and it's the Docker build + ECR push cycle you already know from every other containerized service you run. If your CI already builds and pushes ECS images, this is marginal additional pipeline time, not new complexity.
- **Cold-start overhead** — also real, and less within your control. A Container-built agent has to pull and start a container image on invocation in a way a CodeZip deployment, which is closer to a managed function package, generally doesn't. If your agent is latency-sensitive and traffic is spiky (which, per your team's platform decisions elsewhere, it likely is), this is the dimension that actually matters for user experience.
- **Cognitive/process overhead** — the softest of the three, and honestly the one worth being most honest about. If your team already has mature container tooling — base image management, scanning gates, ECR lifecycle policies — Container adds close to zero new process. If you're picking Container specifically to get those things and you don't have them yet, you're not comparing build types, you're taking on a platform investment, and that's a different conversation than "which flag do we pass to `create`."

Practical recommendation: default to CodeZip unless you have a specific native dependency or a hard compliance requirement (mandatory base image scanning policy, for instance) that CodeZip can't satisfy. Reach for Container when you hit that wall, not preemptively because it feels more familiar.

The one non-negotiable either way: **AgentCore Runtime runs on ARM64 (Graviton)**. The CLI handles this automatically for both build types, but if you're hand-building a Container image outside the CLI's build step, or importing an existing image built for x86, it will not deploy. This is the single most common first-deploy failure for teams coming from an x86 ECS fleet — check your Dockerfile's base image architecture before you're debugging a cryptic deploy failure at the CDK layer.

## What `agentcore deploy` actually does

This is worth being precise about, because "it deploys to AWS" is not an operationally useful description and your first production incident review will need better than that.

```bash
agentcore deploy
```

In order:

1. Reads `agentcore/agentcore.json` and `agentcore/aws-targets.json`
2. Packages your agent code — zip to S3, or container to ECR, per your build type
3. Uses the **AWS CDK** to synthesize CloudFormation from that configuration
4. Deploys the CloudFormation stack, which creates or updates: IAM roles, the AgentCore Runtime resource, and any additional resources implied by what you've `add`ed (Memory, credentials, Gateway targets)

That third step is the one to internalize: **the actual infrastructure-as-code layer here is CDK, generated for you.** You are not writing raw CloudFormation, and you're not hand-authoring Terraform. If your org's existing IaC standard is Terraform, this is a real conversation to have early — CDK-generated CloudFormation stacks don't merge cleanly into a Terraform state story, and "we now have two IaC tools in this account" is the kind of decision that should be made explicitly, not discovered six months in when someone asks why `terraform plan` shows drift on resources it's never heard of.

**Preview before you commit:**

```bash
agentcore deploy --plan
```

This is your `terraform plan` / `aws cloudformation deploy --no-execute-changeset` equivalent. Wire this into CI as a required check on every PR that touches `agentcore/` — you want a human reading the diff of what's about to provision before it happens, exactly like you'd never let a task-def change merge without someone having seen the plan.

**Verbose output when something goes sideways:**

```bash
agentcore deploy -v
```

Shows resource-level CloudFormation events as they happen. This is where you'll actually diagnose failures — the CLI's default output summarizes; `-v` gives you the CloudFormation event stream, which is the same information you'd get watching a stack update in the console, just in your terminal.

## Reading the aftermath

```bash
agentcore status
```

Gives you a live dashboard of deployed resources — treat it the way you'd treat `aws ecs describe-services`, as your first stop before you check the logs. It's also where you confirm provisioning status for anything async, like long-term Memory, which can take a few minutes to come up even after the deploy command itself returns.

Where things physically live, for when you need to go spelunking in the console instead of the CLI:

| Resource | Console location |
|---|---|
| Agent logs | CloudWatch → Log groups → `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT` |
| The CloudFormation stack | CloudFormation → Stacks → search your project name |
| IAM role | IAM → Roles → search "BedrockAgentCore" |
| S3 build artifacts (CodeZip) | S3 → the CDK staging bucket |

## Tearing down cleanly

Because "how do we get rid of this" matters as much as "how do we stand it up," and it's where you validate that the manifest genuinely is your source of truth:

```bash
agentcore remove all   # resets agentcore.json, preserves aws-targets.json + deploy state
agentcore deploy       # detects the removal, tears down the corresponding AWS resources
```

Run this once in your sandbox, deliberately, before you ever run it for a real reason. Confirm what does and doesn't survive — this is the cheapest way to build accurate trust in the tool's declarative model instead of taking it on faith.

## IAM: what to actually scrutinize in review

Two distinct roles are in play here, and conflating them is a real risk, not a theoretical one:

- **The deployer identity** — whatever runs `agentcore deploy`, whether that's your laptop's credentials today or a CI role tomorrow. This needs CloudFormation, CDK bootstrap, and provisioning permissions. It should not be the same role your agent runs under.
- **The agent's execution role** — what the deployed Runtime actually assumes when it's invoked and doing its job: calling Bedrock, calling tools, reading Memory. This should be scoped to exactly what the agent needs, nothing more, and it's the role you should be reviewing line-by-line in the generated CloudFormation before your first production deploy.

If your team's manifest allows `manifest_instance` (tools/skills) to be edited post-deploy, treat every addition there as a potential IAM grant, not just a config tweak — a new tool can imply a new permission, and if that flows through `agentcore deploy` automatically, your review gate needs to be `deploy --plan` in CI, not a human remembering to check.

## Lab

1. Build the same agent from Part 3 twice — once with `--build CodeZip`, once with `--build Container`. Deploy both to your sandbox.
2. Compare: total deploy time, cold-start latency on first invocation after a period of inactivity, and artifact size. Write the numbers down — this is what turns "Container feels heavier" into an actual answer for your team.
3. Run `agentcore deploy -v` on one of them and read the full CloudFormation event stream. Open the CloudFormation console for the same stack and find the generated template. Skim the IAM role resource specifically.
4. Tear one down with `remove all` → `deploy`, and confirm in the console that the resources are actually gone.

## What's next

Part 5 takes this out of your sandbox and into a real pipeline — CI/CD wiring, environment promotion, observability, drift prevention, and the runbook you'll actually want at 3 AM.

---

*Part of the [AgentCore for DevOps Engineers](README.md) series — [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook).*
