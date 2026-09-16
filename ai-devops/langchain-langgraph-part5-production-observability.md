# LangChain and LangGraph for DevOps Architects — Part 5: Production, Observability, and Evals

> Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) AI-DevOps series.
>
> **Series map:**
> 1. Core architecture: Models, Prompts, LCEL, and where LangGraph comes in
> 2. LangGraph in depth: state, nodes, edges, and control loops
> 3. Tools and agents: giving the model hands, safely
> 4. Memory and retrieval: grounding the model in your own data
> 5. **Running this in production: observability, evals, and cost control** (this post)

---

## Recap, in one paragraph

By Part 4 you have the full picture: LCEL chains for straight-line work, LangGraph for anything with a loop or a branch, tools with guardrails for letting the model act, and retrieval for grounding answers in your own docs. This last post is about the question that decides whether any of that is safe to run against real infrastructure: how do you know it's working, how do you know when it stops working, and how do you keep it from quietly running up a bill or a blast radius nobody signed off on.

---

## Tracing: the distributed trace equivalent for an LLM call

You already know why a distributed trace matters: a single user request fans out into six service calls, and when it's slow or wrong, you need to see all six, in order, with timing, not just the request and the final response. An agent loop from Part 3 has exactly the same shape — one user question can turn into a model call, a tool call, another model call, another tool call, and a final answer, and if step 4 is slow or wrong, you need to see all four steps, not just the outcome.

LangSmith is LangChain's own tracing tool, and it's close to zero-effort to turn on:

```python
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_API_KEY"] = "..."
os.environ["LANGCHAIN_PROJECT"] = "incident-triage-agent"

# every chain and graph invocation from here on gets traced automatically
result = app.invoke({"messages": [HumanMessage("Is checkout healthy?")]})
```

Once it's on, every run shows you each node, each model call with the exact prompt sent and response received, each tool call with its arguments and result, and the latency and token cost of every one of those steps. This is the same value a trace waterfall gives you for a slow API request — instead of guessing which of six steps took 4 seconds, you look at the trace and know.

You're not locked into LangSmith specifically. LangGraph and LangChain support standard callback hooks, so you can pipe the same events into whatever you already use for observability — Datadog, an OpenTelemetry collector, your own logging pipeline. The point isn't the specific tool, it's that **every model call and every tool call should be a logged, timed event**, exactly like every database query and every outbound HTTP call already is in your other services. If you wouldn't ship a service with unlogged outbound calls, don't ship an agent that way either.

---

## Evals: the test suite for something that doesn't give the same answer twice

Here's the uncomfortable part for anyone used to deterministic testing: a unit test that calls the model and asserts on an exact string will break constantly, because the model doesn't return exactly the same wording every time, even at `temperature=0`, once a prompt or a model version changes even slightly. You need a different kind of test — an eval — that checks whether an answer is *correct enough*, not whether it's *character-identical* to some fixed string.

A minimal eval set is just a list of realistic inputs with a description of what a correct answer looks like:

```python
eval_cases = [
    {
        "question": "Why did the checkout deployment fail with ImagePullBackOff?",
        "context": "Manifest references api-server:1.4.2-rc, registry only has up to 1.4.1",
        "expected_facts": ["tag 1.4.2-rc does not exist", "latest available is 1.4.1"],
    },
    {
        "question": "Is a rollback needed for a deploy that's still in progress?",
        "context": "Deploy status: in_progress, 40% of pods updated, no errors",
        "expected_facts": ["no rollback needed", "deploy is healthy and in progress"],
    },
]
```

You run each case through your chain or graph, then use a second, cheap model call to grade whether the expected facts actually show up in the answer — this pattern is usually called "LLM-as-judge," and despite the fancy name it's just a grading function:

```python
def grade(question: str, answer: str, expected_facts: list[str]) -> bool:
    verdict = grader_chain.invoke({
        "answer": answer,
        "facts": "\n".join(expected_facts)
    })
    return verdict.content.strip().lower() == "pass"

results = []
for case in eval_cases:
    answer = chain.invoke({"question": case["question"], "context": case["context"]})
    results.append(grade(case["question"], answer, case["expected_facts"]))

pass_rate = sum(results) / len(results)
print(f"Pass rate: {pass_rate:.0%}")
```

Run this in CI, the same way you'd run integration tests — on every pull request that touches a prompt, a chain, or a graph. **This is the single highest-leverage habit in this whole series.** A prompt tweak that reads like a harmless wording fix can quietly drop your pass rate from 95% to 70%, and without an eval suite, you find out from a user, not from your pipeline. With one, it's a failed check on the PR, exactly like a broken unit test would be.

**Do** build a small eval set (even 15–20 cases) before an agent touches anything with real consequences, and grow it every time production surfaces a new failure mode — the same discipline as adding a regression test for every bug you fix.

**Don't** treat a passing eval suite as permanent. Model providers update models under the same name and version pin behind the scenes more often than most teams expect — re-run your evals on a schedule, not just when you change your own code.

---

## Cost: every step is a billed call, and loops multiply it

A single LCEL chain call is one or two model calls — easy to estimate, easy to budget. An agent loop from Part 3 is a variable number of calls, and that number is decided by the model, not by you. A question that takes one tool call on a good day can take five on a bad one, and every one of those is billed.

A few concrete habits that keep this from becoming a surprise line item:

- **Log token counts per run, not just latency.** Most LangChain responses expose usage metadata (`response.usage_metadata`) — capture it on every call and aggregate it the same way you'd aggregate request duration.
- **Set a hard per-run budget, not just a loop-iteration cap.** A cap of "5 tool calls" doesn't protect you if each call involves a huge context window. Track cumulative tokens per run and abort past a threshold, the same way you'd set a timeout on a request instead of just capping retry count.
- **Use the cheapest model that clears your eval bar for each step, not the most capable model for everything.** A classification or routing node (which model can just decide "retrieve more" vs. "done") rarely needs your most expensive model — reserve that for the step that actually needs the reasoning. This is the same instinct as not running every workload on your biggest instance type by default.
- **Cache retrieval and any deterministic sub-step.** If the same question comes in twice, or the same document gets embedded twice, you're paying for redundant work — cache the same way you'd cache any other expensive, repeatable computation.

---

## Deployment shape: where does this actually run

None of this changes how you deploy software. A LangGraph app compiled with a Postgres-backed checkpointer is a stateless-ish service (the state lives in Postgres, not in process memory) that you can run in a container, behind a load balancer, scaled the same way you'd scale any other API service. The things that are genuinely different from a normal service:

- **Long-running requests.** An agent loop with several tool calls can take much longer than a typical API response. Design for async processing and polling (or streaming) rather than assuming every request finishes inside a typical HTTP timeout window.
- **External dependency on the model provider.** A model API outage is now a dependency your service has that it didn't have before, with its own latency and error characteristics — treat it with the same circuit-breaker and fallback thinking you'd apply to any third-party API dependency, including a fallback model provider if you've set one up per Part 1.
- **Human-in-the-loop pauses (Part 3) mean a request might sit "in progress" for hours**, waiting on a person. That's fine, but your infrastructure needs to know the difference between "stuck" and "waiting on a human," or you'll get paged for something that isn't actually broken.

---

## Pulling the whole series together

Five posts, one thread running through all of them: every LangChain and LangGraph concept is a specific, named version of something you already operate.

| Concept | What it actually is |
|---|---|
| `ChatModel` | A swappable adapter to a model provider |
| Prompt template | Config with variables, same as a Helm value or a Terraform var |
| LCEL chain (`\|`) | A fixed pipeline, same shape as a CI/CD job with sequential stages |
| LangGraph state/node/edge | A reconciliation loop — desired state, a reconcile function, and a decision on what runs next |
| Checkpointer | Durable state that survives a restart, same job as etcd for a controller |
| Tool | A function the model can request, but never runs on its own |
| Agent loop | The reconciliation loop again, with the model making the routing decision instead of a fixed condition |
| Retrieval / RAG | A search index lookup wired into the prompt |
| Tracing | A distributed trace, applied to model and tool calls |
| Evals | An integration test suite for something that doesn't return identical output twice |

If a new tool or a new term shows up in this space next year, run it through that table first. Most of what looks new is a fresh name for one of these ten rows.

---

## What you should be able to do after this series

- Read someone else's LangChain/LangGraph code and correctly identify which pieces are chains, which are graphs, and why each choice was made.
- Design a tool-calling agent with a real guardrail plan before it touches anything destructive.
- Build a RAG pipeline and debug a wrong answer by checking chunking, retrieval, and staleness before blaming the model.
- Stand up tracing and a basic eval suite before putting any of this in front of real users, and explain why both are non-negotiable, not nice-to-haves.
- Talk about cost and failure modes for an agent the same way you'd talk about them for any other production service, because that's exactly what it is.

That's the series. The framework will keep changing shape under the hood — it already has once, moving from older chain classes to LCEL — but control loops, typed state, guardrails around side effects, tracing, and evals are the parts that don't go out of date. Build your mental model around those, and the next version of this stack will be a quick read, not a rewrite of what you know.

---

*This is Part 5, the final post, of a 5-part series in [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook). Start from [Part 1](./langchain-langgraph-part1-core-architecture.md) if you're arriving here first.*
