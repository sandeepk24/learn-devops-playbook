# Part 2: Application Anatomy — Reading a Scaffolded Project Like You'd Read a Task Definition

## Start here, not in the docs

The fastest way to actually learn this is backward from what you already do: when you inherit an ECS service, the first thing you do is pull the task definition and read it top to bottom before touching anything. Do the same thing here. Scaffold a throwaway project and read every file before you write a line of agent logic.

```bash
npm install -g @aws/agentcore
agentcore create --name LearningAgent --defaults
cd LearningAgent
```

You get this:

```
LearningAgent/
  agentcore/
    agentcore.json        # Project and agent configuration
    aws-targets.json       # AWS account and region targets
    .env.local             # Local environment variables (gitignored)
  app/
    LearningAgent/
      main.py              # Agent entrypoint
      pyproject.toml        # Python dependencies
  README.md
```

Five files that matter. Let's take them in the order you'd actually need to understand them.

## `agentcore.json` — your task definition equivalent

This is the file that answers "what is this agent and how is it built." It's the closest analog to a task definition you have, and it's the file your CI pipeline will validate before every deploy (`agentcore validate` — run this in a pre-deploy CI step exactly like you'd run `aws ecs describe-task-definition --query` sanity checks today).

It's generated from the flags you pass to `create`, and this matters because **most of those flags are expensive to change after the fact**:

| Flag | Options | How expensive to change later |
|---|---|---|
| `--framework` | `Strands`, `LangChain_LangGraph`, `GoogleADK`, `OpenAIAgents` | High — this shapes your entire `main.py` and dependency tree |
| `--protocol` | `HTTP` (default), `MCP`, `A2A` | High — changes the entrypoint contract |
| `--build` | `CodeZip` (default), `Container` | Medium — Part 4 covers the tradeoff in depth |
| `--model-provider` | `Bedrock`, `Anthropic`, `OpenAI`, `Gemini` | Low — mostly a client swap, some auth plumbing |
| `--memory` | `none`, `shortTerm`, `longAndShortTerm` | Low — add later with `agentcore add memory` |

The practical takeaway: don't run `agentcore create` interactively on autopilot and figure out framework and protocol as you go. Decide those two in the design review, before anyone types a command. Everything else can be bolted on incrementally, which is a genuinely different risk profile than a Dockerfile where almost every choice is cheap to revisit.

## `aws-targets.json` — your account/region map

This is where account and region targeting lives, separated cleanly from application config. If you've ever had a bad afternoon because a Terraform workspace pointed at the wrong AWS profile, you'll appreciate why this is its own file instead of buried inside `agentcore.json`. It's also the file that survives `agentcore remove all` — that command resets your resource config but deliberately preserves account targeting and deployment state, so a teardown doesn't also make you re-figure-out which account you're supposed to be pointed at.

This is your natural per-environment file. A dev target and a prod target should be two distinct `aws-targets.json` values (via separate branches, separate CI variables, or a templated generation step) — not one file with a manually-edited region string before every prod push. Get this wrong once and you'll deploy to the wrong account the way everyone eventually deploys to the wrong ECS cluster once.

## `.env.local` — exactly what it looks like

Gitignored local environment variables. If your model provider needs an API key outside Bedrock's IAM-based auth (Anthropic direct, OpenAI, Gemini), it lives here for local dev. Same discipline as any `.env` file you already avoid committing — nothing new to learn, just don't get complacent because the rest of this tooling feels unfamiliar.

## `app/<Name>/main.py` — the entrypoint

This is your application code, using whatever framework you chose. Two things worth knowing before you write your first line:

**The HTTP protocol contract is fixed.** AgentCore Runtime expects your app to conform to a specific HTTP contract regardless of framework — this is what lets AWS host arbitrary frameworks (Strands, LangGraph, LangChain, Google ADK, OpenAI Agents, or bring-your-own) behind one runtime. You're not writing a raw Flask app and hoping for the best; the framework's AgentCore integration handles contract compliance for you, but it's worth reading the HTTP protocol contract doc once so you know what's happening under your framework's abstraction — the same reason you'd read the ALB health check contract once even though your framework handles the `/health` route for you.

**Payment and Gateway integrations extend this file, not `agentcore.json`.** If your agent needs to call external tools or handle payments, those show up as code-level plugin configuration in `main.py`, provisioned on deploy — not as a separate manifest.

## `pyproject.toml` — dependency management, same as always

Standard Python dependency management. The one AgentCore-specific detail: whatever you pin here travels with your build artifact whether you chose CodeZip or Container, so this file is doing double duty as both your local dev environment spec and part of your deployed artifact's dependency closure. Lock your versions here with the same discipline you'd apply to a `requirements.txt` baked into a production Docker image — because that's effectively what this is, even in the CodeZip path where there's no Dockerfile in sight.

## Adding capability later without re-scaffolding

Once the base project exists, you extend it additively rather than re-running `create`:

```bash
# A second agent in the same project
agentcore add agent --name SecondAgent --language Python --framework Strands --model-provider Bedrock

# Conversational memory
agentcore add memory --name MyMemory --strategies SEMANTIC

# A credential for an external service your agent's tools call
agentcore add credential --name MyApiKey --type api-key --api-key your-api-key
```

Each of these mutates `agentcore.json` and does not provision anything by itself — you still run `agentcore deploy` afterward for the new resources to actually appear in AWS. That's the declarative-config discipline from Part 1 showing up again: the file is the intent, `deploy` is the reconciliation.

## Lab: read before you write

Before Part 3, do this:

1. Scaffold a project with `--framework Strands --protocol HTTP --build CodeZip --memory none`.
2. Open `agentcore.json` and `aws-targets.json` side by side. Identify every field. If a field's purpose isn't obvious from its name, that's a note for your team's internal wiki — you will get asked about it in six months by someone who wasn't in this design review.
3. Run `agentcore validate`. Deliberately break a field (typo the region, corrupt a bracket) and read the error. This is the fastest way to learn what the schema actually enforces versus what's just convention.

## What's next

Part 3 is where you stop reading config and start running the agent — the local dev loop, the agent inspector, and how to debug an agent without deploying anything to AWS.

---

*Part of the [AgentCore for DevOps Engineers](README.md) series — [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook).*
