# 06 — Exam Prep and Practice
## The Checklist, the Scenario Rundown, and the Practice Questions You Do the Week Before

> **Series:** Anthropic Fundamentals for DevOps Engineers → CCAR-F
> **Exam Domains:** All five
> **Why This File Exists:** You've read files 01 through 05. Now you need to check what actually stuck. This file is your final pass — a checklist by domain, a quick look back at the six scenarios, a way to find your weak spots, a big set of practice questions, and a plan for exam day itself.

---

## What This File Is For

This isn't a new topic. It's a review. If you've been through files 01–05, most of this will feel like a recap. If you're skipping straight here to see if you're ready, that's fine too — every checklist item links back to where it's covered in more depth.

Two things before you start: first, don't just read the practice questions and check the answer key. Cover the answer, write down your own pick, then check. That's the only way to know if you actually know something versus recognize it. Second, if you get a question wrong, go back to the file it came from and reread that section — don't just memorize the right letter.

---

## Part 1 — Domain Checklist

Go through each domain. If you can explain every line to a coworker without checking your notes, you're solid on that domain.

### Domain 1 — Agentic Architecture & Orchestration (27%, ~16 questions)

- [ ] You can name the four safety tiers in order: Safe, Ethical, Policy, Helpful. You know Helpful is last on purpose.
- [ ] You know `stop_reason` drives everything in an agent loop — `end_turn` means done, `tool_use` means you have to run the tool and hand back the result.
- [ ] You know the three loop mistakes to avoid: reading Claude's text to guess if it's done, using a fixed number of tries as your only stop condition, and only saving the text part of a response instead of the whole thing.
- [ ] You can tell apart hub-and-spoke, pipeline, and peer-to-peer, and you know hub-and-spoke is the answer most of the time.
- [ ] You know subagents don't automatically see what the coordinator has seen. Someone has to hand them what they need.
- [ ] You know the three error types — tool, reasoning, environment — and the right response to each (return the error and let Claude adjust, fix the tool description, back off and retry).
- [ ] You know why showing an agent's reasoning out loud matters: you can't fix what you can't see.
- [ ] You know the "start simple" rule: one call with good context, then tools, then multiple agents, then a full pipeline — only add a layer once the layer below it isn't enough.
- [ ] You know agents need hard limits: max turns, max tool calls, a cost cap, and a list of actions that always need a human to say yes first.

### Domain 2 — Claude Code Configuration & Workflows (20%, ~12 questions)

- [ ] You know Claude doesn't remember anything between calls — your code has to resend the whole conversation every time.
- [ ] You know the five built-in Claude Code tools: Read, Write, Bash, Grep, Glob — and roughly what each is for.
- [ ] You know Plan Mode looks and reasons but doesn't touch files, and Implementation Mode actually makes changes.
- [ ] You know `-p` runs Claude Code without a person watching — that's the one you use in a pipeline.
- [ ] You know the three CLAUDE.md levels — user, project, directory — and that project-level is the one your whole team gets when they clone the repo.
- [ ] You know the fix for "it works on my machine but not my teammate's" is almost always: the config is in the wrong place, move it to project-level.
- [ ] You know the three hook types — PreToolUse, PostToolUse, Stop — and that a non-zero exit code from a PreToolUse hook stops the tool from running.
- [ ] You know slash commands live in `.claude/commands/` at the project root if you want your whole team to have them.

### Domain 3 — Prompt Engineering & Structured Output (20%, ~12 questions)

- [ ] You know Claude 4.x does exactly what you ask, nothing extra — so vague prompts get you vague answers.
- [ ] You know the five techniques: be specific about what you want, put context before the question, give a couple of examples, use tags to separate the parts of a long prompt, and give Claude room to think for hard problems.
- [ ] You know two ways to get reliable JSON back: describe the schema and retry on bad output, or define the schema as a tool and force Claude to call it. You know the second one is more reliable.
- [ ] You know a second, independent call to check the first call's output is worth more than asking the same conversation to check its own work.

### Domain 4 — Tool Design & MCP Integration (18%, ~11 questions)

- [ ] You know Claude never runs anything itself — it asks, your code runs it, your code hands back the result.
- [ ] You know a tool description tells Claude when to use it and when not to — and a bad description, not a weak model, is almost always the reason Claude picks the wrong tool.
- [ ] You know giving an agent too many tools, or several tools that basically do the same thing, causes bad tool picks. The fix is to split tools across specialized agents, not just delete tools.
- [ ] You know the three MCP pieces: host (your app), client (talks to one server), server (wraps one outside system).
- [ ] You know the three things an MCP server can offer: tools (Claude calls them), resources (Claude reads them, like files), prompts (a person picks them, like a saved command).
- [ ] You know stdio is for local, single-user setups, and Streamable HTTP is for anything remote, shared, or behind a load balancer.
- [ ] You know to treat every tool input as untrusted, since it came from a model, not directly from a person — set `additionalProperties: false` and check inputs in your own code too.

### Domain 5 — Context Management & Reliability (15%, ~9 questions)

- [ ] You know a huge context window isn't the same as a good one — quality can drop well before you hit the token limit. That's context rot.
- [ ] You know `/compact` keeps the session going with a shorter history, and `/clear` wipes it and starts over.
- [ ] You know if compaction keeps firing without the conversation actually getting shorter, the fix is to move the noisy tool work to a separate agent, not to compact harder.
- [ ] You know a good handoff note for the next session includes: what's done, what decisions were made and why, what's in progress, what's next, and any traps to avoid.
- [ ] You know to build in confidence levels — proceed, ask first, or stop and ask a question — and that anything that can't be undone always needs a human to sign off, no matter how confident the agent is.
- [ ] You know the three error tiers: retry with backoff for things like rate limits, retry with feedback for bad output, hand off to a person for anything else — and you don't let an agent retry forever.

### Cross-Domain: Production, Security, Evals (shows up across all domains)

- [ ] You know the difference between a guardrail written into a prompt (a suggestion) and a guardrail written into your code (a rule that always applies).
- [ ] You know the three ways to grade an agent's output: exact match for stuff with a known right answer, another Claude call as judge for anything subjective, and a person for the cases in between or the highest-stakes calls.
- [ ] You know to track an agent's full run — not just one API call — including how many turns it took, which tools fired, how much it cost, and how long it took.
- [ ] You know secrets belong in a secrets manager, loaded by your code at startup — never passed to Claude as a tool argument, never logged.
- [ ] You know test and eval setups need to be fully cut off from production — no shared database, no live network access.
- [ ] You know the four ways to control cost: use the cheapest model that can actually do the job, cache big stable prompts, use the Batch API for anything that doesn't need to happen right now, and set a hard budget per session.

If you checked every box, you're in good shape. If you're missing a handful in one domain, that's your study time for the week — go back to that file and reread the relevant part before you touch the practice questions below.

---

## Part 2 — The Six Scenarios, One More Time

The exam pulls four scenarios at random out of a set of six. You already saw the list in the README — here's what to actually walk in the door knowing for each one.

| # | Scenario | What to have ready |
|---|---|---|
| 1 | Customer support agent | The Agent SDK basics, calling MCP tools, and when a support issue needs to go to a person instead of getting handled automatically |
| 2 | Team using Claude Code | Where CLAUDE.md files go and why, what a slash command is, the difference between Plan Mode and just letting Claude make changes |
| 3 | Multi-agent research system | Hub-and-spoke, how a coordinator splits up work, and why a subagent doesn't automatically know what another subagent found |
| 4 | Developer productivity tooling | The five built-in Claude Code tools plus MCP tools, and picking the right one for the job |
| 5 | Claude Code in a pipeline | The `-p` flag, feeding Claude a diff, and having the pipeline fail when Claude finds something bad |
| 6 | Pulling structured data out of text | JSON schemas, forcing a tool call to guarantee the shape of the output, and what to do when the output comes back malformed |

None of these need separate study guides — they're just the topics from files 01–05 wearing a different scenario. If you know the material, you can answer a question from any of these six without having seen that specific scenario before. That's the actual point of the exam: it's testing whether you understand how Claude behaves, not whether you memorized six stories.

---

## Part 3 — Finding Your Weak Spots

A fast way to check where you actually stand, without redoing the whole series:

1. Go back through each file's "Summary" box. For each line, ask yourself: could I explain this to a coworker in one sentence, right now, without looking? If not, that's a gap.
2. Take the practice questions below by domain, not all at once. Do Domain 1's set, score yourself, then move on. A domain where you miss more than 2 out of 10 is a domain you need to reread, not just retry.
3. Pay attention to *why* you got something wrong. Missing a fact ("I forgot stdio is for local use") is a quick fix — reread one paragraph. Missing the reasoning ("I didn't realize this was a context rot question, not a tool question") means you need to reread the whole section, because you're not yet recognizing the pattern.
4. If you keep missing questions about a specific topic — CLAUDE.md scoping, MCP transports, context management, whatever — that's not bad luck. That's a real gap. Go fix it before exam day, not during it.

---

## Part 4 — Practice Exam

These questions are new — they don't repeat the ones already in files 01–05. Between this file and the rest of the series, you'll have gone through roughly 60 questions by the time you're done, matching the real exam length. Work through each domain's set, then check your answers against the key that follows each question.

### Domain 1 — Agentic Architecture & Orchestration

**Q1.** A team building a multi-step research agent has three subagents running in sequence, where each one's output feeds directly into the next one's input. Which topology fits this?

- A) Hub-and-spoke
- B) Pipeline ✓
- C) Peer-to-peer
- D) Single agent with tools

*Why B: Steps that depend on each other in order — output of one feeding straight into the next — is what a pipeline is for. Hub-and-spoke is for work that can run at the same time across different areas.*

---

**Q2.** An agent is given a `max_iterations` limit of 10 and a `max_cost_usd` limit of $0.50. At iteration 4, it hits the cost limit but hasn't hit the iteration limit. What should happen?

- A) The agent keeps going since it hasn't hit the iteration cap yet
- B) The agent stops and reports status — the cost limit fired first ✓
- C) The agent switches to a cheaper model and keeps going
- D) The agent ignores the cost limit since it's a soft guardrail

*Why B: Guardrails aren't ranked — whichever one fires first stops the agent. A cost cap and an iteration cap are both hard limits, and either one hitting first ends the run.*

---

**Q3.** A coordinator agent needs a second subagent to use findings the first subagent already produced. What's the correct way to make that happen?

- A) Nothing — subagents share context automatically
- B) The coordinator includes the relevant findings directly in the second subagent's task ✓
- C) Store the findings in a database the subagent queries on its own
- D) Merge both subagents into a single agent

*Why B: Subagents start with a blank context. If the second one needs something the first one found, the coordinator has to put it in the prompt.*

---

**Q4.** During a long agent session, a tool call fails because a downstream service is temporarily unreachable. What's the correct classification and response?

- A) Reasoning error — rewrite the tool description
- B) Tool error — return the error to Claude as a tool result and let it adapt ✓
- C) Environment error — escalate to a human immediately
- D) Ignore it and retry the same tool call with the same arguments indefinitely

*Why B: A downstream service being briefly unreachable is a tool-level failure. Returning it as a normal tool result (marked as an error) lets Claude decide what to try next — retry, use another tool, or ask for help — instead of your code guessing on its behalf.*

---

**Q5.** A team wants to build a five-agent hub-and-spoke system for a task that a single agent with three tools has never actually been tried on. What should they do first?

- A) Build the five-agent system — more agents means better coverage
- B) Build and test the single agent with three tools first, and only add agents if that falls short ✓
- C) Split the difference and build a three-agent system
- D) Use Managed Agents to skip the architecture decision

*Why B: This is the same "start simple" rule from file 05 in different words. You don't get credit for anticipating complexity you haven't proven you need yet.*

---

**Q6.** An agent's system prompt tells it to explain its plan before acting, state which tool it's about to call and why, and summarize what each result told it. What's this design choice called, and why does it matter?

- A) Verbosity tuning — it just makes responses longer
- B) Transparency — it makes the agent's behavior something you can actually debug ✓
- C) Extended thinking — it's the same as the `thinking` parameter
- D) Context management — it reduces token usage

*Why B: Writing out the plan, the tool choice, and the takeaway from each result is what makes an agent's failures traceable. It doesn't make the agent more correct — it makes it possible to figure out where it went wrong when it isn't.*

---

**Q7.** In a Planner → Generator → Evaluator pipeline, the Evaluator returns a critique that says the Generator's output missed a requirement from the original task. What should happen next?

- A) The Evaluator fixes the output itself
- B) The task is marked complete anyway since output exists
- C) The critique goes back to the Generator (or a new Generator run) to address the gap ✓
- D) The Planner re-plans the entire task from scratch

*Why C: The Evaluator's job is to catch gaps, not fix them. The fix belongs with generation. Re-planning the whole task (D) is overkill for a single missed requirement.*

---

**Q8.** A company wants five specialized agents coordinating on a shared, evolving task with persistent state across sessions, available today. Which approach should they use?

- A) Anthropic Managed Agents
- B) The self-hosted Agent SDK ✓
- C) A single agent with 40 tools
- D) Wait for Managed Agents to add multi-agent support

*Why B: Managed Agents currently supports single-agent workloads. Multi-agent coordination, right now, means self-hosted.*

---

**Q9.** An agent's code checks `response.content[0].text` for the word "finished" to decide whether to stop looping. What's wrong with this, and what should replace it?

- A) Nothing is wrong — text-based checks work fine
- B) This is unreliable — check `stop_reason` for `end_turn` instead ✓
- C) The fix is to lower `max_tokens` so responses are shorter
- D) The fix is to always run exactly 10 iterations

*Why B: Claude can say it's done in a hundred different ways, or use the word "finished" while still expecting to call a tool. `stop_reason` is a fixed, reliable signal — text content isn't.*

---

**Q10.** A task requires deleting a set of old S3 buckets. The agent is 95% confident about which buckets to delete. What should it do?

- A) Proceed automatically since confidence is above 90%
- B) Ask for confirmation regardless of confidence, because this action can't be undone ✓
- C) Delete half now and ask about the rest
- D) Lower its own confidence score to force a stop

*Why B: Confidence thresholds decide when an agent should double-check itself. Irreversible actions bypass that scale entirely — they always need a human to say yes, no matter how sure the agent is.*

---

### Domain 2 — Claude Code Configuration & Workflows

**Q11.** A developer wants Claude Code to always run `terraform fmt` right after it writes any `.tf` file, with no manual step. What's the right setup?

- A) A slash command the developer runs manually after each session
- B) A `PostToolUse` hook matching the `Write` tool that runs `terraform fmt` ✓
- C) A note in CLAUDE.md asking Claude to remember to format files
- D) A `PreToolUse` hook that blocks writes to `.tf` files

*Why B: This needs to happen automatically, every time, after a write — that's exactly what a `PostToolUse` hook is for. A CLAUDE.md note (C) is a request Claude might forget; a hook always fires.*

---

**Q12.** A subdirectory `infra/CLAUDE.md` says "never touch prod/ without confirmation," while the root `CLAUDE.md` has no such rule. A Claude Code session working inside `infra/` should:

- A) Ignore the subdirectory file since the root file takes priority
- B) Follow the subdirectory rule — it applies on top of the project-wide rules for sessions in that folder ✓
- C) Merge both files and pick whichever rule is stricter
- D) Ask the user which file to follow

*Why B: More specific scope layers on top of broader scope. A directory-level CLAUDE.md adds rules for sessions working in that directory — it doesn't get overridden by the root file.*

---

**Q13.** A Bamboo pipeline runs Claude Code to review a pull request and needs the process to exit cleanly with output a script can parse, without anyone watching the terminal. Which combination is correct?

- A) Interactive mode with `--output-format json`
- B) `-p` with `--output-format json` ✓
- C) Plan Mode with manual approval
- D) A hook that emails the results

*Why B: `-p` runs Claude Code non-interactively — input goes in, output comes out, the process exits. Pairing it with a structured output format is what makes it parseable by the next pipeline step.*

---

**Q14.** A developer writes a message, gets a response, writes a follow-up message referencing something from three messages ago, and Claude responds correctly. What's actually happening under the hood?

- A) Claude remembers the earlier messages from its own memory
- B) The client is resending the entire message history with every new call ✓
- C) The API stores conversation state on Anthropic's servers automatically
- D) The follow-up message triggers a lookup of a session ID

*Why B: Claude has no memory between API calls. Anything that looks like "remembering" is your code resending the full conversation history each time.*

---

**Q15.** A team stores personal shortcuts and draft notes in `.claude/CLAUDE.md` with a `.gitignore` entry, while shared team standards live in the root `CLAUDE.md`, committed to the repo. Why split it this way?

- A) It's required by Claude Code — the two files can't hold the same content
- B) So personal preferences don't get pushed to teammates who didn't ask for them, while shared standards are guaranteed for everyone ✓
- C) To reduce the total token count Claude has to read
- D) `.claude/CLAUDE.md` is read-only and can't be edited

*Why B: This is just about keeping personal setup separate from team-wide rules. Nothing technical forces the split — it's a convention that keeps one person's local habits out of everyone else's sessions.*

---

**Q16.** A slash command is placed in `~/.claude/commands/deploy-check.md`. A teammate clones the repo and runs `/deploy-check`. What happens?

- A) It works the same for everyone since slash commands are always project-wide
- B) It doesn't exist for the teammate — user-scoped commands aren't shared when the repo is cloned ✓
- C) It works but with reduced permissions
- D) Claude Code throws an error on startup

*Why B: Same rule as CLAUDE.md scoping. A command under the user's home directory is personal. For team-wide commands, it needs to live in `.claude/commands/` inside the repo.*

---

**Q17.** A `PreToolUse` hook matching `Bash` exits with code 1 when a command matches a list of blocked patterns. A developer asks Claude to run one of those blocked commands. What happens?

- A) Claude runs the command and the hook logs a warning afterward
- B) The Bash tool call is blocked before it runs ✓
- C) Claude Code asks the developer to override the hook
- D) The session ends immediately

*Why B: A non-zero exit from a `PreToolUse` hook stops the tool call before it executes. This is how you build a hard safety gate instead of relying on Claude to just follow instructions.*

---

**Q18.** A developer runs `claude --plan "refactor the auth module"`. What happens to the files in the repo during this session?

- A) Claude makes changes but asks for approval before each one
- B) Nothing is written — Claude reasons about the change and presents a plan first ✓
- C) Claude writes to a temporary branch automatically
- D) Claude writes changes but skips test files

*Why B: Plan Mode is read-only by design. It's for getting a look at what Claude intends to do before any file actually changes.*

---

### Domain 3 — Prompt Engineering & Structured Output

**Q19.** A prompt asks Claude to "clean up this log file." The output varies a lot between runs — sometimes it summarizes, sometimes it reformats, sometimes it filters. What's the fix?

- A) Lower the temperature setting
- B) Spell out exactly what "clean up" means — what to keep, what to remove, what format to return it in ✓
- C) Switch to a larger model
- D) Add a stop sequence

*Why B: "Clean up" doesn't tell the model what you actually want. Claude 4.x does exactly what you ask — so if the ask is vague, the output will be too. Spell it out.*

---

**Q20.** A prompt is written as: "Here's a long block of infrastructure context. Given all this, what should we do about the failing health checks?" Rewriting it to put the question at the very end, after all the context, tends to produce:

- A) The same result either way — order doesn't affect output
- B) A more targeted answer, because Claude has the full picture before it starts reasoning about the question ✓
- C) A shorter answer since the question is buried
- D) A slower response due to processing order

*Why B: Context-before-question is one of the five prompting techniques. Claude reasons through the prompt in order, so the framing needs to arrive before the ask.*

---

**Q21.** An extraction task needs Claude to return dates in a very specific, slightly unusual format (`DD-Mon-YY`, e.g. `14-Sep-26`) that Claude doesn't default to naturally. What's the fastest way to lock that in?

- A) Explain the format rules in a long paragraph
- B) Give two or three examples showing the exact input and the exact expected output ✓
- C) Use a lower `max_tokens` value to force brevity
- D) Ask Claude to double-check its own date formatting after the fact

*Why B: Few-shot examples are the fastest way to lock in an exact, unusual format. Showing beats describing here.*

---

**Q22.** A system prompt has four distinct parts: role, task instructions, output format, and constraints, all run together as one long paragraph. Claude occasionally mixes up the constraints with the task instructions. What's the fix?

- A) Shorten the prompt overall
- B) Separate the four parts using tags like `<instructions>`, `<output_format>`, and `<constraints>` ✓
- C) Repeat the constraints twice for emphasis
- D) Move the constraints to the end of the user message instead

*Why B: Tagging distinct sections is exactly what XML-style structuring is for — it keeps Claude from blending parts of the prompt that were meant to stay separate.*

---

**Q23.** A hard root-cause analysis task is given a `max_tokens` of 4096 with extended thinking enabled and a `budget_tokens` of 8000. What's wrong with this setup?

- A) Nothing — this is a valid configuration
- B) `max_tokens` needs to be large enough to cover both the thinking content and the final answer — 4096 is too small next to an 8000 thinking budget ✓
- C) Extended thinking doesn't need a token budget
- D) `budget_tokens` should always be smaller than `max_tokens`

*Why B: Thinking tokens and the final answer both come out of the same overall output budget. A thinking budget bigger than the total `max_tokens` almost guarantees a cut-off response.*

---

**Q24.** A task needs Claude to always return an object with a required `severity` field, one of exactly four allowed values, with no other shape possible. Which method guarantees this most reliably?

- A) Describe the four allowed values in the system prompt and validate on your end
- B) Give three few-shot examples covering each severity value
- C) Define the field as an `enum` in a tool's input schema and force that tool with `tool_choice` ✓
- D) Add a regex check after receiving the response

*Why C: Enforcing an `enum` inside a forced tool call means the API itself won't let the value be anything else. The other options all rely on Claude following instructions correctly, which is less certain.*

---

**Q25.** A conversation is at 55% of its context window, and the agent starts repeating a fix it already tried twice. This is:

- A) A sign the context window needs to be bigger
- B) Context rot — quality dropping before the window is actually full ✓
- C) A model capability issue that requires switching models
- D) Expected behavior that doesn't need any intervention

*Why B: This is the textbook definition of context rot. The fix is managing what's in context — usually a directed `/compact` — not switching models or waiting for a bigger window.*

---

**Q26.** An agent is fully done with an incident and about to start a completely unrelated task with no shared context. Should it `/compact` or `/clear`?

- A) `/compact`, to preserve useful history
- B) `/clear`, since there's nothing from the old task worth carrying forward ✓
- C) Neither — just keep going in the same session
- D) Start a brand-new terminal window instead

*Why B: `/compact` is for continuing the same thread with a shorter history. `/clear` is for exactly this case — task complete, next task unrelated, nothing worth keeping.*

---

### Domain 4 — Tool Design & MCP Integration

**Q27.** An agent has 22 tools available, several of which do nearly the same thing with slightly different names (`get_status`, `check_status`, `fetch_status`). Claude picks inconsistently between them. What's the architectural fix?

- A) Delete all but one and hope Claude adapts
- B) Split the tools across a few specialized subagents, each with a small, non-overlapping set ✓
- C) Add a longer system prompt explaining the difference between the three tools
- D) Force `tool_choice` on every single call

*Why B: This is reasoning overload from too many similar tools in one place. The fix is specialization — smaller, focused toolsets per agent — not just trimming the list or adding more prompt text.*

---

**Q28.** In MCP's architecture, which piece is responsible for managing the actual JSON-RPC connection to a single external system?

- A) The host
- B) The MCP client ✓
- C) The MCP server
- D) The model itself

*Why B: The client sits inside the host and manages the connection to one server. The server is the adapter for the outside system; the host is the overall application; the model never touches any of this directly.*

---

**Q29.** A team wants engineers to be able to type a saved, standard incident-review workflow by name during a session, without Claude deciding on its own to run it. Which MCP primitive fits?

- A) Tools
- B) Resources
- C) Prompts ✓
- D) Sampling

*Why C: Prompts are the user-invoked primitive — a person picks them, the model doesn't decide to run them on its own. Tools are model-initiated; resources are read-only data the model can pull in.*

---

**Q30.** An MCP server that a team connected to weeks ago silently changes one of its tool's descriptions and behavior without anyone noticing, after the host already approved it. What's this called, and what's the defense?

- A) A rug pull — treat tool definitions as something to re-check periodically, not something you approve once and forget ✓
- B) A rate-limit issue — add backoff
- C) A schema drift — increase `max_tokens`
- D) A transport error — switch from stdio to Streamable HTTP

*Why A: This is the documented "rug pull" risk with MCP servers. Approving a server once and never checking again leaves you open to it changing behavior later.*

---

**Q31.** A small internal tool used only by one engineer on their own laptop, with no other users, needs an MCP server. What's the simplest correct transport?

- A) Streamable HTTP behind a load balancer
- B) stdio ✓
- C) WebSockets
- D) SSE

*Why B: Single user, local machine, no need for remote access — stdio is the simplest fit and the default for this kind of setup. Standing up a remote, load-balanced service for one person's laptop is unnecessary.*

---

**Q32.** A tool's JSON schema does not set `additionalProperties: false`, and Claude occasionally passes an extra, unexpected field that ends up reaching the underlying database call. What's the risk, and the fix?

- A) No real risk — unexpected fields are ignored automatically
- B) Real risk — an unvalidated extra field could carry an injection attempt; set `additionalProperties: false` and validate inputs server-side too ✓
- C) The fix is to increase the tool's description length
- D) The fix is to switch the tool to a resource instead

*Why B: Tool inputs come from a model, not directly from a trusted user — treat them as untrusted. Locking the schema and checking inputs on your own side is the actual defense, not a longer description.*

---

**Q33.** A tool description says only: "Gets service info." Claude sometimes calls it for the wrong service type entirely. What's missing from the description?

- A) A shorter name for the tool
- B) When to use it, when *not* to use it, and what kind of service it applies to ✓
- C) A `tool_choice` setting forcing this tool every time
- D) A retry loop around the tool call

*Why B: A tool description is an instruction, not a label. Without a clear scope — including what it's *not* for — Claude has no way to tell it apart from similar tools.*

---

### Domain 5 — Context Management & Reliability (plus cross-domain production)

**Q34.** A system prompt tells Claude "never share customer PII." A crafted user message gets around this and Claude includes PII in its response anyway. What's the durable fix?

- A) Reword the system prompt to be more forceful
- B) Add a programmatic output check that blocks or redacts PII patterns before the response reaches the user ✓
- C) Lower the temperature
- D) Add the instruction to CLAUDE.md instead of the system prompt

*Why B: Prompt-based rules are guidance, not enforcement — they can be talked around. A programmatic check on the output is a rule that always applies, regardless of what got past the prompt.*

---

**Q35.** An eval suite grades a summarization task by having a second Claude call score each output for clarity and completeness on a 1–5 scale. What kind of grading method is this, and when is it the right call?

- A) Deterministic grading — use it when there's one exact correct answer
- B) LLM-as-judge — use it when quality is subjective and there's no single correct string to match against ✓
- C) Human review — use it only for the highest-stakes cases
- D) Regression testing — use it to compare model versions only

*Why B: Grading "how good is this summary" isn't a pattern match — it's a judgment call, which is exactly what LLM-as-judge grading is for.*

---

**Q36.** An eval run needs test data that looks like production but must never be able to touch the real production database, even by accident. What's the correct setup?

- A) A read-only connection to the production database
- B) A fully separate database with no network path to production at all ✓
- C) A production connection with an extra confirmation step before writes
- D) Running the eval only during off-peak hours

*Why B: Read-only access still means a live connection to something real — a misconfiguration or bug could still reach it. Full separation, no shared network path, is the only setup that actually rules this out. Anthropic has documented real incidents where eval environments reached live systems through exactly this kind of gap.*

---

**Q37.** A tool implementation needs a database password. Where should that password live, and where should it never appear?

- A) In the tool's input schema, so Claude can pass it when needed
- B) Loaded from a secrets manager at startup, and never passed as a tool argument or written to logs ✓
- C) Hardcoded in the tool function for simplicity
- D) In the system prompt, since system prompts aren't logged

*Why B: A password in a tool's input schema is visible to the model and gets logged along with every other tool call. It should be loaded once, at startup, from somewhere like a secrets manager, and kept out of anything Claude sees or anything that gets logged.*

---

**Q38.** A nightly job needs to classify 40,000 support tickets by category. None of it needs to happen in real time. Which combination keeps cost down the most?

- A) Sonnet 4.6, synchronous calls, one at a time
- B) Haiku 4.5, Batch API ✓
- C) Opus 4.8, prompt caching
- D) Sonnet 4.6, prompt caching

*Why B: Simple classification doesn't need a bigger model — that's Haiku's job. Nothing here is time-sensitive, so the Batch API's discount applies. Together, that's the cheapest valid setup.*

---

**Q39.** A team wants to know, across a week of agent runs, whether task success is dropping, whether one tool is failing more than usual, and whether cost per session is creeping up. What should they be tracking?

- A) Only the final text output of each session
- B) The full trajectory of each session — turns taken, tools called, tokens used, and whether it ended in `end_turn` ✓
- C) Server CPU and memory usage only
- D) Just the number of API calls per day

*Why B: Agent behavior is spread across many steps, not one call. Tracking the whole run — not just the final answer — is what actually surfaces a rising error rate or a creeping cost problem.*

---

## Part 5 — Exam Day, Start to Finish

**A week before:** Go back through every "Summary" box in files 01–05, plus the checklist in Part 1 above. Redo any practice question set where you missed more than 2.

**The night before:** Skim the checklist one more time. Don't cram new material — at this point you're just refreshing what you already know. Get sleep. A tired brain misreads scenario questions, and this exam is full of them.

**Registration and logistics, one more time:**
- Sign up through the Anthropic Partner Academy, under the Claude Partner Network (free at the entry level).
- Delivered through Pearson VUE — either online with a proctor watching over webcam, or at a test center.
- Closed book. No Claude, no docs, no extra browser tabs. If you're testing from home, clear your desk and close everything else first.
- 60 questions, 120 minutes, pulled from a pool with 4 of the 6 scenarios showing up each sitting.
- Passing score is 720 out of 1000. Your report breaks down your percent correct by domain, so you'll know exactly where you lost points if you don't pass.
- A failed first attempt means a 14-day wait before you can retry, then 30 days, then 90. Each attempt costs the full fee, and you're capped at 4 tries in a rolling 12 months.
- Passing means you're certified for 12 months. Renew on time and it's a free non-proctored check; let it lapse and you're back to paying full price.

**During the exam:** Read the scenario fully before looking at the answer choices — a lot of the wrong answers are technically true statements that just don't fit the specific situation described. When two answers both sound reasonable, look for the one that matches the *architectural* pattern (start simple, isolate context, enforce with code not prompts) rather than the one that sounds more thorough. The exam consistently rewards the simpler, more disciplined answer over the more elaborate one.

---

## Summary — What to Lock In Before Your Exam

```
┌────────────────────────────────────────────────────────────────────┐
│  06 — Final Review: What Actually Matters                          │
├────────────────────────────────────────────────────────────────────┤
│ Read the checklist in Part 1 out loud to yourself. Anything you    │
│   can't explain plainly is a gap — go fix it before test day.      │
│                                                                    │
│ The six scenarios are just wrappers. Know the underlying material  │
│   and any scenario becomes answerable.                             │
│                                                                    │
│ Wrong answers on the real exam are usually true statements that    │
│   don't fit the situation — read the scenario carefully before     │
│   picking.                                                         │
│                                                                    │
│ When two answers both seem right, pick the simpler, more           │
│   disciplined one — start simple, isolate context, enforce with    │
│   code, not prompts.                                                │
│                                                                    │
│ Get sleep the night before. This exam rewards careful reading      │
│   more than raw knowledge.                                         │
└────────────────────────────────────────────────────────────────────┘
```

---

## What's Next

That's the series. If you've worked through all six files and the practice questions, you've covered the material across every domain the exam tests. Go register, go take it, and good luck.

If you want more practice beyond this, the freeCodeCamp CCAR-F prep course and the official exam guide (both linked below) are worth a final pass — they'll have some question styles this series doesn't.

---

## Official Resources

- **[CCAR-F Exam Guide v1.0 (PDF)](https://everpath-course-content.s3-accelerate.amazonaws.com/instructor/6nizmqk8tpzpfjvt6qmmav7rh/public/1783542750/Claude+Certified+Architect+%E2%80%93+Foundations+Exam+Guide.pdf)** — read the whole thing at least once.
- **[Anthropic Academy (free courses)](https://anthropic.skilljar.com/)** — "Building with the Claude API" and "Claude Code in Action."
- **[Claude API Docs](https://docs.anthropic.com)** — the reference for anything you're unsure about.
- **[MCP Specification](https://modelcontextprotocol.io)** — for any lingering MCP questions.
- **[freeCodeCamp CCAR-F Prep Course](https://www.freecodecamp.org/news/claude-certified-architect-foundations-prep-for-anthropic-s-new-certification-exam/)** — a good final practice run.

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*
*Found an error or want to contribute? PRs welcome.*
