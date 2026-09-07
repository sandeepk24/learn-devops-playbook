# 05 — Production, Security, and Evals
## Safety Guardrails, Evaluation Frameworks, Observability, and Deploying Claude at Scale

> **Series:** Anthropic Fundamentals for DevOps Engineers → CCAR-F  
> **Exam Domains:** Cross-domain production patterns spanning all five domains  
> **Why This File Exists:** The exam doesn't just test whether you know how to build with Claude — it tests whether you know how to ship it responsibly and keep it working after deployment. This is everything that happens *after* the agent works in dev.

---

## What You'll Learn Here

Passing the CCAR-F requires knowing more than architecture patterns. It requires understanding how to validate that your system actually does what you think it does, how to defend it against misuse, how to observe it when it misbehaves in production, and how to manage the cost and safety tradeoffs that show up at scale.

This file covers evaluation design and grading methods, programmatic vs prompt-based guardrails, production observability for agentic systems, secrets management and security posture, and the minimum-complexity design principle that the exam explicitly tests. By the end you'll have a complete mental model of what "production-ready" means for a Claude-based system.

---

## Part 1 — The Minimum Complexity Principle

Before we get into production hardening, the exam tests a principle that most engineers violate instinctively: start with the simplest architecture that could possibly work.

<citation index="58-1">Anthropic's guidance on building effective agents is clear: start with the simplest solution possible — a single LLM call with retrieval and in-context examples — and add agentic steps only when simpler approaches fall short.</citation>

This runs counter to the instinct of engineers who've just learned about multi-agent hub-and-spoke architectures. The architecture is powerful, but complexity has a cost — more moving parts means more failure modes, harder debugging, and slower iteration.

```
┌──────────────────────────────────────────────────────────────────┐
│          Architecture Selection by Task Complexity               │
├────────────────────────┬─────────────────────────────────────────┤
│ Start Here             │ Add Complexity When                     │
├────────────────────────┼─────────────────────────────────────────┤
│ Single LLM call        │ Context alone isn't enough              │
│ + retrieved context    │ → add RAG                               │
├────────────────────────┼─────────────────────────────────────────┤
│ Single agent + tools   │ Task requires actions beyond reasoning  │
│                        │ → add tools                             │
├────────────────────────┼─────────────────────────────────────────┤
│ Multi-agent            │ Context window limits, specialization   │
│ hub-and-spoke          │ needed, genuine parallelism possible    │
├────────────────────────┼─────────────────────────────────────────┤
│ Full pipeline          │ Sequential dependencies where output    │
│ orchestration          │ of each step feeds the next             │
└────────────────────────┴─────────────────────────────────────────┘
```

> **📝 Exam Tip:** When a scenario asks "what architecture should this team start with for a customer support agent?" the answer is almost always the simplest viable option — single agent with a small tool set — not a multi-agent pipeline. The exam explicitly tests the principle of not over-engineering.

---

## Part 2 — Guardrails: Programmatic vs Prompt-Based

<citation index="26-1">The exam distinguishes between programmatic enforcement and prompt-based guardrails — this is a named concept in Domain 4.</citation> Understanding when to use each — and why — is one of the most practical skills in this certification.

### The Fundamental Difference

```
Prompt-based guardrail:
  "Do not reveal confidential customer data."
  → Claude will try to comply
  → But prompts can be ignored under adversarial pressure
  → Not a security control — a behavioral nudge

Programmatic guardrail:
  if any(word in output for word in BLOCKED_PATTERNS):
      raise GuardrailViolation("Output blocked")
  → Deterministic — fires every time, no exceptions
  → Claude's reasoning is irrelevant
  → This is a security control
```

Production systems need both, applied in layers. Prompt-based guardrails shape Claude's default behavior. Programmatic guardrails catch whatever slips through.

### Input Guardrails — Before Claude Sees It

```python
import anthropic
import re
from dataclasses import dataclass

client = anthropic.Anthropic()

@dataclass
class GuardrailResult:
    passed: bool
    violation_type: str | None = None
    message: str | None = None


# Patterns to catch before the request reaches Claude
INPUT_BLOCKLIST = [
    r"ignore (all |your )?(previous |prior )?instructions",
    r"forget (everything|your instructions)",
    r"you are now (a|an)",
    r"do not follow (your |any |the )?rules",
    r"bypass (your |the |all )?guidelines",
    r"jailbreak",
    r"DAN mode",
]

PII_PATTERNS = [
    r"\b\d{3}-\d{2}-\d{4}\b",              # SSN
    r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",  # Credit card
    r"\b[A-Z]{2}\d{6,9}\b",               # Passport number
]


def check_input(user_message: str) -> GuardrailResult:
    """Run programmatic checks on user input before sending to Claude."""

    # Prompt injection detection
    for pattern in INPUT_BLOCKLIST:
        if re.search(pattern, user_message, re.IGNORECASE):
            return GuardrailResult(
                passed=False,
                violation_type="prompt_injection",
                message="Request contains instruction override attempt"
            )

    # PII detection — don't send raw PII to the model
    for pattern in PII_PATTERNS:
        if re.search(pattern, user_message):
            return GuardrailResult(
                passed=False,
                violation_type="pii_detected",
                message="Input contains sensitive identifiers — please redact before submitting"
            )

    # Length check — very long inputs may be token flooding attacks
    if len(user_message) > 50000:
        return GuardrailResult(
            passed=False,
            violation_type="input_too_long",
            message="Input exceeds maximum allowed length"
        )

    return GuardrailResult(passed=True)
```

### Output Guardrails — After Claude Responds

```python
# Patterns to block in Claude's output
OUTPUT_BLOCKLIST = [
    r"\b(password|secret|api[_-]?key)\s*[:=]\s*\S+",  # Credential leak
    r"\b\d{3}-\d{2}-\d{4}\b",                          # SSN in output
    r"(rm -rf|format [A-Z]:|del /f/s/q)",               # Destructive commands
]

CONFIDENTIAL_TERMS = ["INTERNAL USE ONLY", "CONFIDENTIAL", "proprietary"]


def check_output(claude_response: str, context: dict = None) -> GuardrailResult:
    """Run programmatic checks on Claude's output before returning to the user."""

    # Block credential patterns
    for pattern in OUTPUT_BLOCKLIST:
        if re.search(pattern, claude_response, re.IGNORECASE):
            return GuardrailResult(
                passed=False,
                violation_type="sensitive_data_in_output",
                message="Response blocked — contains potentially sensitive data"
            )

    # Block confidential document contents
    for term in CONFIDENTIAL_TERMS:
        if term.lower() in claude_response.lower():
            return GuardrailResult(
                passed=False,
                violation_type="confidential_content",
                message="Response references confidential materials"
            )

    return GuardrailResult(passed=True)


def safe_claude_call(user_message: str, system_prompt: str) -> dict:
    """
    Complete request pipeline with input and output guardrails.
    This is the pattern for any production-facing Claude endpoint.
    """

    # Layer 1: Input guardrail
    input_check = check_input(user_message)
    if not input_check.passed:
        return {
            "success": False,
            "blocked_at": "input",
            "reason": input_check.violation_type,
            "user_message": input_check.message
        }

    # Layer 2: Claude call
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    output_text = response.content[0].text

    # Layer 3: Output guardrail
    output_check = check_output(output_text)
    if not output_check.passed:
        return {
            "success": False,
            "blocked_at": "output",
            "reason": output_check.violation_type,
            "user_message": "Response could not be delivered — please contact support"
        }

    return {
        "success": True,
        "response": output_text,
        "usage": {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens
        }
    }
```

### Agent-Specific Guardrails: Bounding Autonomous Behavior

<citation index="58-1">Autonomous agents run in a loop, so you must bound them with stopping conditions and a maximum number of turns to prevent runaway cost or infinite loops. The Agent SDK exposes options like maxTurns for exactly this. Clear stop criteria are a core reliability guardrail for agentic systems.</citation>

```python
AGENT_GUARDRAILS = {
    "max_iterations": 10,           # Hard cap on loop iterations
    "max_tool_calls": 25,           # Cap on total tool calls per session
    "max_cost_usd": 0.50,           # Budget limit — stop if exceeded
    "require_confirmation_for": [   # Actions needing human sign-off
        "create_jira_ticket",
        "restart_ecs_service",
        "scale_service",
        "delete_resource"
    ],
    "forbidden_tools": [            # Tools never callable in this context
        "run_terraform_destroy",
        "drop_database"
    ]
}


def check_agent_guardrails(
    tool_name: str,
    iteration: int,
    total_tool_calls: int,
    estimated_cost: float
) -> GuardrailResult:
    """Per-tool-call guardrail check inside the agentic loop."""

    if tool_name in AGENT_GUARDRAILS["forbidden_tools"]:
        return GuardrailResult(
            passed=False,
            violation_type="forbidden_tool",
            message=f"Tool '{tool_name}' is not permitted in this agent context"
        )

    if iteration >= AGENT_GUARDRAILS["max_iterations"]:
        return GuardrailResult(
            passed=False,
            violation_type="iteration_limit",
            message=f"Agent exceeded {AGENT_GUARDRAILS['max_iterations']} iterations"
        )

    if total_tool_calls >= AGENT_GUARDRAILS["max_tool_calls"]:
        return GuardrailResult(
            passed=False,
            violation_type="tool_call_limit",
            message="Agent exceeded maximum tool call budget"
        )

    if estimated_cost >= AGENT_GUARDRAILS["max_cost_usd"]:
        return GuardrailResult(
            passed=False,
            violation_type="cost_limit",
            message=f"Agent session cost exceeded ${AGENT_GUARDRAILS['max_cost_usd']:.2f} limit"
        )

    if tool_name in AGENT_GUARDRAILS["require_confirmation_for"]:
        return GuardrailResult(
            passed=False,
            violation_type="confirmation_required",
            message=f"Human confirmation required before executing '{tool_name}'"
        )

    return GuardrailResult(passed=True)
```

> **📝 Exam Tip:** The exam distinguishes between prompt-based guardrails ("don't do X") and programmatic guardrails (code that blocks X). Prompt-based = behavioral guidance, can be bypassed. Programmatic = deterministic enforcement, cannot be bypassed by Claude. Production systems need both layers.

---

## Part 3 — Evaluation Framework Design

Evals are the discipline that turns "it seems to work" into a measurable, repeatable, audit-defensible answer. The exam tests eval design as an explicit skill — not just knowing that evals exist, but understanding how to design them for different task types.

<citation index="64-1">Building a successful LLM-based application starts with clearly defining your success criteria and then designing evaluations to measure performance against them. Evals should be built around the actual task your product performs, with real inputs, golden answers, and a grading method suited to the task.</citation>

### The Three Grading Methods

```
┌──────────────────────────────────────────────────────────────────┐
│               Eval Grading Methods                               │
├──────────────────────┬───────────────────────┬───────────────────┤
│ Method               │ When to Use           │ Limitations       │
├──────────────────────┼───────────────────────┼───────────────────┤
│ Deterministic        │ Structured output,    │ Requires ground   │
│ (exact match, regex, │ classification,       │ truth; can't      │
│ JSON field match,    │ extraction where      │ handle subjective  │
│ F1 score)            │ correct answer        │ quality           │
│                      │ is known              │                   │
├──────────────────────┼───────────────────────┼───────────────────┤
│ LLM-as-Judge         │ Subjective quality,   │ Model bias toward │
│ (Claude grades       │ reasoning quality,    │ its own outputs;  │
│ Claude's output)     │ nuanced correctness   │ use a different   │
│                      │ where exact match     │ model as judge    │
│                      │ is impossible         │ when possible     │
├──────────────────────┼───────────────────────┼───────────────────┤
│ Human Review         │ High-stakes outputs,  │ Expensive, slow;  │
│ Queue                │ ambiguous LLM judge   │ reserve for cases │
│                      │ results (0.4-0.6      │ where automation  │
│                      │ score range),         │ confidence is low │
│                      │ ground truth creation │                   │
└──────────────────────┴───────────────────────┴───────────────────┘
```

### Building a Production Eval Pipeline

```python
import anthropic
import json
import statistics
from dataclasses import dataclass, field
from typing import Callable, Any

client = anthropic.Anthropic()


@dataclass
class EvalCase:
    case_id: str
    input: str
    expected_output: Any         # Ground truth
    metadata: dict = field(default_factory=dict)


@dataclass
class EvalResult:
    case_id: str
    actual_output: str
    score: float                 # 0.0 to 1.0
    grader_used: str
    passed: bool
    details: dict = field(default_factory=dict)


def deterministic_grader(actual: str, expected: Any, grader_config: dict) -> float:
    """
    Exact match, regex, or JSON field grading.
    Use for extraction, classification, structured output.
    """
    grader_type = grader_config.get("type", "exact_match")

    if grader_type == "exact_match":
        return 1.0 if actual.strip().lower() == str(expected).strip().lower() else 0.0

    elif grader_type == "json_field_match":
        try:
            parsed = json.loads(actual)
            field_name = grader_config["field"]
            actual_value = parsed.get(field_name)
            return 1.0 if str(actual_value).lower() == str(expected).lower() else 0.0
        except (json.JSONDecodeError, KeyError):
            return 0.0

    elif grader_type == "contains":
        return 1.0 if str(expected).lower() in actual.lower() else 0.0

    elif grader_type == "classification":
        # Multi-class: return 1 if correct, 0 if wrong
        return 1.0 if actual.strip().upper() == str(expected).upper() else 0.0

    return 0.0


def llm_judge_grader(actual: str, expected: str, criteria: str) -> float:
    """
    Use Claude as a judge for subjective quality assessment.
    Returns a normalized score 0.0 to 1.0.
    """
    judge_prompt = f"""
    You are an impartial evaluator. Score the following response on a scale of 1-5.

    Evaluation criteria: {criteria}

    Expected answer (reference): {expected}
    Actual response: {actual}

    Return ONLY a JSON object: {{"score": <1-5>, "reasoning": "<one sentence>"}}
    """

    response = client.messages.create(
        model="claude-sonnet-4-6",   # Use same model for consistency
        max_tokens=256,
        messages=[{"role": "user", "content": judge_prompt}]
    )

    try:
        result = json.loads(response.content[0].text)
        raw_score = result["score"]
        return (raw_score - 1) / 4.0  # Normalize 1-5 to 0.0-1.0
    except Exception:
        return 0.5   # Fallback on parse failure — flag for human review


def run_eval_suite(
    eval_cases: list[EvalCase],
    system_prompt: str,
    model: str = "claude-sonnet-4-6",
    grader_config: dict = None,
    pass_threshold: float = 0.7
) -> dict:
    """
    Run a complete eval suite and return aggregate metrics.
    This is the pattern for CI/CD regression testing.
    """
    if grader_config is None:
        grader_config = {"type": "exact_match"}

    results = []

    for case in eval_cases:
        # Get Claude's response for this eval case
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": case.input}]
        )
        actual_output = response.content[0].text

        # Grade the response
        if grader_config.get("type") == "llm_judge":
            score = llm_judge_grader(
                actual=actual_output,
                expected=str(case.expected_output),
                criteria=grader_config.get("criteria", "accuracy and completeness")
            )
            grader_used = "llm_judge"
        else:
            score = deterministic_grader(actual_output, case.expected_output, grader_config)
            grader_used = grader_config.get("type", "exact_match")

        results.append(EvalResult(
            case_id=case.case_id,
            actual_output=actual_output,
            score=score,
            grader_used=grader_used,
            passed=score >= pass_threshold
        ))

    # Aggregate metrics
    scores = [r.score for r in results]
    pass_rate = sum(1 for r in results if r.passed) / len(results)

    return {
        "model": model,
        "total_cases": len(results),
        "pass_rate": pass_rate,
        "mean_score": statistics.mean(scores),
        "min_score": min(scores),
        "failed_cases": [r.case_id for r in results if not r.passed],
        "human_review_queue": [
            r.case_id for r in results
            if grader_used == "llm_judge" and 0.4 <= r.score <= 0.6
        ],
        "results": results
    }


# Example: Eval suite for incident classification
eval_cases = [
    EvalCase("case-001", "ECS service has 0 running tasks", "P1", {"category": "outage"}),
    EvalCase("case-002", "Deployment took 5 minutes instead of 2", "P3", {"category": "perf"}),
    EvalCase("case-003", "One pod restarted once in the last hour", "P4", {"category": "noise"}),
    EvalCase("case-004", "Database connection pool exhausted, 50% requests failing", "P1", {"category": "outage"}),
]

system = "Classify the severity of this DevOps alert as P1, P2, P3, or P4. Return only the severity label."

results = run_eval_suite(
    eval_cases=eval_cases,
    system_prompt=system,
    grader_config={"type": "classification"},
    pass_threshold=1.0   # Classification must be exact
)

print(f"Pass rate: {results['pass_rate']:.0%}")
print(f"Failed: {results['failed_cases']}")
```

### Eval-in-CI: Regression Testing for Claude Systems

The pattern that prevents silent model degradation after prompt changes or model version updates:

```yaml
# .github/workflows/claude-eval.yml — works with Bamboo equivalently
name: Claude Eval Regression

on:
  pull_request:
    paths:
      - 'prompts/**'
      - 'src/agent/**'

jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: pip install anthropic pytest

      - name: Run eval suite against candidate
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python run_evals.py \
            --suite datasets/incident-classification \
            --model claude-sonnet-4-6 \
            --output results/candidate.json

      - name: Compare against baseline
        run: |
          python compare_evals.py \
            --baseline results/baseline.json \
            --candidate results/candidate.json \
            --fail-on-regression 0.05   # Fail if pass rate drops >5%

      - name: Update baseline on main merge
        if: github.ref == 'refs/heads/main'
        run: |
          cp results/candidate.json results/baseline.json
          git add results/baseline.json
          git commit -m "chore: update eval baseline [skip ci]"
```

```python
# compare_evals.py — used by the CI step above
import json
import sys
import argparse

def compare_eval_runs(baseline_path: str, candidate_path: str, regression_threshold: float):
    with open(baseline_path) as f:
        baseline = json.load(f)
    with open(candidate_path) as f:
        candidate = json.load(f)

    baseline_pass_rate = baseline["pass_rate"]
    candidate_pass_rate = candidate["pass_rate"]
    delta = candidate_pass_rate - baseline_pass_rate

    print(f"Baseline pass rate: {baseline_pass_rate:.1%}")
    print(f"Candidate pass rate: {candidate_pass_rate:.1%}")
    print(f"Delta: {delta:+.1%}")

    if delta < -regression_threshold:
        print(f"\n❌ REGRESSION: Pass rate dropped {abs(delta):.1%} (threshold: {regression_threshold:.1%})")
        print(f"Newly failing cases: {set(candidate['failed_cases']) - set(baseline['failed_cases'])}")
        sys.exit(1)

    print(f"\n✅ No regression detected")
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline")
    parser.add_argument("--candidate")
    parser.add_argument("--fail-on-regression", type=float, default=0.05)
    args = parser.parse_args()
    compare_eval_runs(args.baseline, args.candidate, args.fail_on_regression)
```

> **📝 Exam Tip:** The exam tests the three grading methods and when each applies. Deterministic = structured output where correct answer is known. LLM-as-judge = subjective quality. Human review = ambiguous results or ground truth creation. A scenario asking "how do you catch prompt regressions after a system prompt change" → CI eval suite with baseline comparison.

---

## Part 4 — Observability for Agentic Systems

Traditional application observability — metrics, logs, traces — maps awkwardly onto agentic systems because agent behavior is non-deterministic and multi-turn. The key shift is tracing the *agentic trajectory*, not just individual API calls.

### What to Instrument

```python
import time
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class AgentTrace:
    """Complete trace of one agent session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task: str = ""
    model: str = ""
    started_at: float = field(default_factory=time.time)
    iterations: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    final_output: str = ""
    completed_at: float | None = None
    success: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    error: str | None = None

    @property
    def duration_seconds(self) -> float:
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def estimated_cost_usd(self) -> float:
        # Sonnet 4.6: $3/$15 per million tokens
        input_cost = (self.total_input_tokens / 1_000_000) * 3.0
        output_cost = (self.total_output_tokens / 1_000_000) * 15.0
        return input_cost + output_cost

    def log_iteration(self, iteration: int, stop_reason: str, tokens: dict):
        self.iterations.append({
            "iteration": iteration,
            "stop_reason": stop_reason,
            "input_tokens": tokens.get("input_tokens", 0),
            "output_tokens": tokens.get("output_tokens", 0),
            "timestamp": time.time()
        })
        self.total_input_tokens += tokens.get("input_tokens", 0)
        self.total_output_tokens += tokens.get("output_tokens", 0)

    def log_tool_call(self, tool_name: str, inputs: dict, result: Any, duration_ms: float, error: bool = False):
        self.tool_calls.append({
            "tool_name": tool_name,
            "inputs": inputs,  # Log what Claude passed
            "success": not error,
            "duration_ms": duration_ms,
            "timestamp": time.time()
        })

    def to_log_entry(self) -> dict:
        return {
            "session_id": self.session_id,
            "task": self.task[:200],   # Truncate for log storage
            "model": self.model,
            "success": self.success,
            "duration_s": round(self.duration_seconds, 2),
            "iterations": len(self.iterations),
            "tool_calls": len(self.tool_calls),
            "tool_call_breakdown": {
                tc["tool_name"]: sum(
                    1 for t in self.tool_calls if t["tool_name"] == tc["tool_name"]
                )
                for tc in self.tool_calls
            },
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "error": self.error
        }


def run_traced_agent(task: str) -> tuple[str, AgentTrace]:
    """
    Instrumented agentic loop — captures full trajectory for observability.
    """
    import anthropic
    client = anthropic.Anthropic()

    trace = AgentTrace(task=task, model="claude-sonnet-4-6")
    messages = [{"role": "user", "content": task}]
    iteration = 0

    try:
        while iteration < 10:
            iteration += 1

            response = client.messages.create(
                model=trace.model,
                max_tokens=4096,
                tools=devops_tools,
                messages=messages
            )

            trace.log_iteration(
                iteration=iteration,
                stop_reason=response.stop_reason,
                tokens={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens
                }
            )

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                final_text = next(
                    (b.text for b in response.content if b.type == "text"), ""
                )
                trace.final_output = final_text
                trace.success = True
                trace.completed_at = time.time()
                log.info("agent_session_complete", extra=trace.to_log_entry())
                return final_text, trace

            elif response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    start = time.time()
                    try:
                        func = TOOL_DISPATCH[block.name]
                        result = func(**block.input)
                        duration_ms = (time.time() - start) * 1000

                        trace.log_tool_call(
                            tool_name=block.name,
                            inputs=block.input,
                            result=result,
                            duration_ms=duration_ms
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result)
                        })

                    except Exception as e:
                        duration_ms = (time.time() - start) * 1000
                        trace.log_tool_call(
                            tool_name=block.name,
                            inputs=block.input,
                            result=None,
                            duration_ms=duration_ms,
                            error=True
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Error: {str(e)}",
                            "is_error": True
                        })

                messages.append({"role": "user", "content": tool_results})

    except Exception as e:
        trace.error = str(e)
        trace.completed_at = time.time()
        log.error("agent_session_error", extra=trace.to_log_entry())
        raise

    return "", trace
```

### Key Metrics to Track in Production

```
┌──────────────────────────────────────────────────────────────────┐
│               Production Agent Metrics                           │
├────────────────────────┬─────────────────────────────────────────┤
│ Metric                 │ What It Tells You                       │
├────────────────────────┼─────────────────────────────────────────┤
│ Task success rate      │ % of sessions reaching end_turn         │
│                        │ successfully (not hitting iteration cap) │
├────────────────────────┼─────────────────────────────────────────┤
│ Mean iterations/task   │ Baseline for detecting loops and        │
│                        │ over-complex tasks                      │
├────────────────────────┼─────────────────────────────────────────┤
│ Tool call distribution │ Which tools fire most; misrouting       │
│                        │ shows up as unexpected tool spikes      │
├────────────────────────┼─────────────────────────────────────────┤
│ Token usage/session    │ Cost tracking; growth signals context   │
│                        │ management issues                       │
├────────────────────────┼─────────────────────────────────────────┤
│ Tool error rate        │ Infrastructure health; high error rate  │
│                        │ means downstream services degraded      │
├────────────────────────┼─────────────────────────────────────────┤
│ P95 session duration   │ Latency SLA; long tail indicates stuck  │
│                        │ loops or slow external tools            │
├────────────────────────┼─────────────────────────────────────────┤
│ Cost/task              │ Budget tracking; spikes indicate        │
│                        │ context explosion or runaway loops      │
└────────────────────────┴─────────────────────────────────────────┘
```

---

## Part 5 — Security Architecture

### Secrets Management for Claude Integrations

The most common security mistake in Claude deployments is handling credentials the same way you'd handle them in a traditional app — and then discovering that tool call logs, which contain the tool inputs Claude passed, are being stored with embedded credentials.

```python
import os
import boto3
from functools import lru_cache

# ✅ CORRECT: Load secrets at startup from AWS Secrets Manager
# Never pass secrets through tool inputs or store them in prompts

@lru_cache(maxsize=None)
def get_secret(secret_name: str) -> dict:
    """Fetch and cache secrets at application startup."""
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=secret_name)
    import json
    return json.loads(response["SecretString"])


# Tool implementations use pre-loaded secrets — never receive them as parameters
def query_database(sql_query: str) -> list:
    """
    MCP tool: execute a read-only database query.
    Credentials are loaded from Secrets Manager — never passed by Claude.
    """
    secrets = get_secret("prod/database/readonly")

    import psycopg2
    conn = psycopg2.connect(
        host=secrets["host"],
        database=secrets["database"],
        user=secrets["username"],
        password=secrets["password"]   # Never in tool schema, never in logs
    )

    cursor = conn.cursor()
    cursor.execute(sql_query)
    return cursor.fetchall()


# ❌ WRONG: Credentials as tool parameters (gets logged, visible to Claude)
bad_tool_schema = {
    "name": "query_database",
    "input_schema": {
        "properties": {
            "sql_query": {"type": "string"},
            "db_password": {"type": "string"},   # NEVER DO THIS
            "api_key": {"type": "string"}         # NEVER DO THIS
        }
    }
}
```

### Isolation: Eval Environments Must Not Touch Production

<citation index="59-1">Anthropic found three cases where Claude models accessed the internet from third-party testing environments and affected real organizations. Misconfigurations allowed unintended internet access, not model intent.</citation>

This is a real, documented failure mode — not theoretical. The architectural requirement is clear:

```python
import os

def get_environment_config() -> dict:
    """
    Load environment-appropriate configuration.
    Eval environments must be fully isolated from production systems.
    """
    env = os.environ.get("DEPLOYMENT_ENV", "development")

    configs = {
        "production": {
            "database_url": os.environ["PROD_DATABASE_URL"],
            "allow_internet": True,
            "allow_destructive_tools": False,
            "require_human_confirmation": ["delete", "scale", "restart"],
            "max_agent_iterations": 10
        },
        "staging": {
            "database_url": os.environ["STAGING_DATABASE_URL"],
            "allow_internet": True,
            "allow_destructive_tools": False,
            "require_human_confirmation": ["delete"],
            "max_agent_iterations": 15
        },
        "evaluation": {
            "database_url": "sqlite:///eval_sandbox.db",  # Local only — no network
            "allow_internet": False,                       # Network blocked
            "allow_destructive_tools": False,
            "require_human_confirmation": [],
            "max_agent_iterations": 5                      # Shorter for eval efficiency
        },
        "development": {
            "database_url": os.environ.get("DEV_DATABASE_URL", "sqlite:///dev.db"),
            "allow_internet": False,
            "allow_destructive_tools": False,
            "require_human_confirmation": [],
            "max_agent_iterations": 5
        }
    }

    config = configs.get(env, configs["development"])

    # Hard safety check — eval must never reach production
    if env == "evaluation" and "prod" in config.get("database_url", "").lower():
        raise RuntimeError("CRITICAL: Eval environment pointing at production database")

    return config
```

---

## Part 6 — Cost Management at Scale

Production Claude deployments can generate surprising costs quickly, especially when agents run multiple iterations per task. These are the levers you control.

### The Four Cost Levers

```python
import anthropic

client = anthropic.Anthropic()

class CostAwareAgent:
    """
    Agent with all four cost optimization patterns active simultaneously.
    """

    def __init__(self, system_prompt: str, model: str = "claude-haiku-4-5-20251001"):
        self.model = model
        self.session_cost = 0.0
        self.budget_limit = 0.50   # $0.50 per session

        # LEVER 1: Prompt caching for large stable system context
        self.system = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"}   # Cache the large context
            }
        ]

    def estimate_call_cost(self, input_tokens: int, output_tokens: int) -> float:
        # Haiku pricing: $1/$5 per million tokens
        if "haiku" in self.model:
            return (input_tokens * 1.0 + output_tokens * 5.0) / 1_000_000
        # Sonnet pricing: $3/$15 per million tokens
        elif "sonnet" in self.model:
            return (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000
        # Opus pricing: $5/$25 per million tokens
        else:
            return (input_tokens * 5.0 + output_tokens * 25.0) / 1_000_000

    def call(self, messages: list, max_tokens: int = 1024) -> dict:
        # LEVER 2: Budget check before each call
        if self.session_cost >= self.budget_limit:
            raise RuntimeError(f"Session budget ${self.budget_limit} exhausted")

        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=self.system,
            messages=messages
        )

        call_cost = self.estimate_call_cost(
            response.usage.input_tokens,
            response.usage.output_tokens
        )
        self.session_cost += call_cost

        return {
            "content": response.content,
            "stop_reason": response.stop_reason,
            "usage": response.usage,
            "call_cost": call_cost,
            "session_cost": self.session_cost
        }


# LEVER 3: Batch API for non-real-time workloads (50% cost reduction)
def batch_process_alerts(alerts: list[str]) -> list:
    """Process many alerts overnight using Batch API — half the cost of synchronous."""
    batch = client.messages.batches.create(
        requests=[
            {
                "custom_id": f"alert-{i}",
                "params": {
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 256,
                    "system": "Classify severity as P1/P2/P3/P4. Return only the label.",
                    "messages": [{"role": "user", "content": alert}]
                }
            }
            for i, alert in enumerate(alerts)
        ]
    )
    return batch


# LEVER 4: Right-sizing — don't over-provision model tier
TASK_MODEL_MAP = {
    "alert_classification": "claude-haiku-4-5-20251001",     # Simple → Haiku
    "log_summarization": "claude-haiku-4-5-20251001",         # Simple → Haiku
    "incident_triage": "claude-sonnet-4-6",                    # Reasoning → Sonnet
    "root_cause_analysis": "claude-sonnet-4-6",                # Reasoning → Sonnet
    "architecture_review": "claude-opus-4-8",                  # Complex → Opus
    "postmortem_generation": "claude-sonnet-4-6",              # Balanced → Sonnet
}
```

---

## Part 7 — The Transparency Principle

<citation index="58-1">Exposing an agent's planning steps makes behavior observable, so engineers can debug, audit, and intervene when the agent goes off track. Transparency is a core operability principle for production agents — it's not a correctness guarantee.</citation>

This is a named exam principle. Agents that show their work are debuggable. Agents that don't are black boxes that fail in production and can't be diagnosed.

```python
# ✅ Transparent agent — shows its planning and reasoning
transparent_system = """
You are a DevOps incident response agent.

Before taking any action:
1. State what you understand the problem to be
2. List what information you need to gather
3. State which tool you're calling and why
4. After getting results, state what they tell you

Format your reasoning as:
[Understanding]: <your interpretation of the task>
[Plan]: <what you'll investigate and why>
[Action]: <tool name and why you're calling it>
[Finding]: <what the result tells you>
[Conclusion]: <your diagnosis and recommendations>
"""

# ❌ Opaque agent — impossible to debug when it fails
opaque_system = """
You are a DevOps agent. Investigate issues and solve them.
"""
```

The transparent version generates logs you can read. When it makes a wrong call, you can see exactly where its reasoning diverged from the correct path. That's the difference between a system you can maintain and one you have to rebuild.

---

## Summary — What to Lock In Before Moving On

```
┌────────────────────────────────────────────────────────────────────┐
│  05 — Production, Security & Evals: Key Takeaways                 │
├────────────────────────────────────────────────────────────────────┤
│ ARCHITECTURE                                                       │
│ Start simple — add complexity only when simpler approaches fail    │
│ Single agent → add tools → multi-agent → full pipeline            │
│                                                                    │
│ GUARDRAILS                                                         │
│ Prompt-based = behavioral guidance (can be bypassed)              │
│ Programmatic = deterministic enforcement (cannot be bypassed)      │
│ Production needs both layers: input → Claude → output              │
│ Agent guardrails: max_iterations, max_cost, forbidden_tools        │
│                                                                    │
│ EVALS                                                              │
│ Deterministic: exact match, classification, JSON field             │
│ LLM-as-judge: subjective quality (0.4-0.6 → human review)         │
│ Human review: high-stakes, ambiguous, ground truth creation        │
│ CI eval suite: baseline comparison catches prompt regressions      │
│                                                                    │
│ OBSERVABILITY                                                      │
│ Trace agentic trajectories — not just individual API calls         │
│ Key metrics: success rate, iterations/task, tool distribution,     │
│   cost/session, P95 duration                                       │
│                                                                    │
│ SECURITY                                                           │
│ Secrets in Secrets Manager, never in tool schemas or parameters    │
│ Eval environments: no internet, no prod DB, no destructive tools   │
│ Log tool inputs for audit — but scrub secrets before logging       │
│                                                                    │
│ COST                                                               │
│ 4 levers: model right-sizing, prompt caching, Batch API,          │
│   per-session budget limits                                        │
│                                                                    │
│ TRANSPARENCY                                                       │
│ Expose planning steps — agents that show their work are debuggable │
└────────────────────────────────────────────────────────────────────┘
```

---

## Exam Practice Questions — Production, Security & Evals

**Q1.** A team is building a customer support agent. They propose a multi-agent hub-and-spoke architecture with five specialist subagents before building anything. According to Anthropic's guidance, what should they do instead?

- A) Proceed — hub-and-spoke is the recommended starting pattern
- B) Start with a single LLM call with retrieved context and add complexity only when simpler approaches fall short ✓
- C) Build two agents and expand from there
- D) Use the pipeline pattern instead of hub-and-spoke

*Why B: Anthropic's explicit guidance is to start with the simplest viable solution. A multi-agent architecture before you understand the failure modes of a single agent is premature complexity.*

---

**Q2.** A system prompt says "never reveal internal documentation." A user manipulates the prompt to override this instruction and Claude reveals internal content. What is the correct architectural fix?

- A) Improve the system prompt wording to be more emphatic
- B) Switch to a more instruction-following model
- C) Add programmatic output guardrails that block responses containing confidential terms ✓
- D) Use a higher temperature setting for more consistent behavior

*Why C: Prompt-based guardrails can be bypassed under adversarial conditions. Programmatic output guardrails are deterministic — they fire regardless of what Claude generates or what prompt manipulation occurred.*

---

**Q3.** An eval suite produces LLM-as-judge scores between 0.4 and 0.6 for 20% of test cases. What should happen to those cases?

- A) Round them to 0 (fail) to be conservative
- B) Round them to 1 (pass) — the judge is probably right
- C) Send them to a human review queue for manual grading ✓
- D) Re-run them with a different model and average the scores

*Why C: The 0.4-0.6 range is the LLM judge's uncertainty zone — scores that are too close to call for automated grading. Human review resolves genuine ambiguity; rounding introduces systematic bias.*

---

**Q4.** A Claude agent in an evaluation environment is configured to query a database for test data. The evaluation run accidentally connects to the production database and modifies live records. What architectural control would have prevented this?

- A) Use a read-only database user for the eval agent
- B) Isolate the eval environment with a local database and block network access to production systems ✓
- C) Add a confirmation prompt before any write operation
- D) Run evals with a less capable model that is less likely to make writes

*Why B: Complete environment isolation — separate database, no production network access — is the only control that prevents this class of failure. Anthropic documented exactly this failure mode in production eval runs.*

---

**Q5.** An agent's session cost is tracked. At $0.48 against a $0.50 budget, the agent calls a tool that would require 3 more LLM calls to complete. What should the agent do?

- A) Complete the task — $0.02 overage is acceptable
- B) Immediately terminate the session
- C) Escalate to human — report current status and that the budget is nearly exhausted ✓
- D) Switch to Haiku to reduce per-token cost for remaining calls

*Why C: The agent should not silently overspend or terminate without context. Escalating with current status lets the human decide whether to continue, extend the budget, or take over — which is the correct behavior under budget constraints.*

---

## What's Next

**`06-exam-prep-roadmap.md`** is the final file — a complete study checklist organized by domain, a full 60-question practice exam with answer rationale, domain-by-domain gap analysis, and final exam-day logistics. This is the file you read the night before your sitting.

---

## Official Resources

- [Anthropic Eval Guide](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)
- [Strengthen Guardrails](https://docs.anthropic.com/en/docs/test-and-evaluate/strengthen-guardrails)
- [Reduce Hallucinations](https://docs.anthropic.com/en/docs/test-and-evaluate/reduce-hallucinations)
- [AI Constitution (Safety Reference)](https://www.anthropic.com/constitution)
- [Responsible Scaling Policy](https://www.anthropic.com/responsible-scaling-policy)
- [Batch API for Cost Reduction](https://docs.anthropic.com/en/docs/build-with-claude/batch-processing)

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*  
*Found an error or want to contribute? PRs welcome.*
