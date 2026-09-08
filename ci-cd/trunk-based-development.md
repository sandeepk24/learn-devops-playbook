# Trunk-Based Development: The Complete Guide for DevOps Engineers

> The strategy that separates teams who ship confidently from teams who dread deploy day.

---

## Let's Start With a Honest Conversation

Picture this: It's Friday afternoon. Your team has been working on a big feature for two weeks in a separate branch. You're finally ready to merge. You type `git merge` and watch in horror as Git dumps 47 conflicts into your terminal. The feature branch has drifted so far from main that merging it feels like surgery. Someone mutters "we'll deal with it Monday." Monday becomes a week of merge conflict resolution instead of building anything.

Sound familiar?

This is **integration hell** — and it's one of the most common sources of pain in software teams. Trunk-Based Development (TBD) was designed specifically to eliminate it. But it comes with tradeoffs, discipline requirements, and a shift in how you think about "done" work. This guide walks through all of it.

---

## What Trunk-Based Development Actually Is

**Trunk-Based Development is a branching strategy where everyone on the team integrates their code into a single shared branch — called the trunk, or main — at least once per day.**

That's it. That's the whole idea.

But the implications of that simple rule are enormous, and getting them right is what separates a functioning TBD implementation from chaos.

```
WITHOUT TBD:                          WITH TBD:

main ────────────────────►            main ──────────────────────────────►
                                             ↑  ↑  ↑  ↑  ↑  ↑  ↑  ↑  ↑
feature-A ─────────────►                   (small commits, frequently)
feature-B ─────────────►
feature-C ─────────────►
(merge all at end = pain)             (integrations are tiny, conflicts are tiny)
```

The trunk must always be in a **deployable state**. Not "mostly working." Not "working except for the auth module." Deployable. Every single commit.

---

## The Mental Model Shift

Most engineers learn Git with long-lived feature branches. You branch off, work for a week or two, then merge. This feels safe — your work is isolated, you're not breaking anyone else's stuff, you can work at your own pace.

TBD asks you to flip this completely.

**Old thinking:** *"I'll integrate when my feature is ready."*  
**TBD thinking:** *"I'll integrate small pieces continuously, and use feature flags to control when the feature is visible."*

The key insight is separating two things that we've traditionally treated as the same:

- **Code integration** (merging your work into the shared codebase)
- **Feature release** (making that feature visible to users)

In traditional branching, these happen simultaneously when you merge your branch. In TBD, they are completely decoupled. Code goes in continuously. Features go live when you decide to flip a flag.

---

## The Core Principles

### 1. One Trunk, Always Deployable

The trunk (`main`) is sacred. It must pass all tests, all lints, all checks — at every commit. This is non-negotiable.

If someone breaks the trunk, it is the team's highest priority to fix it. Not "let's get to it after standup." Right now.

```bash
# This is the only long-lived branch
main

# Short-lived branches (optional, < 2 days) are fine
feature/add-retry-logic     # created today, merged today or tomorrow
fix/null-check-in-parser    # created this morning, merged this afternoon
```

### 2. Small, Frequent Commits

A commit in TBD is not a "save point" for a half-finished feature. It's a small, complete, working unit of change. Small means:

- One logical change per commit
- Passes all tests when applied
- Doesn't break anything that was working before

What "small" looks like in practice:

```bash
# Too big (a week's worth of work)
git commit -m "implement entire user authentication system"

# Right size
git commit -m "add User model with email and hashed password fields"
git commit -m "add password hashing utility using bcrypt"
git commit -m "add login endpoint with credential validation"
git commit -m "add JWT token generation on successful login"
git commit -m "add authentication middleware for protected routes"
```

Each of those smaller commits integrates cleanly, is reviewable, and doesn't leave the system in a broken state.

### 3. Short-Lived Branches (If You Use Them at All)

Some teams practicing TBD use short-lived feature branches for code review purposes — they open a PR, get a quick review, and merge within a day or two. This is called **scaled trunk-based development** and it's perfectly valid.

The rule of thumb: **if your branch is older than two days, something's wrong.** Either the work needs to be broken down further, or the review process is too slow.

```
Day 1, 9am:  git checkout -b feature/add-search-filter
Day 1, 2pm:  Open PR with 3 commits
Day 1, 4pm:  Reviewed, approved, merged to main
Day 1, 4pm:  Branch deleted

→ This is fine.

Day 1:  git checkout -b feature/rebuild-entire-search
Day 5:  Still working...
Day 9:  Finally opening a PR...
Day 12: Merged (with conflicts)

→ This is not TBD.
```

### 4. The Trunk is the Release Branch

In TBD, you don't maintain a separate release branch for the latest version. You release from `main`. If you need release branches, they're created at release time and only receive cherry-picked bug fixes — code never flows *from* release branches back to main except in very specific scenarios.

---

## Feature Flags: The Engine That Makes TBD Work

Feature flags are what allow you to merge incomplete work into the trunk without exposing it to users. Without feature flags, TBD either requires every commit to be a complete feature (unrealistic) or you ship half-finished features to production (terrible).

**A feature flag is just a conditional in your code that controls whether a feature is active.**

### The Simplest Possible Feature Flag

```python
# config.py
FEATURE_FLAGS = {
    "new_dashboard": False,
    "ai_recommendations": False,
    "redesigned_checkout": True,
}

def is_enabled(flag_name: str) -> bool:
    return FEATURE_FLAGS.get(flag_name, False)
```

```python
# views.py
from config import is_enabled

def dashboard_view(request):
    if is_enabled("new_dashboard"):
        return render(request, "dashboard_v2.html")
    return render(request, "dashboard.html")
```

Your team merges the new dashboard code into `main` while `new_dashboard` is `False`. Zero users see it. When you're ready to ship — you flip the flag to `True`. No deployment needed.

### Graduated Rollouts (Percentage-Based Flags)

```python
import hashlib

def is_enabled_for_user(flag_name: str, user_id: str, rollout_percentage: int) -> bool:
    """
    Deterministically enables a flag for a percentage of users.
    The same user always gets the same result.
    """
    hash_input = f"{flag_name}:{user_id}".encode()
    hash_value = int(hashlib.md5(hash_input).hexdigest(), 16)
    bucket = hash_value % 100
    return bucket < rollout_percentage

# Enable new checkout for 10% of users
is_enabled_for_user("new_checkout", user.id, rollout_percentage=10)
```

This lets you ship to 1% of users first, watch your error rates, then 10%, then 50%, then 100%. If something goes wrong, you flip the flag off — instant rollback, no deployment.

### Production-Grade Feature Flag Services

At scale, hardcoded flags in config files don't cut it. Teams use dedicated services:

| Service | Type | Best For |
|---------|------|----------|
| LaunchDarkly | Commercial | Enterprise, complex targeting rules |
| Flagsmith | Open source | Self-hosted, full control |
| Unleash | Open source | Teams wanting Jira/enterprise integrations |
| AWS AppConfig | Managed | Teams already in AWS |
| Split.io | Commercial | Experimentation-focused teams |

```python
# Using LaunchDarkly as an example
import ldclient
from ldclient.config import Config

ldclient.set_config(Config("YOUR_SDK_KEY"))
client = ldclient.get()

user = {
    "key": str(current_user.id),
    "email": current_user.email,
    "custom": {
        "plan": current_user.plan,
        "country": current_user.country
    }
}

if client.variation("new-checkout-flow", user, False):
    return render_new_checkout()
else:
    return render_old_checkout()
```

### Feature Flag Hygiene: The Part Everyone Ignores

Flags are technical debt if they never get cleaned up. Set a policy:

```python
# BAD: Flag from 2 years ago still in the codebase
if is_enabled("new_login_flow_2022"):  # This launched in 2022. It's 2026. Remove this.
    ...

# GOOD: Flags have expiry dates in comments or tickets
# TODO: Remove this flag after 2026-Q2 rollout is complete (JIRA-1234)
if is_enabled("redesigned_onboarding"):
    ...
```

Rule: when a feature is fully rolled out, schedule the flag removal in the same sprint. Leaving flags forever creates code paths nobody tests.

---

## CI/CD: The Infrastructure TBD Demands

TBD without solid CI/CD is like driving a race car without brakes. You need automated verification running on every single commit to `main`. If you don't have this, fix it before adopting TBD.

### What Your Pipeline Must Do

```
Every commit to main triggers:
│
├── 1. Static Analysis (< 30 seconds)
│   ├── Linting (flake8, pylint, ruff)
│   ├── Type checking (mypy)
│   └── Security scanning (bandit, semgrep)
│
├── 2. Unit Tests (< 2 minutes)
│   └── Fast, isolated, no external dependencies
│
├── 3. Integration Tests (< 10 minutes)
│   └── DB, cache, message queue interactions
│
├── 4. Build & Package (< 5 minutes)
│   └── Docker image, artifacts
│
└── 5. Deploy to Staging (automated)
    └── Run smoke tests
    └── Deploy to production (auto or manual gate)
```

### A Real CI Pipeline (GitHub Actions)

```yaml
# .github/workflows/ci.yml
name: CI Pipeline

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Lint
        run: ruff check .

      - name: Type check
        run: mypy src/

      - name: Security scan
        run: bandit -r src/

  test:
    needs: quality
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_PASSWORD: testpass
          POSTGRES_DB: testdb
        options: >-
          --health-cmd pg_isready
          --health-interval 10s

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Run unit tests
        run: pytest tests/unit/ -v --tb=short

      - name: Run integration tests
        run: pytest tests/integration/ -v --tb=short
        env:
          DATABASE_URL: postgresql://postgres:testpass@localhost/testdb

      - name: Upload coverage
        uses: codecov/codecov-action@v4

  deploy-staging:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - name: Deploy to staging
        run: |
          # Your deploy script here
          echo "Deploying to staging..."
```

### The "10-Minute Rule" for CI

If your CI pipeline takes more than 10 minutes, developers stop waiting for it. They open new PRs, push more commits, and by the time CI finishes, the context is lost. Optimize aggressively:

```python
# Slow: running all tests every time
pytest tests/  # 25 minutes

# Fast: parallelize by test category
pytest tests/unit/ -n auto          # 2 min, parallelized
pytest tests/integration/ -n auto   # 6 min, parallelized
pytest tests/e2e/ --only-changed    # only tests affected by this diff
```

---

## Branch by Abstraction: Merging Incomplete Work Safely

Sometimes feature flags aren't the right tool — especially when you're making large architectural changes (replacing a library, refactoring a module, changing a database schema). For this, TBD engineers use a technique called **Branch by Abstraction**.

### The Pattern

Instead of creating a Git branch for a big refactor, you:

1. Create an abstraction layer (interface/protocol) over the thing you want to replace
2. Redirect the current implementation to use that interface
3. Build the new implementation behind the interface
4. Gradually switch traffic from old → new
5. Delete the old implementation and the abstraction layer

```python
# Step 1: You currently use requests directly everywhere
import requests
response = requests.get(url, timeout=5)  # scattered across 30 files

# Step 2: Introduce an abstraction
from abc import ABC, abstractmethod

class HttpClient(ABC):
    @abstractmethod
    def get(self, url: str, timeout: int = 5) -> dict:
        pass

# Step 3: Wrap the old implementation
class RequestsClient(HttpClient):
    def get(self, url: str, timeout: int = 5) -> dict:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()

# Step 4: Build new implementation (httpx with async support)
import httpx

class HttpxClient(HttpClient):
    def get(self, url: str, timeout: int = 5) -> dict:
        with httpx.Client() as client:
            response = client.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()

# Step 5: Switch implementations with a flag — all in main, no big-bang merge
def get_http_client() -> HttpClient:
    if is_enabled("use_httpx_client"):
        return HttpxClient()
    return RequestsClient()
```

This entire migration happens in `main`. Each step is a commit. There's never a "big merge" because there's never a separate branch. The system works at every step.

---

## Dealing With Database Changes in TBD

Database migrations are the trickiest part of TBD. You can't use a feature flag to hide a missing database column. Here's the discipline required.

### The Expand-Contract Pattern

Never make breaking database changes in a single deployment. Use three phases:

**Phase 1: Expand** — Add the new column/table, keep the old one. Both work.

```python
# Migration: add new column, old column still exists
# 0001_expand_add_email_verified.py

from django.db import migrations, models

class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name='user',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
    ]
```

**Phase 2: Migrate** — Backfill data, write to both old and new. Read from new.

```python
# Code now reads from new column, writes to both
def mark_email_verified(user):
    user.email_verified = True       # new column
    user.is_verified = True          # old column (still writing for safety)
    user.save()
```

**Phase 3: Contract** — Remove old column after confidence is established.

```python
# Migration: drop old column
# 0003_contract_remove_is_verified.py
class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField(
            model_name='user',
            name='is_verified',
        ),
    ]
```

This three-phase approach means each deployment is safe to roll back independently.

---

## Handling Releases in TBD

"But if everything is in main, how do we manage releases?"

There are two common patterns:

### Pattern 1: Release from Main (Continuous Delivery)

Every commit to main is a potential release. You deploy on a schedule (daily, weekly) or trigger deployments manually. No release branches.

```
main ──●──●──●──●──●──●──●──►
           ↑           ↑
        v1.2.0       v1.3.0
       (tag + deploy) (tag + deploy)
```

```bash
# Tag a release
git tag -a v1.3.0 -m "Release 1.3.0"
git push origin v1.3.0

# Your CI/CD deploys on new tags
```

### Pattern 2: Hardening Branch (For Versioned Software)

For products that ship versioned releases (mobile apps, libraries, enterprise software), cut a release branch from main when you're ready to stabilize.

```
main ──●──●──●──●──●──●──●──►
            ↓
        release/1.3   ────●──●──►
                        (only bug fixes cherry-picked in)
```

```bash
# Cut release branch from main
git checkout -b release/1.3.0 main

# Only bug fixes go into the release branch
# They're cherry-picked from main (never the other way)
git cherry-pick abc1234  # specific bug fix commit
```

The rule is absolute: **code only flows from main to release branches, never from release branches back to main.** Bug fixes are fixed in main first, then cherry-picked.

---

## Team Dynamics and Culture

TBD is as much a cultural practice as a technical one. Here's what shifts when a team adopts it.

### Communication Becomes More Important

When everyone is working in the same branch, the cost of surprises goes up. Engineers naturally start talking more:

- "Hey, I'm about to refactor the payment module, anyone else touching that?"
- "I'm going to push a DB migration in about 20 minutes, heads up"
- Stand-ups become more about "what am I touching today" and less about status theater

### Code Reviews Change Shape

In TBD, code reviews happen faster and on smaller pieces. A PR with 3 commits and 80 lines of changes is reviewed in 20 minutes. A PR with 3 weeks of work and 1,200 lines of changes takes days and frustrates everyone.

```
Traditional branching:
PR: 1,200 lines changed
Review time: 2-3 days
Reviewer mood: 😤

TBD-style PR:
PR: 85 lines changed
Review time: 20-30 minutes
Reviewer mood: 😊
```

This feedback loop is one of TBD's underrated benefits — issues are caught sooner, when they're still cheap to fix.

### Broken Trunk is a Team Emergency

In TBD, a broken `main` isn't "that engineer's problem." It's everyone's problem. The whole team is blocked.

```
✅ Team norms in TBD:
- "I broke main" is said out loud, immediately
- The person who broke it fixes it — with help if needed
- A broken main is fixed within minutes, not hours
- No one ever says "we'll deal with it later"

❌ Antipatterns:
- Silently opening a "fix CI" PR and going to lunch
- Arguing about whether the tests were already failing
- Deciding the broken tests "don't really matter"
```

---

## Common Objections (And Honest Answers)

**"We can't do TBD because our features take weeks to build."**

This isn't a TBD problem — it's a task decomposition problem. Any feature can be broken into smaller vertical slices that individually work. The question is whether you're willing to learn that skill. Feature flags handle anything that isn't "done" yet.

**"TBD means we can't do code review."**

False. Short-lived branches (1-2 days max) with PRs are fully compatible with TBD. Google, Meta, and Netflix all do code review. The review is just on smaller pieces, which is better anyway.

**"We'll break production constantly."**

If your CI is solid and your feature flags are used properly, TBD is actually *safer* than traditional branching. The failure mode in traditional branching is "everything breaks at once during a big merge." In TBD, failures are small and caught immediately.

**"Our team isn't senior enough for TBD."**

TBD with strong CI is often *better* for junior engineers because they get faster feedback. A broken test on a 50-line PR is much easier to fix than a broken merge conflict on a 1,500-line branch. Pair this with code review and TBD is a learning accelerant, not a hazard.

**"Our existing codebase can't support this."**

This one might actually be true in the short term. Legacy codebases without tests or CI pipelines need investment before TBD is safe. The migration path is: add tests → automate CI → introduce feature flags → shorten branch lifetimes → arrive at TBD.

---

## The Migration Path: Getting to TBD From Where You Are

If you're currently using Git Flow or long-lived branches, here's a realistic migration:

### Phase 1: Tighten the Pipeline (Month 1–2)

- Set up CI that runs on every push
- Achieve at least 60% test coverage on critical paths
- Enforce that `main` must pass CI before merge

### Phase 2: Shorten Branch Lifetimes (Month 2–3)

- Set a policy: no branch older than 5 days
- Break down tickets to match smaller branch sizes
- Hold retros when branches go long — "why did this take so long?"

### Phase 3: Introduce Feature Flags (Month 3–4)

- Adopt a feature flag library or service
- Start using flags for all new features
- Train the team on flag hygiene (flags must be removed after rollout)

### Phase 4: Tighten Further (Month 4–6)

- Reduce branch lifetime target to 2 days
- Introduce branch-by-abstraction for large refactors
- Automate deployment from `main` to staging

### Phase 5: Arrive at TBD (Month 6+)

- Branches are 1-2 days or less (or you commit directly)
- `main` is always deployable
- Feature flags are the default for all new work

Don't try to do all of this at once. Teams that flip to "pure TBD overnight" usually abandon it within a month because the culture and tooling weren't ready.

---

## Observability: Knowing What's in Production

In TBD, code reaches production frequently. You need to *see* what's happening:

### Distributed Tracing

```python
# Using OpenTelemetry — vendor-agnostic
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def process_payment(order_id: str, amount: float):
    with tracer.start_as_current_span("process_payment") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("payment.amount", amount)
        # your logic here
```

### Structured Logging

```python
import structlog

logger = structlog.get_logger()

def handle_webhook(event: dict):
    logger.info(
        "webhook_received",
        event_type=event.get("type"),
        event_id=event.get("id"),
        source=event.get("source"),
    )
```

### Health Checks

```python
# Every service should expose a health endpoint
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "version": "1.3.4",
        "commit": "a3f9c12",   # the actual commit that's deployed
        "timestamp": "2026-05-24T10:00:00Z"
    }
```

Embedding the commit SHA in your health check lets you instantly verify which version of the code is running — critical when you're deploying from main frequently.

---

## Key Insights by Experience Level

### For Junior Engineers

TBD will make you a better developer faster than any other practice. Here's why:

- You get feedback on your code *today*, not at the end of a two-week sprint
- Small commits force you to think clearly about what you're actually changing
- Breaking tests are your problem right now, when you remember exactly what you changed
- You'll learn to decompose big tasks into small steps — a skill that scales to your entire career

The most important habit to build: **never let a day end with uncommitted work sitting on a local branch**. Push something, even a work-in-progress behind a feature flag.

### For Mid-Level Engineers

Your edge in TBD is in the abstractions. When a feature is complex:

- Design the interface first, merge it (empty/stub implementations are fine)
- Implement incrementally, merging each piece
- Use branch-by-abstraction for anything touching existing code at scale
- Own the feature flag lifecycle — you create it, you clean it up

Watch for this trap: "I'll merge it when it's perfect." Perfection is the enemy of integration. Merge working code continuously and iterate.

### For Senior Engineers and Tech Leads

Your job in a TBD environment shifts to:

- **Setting the bar for what "deployable" means.** If the standard is fuzzy, the trunk will be unreliable.
- **Designing systems that are decomposable.** Monolithic code is hard to work on in small increments. Modular code isn't.
- **Enforcing flag hygiene.** Technical debt from abandoned flags accumulates fast without ownership.
- **Mentoring the commit discipline.** The "how" of breaking down a feature into safe incremental steps is a teachable skill that most engineers never explicitly learn.
- **Measuring what matters.** TBD should reduce your lead time (idea to production) and mean time to recovery (MTTR). If it's not, investigate why.

---

## Metrics: How You Know TBD Is Working

The DORA metrics (from the DevOps Research and Assessment team) are the industry standard for measuring this:

| Metric | What It Measures | Elite Performance |
|--------|-----------------|-------------------|
| Deployment Frequency | How often you deploy to production | Multiple times per day |
| Lead Time for Changes | Code committed → code in production | Less than 1 hour |
| Change Failure Rate | % of deployments causing incidents | 0-5% |
| Mean Time to Recovery | Time to recover from a production incident | Less than 1 hour |

TBD directly improves all four. Smaller changes deploy more frequently, reach production faster, have lower failure rates (because they're smaller), and recover faster (because rollback is a flag flip or a single small revert).

---

## What TBD Is Not

A few things TBD is commonly confused with:

**TBD is not "commit broken code to main."**
Broken code in the trunk is a failure of the practice, not a feature of it. The trunk must always be deployable.

**TBD is not "skip code review."**
Short-lived branches + PRs are standard in TBD. The reviews are just smaller and faster.

**TBD is not only for large teams.**
Google and Facebook use it at scale, but so do 3-person startups. It scales in both directions.

**TBD is not the same as Continuous Deployment.**
TBD is a branching strategy. Continuous Deployment is a deployment practice. They pair beautifully, but you can do TBD without deploying every commit (you just deploy from a deployable trunk on a schedule).

---

## The Bottom Line

Trunk-Based Development is the closest thing the industry has to a "best practice" for high-performing teams. It eliminates integration hell, surfaces problems early, and creates a culture of continuous, incremental progress.

But it is not plug-and-play. It requires:

- Automated CI that is fast and reliable
- Feature flags as a first-class engineering practice
- A team culture where breaking main is taken seriously
- The discipline to decompose large features into small commits
- Observability so you can see what your code is doing in production

Teams that do TBD well ship more features, have fewer outages, recover faster when incidents happen, and spend their Friday afternoons building instead of resolving merge conflicts.

Teams that do it poorly have a perpetually broken `main`, flags that have been `False` for two years, and a CI pipeline that takes 40 minutes to run.

The difference isn't the strategy — it's the craft.

---

## Quick Reference

```
Core rule:         Integrate to main at least once per day
Branch lifetime:   < 2 days (ideally hours)
Trunk state:       Always deployable, always passing CI
Incomplete work:   Hidden behind feature flags
Big refactors:     Branch by abstraction (no Git branch needed)
DB changes:        Expand → Migrate → Contract
Broken trunk:      Team's highest priority, fix immediately
Code review:       Still happens, on smaller PRs
Release:           Tag from main, or cut release branch for versioning
Measure success:   DORA metrics (deploy frequency, lead time, CFR, MTTR)
```

---

*For teams migrating from Git Flow or long-lived branches: start with CI automation and test coverage, then shorten branch lifetimes, then introduce feature flags. Don't try to flip to TBD overnight.*
