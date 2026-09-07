# 04 — Tool Use, MCP, and Agentic Architecture
## Tool Design, the Model Context Protocol, the Agentic Loop, and Hub-and-Spoke Orchestration

> **Series:** Anthropic Fundamentals for DevOps Engineers → CCAR-F  
> **Exam Domains:** Domain 1 — Agentic Architecture & Orchestration (27%) | Domain 4 — Tool Design & MCP Integration (18%)  
> **Combined Weight:** ~27 questions out of 60 — the single largest chunk of the exam

---

## What You'll Learn Here

This is the exam's heaviest territory. Domain 1 alone is 27% of your score — roughly 16 questions — and it's the domain where most engineers lose points because they understand the concepts in isolation but can't reason about them under production conditions.

The material here builds in a deliberate sequence: tools first (because agents are built from tools), then MCP (because MCP is how tools reach the outside world), then the agentic loop (because the loop is how Claude drives tool use), then orchestration patterns (because real systems need more than one agent). By the end, you'll be able to look at a broken agent scenario and diagnose exactly where the failure is.

---

## Part 1 — Tool Design Fundamentals

### What Tools Actually Are

When Claude "uses a tool," what's really happening is this: Claude generates a structured JSON object describing the function it wants to call and the arguments it wants to pass. Your code receives that JSON, runs the actual function, and passes the result back. Claude never executes anything directly — it requests, you execute, you return.

That distinction matters architecturally. It means Claude's tool use is fully auditable. Every call goes through your code. You control what runs, when it runs, and what Claude gets back.

```
┌──────────────────────────────────────────────────────────────┐
│                  Tool Use — What Actually Happens             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. You define tools (name, description, JSON schema)        │
│  2. You pass tools to messages.create()                      │
│  3. Claude reasons about which tool to call and with what    │
│  4. Claude returns stop_reason: "tool_use" + tool call JSON  │
│  5. YOUR code executes the actual function                   │
│  6. You return the result as a tool_result content block     │
│  7. Claude incorporates the result and continues reasoning   │
│  8. Repeat until stop_reason: "end_turn"                     │
│                                                              │
│  Claude never executes code. Claude requests execution.      │
└──────────────────────────────────────────────────────────────┘
```

### Writing Tool Schemas That Work

Tool descriptions are not comments — they are instructions. Claude reads your description to decide *when* to call the tool and *how* to populate its arguments. A vague description produces wrong calls. An ambiguous schema produces malformed inputs.

```python
import anthropic
import json
import subprocess

client = anthropic.Anthropic()

# Define tools for a DevOps automation agent
devops_tools = [
    {
        "name": "get_ecs_service_status",
        "description": (
            "Retrieve the current status of an ECS service including running task count, "
            "desired task count, pending count, and recent events. "
            "Use this when you need to diagnose ECS service health or verify deployment state. "
            "Do NOT use this for non-ECS workloads — use get_pod_status for Kubernetes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cluster_name": {
                    "type": "string",
                    "description": "The ECS cluster name (e.g., 'prod-us-east-1-cluster')"
                },
                "service_name": {
                    "type": "string",
                    "description": "The ECS service name (e.g., 'api-gateway-service')"
                },
                "region": {
                    "type": "string",
                    "description": "AWS region (e.g., 'us-east-1'). Defaults to us-east-1 if not specified.",
                    "default": "us-east-1"
                }
            },
            "required": ["cluster_name", "service_name"]
        }
    },
    {
        "name": "get_cloudwatch_logs",
        "description": (
            "Fetch recent CloudWatch log entries for a log group. "
            "Use this to investigate errors, check application output, or trace request failures. "
            "Limit to the most recent logs needed — do not fetch more than 100 lines unless specifically asked."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "log_group": {
                    "type": "string",
                    "description": "CloudWatch log group name (e.g., '/ecs/prod-api-gateway')"
                },
                "minutes": {
                    "type": "integer",
                    "description": "How many minutes of logs to retrieve (1-60). Default: 15.",
                    "minimum": 1,
                    "maximum": 60,
                    "default": 15
                },
                "filter_pattern": {
                    "type": "string",
                    "description": "CloudWatch Insights filter pattern. Optional — omit to return all logs."
                }
            },
            "required": ["log_group"]
        }
    },
    {
        "name": "create_jira_ticket",
        "description": (
            "Create a Jira incident ticket. "
            "ONLY use this when the user explicitly asks to create a ticket, "
            "or when you've identified a P1/P2 issue that requires formal tracking. "
            "Do NOT create tickets for investigations or informational queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Ticket title — concise, under 80 characters"
                },
                "description": {
                    "type": "string",
                    "description": "Full description including symptoms, impact, and investigation steps taken"
                },
                "priority": {
                    "type": "string",
                    "enum": ["P1", "P2", "P3", "P4"],
                    "description": "Ticket priority based on business impact"
                },
                "assignee": {
                    "type": "string",
                    "description": "Jira username of assignee. Optional — leave unset for auto-assignment."
                }
            },
            "required": ["summary", "description", "priority"]
        }
    }
]
```

Notice what each description does: it tells Claude *when* to use this tool (diagnosis, investigation, explicit user request), *when not to* (non-ECS workloads, informational queries), and any behavioral constraints (don't fetch more than 100 lines). These aren't nice-to-have — they're what prevents Claude from over-calling tools or calling the wrong one.

> **📝 Exam Tip:** The exam tests tool description quality directly. A scenario where Claude calls a tool too eagerly, calls the wrong tool, or passes bad arguments is almost always a tool description problem, not a model problem. The fix is always improving the description and schema — not switching models.

### Tool Boundaries and Reasoning Overload

<citation index="50-1">Managing tool boundaries to prevent reasoning overload is an explicit exam topic in Domain 4.</citation> Reasoning overload happens when you give Claude too many tools in a single context, or tools that are too similar to each other. Claude has to reason about which tool to use for every decision — more tools means more reasoning overhead, and similar tools create ambiguity that produces wrong calls.

```
The tool overload problem — what not to do:

❌ 40 tools in a single agent context
❌ get_ec2_instance, get_ec2_status, describe_ec2, check_ec2_health
   (four tools doing the same thing — Claude doesn't know which to call)
❌ Tools with overlapping trigger conditions and no clear differentiation
❌ Catch-all tools: "do_anything", "run_command" with no scope

✅ 5-10 tightly scoped tools per agent
✅ One tool per distinct operation
✅ Descriptions that explicitly say when NOT to use the tool
✅ Separate tools for separate domains; route to specialist subagents
```

The architectural solution to too many tools isn't consolidation — it's specialization. A coordinator agent with 5 tools, each of which routes to a specialist subagent with its own 5-10 tools, scales to 50 capabilities without overloading any single agent's reasoning.

---

## Part 2 — The Full Agentic Loop

The agentic loop is the heartbeat of every Claude-powered agent. Understanding it completely — including all the ways it can fail — is the single most important thing you can learn for Domain 1.

### The Loop in Code

```python
import anthropic
import json

client = anthropic.Anthropic()

# Tool implementations — the actual functions your code runs
def get_ecs_service_status(cluster_name: str, service_name: str, region: str = "us-east-1") -> dict:
    """Real implementation would call boto3. Simplified here for clarity."""
    import boto3
    ecs = boto3.client("ecs", region_name=region)
    response = ecs.describe_services(cluster=cluster_name, services=[service_name])
    service = response["services"][0]
    return {
        "status": service["status"],
        "running_count": service["runningCount"],
        "desired_count": service["desiredCount"],
        "pending_count": service["pendingCount"],
        "events": [e["message"] for e in service["events"][:5]]
    }


def get_cloudwatch_logs(log_group: str, minutes: int = 15, filter_pattern: str = None) -> list:
    """Fetch recent log entries from CloudWatch."""
    import boto3, time
    logs = boto3.client("logs")
    end_time = int(time.time() * 1000)
    start_time = end_time - (minutes * 60 * 1000)

    kwargs = {
        "logGroupName": log_group,
        "startTime": start_time,
        "endTime": end_time,
        "limit": 100
    }
    if filter_pattern:
        kwargs["filterPattern"] = filter_pattern

    response = logs.filter_log_events(**kwargs)
    return [e["message"] for e in response.get("events", [])]


def create_jira_ticket(summary: str, description: str, priority: str, assignee: str = None) -> dict:
    """Create a Jira ticket via API. Returns ticket key."""
    # Real implementation calls Jira REST API
    return {"ticket_key": "INFRA-4821", "url": "https://jira.company.com/browse/INFRA-4821"}


# Tool dispatch map — routes tool names to Python functions
TOOL_DISPATCH = {
    "get_ecs_service_status": get_ecs_service_status,
    "get_cloudwatch_logs": get_cloudwatch_logs,
    "create_jira_ticket": create_jira_ticket,
}


def run_agentic_loop(user_task: str, max_iterations: int = 10) -> str:
    """
    The complete agentic loop.
    Continues until stop_reason is 'end_turn' or max_iterations is reached.
    """
    messages = [{"role": "user", "content": user_task}]
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        print(f"\n[Loop iteration {iteration}]")

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            tools=devops_tools,
            messages=messages,
            system=(
                "You are a DevOps incident response agent. "
                "Investigate issues methodically. Use tools to gather real data. "
                "When you have enough information, provide a clear diagnosis and recommended actions."
            )
        )

        print(f"  stop_reason: {response.stop_reason}")

        # Append Claude's full response to conversation history
        # Critical: include ALL content blocks, not just text
        messages.append({"role": "assistant", "content": response.content})

        # Branch on stop_reason — this is the entire logic of the loop
        if response.stop_reason == "end_turn":
            # Claude is done — extract and return the final text
            final_text = next(
                (block.text for block in response.content if block.type == "text"),
                "No text response generated."
            )
            print(f"[Agent complete after {iteration} iterations]")
            return final_text

        elif response.stop_reason == "tool_use":
            # Claude wants to call one or more tools
            # Process ALL tool_use blocks — Claude may request multiple in one response
            tool_results = []

            for block in response.content:
                if block.type != "tool_use":
                    continue

                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                print(f"  Tool call: {tool_name}({json.dumps(tool_input, indent=2)})")

                try:
                    func = TOOL_DISPATCH[tool_name]
                    result = func(**tool_input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": json.dumps(result)
                    })
                    print(f"  Tool result: {str(result)[:200]}...")

                except KeyError:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"Error: Unknown tool '{tool_name}'",
                        "is_error": True
                    })

                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": f"Error executing {tool_name}: {str(e)}",
                        "is_error": True
                    })

            # Return ALL tool results in a single user message
            messages.append({"role": "user", "content": tool_results})

        elif response.stop_reason == "max_tokens":
            # Response was truncated — don't treat as completion
            return f"Error: Response truncated at iteration {iteration}. Increase max_tokens."

        else:
            # Unexpected stop_reason — don't assume it's safe to continue
            return f"Error: Unexpected stop_reason '{response.stop_reason}'"

    # Reached max iterations without end_turn
    return f"Error: Agent exceeded {max_iterations} iterations without completing. Possible loop."


# Run it
result = run_agentic_loop(
    "The prod api-gateway ECS service seems down. Check its status and logs, then tell me what's wrong."
)
print(f"\n[Final answer]\n{result}")
```

### The Anti-Patterns That Fail the Exam

<citation index="57-1">The exam specifically tests avoiding these agentic loop anti-patterns: parsing natural language signals to determine loop termination, setting arbitrary iteration caps as the primary stopping mechanism, and checking for assistant text content as a completion indicator.</citation>

```python
# ❌ ANTI-PATTERN 1: Parsing text to detect completion
# Claude might say "I'm done" in different ways — this breaks
while True:
    response = client.messages.create(...)
    text = response.content[0].text
    if "done" in text.lower() or "complete" in text.lower():  # WRONG
        break

# ❌ ANTI-PATTERN 2: Iteration cap as the ONLY stopping condition
for i in range(10):           # You'll loop 10 times even when Claude is done at iteration 2
    response = client.messages.create(...)
    messages.append({"role": "assistant", "content": response.content})

# ❌ ANTI-PATTERN 3: Only appending text, not tool_use blocks
messages.append({
    "role": "assistant",
    "content": response.content[0].text  # WRONG — drops tool_use blocks
})

# ✅ CORRECT: Branch on stop_reason, append full content
messages.append({"role": "assistant", "content": response.content})  # Full content
if response.stop_reason == "end_turn":
    break  # The only reliable completion signal
elif response.stop_reason == "tool_use":
    # Execute tools and continue
    pass
```

> **📝 Exam Tip:** If a scenario describes "an agent that never terminates" or "keeps calling tools after it should be done," the answer is always a loop control bug — usually the code is not breaking on `stop_reason: "end_turn"` or is treating partial responses as completion signals.

---

## Part 3 — Multi-Agent Topology: Hub-and-Spoke

<citation index="52-1">Multi-agent topology patterns — hub-and-spoke, pipeline, peer-to-peer — are explicitly listed as exam content in Domain 1.</citation> Hub-and-spoke is the dominant production pattern, and it's what most CCAR-F scenarios are built around.

### Why Hub-and-Spoke

Hub-and-spoke solves three problems that single-agent systems can't: tool overload (each subagent has a focused set of tools), context isolation (subagents don't share conversation history, so their contexts stay small), and parallel execution (multiple subagents can work simultaneously).

```
┌─────────────────────────────────────────────────────────────────────┐
│               Hub-and-Spoke Architecture                            │
│                                                                     │
│                    ┌──────────────────┐                             │
│                    │  COORDINATOR     │ ← Sonnet/Opus               │
│                    │  (Hub)           │   Plans, delegates,          │
│                    │                  │   aggregates results         │
│                    └──┬───┬───┬───┬──┘                              │
│                       │   │   │   │                                 │
│            ┌──────────┘   │   │   └──────────┐                     │
│            │          ┌───┘   └───┐          │                     │
│            ▼          ▼           ▼          ▼                     │
│     ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐   │
│     │ ECS Agent  │ │ Logs Agent │ │ Metrics    │ │ Jira Agent │   │
│     │ (Haiku)    │ │ (Haiku)    │ │ Agent      │ │ (Haiku)    │   │
│     │            │ │            │ │ (Haiku)    │ │            │   │
│     │ Tools:     │ │ Tools:     │ │ Tools:     │ │ Tools:     │   │
│     │ - ECS API  │ │ - CW Logs  │ │ - Prom     │ │ - Create   │   │
│     │ - EC2 API  │ │ - LogInsig │ │ - Grafana  │ │ - Update   │   │
│     └────────────┘ └────────────┘ └────────────┘ └────────────┘   │
│                                                                     │
│  Key property: Each subagent has ISOLATED context.                  │
│  They do NOT share the coordinator's conversation history.          │
└─────────────────────────────────────────────────────────────────────┘
```

<citation index="56-1">Subagents operate with isolated context — they do not inherit the coordinator's conversation history automatically. The coordinator is responsible for task decomposition, delegation, result aggregation, and deciding which subagents to invoke based on query complexity.</citation>

### The Implementation

```python
import anthropic
from concurrent.futures import ThreadPoolExecutor, as_completed

client = anthropic.Anthropic()

# Each subagent is a self-contained function with its own tools and system prompt
def ecs_diagnostic_agent(task: str) -> str:
    """Specialist agent for ECS-specific diagnostics."""
    ecs_tools = [devops_tools[0]]  # Only the ECS tool

    messages = [{"role": "user", "content": task}]

    for _ in range(5):  # Max iterations per subagent
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",   # Haiku for leaf nodes
            max_tokens=2048,
            tools=ecs_tools,
            messages=messages,
            system=(
                "You are an ECS specialist agent. "
                "Investigate ECS service issues and report findings as structured data. "
                "Be concise — your output is consumed by a coordinator agent."
            )
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return next(
                (b.text for b in response.content if b.type == "text"), ""
            )

        elif response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    func = TOOL_DISPATCH[block.name]
                    result = func(**block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {str(e)}",
                        "is_error": True
                    })
            messages.append({"role": "user", "content": tool_results})

    return "Error: ECS agent hit iteration limit"


def logs_diagnostic_agent(task: str) -> str:
    """Specialist agent for CloudWatch log analysis."""
    log_tools = [devops_tools[1]]  # Only the logs tool
    messages = [{"role": "user", "content": task}]

    for _ in range(5):
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            tools=log_tools,
            messages=messages,
            system=(
                "You are a log analysis specialist. "
                "Find errors, patterns, and root causes in CloudWatch logs. "
                "Be concise — your output feeds a coordinator agent."
            )
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            return next((b.text for b in response.content if b.type == "text"), "")
        elif response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = TOOL_DISPATCH[block.name](**block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
                except Exception as e:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: {str(e)}",
                        "is_error": True
                    })
            messages.append({"role": "user", "content": tool_results})

    return "Error: Logs agent hit iteration limit"


def coordinator_agent(incident_description: str) -> str:
    """
    Hub coordinator — plans investigation, dispatches subagents in parallel,
    synthesizes results into a final diagnosis.
    """

    # Step 1: Plan — coordinator decides what to investigate
    plan_response = client.messages.create(
        model="claude-sonnet-4-6",   # Coordinator gets Sonnet — needs planning ability
        max_tokens=1024,
        system=(
            "You are an incident response coordinator. "
            "Given an incident description, decide what needs to be investigated. "
            "Return a JSON object: "
            '{"ecs_task": "what to investigate in ECS (or null)", '
            '"logs_task": "what to check in logs (or null)", '
            '"summary_needed": true/false}'
        ),
        messages=[{"role": "user", "content": incident_description}]
    )

    plan = json.loads(plan_response.content[0].text)
    print(f"[Coordinator] Plan: {plan}")

    # Step 2: Dispatch subagents in parallel
    results = {}
    subagent_tasks = {}

    if plan.get("ecs_task"):
        subagent_tasks["ecs"] = (ecs_diagnostic_agent, plan["ecs_task"])
    if plan.get("logs_task"):
        subagent_tasks["logs"] = (logs_diagnostic_agent, plan["logs_task"])

    with ThreadPoolExecutor(max_workers=len(subagent_tasks)) as executor:
        futures = {
            executor.submit(func, task): name
            for name, (func, task) in subagent_tasks.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
                print(f"[Coordinator] {name} agent complete")
            except Exception as e:
                results[name] = f"Error: {str(e)}"

    # Step 3: Synthesize — coordinator aggregates all findings
    synthesis_prompt = f"""
    Incident: {incident_description}

    Investigation findings:
    {json.dumps(results, indent=2)}

    Synthesize these findings into:
    1. Root cause (one sentence)
    2. Current impact
    3. Immediate remediation steps (ordered)
    4. Whether a Jira ticket should be created (P1/P2/P3/P4)
    """

    synthesis_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system="You are an incident response coordinator. Be concise and actionable.",
        messages=[{"role": "user", "content": synthesis_prompt}]
    )

    return synthesis_response.content[0].text


# Run the full hub-and-spoke pipeline
result = coordinator_agent(
    "prod-api-gateway ECS service has 0 running tasks. Last deploy was 20 minutes ago."
)
print(f"\n[Incident Report]\n{result}")
```

### Multi-Agent Topology Comparison

The exam tests all three topology patterns. Know when each one applies.

```
┌──────────────────────────────────────────────────────────────────────┐
│               Multi-Agent Topology Patterns                          │
├────────────────┬────────────────────────┬────────────────────────────┤
│ Pattern        │ Structure              │ When to Use                │
├────────────────┼────────────────────────┼────────────────────────────┤
│ Hub-and-Spoke  │ One coordinator,       │ Complex investigations     │
│                │ N specialist agents    │ requiring parallel work    │
│                │                        │ across domains             │
├────────────────┼────────────────────────┼────────────────────────────┤
│ Pipeline       │ Agent A → Agent B →    │ Sequential transformations │
│                │ Agent C (each output   │ where each step depends    │
│                │ feeds the next)        │ on the previous            │
├────────────────┼────────────────────────┼────────────────────────────┤
│ Peer-to-Peer   │ Agents communicate     │ Rarely used — complex      │
│                │ directly with each     │ coordination, harder to    │
│                │ other                  │ debug and audit            │
└────────────────┴────────────────────────┴────────────────────────────┘
```

> **📝 Exam Tip:** Hub-and-spoke is almost always the correct answer when a scenario describes a complex multi-step task with distinct investigation domains. Pipeline is correct when steps are strictly sequential with dependencies. Peer-to-peer is almost never the right answer in exam scenarios — it's the most complex and least auditable pattern.

---

## Part 4 — Task Decomposition

Good task decomposition is what separates agents that work from agents that look like they work until they don't. The exam tests this in the context of the coordinator's planning step.

### Sequential vs Parallel Decomposition

```python
def decompose_task(complex_task: str) -> dict:
    """
    Coordinator breaks a task into sequential and parallel subtasks.
    Returns a structured execution plan.
    """
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system="""
        You are a task decomposition specialist. Break complex tasks into subtasks.
        
        Return JSON:
        {
            "sequential_phases": [
                {
                    "phase": 1,
                    "description": "what this phase does",
                    "parallel_tasks": [
                        {"task": "description", "agent": "which specialist"},
                        {"task": "description", "agent": "which specialist"}
                    ],
                    "depends_on": null
                },
                {
                    "phase": 2,
                    "description": "what this phase does",  
                    "parallel_tasks": [...],
                    "depends_on": 1
                }
            ],
            "success_criteria": "how we know the task is complete"
        }
        
        Parallel tasks within a phase can run simultaneously.
        Phases must run sequentially — each phase depends on the prior one completing.
        """,
        messages=[{"role": "user", "content": f"Decompose: {complex_task}"}]
    )

    return json.loads(response.content[0].text)


# Example decomposition output for an incident investigation:
example_plan = {
    "sequential_phases": [
        {
            "phase": 1,
            "description": "Gather current state data",
            "parallel_tasks": [
                {"task": "Check ECS service status and events", "agent": "ecs"},
                {"task": "Fetch last 30 min of application logs", "agent": "logs"},
                {"task": "Check recent CloudWatch metrics for anomalies", "agent": "metrics"}
            ],
            "depends_on": None
        },
        {
            "phase": 2,
            "description": "Diagnose root cause from gathered data",
            "parallel_tasks": [
                {"task": "Correlate ECS events with log errors", "agent": "coordinator"}
            ],
            "depends_on": 1
        },
        {
            "phase": 3,
            "description": "Execute remediation",
            "parallel_tasks": [
                {"task": "Create Jira P1 ticket with full context", "agent": "jira"},
                {"task": "Post incident channel update", "agent": "notification"}
            ],
            "depends_on": 2
        }
    ],
    "success_criteria": "ECS service running count equals desired count AND no new errors in logs"
}
```

---

## Part 5 — Model Context Protocol (MCP)

MCP is Domain 4 on the exam — 18%, roughly 11 questions. It's the protocol that lets Claude reach outside itself and talk to real systems.

### The Problem MCP Solves

<citation index="48-1">Before MCP, connecting an AI model to external tools was an engineering nightmare. Every combination of model and tool required a custom integration — a fragile, expensive, and unscalable approach. Anthropic described this as the M×N problem: M models multiplied by N tools equals M×N separate integrations to build and maintain.</citation>

MCP collapses that to M+N: build a server once per tool, build a client once per model, and any combination works automatically.

### The Architecture: Three Roles

<citation index="46-1">The host is the AI application — Claude Desktop, a custom enterprise agent framework. The MCP client is embedded within the host and manages the stateful JSON-RPC channels to each connected server. Each MCP server is a dedicated adapter for a single external system: GitHub, Slack, PostgreSQL, and so on.</citation>

```
┌──────────────────────────────────────────────────────────────────┐
│                    MCP Architecture                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────┐                    │
│  │  HOST (your application / Claude Desktop)│                   │
│  │  ┌───────────────────────────────────┐  │                    │
│  │  │  MCP CLIENT (one per server)      │  │                    │
│  │  │  Manages JSON-RPC channel         │  │                    │
│  │  └──────────────┬────────────────────┘  │                    │
│  └─────────────────┼───────────────────────┘                    │
│                    │ JSON-RPC 2.0                                │
│          ┌─────────┼──────────┐                                 │
│          ▼         ▼          ▼                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                        │
│  │MCP Server│ │MCP Server│ │MCP Server│                        │
│  │(GitHub)  │ │(AWS)     │ │(Jira)    │                        │
│  │          │ │          │ │          │                        │
│  │Tools:    │ │Tools:    │ │Tools:    │                        │
│  │- list_PRs│ │- describe│ │- create  │                        │
│  │- get_diff│ │  services│ │  ticket  │                        │
│  │- comment │ │- get_logs│ │- update  │                        │
│  └──────────┘ └──────────┘ └──────────┘                        │
│                                                                  │
│  One server per external system. One client per server.         │
└──────────────────────────────────────────────────────────────────┘
```

### The Three MCP Primitives

Every MCP server exposes some combination of these three capabilities:

```
┌──────────────────────────────────────────────────────────────────┐
│               MCP Primitives                                     │
├────────────┬─────────────────────────────────────────────────────┤
│ Primitive  │ Description                       │ Example         │
├────────────┼───────────────────────────────────┼─────────────────┤
│ Tools      │ Functions the model can call.      │ create_ticket() │
│            │ Most common primitive.             │ query_logs()    │
│            │ Controlled by model reasoning.     │ get_service()   │
├────────────┼───────────────────────────────────┼─────────────────┤
│ Resources  │ Data the model can read.           │ /logs/prod      │
│            │ URI-addressed, read-only.          │ /config/prod    │
│            │ Like file system access.           │ db://schema     │
├────────────┼───────────────────────────────────┼─────────────────┤
│ Prompts    │ Pre-defined workflow templates.    │ analyze_deploy  │
│            │ User-invoked (slash commands).     │ review_pr       │
│            │ Not model-controlled.              │ triage_incident │
└────────────┴───────────────────────────────────┴─────────────────┘
```

> **📝 Exam Tip:** The exam tests which primitive to use for which use case. Tools = model-initiated function calls. Resources = model reads data at a URI. Prompts = human-invoked workflow templates. A scenario asking "how does Claude read a configuration file via MCP" → Resources. "How does Claude list open PRs" → Tools. "How does an engineer invoke a standard investigation workflow" → Prompts.

### Transport Protocols: stdio vs Streamable HTTP

<citation index="44-1">MCP supports two transport modes. stdio handles local inter-process communication and is the default for running local MCP servers in Claude Desktop or Claude Code. Streamable HTTP, introduced in the November 2025 spec, replaces the legacy SSE transport and enables MCP servers to run as remote services.</citation>

<citation index="46-1">The legacy SSE transport was officially deprecated June 18, 2025. Streamable HTTP enables remote server deployments behind load balancers.</citation>

```
┌──────────────────────────────────────────────────────────────────┐
│               MCP Transport Comparison                           │
├──────────────────┬──────────────────┬────────────────────────────┤
│ Factor           │ stdio            │ Streamable HTTP             │
├──────────────────┼──────────────────┼────────────────────────────┤
│ Process model    │ Subprocess       │ Remote service              │
│ Network          │ None (IPC)       │ HTTP/HTTPS                  │
│ Latency          │ Lowest           │ Higher (network round-trip) │
│ Deployment       │ Local only       │ Cloud, load-balanced        │
│ Scalability      │ Single process   │ Horizontal scaling          │
│ Authentication   │ Process-level    │ OAuth 2.1 / API keys        │
│ Best for         │ Developer tools, │ Production services,        │
│                  │ Claude Desktop,  │ multi-user deployments,     │
│                  │ local testing    │ enterprise integrations     │
│ State            │ Stateful         │ Stateless (horizontal)      │
│                  │ (session-bound)  │ or Stateful (single node)   │
└──────────────────┴──────────────────┴────────────────────────────┘
```

> **📝 Exam Tip:** The exam loves transport selection questions. stdio = local, low-latency, developer tools. Streamable HTTP = remote, scalable, production. Any scenario mentioning "load balancer," "multiple users," or "cloud deployment" → Streamable HTTP. Any scenario with "Claude Desktop," "local development," or "subprocess" → stdio.

### Building an MCP Server in Python

```python
from mcp.server.fastmcp import FastMCP
import boto3
import json

# Create the server — name becomes the server identifier
mcp = FastMCP("devops-aws-server")


@mcp.tool()
def get_ecs_service_status(cluster_name: str, service_name: str, region: str = "us-east-1") -> str:
    """
    Get the current status of an ECS service.
    Returns running count, desired count, and recent service events.
    Use for ECS health checks and deployment verification.
    """
    try:
        ecs = boto3.client("ecs", region_name=region)
        response = ecs.describe_services(
            cluster=cluster_name,
            services=[service_name]
        )
        service = response["services"][0]

        return json.dumps({
            "status": service["status"],
            "running_count": service["runningCount"],
            "desired_count": service["desiredCount"],
            "pending_count": service["pendingCount"],
            "events": [e["message"] for e in service["events"][:5]]
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def restart_ecs_service(cluster_name: str, service_name: str, region: str = "us-east-1") -> str:
    """
    Force a new deployment of an ECS service (triggers task replacement).
    This is a destructive operation — use only when explicitly requested.
    Equivalent to 'aws ecs update-service --force-new-deployment'.
    """
    try:
        ecs = boto3.client("ecs", region_name=region)
        response = ecs.update_service(
            cluster=cluster_name,
            service=service_name,
            forceNewDeployment=True
        )
        return json.dumps({
            "status": "restart_triggered",
            "deployment_id": response["service"]["deployments"][0]["id"]
        })

    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.resource("aws://ecs/clusters")
def list_ecs_clusters() -> str:
    """List all ECS clusters in the default region."""
    ecs = boto3.client("ecs")
    response = ecs.list_clusters()
    return json.dumps({"clusters": response["clusterArns"]})


@mcp.prompt()
def incident_triage(service_name: str, environment: str) -> str:
    """Standard incident triage workflow for an ECS service."""
    return (
        f"Investigate the {service_name} service in {environment}. "
        f"Check ECS service status, recent events, and CloudWatch logs. "
        f"Identify root cause and provide remediation steps. "
        f"Create a Jira P1 ticket if the service has been down more than 5 minutes."
    )


# Run with stdio transport (default for local use)
if __name__ == "__main__":
    mcp.run()   # stdio by default

    # For Streamable HTTP (remote/production):
    # mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

### Connecting to an MCP Server from Your Agent

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import anthropic

async def run_agent_with_mcp():
    """Agent that uses tools from an MCP server."""
    anthropic_client = anthropic.Anthropic()

    # Connect to the MCP server
    server_params = StdioServerParameters(
        command="python",
        args=["devops_mcp_server.py"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the connection
            await session.initialize()

            # Discover what tools this server offers
            tools_result = await session.list_tools()
            mcp_tools = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema
                }
                for tool in tools_result.tools
            ]

            print(f"MCP server exposes {len(mcp_tools)} tools: {[t['name'] for t in mcp_tools]}")

            # Use discovered tools in a Claude API call
            messages = [{"role": "user", "content": "What's the status of the prod-api ECS service?"}]

            while True:
                response = anthropic_client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=2048,
                    tools=mcp_tools,
                    messages=messages
                )

                messages.append({"role": "assistant", "content": response.content})

                if response.stop_reason == "end_turn":
                    print(next(b.text for b in response.content if b.type == "text"))
                    break

                elif response.stop_reason == "tool_use":
                    tool_results = []
                    for block in response.content:
                        if block.type != "tool_use":
                            continue
                        # Execute the tool via MCP
                        result = await session.call_tool(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result.content[0].text if result.content else "No result"
                        })
                    messages.append({"role": "user", "content": tool_results})


asyncio.run(run_agent_with_mcp())
```

### MCP Security — What the Exam Tests

<citation index="43-1">MCP servers are a significant attack surface. Treat all tool inputs as untrusted — they come from an LLM, not directly from the user. Apply strict JSON Schema with `additionalProperties: false`. A malicious server could change tool definitions after the host has approved them — this is called a rug pull attack.</citation>

Key security principles for the exam:

```python
# ✅ Strict schema — reject unexpected parameters
"input_schema": {
    "type": "object",
    "properties": {
        "cluster_name": {"type": "string"},
        "service_name": {"type": "string"}
    },
    "required": ["cluster_name", "service_name"],
    "additionalProperties": False    # Reject any extra fields
}

# ✅ Validate and sanitize all tool inputs before execution
def execute_tool_safely(tool_name: str, tool_input: dict) -> str:
    # Allowlist tool names
    if tool_name not in ALLOWED_TOOLS:
        raise ValueError(f"Tool '{tool_name}' is not in the allowed list")

    # Validate input values — don't trust Claude's parameter values
    if tool_name == "get_ecs_service_status":
        assert re.match(r'^[a-zA-Z0-9\-_]+$', tool_input.get("cluster_name", ""))
        assert re.match(r'^[a-zA-Z0-9\-_]+$', tool_input.get("service_name", ""))

    return TOOL_DISPATCH[tool_name](**tool_input)

# ✅ Scope permissions per tool — don't give read-only tools write permissions
# ✅ Use OAuth 2.1 for Streamable HTTP servers — not API keys in headers
# ✅ Never log tool inputs that contain secrets or PII
```

> **📝 Exam Tip:** The exam tests MCP security with scenarios where a tool receives unexpected parameters or where an agent blindly trusts Claude's tool inputs. The correct answer is always `additionalProperties: false` in the schema and server-side input validation — never trust what comes from the model without validating it.

---

## Part 6 — Error Classification in Agentic Systems

<citation index="52-1">Error classification — tool errors, reasoning errors, and environment errors — is explicit exam content in Domain 1.</citation> Each type requires a different recovery strategy.

```
┌──────────────────────────────────────────────────────────────────┐
│               Agentic Error Classification                       │
├───────────────────┬──────────────────────────┬───────────────────┤
│ Error Type        │ What It Looks Like        │ Recovery          │
├───────────────────┼──────────────────────────┼───────────────────┤
│ Tool Error        │ Tool returns error status │ Return error in   │
│                   │ API unavailable           │ tool_result,      │
│                   │ Permission denied         │ let Claude adapt  │
│                   │ Invalid parameters        │                   │
├───────────────────┼──────────────────────────┼───────────────────┤
│ Reasoning Error   │ Claude calls wrong tool   │ Improve tool      │
│                   │ Passes bad arguments      │ descriptions,     │
│                   │ Loops without progress    │ add guardrails,   │
│                   │ Ignores tool results      │ restructure prompt │
├───────────────────┼──────────────────────────┼───────────────────┤
│ Environment Error │ API rate limits           │ Exponential       │
│                   │ Network timeouts          │ backoff + retry   │
│                   │ Downstream service down   │ or escalate       │
└───────────────────┴──────────────────────────┴───────────────────┘
```

```python
def handle_tool_error(tool_name: str, error: Exception, tool_use_id: str) -> dict:
    """
    Return tool errors to Claude as tool_result with is_error=True.
    Claude can reason about the error and adapt its approach.
    Do NOT raise exceptions — that breaks the agentic loop.
    """
    error_type = classify_tool_error(error)

    error_message = {
        "error_type": error_type,
        "message": str(error),
        "suggestion": {
            "permission_denied": "Check IAM permissions for this operation",
            "resource_not_found": "Verify the resource name and region",
            "rate_limited": "Reduce call frequency or use backoff",
            "timeout": "The service may be degraded — check CloudWatch"
        }.get(error_type, "Unexpected error — try an alternative approach")
    }

    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(error_message),
        "is_error": True    # Signals to Claude this is an error response
    }
```

---

## Summary — What to Lock In Before Moving On

```
┌────────────────────────────────────────────────────────────────────┐
│  04 — Tools, MCP, Agents: Key Takeaways                           │
├────────────────────────────────────────────────────────────────────┤
│ TOOL DESIGN                                                        │
│ Claude requests execution — it never runs code directly            │
│ Tool description = when to call + when NOT to call + constraints   │
│ Reasoning overload: 5-10 tools max per agent, no overlap           │
│ Fix: specialize agents, not consolidate tools                      │
│                                                                    │
│ AGENTIC LOOP                                                       │
│ Branch on stop_reason: tool_use → execute; end_turn → done        │
│ Append FULL content blocks (not just text) to history              │
│ Return ALL tool results in one user message                        │
│ Use is_error: true for tool failures — let Claude adapt            │
│ Anti-patterns: text parsing, arbitrary caps, partial appends       │
│                                                                    │
│ ORCHESTRATION                                                      │
│ Hub-and-spoke: coordinator + specialist subagents (dominant)       │
│ Subagents have ISOLATED context — no inherited history             │
│ Parallel execution: ThreadPoolExecutor for independent subagents   │
│ Coordinator = Sonnet/Opus; subagents = Haiku/Sonnet                │
│                                                                    │
│ MCP                                                                │
│ Host → Client → Server (one server per external system)           │
│ Three primitives: Tools (model-called), Resources (URI data),      │
│   Prompts (user-invoked templates)                                 │
│ Transport: stdio (local) vs Streamable HTTP (remote/prod)          │
│ SSE is deprecated as of June 2025                                  │
│ Security: additionalProperties: false, validate all inputs         │
│                                                                    │
│ ERRORS                                                             │
│ Tool → return error in tool_result with is_error: true             │
│ Reasoning → fix description/schema/prompt                          │
│ Environment → backoff retry or escalate                            │
└────────────────────────────────────────────────────────────────────┘
```

---

## Exam Practice Questions — Tools, MCP, Agents

**Q1.** An agent frequently calls `get_ec2_info` when it should call `get_ecs_service_status`. Both tools are available in the same agent context. What is the most likely cause?

- A) The model is not capable enough — switch to a higher-tier model
- B) Tool descriptions are ambiguous — add explicit "when to use" and "when NOT to use" guidance ✓
- C) There are too many tools in context — remove one
- D) Increase max_tokens to give Claude more room to reason

*Why B: Wrong tool selection is a description quality problem. Clear differentiation (including "do NOT use this for ECS") resolves the ambiguity. The model can reason correctly when descriptions are unambiguous.*

---

**Q2.** An agentic loop receives `stop_reason: "tool_use"`. The agent appends only the text blocks from `response.content` to conversation history, ignoring `tool_use` blocks. What happens on the next iteration?

- A) The loop works correctly — text blocks contain the necessary context
- B) Claude loses track of which tool it called and may request the same tool again ✓
- C) The API rejects the request with a validation error
- D) Claude automatically reconstructs the tool call from context

*Why B: The tool_use block contains the tool call ID that must match the tool_result ID in the next message. Without it, the conversation history is malformed and Claude cannot properly correlate results with requests.*

---

**Q3.** A production MCP server needs to serve multiple simultaneous users and sit behind an AWS load balancer. Which transport should it use?

- A) stdio
- B) SSE (Server-Sent Events)
- C) Streamable HTTP ✓
- D) WebSockets

*Why C: Streamable HTTP supports remote deployment, horizontal scaling, and load balancers. stdio is local-only (subprocess). SSE was deprecated June 2025. WebSockets is not an MCP transport.*

---

**Q4.** An MCP tool receives unexpected parameters from Claude that could cause a SQL injection if passed to the database. The tool schema does not include these parameters. What is the correct prevention?

- A) Validate inputs in the tool description to warn Claude not to pass unexpected parameters
- B) Use `additionalProperties: false` in the JSON schema and validate all inputs server-side ✓
- C) Switch to a tool_choice forced call to prevent unexpected parameters
- D) Rate-limit tool calls to reduce the attack surface

*Why B: Schema-level rejection (`additionalProperties: false`) drops unexpected fields before they reach your code. Server-side validation catches anything that passes schema. Defense in depth. Prompt-level warnings (A) are not reliable security controls.*

---

**Q5.** In a hub-and-spoke architecture, a subagent has completed its investigation and returned results to the coordinator. The coordinator needs to pass specific findings to a second subagent. How does the second subagent access these findings?

- A) It automatically inherits the coordinator's conversation history
- B) The coordinator explicitly passes the relevant findings in the second subagent's task prompt ✓
- C) Subagents share a common memory store
- D) The first subagent writes findings to a shared context object

*Why B: Subagents have isolated context — they do not inherit the coordinator's conversation history. The coordinator must explicitly include relevant information in the task it sends to each subagent.*

---

## What's Next

**`05-production-devops-security-and-evals.md`** covers the cross-domain production concerns: safety and guardrails, testing and evaluation frameworks, observability for agentic systems, and security patterns that apply across all five exam domains. This is the file that ties everything together for a real production deployment.

---

## Official Resources

- [Tool Use Documentation](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)
- [Agentic Systems Guide](https://docs.anthropic.com/en/docs/build-with-claude/agentic-systems)
- [MCP Specification](https://modelcontextprotocol.io/specification)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [FastMCP Documentation](https://gofastmcp.com)
- [MCP Inspector (debugging)](https://github.com/modelcontextprotocol/inspector)

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*  
*Found an error or want to contribute? PRs welcome.*
