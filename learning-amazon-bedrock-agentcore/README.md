# AgentCore for DevOps Engineers

A five-part series for engineers who already know how to ship containers to ECS and are now being handed an agent to deploy on Amazon Bedrock AgentCore.

## Who this is for

You've cut task definitions, wired ALBs to target groups, and debugged a service stuck at `PROVISIONING` more times than you'd like to admit. Somebody on your team just pointed at an Excalidraw board with boxes labeled `agentcore create` and `config_manifest` and said "we're doing this now." This series exists to get you from that whiteboard to a production runbook without wasting a week rediscovering things AWS already documented — just not in an order that maps to how you think.

This is not a Strands Agents tutorial or a prompt-engineering guide. It assumes you can already write the agent. It's about the operational half: what gets built, what gets provisioned, what can fail, and what you're accountable for once this thing is live.

## What AgentCore actually is, in one paragraph

AgentCore is a managed runtime for hosting agentic workloads — think of it as the ECS-to-Fargate relationship, but for agents instead of arbitrary containers. AWS provisions the compute, handles session isolation, and gives you a CLI that scaffolds a project, tests it locally, and deploys it via CDK-synthesized CloudFormation. You still own the agent code, the IAM boundary, the deployment pipeline, and the 3 AM page when it breaks. The managed part is narrower than people expect on first read, and Part 1 spends real time on exactly where that line sits.

## Series structure

| # | File | What it covers | You'll be able to |
|---|---|---|---|
| 1 | [01-agentcore-foundations.md](01-agentcore-foundations.md) | Core concepts, the ECS-to-AgentCore mental model, what's managed vs. what's yours | Explain AgentCore to your team without hand-waving |
| 2 | [02-agentcore-application-anatomy.md](02-agentcore-application-anatomy.md) | Project structure, `agentcore.json`, `aws-targets.json`, framework/protocol choices | Read a scaffolded project and know what every file does |
| 3 | [03-local-development-and-testing.md](03-local-development-and-testing.md) | `agentcore dev`, the agent inspector, local iteration loop, debugging patterns | Develop and test an agent entirely offline before touching AWS |
| 4 | [04-deployment-options.md](04-deployment-options.md) | CodeZip vs. Container builds, what `agentcore deploy` provisions, IAM boundaries | Choose a build strategy with numbers, not gut feel |
| 5 | [05-production-devops-readiness.md](05-production-devops-readiness.md) | CI/CD wiring, observability, rollback, drift, cost attribution, a real runbook | Run this in production without being the single point of failure |

## Prerequisites

- Comfort with ECS/Fargate deployments — this series builds on that vocabulary rather than starting from zero
- Python 3.10+ and basic familiarity with a Python agent framework (Strands is used in examples; the concepts transfer)
- An AWS sandbox account you're allowed to break things in — seriously, don't do your first `agentcore deploy` in prod
- Node.js 20+ (the AgentCore CLI ships as an npm package, which trips people up the first time)

## How to work through this

Each part has a lab section. Do them in a sandbox account, in order — Part 4's cost comparison depends on artifacts you built in Part 3, and Part 5's CI/CD pipeline assumes the manifest structure from Part 2. If you only have an afternoon, Parts 1 and 2 will get you through your first design review. If you're the one signing off on the production rollout, all five.

---

*Part of [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) — production-grade reference material for DevOps and cloud engineers.*
