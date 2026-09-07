# 03 — Prompting, Context, and Reliability
## Prompt Engineering That Actually Works, Structured Output, Context Management, and Building Agents That Don't Fall Apart

> **Series:** Anthropic Fundamentals for DevOps Engineers → CCAR-F  
> **Exam Domains:** Domain 3 — Prompt Engineering & Structured Output (20%) | Domain 5 — Context Management & Reliability (15%)  
> **Combined Weight:** ~21 questions out of 60

---

## What You'll Learn Here

Prompt engineering has a reputation problem. Engineers either dismiss it as "just talking to a chatbot" or treat it like magic incantations — throw enough words at the model and hope for the best. Neither approach holds up in production.

The reality is simpler and more mechanical than both camps suggest. Claude 4.x and newer models are literal interpreters. They do exactly what you ask, nothing more. That's a feature, not a limitation — but it means vague instructions produce vague results, and sloppy output schemas produce sloppy data. Once you internalize that, prompting becomes an engineering discipline with predictable cause-and-effect relationships.

By the end of this article you'll know the five prompt engineering techniques that the exam actually tests, how to force reliable structured output using JSON schemas and retry loops, how to manage context windows without losing critical state, and when to trigger human-in-the-loop escalation rather than letting an agent keep spinning.

---

## Part 1 — Prompt Engineering Techniques That Matter

### The Five Techniques the Exam Tests

<citation index="28-1">Structured XML/JSON prompts, extended thinking, explicit requirements, few-shot examples, and context-first ordering are the five prompting techniques that measurably improve output from Claude 4.x and newer models.</citation>

These aren't arbitrary — they map directly to how Claude processes instructions. Let's go through each one with DevOps examples.

---

### Technique 1: Explicit Requirements Over Vague Intent

<citation index="28-1">Claude 4.x and newer models take you literally and do exactly what you ask for, nothing more. Earlier versions would infer your intent and expand on vague requests.</citation>

This is the single most important shift from using Claude as a chatbot to using it in production systems. Vague instructions that worked on GPT-3-era models now produce exactly the minimum you asked for.

```python
import anthropic

client = anthropic.Anthropic()

# ❌ VAGUE — produces inconsistent, unpredictable output
bad_prompt = "Look at these logs and tell me what's wrong."

# ✅ EXPLICIT — produces consistent, actionable output
good_prompt = """
Analyze the following ECS task logs for issues.

Return your findings as a structured list. For each issue found:
1. State the specific error or anomaly
2. Identify the root cause (one sentence)
3. Provide the exact remediation command or config change
4. Rate severity: P1 (service down), P2 (degraded), P3 (warning)

If no issues are found, return: "No actionable issues detected."
Do not include commentary outside this structure.

Logs:
{logs}
"""

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2048,
    messages=[{"role": "user", "content": good_prompt.format(logs=log_data)}]
)
print(response.content[0].text)
```

The difference isn't subtle. The explicit version produces output you can parse and act on. The vague version produces whatever Claude thinks is helpful that day.

> **📝 Exam Tip:** When a scenario describes "inconsistent Claude outputs across runs," the diagnosis is almost always under-specified instructions. The fix is always adding explicit requirements — output format, what to include, what to exclude, how to handle edge cases.

---

### Technique 2: Context Before Question

The ordering of information inside a prompt matters more than most engineers expect. Claude reads your prompt sequentially. Relevant context placed after the question lands too late to properly frame the answer.

```python
# ❌ WRONG ORDER — question before context
wrong_order = """
What's the best deployment strategy for this service?

Context:
- 7 EKS clusters across dev/staging/prod
- Service has stateful sessions (Redis)
- Current uptime SLA: 99.9%
- Team does 3-4 deploys per week
- Last outage: rolling update caused session drops
"""

# ✅ RIGHT ORDER — context first, question last
right_order = """
Context:
- 7 EKS clusters across dev/staging/prod
- Service has stateful sessions stored in Redis
- Current uptime SLA: 99.9%
- Team does 3-4 deploys per week
- Last production outage: rolling update caused session drops due to in-flight requests

Given this context, what's the best deployment strategy for this service?
Focus specifically on session continuity during deploys.
"""
```

The second version produces a more targeted answer because Claude has the constraints *before* it starts reasoning about deployment strategies. It's the same reason a good architecture diagram goes before the design discussion, not after.

---

### Technique 3: Few-Shot Examples

Few-shot prompting — giving Claude examples of input/output pairs — is the fastest way to enforce a specific output style or format. It's especially valuable for extraction tasks where you need consistent structure across thousands of documents.

```python
few_shot_prompt = """
Extract deployment events from the log lines below. 

Format each event as:
EVENT: <type> | SERVICE: <name> | STATUS: <success|failed|rollback> | DURATION: <seconds>

Examples:
Log: "2026-08-16 14:23:01 [INFO] Deploying api-gateway v2.3.1 to prod-us-east-1"
Log: "2026-08-16 14:25:44 [INFO] api-gateway deployment completed successfully in 163s"
Output: EVENT: deployment | SERVICE: api-gateway | STATUS: success | DURATION: 163

Log: "2026-08-16 09:11:22 [ERROR] auth-service deploy failed: health check timeout after 300s"
Log: "2026-08-16 09:11:23 [INFO] Initiating rollback for auth-service"
Output: EVENT: deployment | SERVICE: auth-service | STATUS: rollback | DURATION: 300

Now extract events from these logs:
{logs}
"""
```

Two examples is usually enough for well-defined extraction tasks. The exam sometimes presents scenarios where Claude produces malformed output — the fix is almost always adding few-shot examples that demonstrate the exact format you want.

---

### Technique 4: XML Tags for Structure

Claude was trained heavily on structured text and responds especially well to XML tags for separating sections of a complex prompt. This is particularly useful when your prompt contains multiple distinct components — instructions, data, examples, constraints.

```python
system_prompt = """
You are a senior DevOps architect performing infrastructure security reviews.

<instructions>
Review the provided Terraform configuration for security issues.
Focus on: IAM over-permissioning, public exposure, missing encryption, 
hardcoded secrets, and missing resource tagging.
</instructions>

<output_format>
Return a JSON array. Each item must have:
- "severity": "critical" | "high" | "medium" | "low"
- "resource": the Terraform resource type and name
- "issue": one-sentence description of the problem
- "fix": specific remediation (code snippet preferred over prose)
</output_format>

<constraints>
- Only report actionable issues, not best-practice suggestions
- If a resource is correctly configured, do not include it
- Maximum 20 items in the response
</constraints>
"""

user_message = """
<terraform_config>
{terraform_hcl}
</terraform_config>

Review the above configuration.
"""
```

The XML structure separates concerns clearly — Claude processes instructions, format, and constraints as distinct sections rather than a run-on paragraph. On the exam, questions about "improving prompt reliability" or "reducing format errors" frequently have XML structuring as the correct answer.

---

### Technique 5: Extended Thinking

Extended thinking gives Claude space to reason through a problem before producing its final answer. It's particularly valuable for complex architectural decisions, root cause analysis, and any task where the answer depends on multi-step reasoning.

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=16000,
    thinking={
        "type": "enabled",
        "budget_tokens": 10000   # How much "thinking" Claude can do before answering
    },
    messages=[
        {
            "role": "user",
            "content": (
                "We have an EKS cluster with intermittent pod evictions "
                "during business hours only. Node CPU never exceeds 60%. "
                "Memory pressure alerts fire 10 minutes before evictions. "
                "What are all the possible causes and how do we diagnose each?"
            )
        }
    ]
)

# The response contains both thinking blocks and text blocks
for block in response.content:
    if block.type == "thinking":
        print(f"[Claude's reasoning]: {block.thinking[:500]}...")  # Often verbose
    elif block.type == "text":
        print(f"[Answer]: {block.text}")
```

> **📝 Exam Tip:** Extended thinking raises `max_tokens` requirements significantly — you need room for both the thinking content and the final answer. On the exam, a scenario where extended thinking produces truncated output is solved by increasing `max_tokens`, not by disabling thinking.

---

## Part 2 — Structured Output: Forcing Reliable JSON

This is Exam Scenario 6 — Structured Data Extraction. Getting Claude to reliably return valid, parseable JSON is one of the most practically important skills in this certification, and the exam tests it in detail.

### The Three-Layer Approach

Reliable structured output requires three things working together: a schema defined in the system prompt, a client-side validation layer, and a retry loop that feeds errors back to Claude. Any one of these alone is fragile.

<citation index="32-1">You must know how to force Claude to return valid JSON. This involves: describing the JSON schema in the tool definitions or system prompt, instructing Claude to skip conversational preambles and output only raw JSON, and implementing parsing validation on the client side with a retry loop that feeds the error trace back to Claude.</citation>

```python
import anthropic
import json
from typing import Any

client = anthropic.Anthropic()

EXTRACTION_SCHEMA = """
{
    "deployment_id": "string — unique identifier from the log",
    "service_name": "string — name of the deployed service",
    "environment": "string — one of: dev | staging | prod",
    "status": "string — one of: success | failed | rollback | in_progress",
    "duration_seconds": "integer — deployment duration, null if unknown",
    "error_message": "string — error detail if status is failed, null otherwise",
    "deployed_by": "string — user or system that triggered deployment",
    "timestamp": "string — ISO 8601 format"
}
"""

def extract_deployment_event(log_text: str, max_retries: int = 3) -> dict[str, Any]:
    """
    Extract structured deployment data from unstructured log text.
    Implements the retry loop with error feedback pattern.
    """

    system_prompt = f"""
    You are a log parsing agent. Extract deployment events from log text.
    
    Return ONLY a valid JSON object matching this exact schema:
    {EXTRACTION_SCHEMA}
    
    Rules:
    - Output raw JSON with no markdown fences, no preamble, no explanation
    - Use null for fields that cannot be determined from the log
    - Do not invent data that isn't present in the log
    - If the log contains no deployment event, return: {{"error": "no_deployment_event"}}
    """

    messages = [{"role": "user", "content": f"Extract deployment event:\n\n{log_text}"}]

    for attempt in range(max_retries):
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=messages
        )

        raw_output = response.content[0].text.strip()

        # Strip markdown fences if Claude adds them despite instructions
        if raw_output.startswith("```"):
            raw_output = raw_output.split("```")[1]
            if raw_output.startswith("json"):
                raw_output = raw_output[4:]

        try:
            parsed = json.loads(raw_output)
            return parsed  # Success — return immediately

        except json.JSONDecodeError as e:
            if attempt < max_retries - 1:
                # Feed the error back to Claude — this is the key pattern
                messages.append({"role": "assistant", "content": raw_output})
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your response was not valid JSON. Parse error: {str(e)}\n"
                        f"Your output was:\n{raw_output}\n\n"
                        "Please return ONLY valid JSON matching the schema. "
                        "No markdown, no explanation."
                    )
                })
            else:
                raise ValueError(
                    f"Failed to extract valid JSON after {max_retries} attempts. "
                    f"Last output: {raw_output}"
                )

    return {}  # Unreachable but satisfies type checker


# Test it
log_sample = """
2026-08-16 14:23:01 UTC [deploy-agent] Starting deployment job #DPL-4821
2026-08-16 14:23:01 UTC [deploy-agent] Service: payment-processor, version: 3.1.4
2026-08-16 14:23:01 UTC [deploy-agent] Target: prod-us-east-1, triggered by: ci-bot
2026-08-16 14:26:44 UTC [deploy-agent] Health checks passing (3/3)
2026-08-16 14:26:44 UTC [deploy-agent] Deployment DPL-4821 completed successfully (223s)
"""

result = extract_deployment_event(log_sample)
print(json.dumps(result, indent=2))
```

The retry loop is the part most engineers skip. Without it, a single malformed response from Claude breaks your entire pipeline. With it, Claude self-corrects on the next attempt — and in practice, it almost always gets it right within two tries.

### Using Tool Use to Enforce Schema

There's a more reliable approach than prompt-based JSON extraction — defining your schema as a tool definition and forcing Claude to call it. When Claude calls a tool, it must conform to the JSON schema you've defined. The model can't return free-text when a tool call is expected.

```python
# Define the output structure as a tool
deployment_schema_tool = {
    "name": "record_deployment_event",
    "description": "Record a structured deployment event extracted from logs",
    "input_schema": {
        "type": "object",
        "properties": {
            "deployment_id": {
                "type": "string",
                "description": "Unique deployment identifier from the log"
            },
            "service_name": {
                "type": "string",
                "description": "Name of the deployed service"
            },
            "environment": {
                "type": "string",
                "enum": ["dev", "staging", "prod"],
                "description": "Deployment target environment"
            },
            "status": {
                "type": "string",
                "enum": ["success", "failed", "rollback", "in_progress"]
            },
            "duration_seconds": {
                "type": ["integer", "null"],
                "description": "Deployment duration in seconds"
            },
            "error_message": {
                "type": ["string", "null"]
            },
            "deployed_by": {"type": "string"},
            "timestamp": {
                "type": "string",
                "description": "ISO 8601 timestamp"
            }
        },
        "required": ["deployment_id", "service_name", "environment", "status", "deployed_by", "timestamp"]
    }
}

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=[deployment_schema_tool],
    tool_choice={"type": "tool", "name": "record_deployment_event"},  # Force this specific tool
    messages=[
        {
            "role": "user",
            "content": f"Extract the deployment event from these logs:\n\n{log_sample}"
        }
    ]
)

# Extract the tool call arguments — guaranteed valid against the schema
tool_block = next(b for b in response.content if b.type == "tool_use")
event = tool_block.input  # Already a dict — no JSON parsing needed
print(event)
```

`tool_choice: {"type": "tool", "name": "..."}` forces Claude to call that specific tool. The response will always contain a `tool_use` block with input that conforms to your schema. This eliminates the JSON parsing step entirely.

> **📝 Exam Tip:** The exam distinguishes between two structured output approaches: prompt-based (instruct Claude to return JSON + retry loop) and tool-based (define schema as tool, force tool call). Tool-based is more reliable because schema validation is enforced by the API, not by prompting. Know which scenario calls for each.

---

### Multi-Pass Review for Quality

For high-stakes extraction where accuracy really matters, a single pass isn't enough. The multi-pass pattern runs a second Claude call to verify the first one's output.

```python
def extract_with_verification(document: str) -> dict:
    """Two-pass extraction with independent verification."""

    # Pass 1: Extract
    extraction = extract_deployment_event(document)

    # Pass 2: Verify — independent call, no shared context with pass 1
    verification_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=(
            "You are a data quality reviewer. "
            "Verify that the extracted data matches the source document. "
            "Return JSON: {\"valid\": true/false, \"issues\": [\"list of discrepancies\"]}"
        ),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Source document:\n{document}\n\n"
                    f"Extracted data:\n{json.dumps(extraction, indent=2)}\n\n"
                    "Does the extracted data accurately reflect the source? "
                    "Flag any fields that appear incorrect or invented."
                )
            }
        ]
    )

    verification = json.loads(verification_response.content[0].text)

    if not verification["valid"]:
        # Log issues but still return extraction — caller decides what to do
        print(f"[QA Warning] Extraction issues: {verification['issues']}")

    return {
        "data": extraction,
        "verified": verification["valid"],
        "issues": verification.get("issues", [])
    }
```

The independence between passes matters. If you pass the extraction result to the same conversation that produced it, Claude has an incentive to confirm its own output. A fresh call with no prior context is a genuinely independent review.

---

## Part 3 — Context Management

Context window management is Domain 5 on the exam — 15%, about 9 questions. It's the domain that rewards engineers who've actually run long-running agents in production, because the failure modes are subtle and the fixes are counterintuitive.

### Understanding Context Rot

<citation index="39-1">As token count grows, accuracy and recall degrade, a phenomenon known as context rot.</citation> This is the core problem. A 1M token context window doesn't mean you want 1M tokens in it — it means you *can* handle 1M tokens before the API rejects your request. But long before you hit that ceiling, response quality starts to slip.

In practice, context rot shows up as:
- Claude forgetting constraints you set early in the conversation
- Repeating solutions it already tried and you rejected
- Mixing up details from different parts of a long task
- Gradually drifting from the original objective

The fix isn't a bigger context window. It's managing what lives in context.

### The Four Context Management Tools

```
┌──────────────────────────────────────────────────────────────────────┐
│              Context Management Decision Tree                        │
├─────────────────┬────────────────────────────────────────────────────┤
│ Tool            │ When to Use                                        │
├─────────────────┼────────────────────────────────────────────────────┤
│ /compact        │ Session getting long, debugging noise in history,  │
│ (Claude Code)   │ want to continue without losing the thread         │
├─────────────────┼────────────────────────────────────────────────────┤
│ /clear          │ Task complete, starting something unrelated,        │
│ (Claude Code)   │ context too corrupted to salvage                   │
├─────────────────┼────────────────────────────────────────────────────┤
│ Server-side     │ API-based agents, multi-turn conversations that    │
│ Compaction      │ may exceed window limits automatically             │
├─────────────────┼────────────────────────────────────────────────────┤
│ Subagent        │ High-volume tool output (logs, file reads) that    │
│ Delegation      │ would flood the orchestrator's context             │
└─────────────────┴────────────────────────────────────────────────────┘
```

### Server-Side Compaction via the API

<citation index="36-1">Server-side compaction is the recommended strategy for managing context in long-running conversations and agentic workflows. It handles context management automatically, without client-side summarization code. Compaction extends the effective context length by automatically summarizing older context when approaching the context window limit.</citation>

```python
import anthropic

client = anthropic.Anthropic()
messages = []

def chat_with_compaction(user_message: str) -> str:
    """
    Multi-turn conversation with automatic server-side compaction.
    Context is managed automatically — the conversation can continue
    indefinitely without manual truncation.
    """
    messages.append({"role": "user", "content": user_message})

    response = client.beta.messages.create(
        betas=["compact-2026-01-12"],   # Enable compaction beta
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=(
            "You are a DevOps incident commander. "
            "Help diagnose and resolve infrastructure incidents. "
            "Maintain awareness of all context discussed in this session."
        ),
        messages=messages,
        context_management={
            "edits": [
                {
                    "type": "compact_20260112",
                    # Optional: guide what the summary preserves
                    "instructions": (
                        "Preserve: all error messages and stack traces, "
                        "all commands run and their outputs, "
                        "all decisions made and their rationale, "
                        "current incident status and next actions. "
                        "Drop: exploratory tangents, repeated information."
                    )
                }
            ]
        }
    )

    # Include the full response content — compaction blocks are part of this
    messages.append({"role": "assistant", "content": response.content})

    return next(
        block.text for block in response.content if block.type == "text"
    )


# This conversation can run for hours — compaction fires automatically
print(chat_with_compaction("We have a P1 — ECS service prod-api has 0 running tasks."))
print(chat_with_compaction("ECS events show: 'Task failed ELB health checks'. Logs show 502s."))
print(chat_with_compaction("Port 8080 is correct. The new deployment was 20 minutes ago."))
# ... continue as long as needed
```

<citation index="37-1">The custom compaction instructions make a real difference — a generic summary might say "The user requested help with Python code," while a guided summary preserves the specific error, the root cause, and the next steps — everything an engineer needs to continue mid-incident without losing thread.</citation>

### Compaction Thrashing — The Failure Mode to Know

<citation index="38-1">If the context refills almost immediately after each compaction — for example because a single tool keeps producing more output than the summary reclaims — compaction reclaims little and the session can stall, repeatedly compacting without making forward progress. Treat that "thrashing" as a signal: it means the working pattern itself needs to change (smaller reads, delegation to a subagent, a fresh session), rather than continuing to compact.</citation>

> **📝 Exam Tip:** Compaction thrashing is a real exam scenario. The question describes an agent that keeps compacting without making progress. The correct answer is architectural: delegate the high-volume tool work to a subagent with isolated context, not "increase the context window" or "disable compaction."

### The Handoff Pattern for Multi-Session Work

Long tasks that span multiple sessions need a handoff document — a structured summary of current state that a new session can pick up from. This is the context equivalent of a good on-call handoff.

```python
HANDOFF_PROMPT = """
Before this session ends, create a handoff document for the next session.

Include exactly:
## Current Status
[One paragraph on what was accomplished and what's left]

## Critical Decisions Made  
[Bulleted list of architectural/operational decisions and their rationale]

## Active State
[Current state of any in-progress work — files modified, services affected, etc.]

## Next Actions
[Ordered list of next steps for the incoming session]

## Constraints and Gotchas
[Things the next session must know to avoid repeating mistakes]

Be specific. The next session has no context from this one.
"""

def generate_handoff(conversation_history: list) -> str:
    """Generate a structured handoff document at session end."""
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=conversation_history + [
            {"role": "user", "content": HANDOFF_PROMPT}
        ]
    )
    return response.content[0].text


# At the end of a long incident session
handoff = generate_handoff(conversation_history)

# Write to a file the next session can load
with open("incident-handoff.md", "w") as f:
    f.write(handoff)
```

The next session starts by reading this file into context before doing anything else. It's not elegant — it's just reliable. Reliability is what the exam rewards.

---

## Part 4 — Reliability: When Agents Go Wrong

Domain 5 isn't just about context windows. It's about building agents that fail gracefully, escalate intelligently, and don't spiral into useless loops when they hit something unexpected.

### Confidence Calibration

Agents need to know when they don't know. An agent that plows forward on a guess is more dangerous than one that stops and asks. The pattern for this is explicit uncertainty thresholds built into the system prompt.

```python
system_prompt = """
You are a DevOps automation agent. When you are asked to make changes:

1. If you are >90% confident the action is correct and safe: proceed
2. If you are 70-90% confident: state your uncertainty and proposed action,
   then wait for explicit confirmation before proceeding
3. If you are <70% confident: explain what's unclear and ask a clarifying question
   Do NOT guess. Do NOT proceed.

For ANY action that is irreversible (deletes, scaling down, config changes in prod):
Always require explicit confirmation regardless of confidence level.
Output the confirmation request in this format:
CONFIRMATION_REQUIRED: [action] | REASON: [why you need confirmation] | IMPACT: [what will change]
"""
```

This is the architectural equivalent of a dry-run flag. You're building uncertainty-aware behavior into the agent's operating instructions, not patching it in after the first production incident.

### Human-in-the-Loop Escalation

<citation index="29-1">Designing effective escalation and ambiguity resolution patterns is an explicit exam topic in Domain 5.</citation> The pattern is straightforward: define triggers for escalation, and make the escalation output structured enough that a human can act on it quickly.

```python
import anthropic
import json

client = anthropic.Anthropic()

ESCALATION_TRIGGERS = [
    "production database",
    "delete",
    "destroy",
    "scale down",
    "terminate",
    "remove all",
    "drop table",
    "truncate",
]

def check_escalation_needed(proposed_action: str) -> bool:
    """Determine if a proposed action requires human escalation."""
    action_lower = proposed_action.lower()
    return any(trigger in action_lower for trigger in ESCALATION_TRIGGERS)


def agent_with_escalation(task: str, conversation: list) -> dict:
    """
    Agent loop with human-in-the-loop escalation.
    Returns either a completed result or an escalation request.
    """
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system="""
        You are a DevOps automation agent. For each task:
        1. Plan what you would do
        2. Identify any actions that affect production or are irreversible
        3. Return your plan as JSON:
        {
            "plan": "description of what you'll do",
            "requires_escalation": true/false,
            "escalation_reason": "why this needs human review (null if not required)",
            "safe_actions": ["actions you can take without approval"],
            "pending_actions": ["actions requiring approval before proceeding"]
        }
        """,
        messages=conversation + [{"role": "user", "content": task}]
    )

    plan = json.loads(response.content[0].text)

    if plan["requires_escalation"]:
        # Surface to human — do not proceed automatically
        return {
            "status": "escalated",
            "reason": plan["escalation_reason"],
            "pending_actions": plan["pending_actions"],
            "safe_actions_completed": [],
            "message": (
                f"Human approval required before continuing.\n"
                f"Reason: {plan['escalation_reason']}\n"
                f"Pending: {', '.join(plan['pending_actions'])}"
            )
        }

    # No escalation needed — proceed with safe actions
    return {
        "status": "proceeding",
        "actions": plan["safe_actions"],
        "plan": plan["plan"]
    }


# Example — this triggers escalation
result = agent_with_escalation(
    task="The ECS service is running 10 tasks. Scale it down to 2 in prod.",
    conversation=[]
)
print(json.dumps(result, indent=2))
# → {"status": "escalated", "reason": "Scale down in production requires approval", ...}
```

### Error Recovery — The Three-Tier Model

Production agents need a tiered response to failures. Not every error deserves the same response, and over-escalating is as bad as under-escalating.

```python
import time
from enum import Enum

class ErrorTier(Enum):
    RETRY = "retry"           # Transient — retry with backoff
    FALLBACK = "fallback"     # Recoverable — try alternate approach
    ESCALATE = "escalate"     # Unrecoverable — needs human

def classify_error(error: Exception, attempt: int) -> ErrorTier:
    """Classify errors into recovery tiers."""
    error_msg = str(error).lower()

    # Transient API errors — always retry
    if "rate_limit" in error_msg or "timeout" in error_msg or "529" in error_msg:
        return ErrorTier.RETRY

    # Bad output we can ask Claude to fix — retry with feedback
    if isinstance(error, (json.JSONDecodeError, ValueError)) and attempt < 3:
        return ErrorTier.RETRY

    # Tool execution failure — try a different approach
    if "tool_execution_error" in error_msg:
        return ErrorTier.FALLBACK

    # Anything else after retries — escalate
    return ErrorTier.ESCALATE


def resilient_agent_call(task: str, max_attempts: int = 3) -> dict:
    """Agent call with tiered error recovery."""
    last_error = None

    for attempt in range(max_attempts):
        try:
            result = agent_with_escalation(task, [])
            return result

        except Exception as e:
            last_error = e
            tier = classify_error(e, attempt)

            if tier == ErrorTier.RETRY:
                wait = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                print(f"[Retry {attempt + 1}] {str(e)} — waiting {wait}s")
                time.sleep(wait)
                continue

            elif tier == ErrorTier.FALLBACK:
                print(f"[Fallback] Tool failed — attempting alternate approach")
                task = f"The direct approach failed with: {str(e)}. Try an alternative method for: {task}"
                continue

            elif tier == ErrorTier.ESCALATE:
                return {
                    "status": "escalated",
                    "reason": f"Unrecoverable error after {attempt + 1} attempts: {str(e)}",
                    "original_task": task
                }

    return {
        "status": "failed",
        "reason": f"Exhausted {max_attempts} attempts. Last error: {str(last_error)}"
    }
```

> **📝 Exam Tip:** The exam loves to ask which error type should trigger which recovery action. The pattern: transient API errors (rate limits, timeouts) → exponential backoff retry. Bad model output → retry with error feedback. Tool failures → fallback with alternate approach. Anything else → escalate to human. Never let an agent loop more than 3-5 times without escalating.

---

## Part 5 — Putting It Together: A Production Extraction Pipeline

Here's a complete pipeline that combines all of the patterns from this article — explicit prompting, structured output with retry, multi-pass verification, and context-aware batch processing. This is the kind of system the exam's Scenario 6 (Structured Data Extraction) is based on.

```python
import anthropic
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

client = anthropic.Anthropic()

@dataclass
class ExtractionResult:
    document_id: str
    data: dict
    verified: bool
    attempts: int
    error: str | None = None


def extract_single_document(doc_id: str, content: str) -> ExtractionResult:
    """Extract structured data from a single document with retry and verification."""
    max_attempts = 3

    # System prompt — XML-structured with explicit schema
    system = """
    <role>Log parsing agent for DevOps pipeline events</role>

    <task>
    Extract deployment event data from the provided log content.
    Return ONLY raw JSON — no markdown, no explanation, no preamble.
    </task>

    <schema>
    {
        "service": "string",
        "version": "string or null",
        "environment": "dev|staging|prod",
        "status": "success|failed|rollback|in_progress",
        "duration_seconds": "integer or null",
        "timestamp": "ISO 8601 string",
        "error": "string or null"
    }
    </schema>

    <rules>
    - null for any field not determinable from the log
    - Do not invent data
    - If no deployment event exists: {"error": "no_deployment_event"}
    </rules>
    """

    messages = [{"role": "user", "content": f"Extract from:\n\n{content}"}]

    for attempt in range(max_attempts):
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",  # Haiku for high-volume extraction
                max_tokens=512,
                system=system,
                messages=messages
            )
            raw = response.content[0].text.strip().strip("```json").strip("```")
            data = json.loads(raw)

            # Quick verification pass
            verified = verify_extraction(content, data)

            return ExtractionResult(
                document_id=doc_id,
                data=data,
                verified=verified,
                attempts=attempt + 1
            )

        except (json.JSONDecodeError, ValueError) as e:
            if attempt < max_attempts - 1:
                # Feed error back — the retry pattern
                messages.append({"role": "assistant", "content": response.content[0].text})
                messages.append({
                    "role": "user",
                    "content": f"Invalid JSON: {e}. Return ONLY valid JSON matching the schema."
                })
            else:
                return ExtractionResult(
                    document_id=doc_id,
                    data={},
                    verified=False,
                    attempts=attempt + 1,
                    error=str(e)
                )


def verify_extraction(source: str, extracted: dict) -> bool:
    """Independent verification pass — separate API call, no shared context."""
    if "error" in extracted:
        return True  # No-event response is always valid

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=128,
        system='Return only JSON: {"valid": true} or {"valid": false, "reason": "string"}',
        messages=[{
            "role": "user",
            "content": (
                f"Source:\n{source}\n\n"
                f"Extracted:\n{json.dumps(extracted)}\n\n"
                "Does the extracted data accurately reflect the source?"
            )
        }]
    )
    result = json.loads(response.content[0].text)
    return result.get("valid", False)


def run_batch_extraction(documents: dict[str, str], max_workers: int = 10) -> list[ExtractionResult]:
    """
    Process many documents in parallel.
    For non-real-time: consider Batch API instead (50% cost savings).
    """
    results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_single_document, doc_id, content): doc_id
            for doc_id, content in documents.items()
        }

        for future in as_completed(futures):
            doc_id = futures[future]
            try:
                result = future.result()
                results.append(result)
                status = "✓" if result.verified else "⚠"
                log.info(f"{status} {doc_id} — {result.attempts} attempt(s)")
            except Exception as e:
                log.error(f"✗ {doc_id} — unhandled exception: {e}")
                results.append(ExtractionResult(
                    document_id=doc_id, data={}, verified=False,
                    attempts=0, error=str(e)
                ))

    return results
```

---

## Summary — What to Lock In Before Moving On

```
┌────────────────────────────────────────────────────────────────────┐
│  03 — Prompting & Context: Key Takeaways                           │
├────────────────────────────────────────────────────────────────────┤
│ PROMPTING                                                          │
│ Claude 4.x is literal — vague instructions produce vague output   │
│ 5 techniques: explicit requirements, context-first, few-shot,      │
│   XML tags, extended thinking                                      │
│ Context before question — ordering matters                         │
│ Two few-shot examples usually sufficient for extraction tasks      │
│                                                                    │
│ STRUCTURED OUTPUT                                                  │
│ Three layers: schema in prompt + client validation + retry loop    │
│ Tool-based schema enforcement is more reliable than prompt-based   │
│ tool_choice: force a specific tool → guaranteed schema compliance  │
│ Multi-pass: independent verification call, not same conversation   │
│                                                                    │
│ CONTEXT MANAGEMENT                                                 │
│ Context rot degrades quality before you hit the window limit       │
│ /compact = continue session, summarize history                     │
│ /clear = start fresh, unrelated task                               │
│ Server-side compaction: add compact_20260112 beta header           │
│ Compaction thrashing → delegate high-volume work to subagent       │
│ Handoff document = structured state transfer between sessions      │
│                                                                    │
│ RELIABILITY                                                        │
│ Confidence thresholds in system prompt — >90%/70-90%/<70%         │
│ Escalation triggers: prod, delete, destroy, scale down, terminate  │
│ Error tiers: retry (transient) → fallback → escalate              │
│ Max 3-5 retry attempts before escalating to human                 │
└────────────────────────────────────────────────────────────────────┘
```

---

## Exam Practice Questions — Prompting & Context

**Q1.** A log extraction pipeline returns malformed JSON on roughly 15% of calls. The schema is defined in the system prompt and Claude is instructed to return only JSON. What is the most reliable architectural fix?

- A) Switch to a more capable model
- B) Add few-shot examples of correct JSON output and implement a retry loop feeding parse errors back to Claude ✓
- C) Increase `max_tokens` to prevent truncation
- D) Use a lower temperature setting

*Why B: Malformed JSON at 15% suggests the model occasionally adds preambles or breaks formatting under edge cases. Few-shot examples reinforce the exact format. The retry loop with error feedback corrects it on the next attempt. Model switching (A) addresses capability, not format compliance.*

---

**Q2.** An agent running a long incident investigation session starts repeating solutions it already tried and forgetting early constraints. The context window is at 60% utilization. What is the most appropriate intervention?

- A) Increase `max_tokens` to allow more output
- B) Switch to a model with a larger context window
- C) Run `/compact` with directed instructions to preserve key decisions and constraints ✓
- D) Start a fresh session from scratch

*Why C: This is context rot — quality degrading before the window is full. /compact summarizes and resets, preserving what matters. The session continues without losing the thread. A fresh session (D) loses all current context unnecessarily.*

---

**Q3.** An extraction agent using server-side compaction appears to be compacting after every response without making forward progress. What is the root cause and fix?

- A) The compaction threshold is set too low — increase the trigger token value
- B) A tool is generating more output per call than compaction reclaims — delegate that tool work to a subagent ✓
- C) The model is hitting rate limits — implement backoff
- D) The system prompt is too long — reduce its size

*Why B: This is compaction thrashing. When a single tool produces more tokens than the summary saves, the agent loops. The architectural fix is moving that high-volume tool work to a subagent with its own isolated context.*

---

**Q4.** You need Claude to always return a JSON object with specific required fields. Which approach gives the strongest schema enforcement?

- A) Include the schema in the system prompt and validate client-side
- B) Use few-shot examples showing correct JSON structure
- C) Define the schema as a tool and use `tool_choice` to force Claude to call it ✓
- D) Use a stop sequence to prevent Claude from adding preambles

*Why C: Tool-based enforcement is validated by the API layer — Claude must conform to the JSON schema in the tool definition. The other approaches rely on the model following prompt instructions, which is less reliable.*

---

## What's Next

**`04-tool-use-mcp-and-agents.md`** covers the two heaviest exam domains combined — Tool Design & MCP Integration (18%) and Agentic Architecture & Orchestration (27%). This is where the biggest concentration of exam questions lives. We'll go deep on MCP server design, transport protocols, tool boundaries, the full agentic loop, and hub-and-spoke orchestration patterns.

---

## Official Resources

- [Prompt Engineering Guide](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
- [Tool Use for Structured Output](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [Context Windows Reference](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Server-Side Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction)
- [Message Batches API](https://docs.anthropic.com/en/docs/build-with-claude/batch-processing)

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*  
*Found an error or want to contribute? PRs welcome.*
