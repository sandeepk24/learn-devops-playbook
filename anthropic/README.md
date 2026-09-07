# Anthropic Fundamentals for DevOps Engineers
### A Field-Grade Study Series for the Claude Certified Architect – Foundations (CCAR-F) Exam

> **Exam Code:** CCAR-F &nbsp;|&nbsp; **Fee:** $125 &nbsp;|&nbsp; **Questions:** 60 &nbsp;|&nbsp; **Time:** 120 min &nbsp;|&nbsp; **Pass:** 720/1000  
> **Delivery:** Pearson VUE (online proctored or test center) &nbsp;|&nbsp; **Valid:** 12 months

---

## Who This Is For

You've shipped pipelines. You've debugged CrashLoopBackOffs at 2 AM. You know Terraform, Kubernetes, and the particular joy of watching a deployment succeed after seven failed attempts. But AI workloads are different — they fail silently, they behave probabilistically, and the architecture decisions that matter most aren't the ones you'd find in an AWS whitepaper.

This series is written for DevOps and Cloud Engineers who want to understand Claude deeply enough to build production-grade systems with it — and who want the CCAR-F certification to prove it. Every article ties back to exam domains, includes working Python examples, and explains the *why* behind architectural decisions, not just the *what*.

If you want to just memorize answers, Udemy has practice exams. This series is for engineers who want to actually understand the material.

---

## The Exam at a Glance

The Claude Certified Architect – Foundations is Anthropic's proctored, scenario-based certification for solution architects working with Claude Code, MCP, and agentic systems. It launched March 2026 and is delivered through Pearson VUE — closed book, no documentation, no browser tabs.

```
┌──────────────────────────────────────────────────────────────┐
│               CCAR-F Domain Weights                          │
├──────────────────────────────────────────────┬───────────────┤
│ Domain                                       │ Weight (~Qs)  │
├──────────────────────────────────────────────┼───────────────┤
│ 1. Agentic Architecture & Orchestration      │ 27%  (~16 Qs) │
│ 2. Claude Code Configuration & Workflows     │ 20%  (~12 Qs) │
│ 3. Prompt Engineering & Structured Output    │ 20%  (~12 Qs) │
│ 4. Tool Design & MCP Integration             │ 18%  (~11 Qs) │
│ 5. Context Management & Reliability          │ 15%  (~9 Qs)  │
├──────────────────────────────────────────────┼───────────────┤
│ TOTAL                                        │ 100% (60 Qs)  │
└──────────────────────────────────────────────┴───────────────┘
```

Each sitting pulls **4 scenarios at random from a bank of 6.** Every question hangs off a real production situation. Knowing the six scenario contexts before you walk in is half the battle:

| # | Scenario | Core Skills Tested |
|---|---|---|
| 1 | Customer support resolution agent | Agent SDK, MCP tools, escalation paths |
| 2 | Team code generation with Claude Code | CLAUDE.md config, slash commands, plan mode |
| 3 | Multi-agent research system | Coordinator/subagent delegation, decomposition |
| 4 | Developer productivity tooling | Built-in tools (Read/Write/Bash/Grep/Glob) + MCP |
| 5 | Claude Code in CI/CD pipeline | Automated review, test gen, PR feedback |
| 6 | Structured data extraction | JSON schema validation, output reliability |

---

## Series Structure

Each file maps to specific exam domains. Study them in order — each one builds on the last.

| File | Topic | Exam Domains | Priority |
|---|---|---|---|
| `README.md` | Series orientation + exam logistics | Meta | — |
| `01-anthropic-foundations.md` | Anthropic, safety, model family, API basics | Model selection across all domains | Start here |
| `02-claude-api-and-sdk.md` | Messages API, Agent SDK, Claude Code, CLAUDE.md | Domain 2 + Domain 3 (partial) | High |
| `03-prompting-context-and-reliability.md` | Prompting, structured output, context management | Domain 3 + Domain 5 | High |
| `04-tool-use-mcp-and-agents.md` | Tool design, MCP, agentic loops, orchestration | Domain 1 + Domain 4 | **Highest** |
| `05-production-devops-security-and-evals.md` | Security, safety, evals, observability, CI/CD | Cross-domain production patterns | High |
| `06-exam-prep-roadmap.md` | Practice Qs, scenario walkthroughs, final checklist | All domains | Final review |

---

## How DevOps Skills Map to the Exam

This is the reframe that makes this certification click for systems engineers. You already think this way — the vocabulary is just different.

| Your DevOps Instinct | CCAR-F Equivalent |
|---|---|
| Microservices decomposition | Multi-agent task decomposition |
| API gateway routing logic | Agentic orchestration and routing |
| Idempotent pipeline steps | Reliable tool execution in agents |
| GitOps / env config management | CLAUDE.md configuration hierarchy |
| CI/CD pipeline automation | Claude Code in CI/CD workflows |
| Health checks + retry logic | Context management + confidence calibration |
| Secrets management | MCP tool auth and security boundaries |
| Service mesh observability | Agent trace logging and eval frameworks |

---

## Prerequisites

**To follow along:** Python 3.10+, an Anthropic API key, and basic familiarity with REST APIs.  
**For the exam itself:** No mandatory prerequisites. Anthropic recommends 6+ months hands-on with Claude.

```bash
pip install anthropic
export ANTHROPIC_API_KEY="your-key-here"
```

---

## Exam Logistics

**Registration:** Through the [Anthropic Partner Academy](https://anthropic-partners.skilljar.com/). Requires joining the Claude Partner Network — free at the Registered (entry) level.

**Delivery:** Pearson VUE. Online proctored (webcam, clear workspace) or test center. Closed-book — no Claude, no docs, no browser.

**Scoring:** Scaled 100–1000. Pass at 720. Score report shows percent correct per domain.

**Retakes:** 14-day wait after fail 1 → 30 days → 90 days. Max 4 attempts per rolling 12 months. Each attempt costs the full $125.

**Renewal:** Every 12 months. On-time renewal = free non-proctored assessment. Let it lapse = full exam at full price.

---

## Free Official Study Resources

These are the only resources you actually need alongside this series:

- **[CCAR-F Exam Guide v1.0 (PDF)](https://everpath-course-content.s3-accelerate.amazonaws.com/instructor/6nizmqk8tpzpfjvt6qmmav7rh/public/1783542750/Claude+Certified+Architect+%E2%80%93+Foundations+Exam+Guide.pdf)** — 39 pages. Read it in full. It has task statements and sample questions with rationale.
- **[Anthropic Academy (free courses)](https://anthropic.skilljar.com/)** — "Building with the Claude API" and "Claude Code in Action" are the two most exam-relevant.
- **[Claude API Docs](https://docs.anthropic.com)** — The source of truth for everything in Domains 2–4.
- **[MCP Specification](https://modelcontextprotocol.io)** — Required reading for Domain 4 questions.
- **[freeCodeCamp CCAR-F Prep Course](https://www.freecodecamp.org/news/claude-certified-architect-foundations-prep-for-anthropic-s-new-certification-exam/)** — Free, practical, by Andrew Brown. Excellent supplement.

---

## How to Use This Series

**Reading to learn:** Go file 01 through 06 in order. Each article opens with what the section covers and closes with exam callouts summarizing what to remember.

**Studying for the exam:** On your second pass, focus on the `📝 Exam Tip` callouts and the comparison tables. Those map directly to the question types you'll see.

**Quick reference before the exam:** Jump to `06-exam-prep-roadmap.md` and work through the domain-by-domain checklist.

Every code example is runnable. Run it, break it, modify it. The exam tests architectural judgment — and that only comes from building real things.

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*  
*Found an error or want to contribute? PRs welcome.*
