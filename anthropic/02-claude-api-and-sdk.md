# 02 — Claude API and SDK
## Messages API, Streaming, Multi-Turn Conversations, Agent SDK, Claude Code, and CLAUDE.md

> **Series:** Anthropic Fundamentals for DevOps Engineers → CCAR-F  
> **Exam Domains:** Domain 2 — Claude Code Configuration & Workflows (20%) | Domain 3 — Prompt Engineering & Structured Output (partial, 20%)  
> **Combined Weight:** ~24 questions out of 60

---

## What You'll Learn Here

This is the hands-on core of the series. The API is the foundation everything else sits on — agents, tools, MCP servers, Claude Code workflows — all of it starts with a `client.messages.create()` call. Once you understand the API deeply, the higher-level abstractions make sense. Skip it and you're memorizing patterns without understanding why they work.

By the end of this article you'll be comfortable with the full Messages API including streaming and multi-turn conversations, understand the Agent SDK's three-layer architecture and when to use it over raw API calls, know Claude Code's tool system and execution model, and master the CLAUDE.md configuration hierarchy that the exam tests repeatedly.

---

## Part 1 — The Messages API in Depth

### The Request Structure

You saw the basic call in file 01. Now let's pull it apart completely, because every field has exam implications.

```python
import anthropic

client = anthropic.Anthropic()  # Reads ANTHROPIC_API_KEY from environment

response = client.messages.create(
    # Required fields
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[
        {"role": "user", "content": "Your message here"}
    ],

    # Optional but important
    system="You are a senior DevOps engineer...",  # System prompt
    temperature=1.0,          # Default. Range 0-1. Lower = more deterministic
    top_p=0.999,              # Nucleus sampling — rarely need to touch this
    stop_sequences=["\n\n"],  # Stop generation on these strings
    stream=False,             # Set True for streaming (covered below)
    metadata={"user_id": "eng-sandeep"},  # Passed through, not used by model
)
```

The `system` parameter sits outside the `messages` array deliberately. It's a persistent instruction layer that stays constant across the entire conversation. Think of it as your Terraform variable file — it defines the operating context before any user input arrives.

### The content Field — More Than Just Strings

Most engineers start by passing plain strings as message content. That works. But the exam tests the full content block structure, and you'll need it for tool results and multi-modal inputs.

```python
# Plain string — works fine for simple cases
messages=[{"role": "user", "content": "What's wrong with this pod?"}]

# Content block array — required for tool results, images, documents
messages=[
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "Analyze this ECS task definition for security issues:"
            },
            {
                "type": "document",
                "source": {
                    "type": "text",
                    "media_type": "text/plain",
                    "data": task_definition_json
                }
            }
        ]
    }
]
```

Content block types you need to know for the exam:
- `text` — plain text
- `image` — base64 or URL-referenced image
- `document` — text documents, PDFs
- `tool_use` — model requesting a tool call (appears in *responses*)
- `tool_result` — your tool's response (appears in *requests*)

> **📝 Exam Tip:** Tool results must be passed back as `tool_result` content blocks in a subsequent `user` message. The model cannot continue an agentic loop without receiving tool results. This is one of the most tested patterns in Domain 1 and Domain 4.

---

### Streaming — When It Matters and How to Handle It

For short responses, standard API calls are fine. For long outputs — code generation, document analysis, multi-step reasoning — streaming lets you show progress and handle timeouts gracefully. In a CI/CD pipeline context, streaming also lets you parse partial output as it arrives.

```python
import anthropic

client = anthropic.Anthropic()

# Streaming a long DevOps task — e.g. generating an IaC review
with client.messages.stream(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    system="You are a senior Terraform reviewer. Be thorough.",
    messages=[
        {
            "role": "user",
            "content": f"Review this Terraform module for security and best-practice issues:\n\n{terraform_code}"
        }
    ]
) as stream:
    # Stream text as it arrives — good for CLI tools
    for text in stream.text_stream:
        print(text, end="", flush=True)

    # After streaming completes, get the full response object
    final_message = stream.get_final_message()
    print(f"\n\nStop reason: {final_message.stop_reason}")
    print(f"Total tokens: {final_message.usage.input_tokens + final_message.usage.output_tokens}")
```

The streaming context manager handles connection lifecycle automatically. You get token-by-token text through `stream.text_stream`, and the full `Message` object is available after the stream closes via `get_final_message()`.

---

### Multi-Turn Conversations — Building Stateful Interactions

Here's something that trips up engineers coming from stateless HTTP APIs: Claude has no memory between calls. Every `messages.create()` is independent. You maintain conversation state by accumulating the message history and passing the full array on every call.

```python
import anthropic

client = anthropic.Anthropic()

def devops_assistant():
    """
    A stateful DevOps assistant that remembers context across turns.
    This is the foundational pattern for any conversational agent.
    """
    conversation_history = []

    system_prompt = """
    You are a senior DevOps engineer. Help diagnose infrastructure issues.
    Ask clarifying questions when needed. Be concise and technical.
    """

    print("DevOps Assistant (type 'exit' to quit)\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == "exit":
            break

        # Append the new user message to history
        conversation_history.append({
            "role": "user",
            "content": user_input
        })

        # Send the FULL history every time — this is how Claude "remembers"
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=conversation_history   # Full history, not just the latest message
        )

        assistant_message = response.content[0].text

        # Append the assistant's response to history too
        conversation_history.append({
            "role": "assistant",
            "content": assistant_message
        })

        print(f"\nAssistant: {assistant_message}\n")

        # Watch your context window — 1M tokens for Sonnet but costs add up
        total_tokens = sum(
            len(msg["content"].split()) * 1.3  # rough estimate
            for msg in conversation_history
        )
        if total_tokens > 50000:
            print("[Warning: conversation getting long — consider /compact]")


devops_assistant()
```

The key insight here is that `conversation_history` grows with every exchange. In production agents, you need a strategy for when it gets too long — truncation, summarization, or context compaction. The exam tests this in Domain 5 (Context Management). We cover it in depth in file 03.

> **📝 Exam Tip:** "Claude isn't maintaining conversation context across sessions" is never a bug in Claude — it's always a state management bug in your application. The fix is always to persist and replay the message history.

---

## Part 2 — The Claude Agent SDK

### Why the SDK Exists

The raw Messages API is powerful but low-level. When you're building agentic systems — agents that plan, use tools, spawn subagents, recover from errors — you end up writing the same scaffolding over and over: the agentic loop, tool dispatch, result injection, retry logic. The Agent SDK packages all of that into a higher-level abstraction.

<citation index="12-1">The SDK was designed around four production concerns: sandboxing, permissions, state persistence, and error recovery.</citation> Instead of wiring those yourself, the SDK handles them through managed infrastructure.

### The Three-Layer Architecture

<citation index="20-1">The Anthropic Agent SDK has a three-layer structure that the exam specifically tests: the orchestrator, the agent, and the tool layer.</citation>

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent SDK Architecture                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Layer 3: Orchestrator (Sonnet/Opus)                            │
│  ┌─────────────────────────────────────┐                        │
│  │  Plans, delegates, synthesizes       │                        │
│  │  Spawns subagents via Task Tool      │                        │
│  └──────────────┬──────────────────────┘                        │
│                 │ delegates                                       │
│  Layer 2: Subagents (Haiku/Sonnet)                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                      │
│  │ Agent A  │  │ Agent B  │  │ Agent C  │  ← parallel execution │
│  │ (focused │  │ (focused │  │ (focused │                        │
│  │  task)   │  │  task)   │  │  task)   │                        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                      │
│       │             │             │                               │
│  Layer 1: Tools (deterministic execution)                        │
│  ┌──────────────────────────────────────┐                        │
│  │  Read / Write / Bash / Grep / Glob   │                        │
│  │  MCP servers / Custom tools          │                        │
│  └──────────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘
```

<citation index="11-1">The lead agent breaks a job into pieces and delegates each piece to a specialist subagent with its own model, prompts, and tools. Subagents can work in parallel on a shared file system, feeding results back into the lead agent's context.</citation>

### The Planner → Generator → Evaluator Pattern

<citation index="12-1">Anthropic published a production-validated pattern for long-running agents in April 2026: divide work among a Planner agent (structure and goals), a Generator agent (execution), and an Evaluator agent (independent quality assessment). Agents hand off through structured artifacts rather than shared context.</citation>

This is the pattern the exam uses for multi-agent scenario questions. Here it is in Python:

```python
import anthropic
from concurrent.futures import ThreadPoolExecutor

client = anthropic.Anthropic()

def run_agent(system_prompt: str, user_message: str, model: str = "claude-sonnet-4-6") -> str:
    """Single agent call — the reusable primitive for all agent patterns."""
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    return response.content[0].text


def planner_agent(task: str) -> str:
    """Breaks a complex task into discrete subtasks."""
    return run_agent(
        system_prompt=(
            "You are a planning agent. Break the given task into discrete, "
            "independently executable subtasks. Return a numbered list. "
            "Each subtask must be completable without context from other subtasks."
        ),
        user_message=f"Plan this task: {task}",
        model="claude-sonnet-4-6"   # Orchestrator gets Sonnet
    )


def generator_agent(subtask: str) -> str:
    """Executes a single subtask and returns a structured artifact."""
    return run_agent(
        system_prompt=(
            "You are an execution agent. Complete the given subtask precisely. "
            "Return only the deliverable — no commentary."
        ),
        user_message=subtask,
        model="claude-haiku-4-5-20251001"  # Leaf nodes get Haiku — cheaper
    )


def evaluator_agent(original_task: str, results: list[str]) -> str:
    """Independently evaluates output quality. Runs critique-refine cycles."""
    combined = "\n\n---\n\n".join(results)
    return run_agent(
        system_prompt=(
            "You are an independent evaluator. Review the results against "
            "the original task. Identify gaps, inconsistencies, or quality issues. "
            "Be critical. Your job is to catch what the generator missed."
        ),
        user_message=f"Original task:\n{original_task}\n\nResults:\n{combined}",
        model="claude-sonnet-4-6"
    )


def run_multi_agent_pipeline(task: str) -> dict:
    """
    Full Planner → Generator → Evaluator pipeline.
    DevOps use case: generate a full runbook for a P1 incident type.
    """

    print(f"[Planner] Breaking down task...")
    plan = planner_agent(task)
    subtasks = [line.strip() for line in plan.split("\n") if line.strip()]

    print(f"[Generator] Executing {len(subtasks)} subtasks in parallel...")
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(generator_agent, subtasks))

    print(f"[Evaluator] Reviewing results...")
    evaluation = evaluator_agent(task, results)

    return {
        "plan": plan,
        "results": results,
        "evaluation": evaluation
    }


# Example: Generate an incident runbook
output = run_multi_agent_pipeline(
    task=(
        "Create a complete runbook for an ECS service that has 0 running tasks. "
        "Include: triage steps, common root causes, resolution commands, "
        "escalation criteria, and post-incident checklist."
    )
)
print(output["evaluation"])
```

> **📝 Exam Tip:** The exam distinguishes between orchestrator and subagent roles by *what model they run* and *what they're responsible for*. Orchestrators plan and synthesize (Sonnet/Opus). Subagents execute well-defined tasks (Haiku/Sonnet). Evaluators critique independently (Sonnet). Getting model selection wrong in a multi-agent scenario is a common wrong answer.

---

### Managed Agents vs Self-Hosted SDK

<citation index="15-1">Anthropic launched Claude Managed Agents as a hosted harness for long-running agent work in April 2026, giving developers a managed environment with secure sandboxing, credential management, durable session state, and persistent event history.</citation>

The choice between them is an exam-tested architectural decision:

| Factor | Self-Hosted SDK | Managed Agents |
|---|---|---|
| Infrastructure ownership | You own it | Anthropic manages it |
| Multi-agent coordination | Supported (current) | Roadmap (not yet shipped) |
| RAG / retrieval design | You own it | You still own it |
| Session cost | Token cost only | $0.08/hr runtime + tokens |
| Sandboxing | You implement | Included |
| Best for | Complex multi-agent pipelines today | Single-agent long-running tasks |

<citation index="12-1">For teams building multi-agent pipelines today, the self-hosted SDK remains the only viable Anthropic-native path.</citation>

> **📝 Exam Tip:** When a scenario involves multiple specialized agents coordinating with shared state, the answer is self-hosted SDK — not Managed Agents. Managed Agents is currently single-agent.

---

## Part 3 — Claude Code

### What Claude Code Actually Is

Claude Code is Anthropic's agentic coding environment — a command-line tool that gives Claude direct access to your file system, terminal, and development toolchain. It's not a chatbot with a code block — it's an agent that can read files, write files, run bash commands, search codebases, and iterate on its own output.

For DevOps engineers, this is particularly useful for infrastructure automation: reviewing Terraform plans, generating runbooks, writing and testing pipeline configs, and doing the kind of multi-file refactors that take hours manually.

### The Built-In Tool System

Claude Code ships with five built-in tools. The exam tests which tool to use for which task:

```
┌──────────────────────────────────────────────────────────────┐
│                 Claude Code Built-In Tools                    │
├──────────┬───────────────────────────────────────────────────┤
│ Tool     │ What It Does                                       │
├──────────┼───────────────────────────────────────────────────┤
│ Read     │ Read file contents. Safe, no side effects.         │
│ Write    │ Create or overwrite files. Requires confirmation   │
│          │ for existing files in default mode.                │
│ Bash     │ Execute shell commands. Most powerful, most        │
│          │ dangerous. Scope it tightly.                       │
│ Grep     │ Search file contents by regex pattern.            │
│ Glob     │ Find files by pattern (e.g. **/*.tf, src/**/*.py) │
└──────────┴───────────────────────────────────────────────────┘
```

A DevOps use case: ask Claude Code to find all Terraform files missing a `tags` block, show you the violations, and generate the fix — all using Read + Glob + Bash + Write in sequence, without you touching a single file manually.

### Plan Mode vs Implementation Mode

This is a key Claude Code concept the exam tests directly.

**Plan Mode** (`claude --plan`): Claude reads the codebase, reasons about what needs to change, and presents a plan before making any modifications. No files are written. Use this when you want human review before any changes land.

**Implementation Mode** (default): Claude proceeds with changes after confirming intent. Writes files, runs commands, iterates.

```bash
# Plan mode — review before any changes
claude --plan "Refactor all hardcoded AWS account IDs in this Terraform repo to use variables"

# Implementation mode — Claude will make changes
claude "Add retry logic with exponential backoff to all boto3 calls in src/"

# Non-interactive mode — for CI/CD pipelines
claude -p "Review this PR for security issues in IAM policy changes" --output-format json
```

The `-p` flag (print mode) runs Claude Code non-interactively — it takes input, generates output, and exits. This is how you integrate Claude Code into a Bamboo or Jenkins pipeline without a human sitting at a terminal.

---

## Part 4 — The CLAUDE.md Configuration Hierarchy

This is where a lot of engineers lose exam points. The CLAUDE.md hierarchy sounds simple but the scoping rules have specific behaviors that the exam tests with scenario questions.

### The Three Levels

<citation index="25-1">Claude Code reads CLAUDE.md files from three distinct levels, and confusing those levels is the single most common misconfiguration people hit. The exam leans on this hard.</citation>

```
┌──────────────────────────────────────────────────────────────────┐
│                  CLAUDE.md Configuration Hierarchy               │
├──────────────────┬───────────────────────────────────────────────┤
│ Level            │ Location                    │ Scope           │
├──────────────────┼─────────────────────────────┼─────────────────┤
│ User (global)    │ ~/.claude/CLAUDE.md          │ All sessions,   │
│                  │                             │ all repos, this  │
│                  │                             │ developer only   │
├──────────────────┼─────────────────────────────┼─────────────────┤
│ Project (shared) │ <repo-root>/CLAUDE.md   OR  │ All team members │
│                  │ <repo-root>/.claude/CLAUDE.md│ who clone this  │
│                  │                             │ repo             │
├──────────────────┼─────────────────────────────┼─────────────────┤
│ Directory        │ Any subdirectory CLAUDE.md  │ Claude Code      │
│ (path-specific)  │ e.g. src/CLAUDE.md          │ sessions in that │
│                  │      infra/CLAUDE.md        │ directory only   │
└──────────────────┴─────────────────────────────┴─────────────────┘

Precedence: More specific scope layers on top of broader scope.
Directory > Project > User
```

<citation index="19-1">CLAUDE.md is a Markdown file that acts as a persistent system prompt scoped to your project. Unlike conversation-level instructions that disappear after compaction, CLAUDE.md is re-read from disk at the start of every session and after every context compaction event.</citation>

### The Classic Exam Scenario

<citation index="25-1">You clone a repository, fire up Claude Code, and it ignores every convention your team agreed on. No naming standards. No test patterns. Wrong error handling everywhere. Your colleague swears it works perfectly on their machine.</citation>

The culprit is almost always configuration at the wrong scope level. The team put guidelines in `~/.claude/CLAUDE.md` (user scope) instead of the project `CLAUDE.md` (project scope). New engineers who clone the repo don't get those guidelines.

<citation index="22-1">The solution is to move shared guidelines to project scope. Use `/memory` to verify which memory files are loaded and diagnose inconsistent behavior across sessions.</citation>

> **📝 Exam Tip:** "New team member" + "inconsistent behavior" + "colleague's machine works fine" = configuration scoping problem. The fix is always moving shared instructions to project-level CLAUDE.md committed to version control.

### What Goes in a Production CLAUDE.md

<citation index="24-1">CLAUDE.md is for what the agent must know every session; skills are for what it must know some sessions; hooks are for what must happen regardless of what it knows.</citation>

Here's a realistic CLAUDE.md for a DevOps platform team:

```markdown
# Platform Team — Claude Code Instructions

## Project Context
This repo manages infrastructure for a state government platform spanning 7 EKS clusters.
All changes must be backward-compatible. Destructive operations require explicit confirmation.

## Stack
- IaC: Terraform 1.9+, modules in /infra/modules/
- Container orchestration: EKS 1.30, Helm 3.15
- CI/CD: Bamboo pipelines, configs in /ci/
- Secrets: AWS Secrets Manager, never hardcode credentials
- Observability: Prometheus + Grafana, dashboards in /monitoring/

## Coding Standards
- Python: black formatter, type hints required, docstrings for all public functions
- Terraform: tag all resources with env, team, project, managed-by=terraform
- Bash: set -euo pipefail on all scripts, always quote variables
- Never use `latest` tags in container image references

## Testing Requirements
- Unit tests required for all Python utilities (pytest, >80% coverage)
- Run `make test` not bare `pytest` — the Makefile sets required env vars
- Terraform: run `terraform validate` and `tflint` before proposing changes

## Commit Format
- Format: `type(scope): description` (Conventional Commits)
- Types: feat, fix, docs, chore, refactor, ci
- Example: `feat(eks): add cluster autoscaler config for prod`

## Do Not
- Modify /infra/prod/ without explicit user confirmation
- Run `terraform destroy` under any circumstances
- Push directly to main — all changes through PRs
```

<citation index="19-1">Commit the project root CLAUDE.md to version control — it's most useful when the whole team benefits from it. For personal overrides (machine-specific paths, draft notes, instructions you want but your team doesn't), use .claude/CLAUDE.md with a gitignore entry.</citation>

### Path-Specific Rules and Subdirectory Config

For large repos where different directories need different behavior, subdirectory CLAUDE.md files let you apply focused rules without polluting the root config:

```
repo/
├── CLAUDE.md                    # Project-wide rules
├── infra/
│   ├── CLAUDE.md                # "Always run tflint after changes.
│   │                             #  Never touch prod/ without confirmation."
│   └── modules/
├── src/
│   ├── CLAUDE.md                # "Python only. Use our internal SDK at src/lib/.
│   │                             #  Tests go in src/tests/ matching src structure."
│   └── api/
└── ci/
    └── CLAUDE.md                # "Bamboo YAML only. Validate with yamllint."
```

### Custom Slash Commands

Slash commands are reusable workflows you define once and invoke with `/command-name`. They live in `.claude/commands/` and can take arguments.

```markdown
<!-- .claude/commands/incident-runbook.md -->
# Generate Incident Runbook

Generate a complete P1 incident runbook for: $ARGUMENTS

Include:
1. Triage steps (first 5 minutes)
2. Common root causes with kubectl/awscli diagnosis commands
3. Resolution steps for each root cause
4. Escalation criteria
5. Post-incident checklist
6. Relevant CloudWatch/Prometheus queries

Format as markdown. Use actual command syntax, not placeholders.
```

```bash
# Using it:
claude "/incident-runbook ECS service with 0 running tasks"
```

> **📝 Exam Tip:** The exam tests slash command placement — they must be in `.claude/commands/` at the project root to be available to all team members. A command in `~/.claude/commands/` is user-scoped and won't be shared when the repo is cloned.

---

### Hooks — Lifecycle Events for Automation

Hooks let you run scripts at specific points in the Claude Code lifecycle. The exam tests the three hook types and their firing order:

```
PreToolUse  → fires BEFORE Claude executes a tool
PostToolUse → fires AFTER tool execution completes
Stop        → fires when Claude finishes the task
```

Configure them in `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "echo '[Hook] Bash command about to run: ' && cat"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/run-linter.sh"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /scripts/log-session-summary.py"
          }
        ]
      }
    ]
  }
}
```

Real DevOps uses for hooks:
- `PreToolUse` on `Bash`: log all shell commands to an audit trail before execution
- `PostToolUse` on `Write`: run `terraform fmt` or `black` automatically after any file write
- `Stop`: post a Slack notification when a long-running agent task completes

> **📝 Exam Tip:** Hook exit codes matter. A non-zero exit from a `PreToolUse` hook blocks the tool from running. This is how you implement safety gates — a script that rejects certain bash commands before Claude can execute them.

---

## Part 5 — Connecting It All: Claude Code in a CI/CD Pipeline

This is Exam Scenario 5 — Claude Code in a CI/CD pipeline. Here's what a Bamboo integration looks like in practice:

```python
#!/usr/bin/env python3
"""
claude_pr_review.py
Runs Claude Code analysis on a PR diff and posts findings as a comment.
Called from Bamboo with: python claude_pr_review.py --pr-diff diff.txt --pr-number 42
"""

import anthropic
import argparse
import json
import subprocess
import sys


def get_pr_diff(pr_number: int) -> str:
    """Fetch the PR diff from Bitbucket API."""
    result = subprocess.run(
        ["git", "diff", "origin/main...HEAD"],
        capture_output=True, text=True, check=True
    )
    return result.stdout


def review_pr_with_claude(diff: str, pr_number: int) -> dict:
    """Run Claude Code analysis on a PR diff."""
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system="""
        You are a senior DevOps architect reviewing infrastructure and application code.
        Focus on: security issues, IAM over-permissioning, hardcoded secrets,
        missing error handling, and violations of 12-factor app principles.

        Return a JSON object with this exact structure:
        {
            "verdict": "approve|request_changes|comment",
            "summary": "one paragraph summary",
            "issues": [
                {
                    "severity": "critical|high|medium|low",
                    "file": "filename",
                    "line": "line number or range",
                    "description": "what the issue is",
                    "recommendation": "how to fix it"
                }
            ],
            "positives": ["list of things done well"]
        }
        """,
        messages=[
            {
                "role": "user",
                "content": f"Review this PR diff (PR #{pr_number}):\n\n```diff\n{diff}\n```"
            }
        ]
    )

    return json.loads(response.content[0].text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr-number", type=int, required=True)
    args = parser.parse_args()

    print(f"[Claude PR Review] Analyzing PR #{args.pr_number}...")
    diff = get_pr_diff(args.pr_number)

    if not diff.strip():
        print("No diff found. Skipping review.")
        sys.exit(0)

    review = review_pr_with_claude(diff, args.pr_number)

    # Print findings
    print(f"\nVerdict: {review['verdict'].upper()}")
    print(f"Summary: {review['summary']}\n")

    critical_count = sum(1 for i in review["issues"] if i["severity"] == "critical")
    high_count = sum(1 for i in review["issues"] if i["severity"] == "high")

    for issue in review["issues"]:
        print(f"[{issue['severity'].upper()}] {issue['file']} - {issue['description']}")

    # Fail the pipeline if critical issues found
    if critical_count > 0:
        print(f"\n❌ Pipeline blocked: {critical_count} critical issue(s) found.")
        sys.exit(1)

    print(f"\n✅ Review complete. {len(review['issues'])} issue(s) found.")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

This is a complete, real pipeline integration. The structured JSON output, the `sys.exit(1)` on critical findings, the `max_tokens` sized for a full review — all of these are production decisions that the exam tests in scenario form.

---

## Summary — What to Lock In Before Moving On

```
┌────────────────────────────────────────────────────────────────┐
│  02 — API & SDK: Key Takeaways                                 │
├────────────────────────────────────────────────────────────────┤
│ Messages API: full history every call — Claude has no memory   │
│ Content blocks: text, image, document, tool_use, tool_result   │
│ Streaming: use .stream() for long outputs, get_final_message() │
│ Agent SDK: 3 layers — Orchestrator → Subagents → Tools         │
│ Planner/Generator/Evaluator: the production multi-agent pattern│
│ Managed Agents: single-agent only (multi-agent = self-hosted)  │
│ Claude Code tools: Read, Write, Bash, Grep, Glob               │
│ Plan mode: no file writes until human approves                 │
│ -p flag: non-interactive mode for CI/CD pipelines              │
│ CLAUDE.md levels: User (global) → Project (shared) → Directory │
│ Scoping rule: "new member, inconsistent behavior" = project    │
│ Hooks: PreToolUse → PostToolUse → Stop. Exit code blocks tool. │
│ Slash commands: .claude/commands/ for team-shared workflows     │
└────────────────────────────────────────────────────────────────┘
```

---

## Exam Practice Questions — API & SDK

**Q1.** A developer puts team coding standards in `~/.claude/CLAUDE.md`. New engineers who join and clone the repository don't see consistent Claude Code behavior. What is the fix?

- A) Add the standards to each developer's user-level CLAUDE.md during onboarding
- B) Move the standards to the project-level CLAUDE.md committed to version control ✓
- C) Use environment variables to set Claude Code behavior
- D) Add a PostToolUse hook that enforces standards after each write

*Why B: User-level config is personal and not shared when a repo is cloned. Project-level CLAUDE.md is version-controlled and inherited by all contributors.*

---

**Q2.** An agent workflow uses Claude Code in a Bamboo pipeline. The pipeline should fail if Claude finds critical security issues. Which flag enables non-interactive Claude Code execution in this context?

- A) `--no-confirm`
- B) `--ci-mode`
- C) `-p` (print mode) ✓
- D) `--stream`

*Why C: The `-p` flag runs Claude Code non-interactively — input in, output out, process exits. Required for CI/CD integration.*

---

**Q3.** In a Planner → Generator → Evaluator multi-agent pipeline, which model assignment is most cost-efficient while maintaining output quality?

- A) Opus for all three agents
- B) Sonnet for Planner, Haiku for Generator, Sonnet for Evaluator ✓
- C) Haiku for all three agents
- D) Sonnet for all three agents

*Why B: Planner and Evaluator require reasoning (Sonnet). Generator executes well-defined subtasks (Haiku sufficient). Using Opus unnecessarily triples cost.*

---

**Q4.** A PreToolUse hook script returns exit code 1 when a Bash command matches a blocklist pattern. What happens?

- A) Claude Code logs a warning but continues execution
- B) Claude Code asks the user for confirmation before proceeding
- C) The Bash tool is blocked from executing ✓
- D) The session terminates

*Why C: Non-zero exit from PreToolUse hooks blocks the tool. This is how you implement safety gates in Claude Code pipelines.*

---

## What's Next

**`03-prompting-context-and-reliability.md`** covers the two domains that live or die on technique: prompt engineering patterns that actually work in production, structured output with JSON schemas and retry loops, context window management strategies, and confidence calibration. These are the "invisible architecture" decisions — they don't show up in your repo but they determine whether your agent is reliable or not.

---

## Official Resources

- [Claude API Messages Reference](https://docs.anthropic.com/en/api/messages)
- [Streaming Guide](https://docs.anthropic.com/en/api/messages-streaming)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)
- [CLAUDE.md Reference](https://docs.anthropic.com/en/docs/claude-code/memory)
- [Claude Code Hooks](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Agent SDK Documentation](https://docs.anthropic.com/en/docs/agents-and-tools/agent-sdk)

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*  
*Found an error or want to contribute? PRs welcome.*
