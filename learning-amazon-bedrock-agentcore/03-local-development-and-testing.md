# Part 3: Local Development and Testing — The Loop Before AWS Sees Any of This

## Why this part exists as its own document

In the ECS world, "local testing" usually means either running the container locally with `docker run` and hoping your local env vars are close enough to task-def env vars, or just deploying to a dev cluster and iterating there because local parity was never quite worth the setup cost. AgentCore's local dev story is meaningfully better than that, and if you skip straight to `agentcore deploy` because deploying-to-see-what-happens is a habit ECS trained into you, you're paying for AWS API calls and CloudFormation cycles to catch bugs a local run would have caught in seconds. Break that habit here — it's the change in workflow that pays off the most out of everything this series asks of you.

## Starting the local server

```bash
cd LearningAgent
agentcore dev
```

This single command does more than a `docker run` would:

- Opens the **agent inspector** in your browser — a chat UI purpose-built for exercising an agent, not a generic Swagger page
- Automatically creates a Python virtual environment and installs dependencies from `pyproject.toml`
- Starts a local server that mimics the AgentCore Runtime environment on `http://localhost:8080` by default

That middle bullet is the one to notice: it's not just running your code, it's running your code inside a setup that approximates what production will do to it. That's closer to what `docker-compose` with a matched base image gives you than to a bare `python main.py`.

Options worth knowing immediately:

```bash
agentcore dev -p 3000        # different port, when 8080's taken
agentcore dev --logs          # non-interactive, streams logs directly
```

If you hit `Port 8080 in use`, it's almost always a previous dev server you forgot to kill — `lsof -ti:8080 | xargs kill -9` and move on, same muscle memory as clearing a stuck local Postgres port.

## Invoking the local agent

Two ways, and you'll use both depending on what you're debugging.

**From a second terminal, one-shot:**

```bash
agentcore dev "Hello, tell me a joke"
agentcore dev "Hello, tell me a joke" --stream    # watch tokens arrive in real time
```

**From the browser inspector**, which is where you actually want to spend most of your time once the agent has any real logic — you can see tool calls, intermediate reasoning steps, and the full request/response shape, not just the final text. This is your closest equivalent to reading CloudWatch Logs Insights output, except it's happening before anything ships to CloudWatch.

## What "local parity" does and doesn't mean here

Be precise about this with your team, because it's a common source of false confidence. The local server mimics runtime *behavior* — the request/response contract, session handling patterns. It does not replicate:

- IAM permission boundaries (locally you're generally running under your own broad credentials or a local API key, not the constrained execution role your deployed agent will run under)
- Cold start latency characteristics
- The actual provisioned Memory or Gateway resources, if you're using them — those are AWS-side services your local run either stubs or skips
- Network path differences (VPC configs, if your Gateway integrations route through a VPC)

The practical implication: a clean local run is necessary but not sufficient. It catches logic bugs, prompt issues, and tool-calling mistakes cheaply. It does not catch "the execution role can't reach the S3 bucket" or "cold start under load blows your latency SLO." Budget a real staging deployment for those — Part 5 covers what staging should look like.

## Debugging patterns that map from your ECS instincts

| ECS instinct | AgentCore equivalent |
|---|---|
| `docker logs -f <container>` | `agentcore dev --logs`, or the inspector's live log pane |
| Shelling into a running task to poke at env vars | Check `.env.local` and the inspector's request inspector panel |
| Bisecting a bad deploy by rolling back a task-def revision | Bisecting locally is cheaper — you haven't deployed yet |
| `curl` against the ALB with a crafted payload | `agentcore dev "<prompt>" --stream` or the inspector's chat pane |
| Reading `ecs describe-tasks` for a stopped-task reason | Reading the traceback in the dev server's terminal — usually more informative here, since it's your actual Python stack trace, not an ECS scheduling reason string |

The agent-specific failure modes that won't have an ECS analog:

- **Tool-calling loops that don't converge** — the agent calls a tool, gets a result, and calls the same tool again indefinitely. The inspector's step-by-step view is what catches this; a flat log tail won't make the pattern obvious.
- **Prompt/context length issues** that only surface with realistic conversation length — test with multi-turn conversations locally, not just single-shot prompts, especially once you enable memory.
- **Framework-specific error swallowing** — some agent frameworks catch and reformat exceptions in ways that obscure the real Python traceback. If an error in the inspector looks suspiciously clean, check the raw dev server terminal output too.

## Testing beyond manual chat

Manual poking in the inspector is where you start, not where you stop. Before you're comfortable calling an agent "tested":

```python
# test_agent_smoke.py — a minimal smoke test pattern
# Run against the local dev server before every deploy, same spirit
# as a pre-deploy health check curl against a staging ALB.

import httpx

LOCAL_ENDPOINT = "http://localhost:8080"

def invoke(prompt: str, session_id: str = "smoke-test") -> dict:
    response = httpx.post(
        f"{LOCAL_ENDPOINT}/invoke",
        json={"prompt": prompt, "session_id": session_id},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()

def test_basic_response():
    result = invoke("What can you help me with?")
    assert result.get("response"), "Expected non-empty response"

def test_tool_call_completes():
    # Replace with a prompt that forces your agent's actual tool
    result = invoke("Look up the status of order 12345")
    assert "error" not in result.get("response", "").lower()

def test_multi_turn_session_continuity():
    session = "smoke-test-multiturn"
    invoke("My name is Jordan.", session_id=session)
    result = invoke("What's my name?", session_id=session)
    assert "jordan" in result.get("response", "").lower()
```

Check the exact request/response shape against your framework's generated `main.py` — the field names above are illustrative, not gospel, since the HTTP contract details can vary slightly by framework integration. The point isn't the specific assertions; it's that these are cheap enough to run in CI against the local dev server, before anything touches AWS, and multi-turn session continuity is the one ECS testing habits won't naturally think to check.

## Lab

1. Scaffold the project from Part 2's lab, or reuse it.
2. Run `agentcore dev`, and deliberately send it a prompt that should trigger a tool call (or, if you haven't wired a tool yet, any multi-step reasoning prompt). Watch the inspector's step view, not just the final answer.
3. Kill the dev server mid-response and restart it. Confirm session continuity behavior — does a new `agentcore dev` process remember the prior session, or does local state reset? This tells you something real about how much you can rely on local runs to validate memory behavior versus needing a deployed Memory resource.
4. Write two or three smoke tests in the shape above and get them running against your local server before you touch Part 4.

## What's next

Part 4 is the build-and-deploy decision: CodeZip versus Container, what `agentcore deploy` actually provisions in your AWS account, and how to read the CloudFormation events it generates.

---

*Part of the [AgentCore for DevOps Engineers](README.md) series — [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook).*
