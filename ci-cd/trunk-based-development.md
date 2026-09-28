# Trunk-based development

A feature branch that lives for two weeks does not merge. It gets reconciled. Forty conflicts, a Monday that was supposed to be for the next piece of work, and a trunk nobody trusts. That is integration hell. Trunk-based development is the practice of not letting the branch get that far from `main`.

Everyone integrates into one shared branch, the trunk, at least once a day. The trunk stays deployable. Not "deployable except auth." Deployable, on every commit.

```
WITHOUT TBD:                          WITH TBD:

main ────────────────────►            main ──────────────────────────────►
                                             ↑  ↑  ↑  ↑  ↑  ↑  ↑  ↑  ↑
feature-A ─────────────►                   (small commits, frequently)
feature-B ─────────────►
feature-C ─────────────►
(merge all at end = pain)             (integrations are tiny, conflicts are tiny)
```

---

## The split that matters

Most of us learned Git as: branch, disappear for a week, come back, merge. The isolation feels safe. It also means the first time your code meets everyone else's is the day you wanted to ship.

Trunk-based splits two events that a long-lived branch glues together.

- **Integration.** Your change is on the shared branch.
- **Release.** A user can see the feature.

On a long-lived branch those happen at merge time. On trunk-based, code lands continuously and a flag decides when the feature is visible. You can have the code in production on Monday and turn it on Thursday.

---

## One trunk

`main` passes tests and checks on every commit. A red trunk is the team's work, before standup, before the next feature. The person who broke it says so and fixes it. Other people help if the fix is not obvious. Nobody opens a "fix CI" PR and goes to lunch.

```bash
main

feature/add-retry-logic      # opened today, merged today or tomorrow
fix/null-check-in-parser     # opened this morning, merged this afternoon
```

Short-lived branches for review are normal. That is scaled trunk-based. Google, Meta, and Netflix review code. The review is on a small diff.

If the branch is older than two days, it is not trunk-based. The work was too big, or the review sat.

```
Day 1, 9am:  git checkout -b feature/add-search-filter
Day 1, 2pm:  PR, three commits
Day 1, 4pm:  merged, branch deleted

Day 1:  git checkout -b feature/rebuild-entire-search
Day 12: merged, with conflicts
```

The second one is a feature branch with a hopeful name.

You release from `main`. If you need a release branch for a versioned product, you cut it at release time and cherry-pick fixes onto it. Fixes are written on `main` first. Code does not flow from the release branch back.

---

## Small commits

A commit is a change that passes tests on its own. It is not a save point for a half-finished feature.

```bash
git commit -m "implement entire user authentication system"

git commit -m "add User model with email and hashed password fields"
git commit -m "add password hashing utility using bcrypt"
git commit -m "add login endpoint with credential validation"
git commit -m "add JWT token generation on successful login"
git commit -m "add authentication middleware for protected routes"
```

The first one cannot be reviewed, reverted, or bisected in any useful way. The others can.

---

## Flags

Without a flag you have two bad options: every commit is a finished feature, or users see half a feature. A flag is a conditional.

```python
FEATURE_FLAGS = {
    "new_dashboard": False,
    "ai_recommendations": False,
    "redesigned_checkout": True,
}

def is_enabled(flag_name: str) -> bool:
    return FEATURE_FLAGS.get(flag_name, False)
```

```python
from config import is_enabled

def dashboard_view(request):
    if is_enabled("new_dashboard"):
        return render(request, "dashboard_v2.html")
    return render(request, "dashboard.html")
```

The new dashboard is on `main` while the flag is off. Flipping it does not require a deploy if the flag service is outside the process. A dict in the repo still needs a deploy to change. Fine for a first version. It will not survive more than a few flags.

Percentage rollouts have to be stable per user. Hash the flag and the user id. Do not use `random()`.

```python
import hashlib

def is_enabled_for_user(flag_name: str, user_id: str, rollout_percentage: int) -> bool:
    hash_input = f"{flag_name}:{user_id}".encode()
    hash_value = int(hashlib.md5(hash_input).hexdigest(), 16)
    bucket = hash_value % 100
    return bucket < rollout_percentage
```

MD5 here is a bucket function, not a password hash. Start at 1%, watch errors and latency, then 10, 50, 100. Turning the flag off is the rollback.

A config file stops working once you need targeting, an audit log, or an off switch that does not ship a binary. Use a service.

| Service | What it is | When I use it |
|---------|------------|---------------|
| LaunchDarkly | Commercial | Targeting rules you do not want to build |
| Flagsmith | Open source | You want to host it |
| Unleash | Open source | You want the API and the audit log |
| AWS AppConfig | Managed | The app is already on AWS and the flag is configuration |
| Split.io | Commercial | The flag is an experiment with a metric attached |

```python
import ldclient
from ldclient.config import Config

ldclient.set_config(Config("YOUR_SDK_KEY"))
client = ldclient.get()

user = {
    "key": str(current_user.id),
    "email": current_user.email,
    "custom": {
        "plan": current_user.plan,
        "country": current_user.country,
    },
}

if client.variation("new-checkout-flow", user, False):
    return render_new_checkout()
return render_old_checkout()
```

The third argument to `variation` is the default when the service cannot be reached. Pick the safe one, usually off for a new path.

Flags that never get deleted are untested branches. When the rollout is done, remove the flag in that same stretch of work. A comment with a ticket is the minimum. A flag named `new_login_flow_2022` in 2026 is not a feature. It is a fork in the code that nobody runs in tests as the false path anymore, or worse, that some client still hits.

---

## CI

Trunk-based without a fast pipeline is merging straight to the branch you deploy. Fix CI first.

Every commit to `main` should:

1. Lint, typecheck, and a cheap security scan. Under a minute.
2. Unit tests. A couple of minutes, no network.
3. Integration tests. Under ten minutes, with the real dependencies you can run in CI.
4. Build the artifact once.
5. Deploy that artifact to staging. Production is the same artifact, automatic or behind a person, depending on the service.

```yaml
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
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: ruff check .
      - run: mypy src/
      - run: bandit -r src/

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
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt -r requirements-dev.txt
      - run: pytest tests/unit/ -v --tb=short
      - run: pytest tests/integration/ -v --tb=short
        env:
          DATABASE_URL: postgresql://postgres:testpass@localhost/testdb
      - uses: codecov/codecov-action@v4

  deploy-staging:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - run: echo "Deploying to staging..."
```

If the pipeline takes longer than about ten minutes, people stop waiting. They push the next commit before they know the last one failed. Parallelize the tests. Do not "fix" a slow suite by skipping it on `main`.

```bash
pytest tests/unit/ -n auto
pytest tests/integration/ -n auto
```

---

## Branch by abstraction

Flags hide a feature. They do not help when you are replacing a library or a schema and every call site has to move. For that, do the refactor on `main` in steps.

1. Put an interface in front of the thing you are replacing.
2. Point the current code at that interface. Behavior does not change.
3. Write the new implementation behind the interface.
4. Switch call sites, or switch them with a flag.
5. Delete the old implementation and, if nothing else uses it, the interface.

```python
from abc import ABC, abstractmethod

import httpx
import requests

class HttpClient(ABC):
    @abstractmethod
    def get(self, url: str, timeout: int = 5) -> dict:
        pass

class RequestsClient(HttpClient):
    def get(self, url: str, timeout: int = 5) -> dict:
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()
        return response.json()

class HttpxClient(HttpClient):
    def get(self, url: str, timeout: int = 5) -> dict:
        with httpx.Client() as client:
            response = client.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()

def get_http_client() -> HttpClient:
    if is_enabled("use_httpx_client"):
        return HttpxClient()
    return RequestsClient()
```

Each step is a commit on `main`. The system works after each one. There is no merge at the end because there was no long-lived branch.

---

## Databases

You cannot flag away a missing column. Break the schema change into expand, migrate, contract. Each deploy rolls back on its own.

**Expand.** Add the new column. Keep the old one. Deploy code that still works with both.

```python
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verified",
            field=models.BooleanField(default=False),
        ),
    ]
```

**Migrate.** Backfill. Write both. Read the new one.

```python
def mark_email_verified(user):
    user.email_verified = True
    user.is_verified = True
    user.save()
```

**Contract.** After you have run long enough to trust the new column, and nothing reads the old one, drop it.

```python
class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField(
            model_name="user",
            name="is_verified",
        ),
    ]
```

Dropping the column in the same deploy that starts reading the new one is how you get a rollback that cannot roll back.

---

## Releases

**From main.** Every commit can be released. You tag when you deploy, or you deploy every green commit.

```
main ──●──●──●──●──●──●──●──►
           ↑           ↑
        v1.2.0       v1.3.0
```

```bash
git tag -a v1.3.0 -m "Release 1.3.0"
git push origin v1.3.0
```

**A hardening branch.** For something that ships a version people keep: mobile, a library, on-prem. Cut from `main` when you freeze. Only cherry-picks go on it, and those commits land on `main` first.

```
main ──●──●──●──●──●──●──●──►
            ↓
        release/1.3 ────●──●──►
```

```bash
git checkout -b release/1.3.0 main
git cherry-pick abc1234
```

Trunk-based is not continuous deployment. You can integrate daily and still ship on a schedule. The trunk is deployable either way. Continuous deployment is what you do with that.

---

## How the team behaves

People say what they are about to touch. A migration in twenty minutes is a message, not a surprise in someone else's test run.

Reviews get smaller. Eighty lines this afternoon, not twelve hundred lines after three weeks. The second kind of PR does not get a real review. It gets a skim.

A broken `main` blocks the team. Say it. Fix it in minutes. Do not debate whether the test was already flaky while the trunk stays red. If the test is flaky, fix the test or delete it. A flaky required check trains people to rerun until green.

---

## The objections

**"Features take weeks."** That is the size of the ticket, not a property of the feature. Slice it. Hide the unfinished slice behind a flag.

**"We will lose code review."** You will not. A one-day branch and a PR is normal. The review is easier because the diff is smaller.

**"We will break production."** A big merge breaks production all at once, after the branch has been green on its own for two weeks. Small commits fail small, and CI sees them the day they are written. That is safer if CI is real. If CI is not real, do not start here.

**"The team is too junior."** A failing test on a fifty-line change is easier to understand than a conflict on a fifteen-hundred-line branch. Pair the small PR with a review. The feedback arrives while they remember the change.

**"The codebase cannot do this."** Sometimes true this quarter. No tests and no CI means trunk-based is just pushing to production. Order is: tests on the paths that page you, CI that can fail a merge, flags, then shorter branches. Do not announce trunk-based on Monday and delete `develop` on Tuesday.

A workable sequence:

1. CI on every push. `main` cannot merge red. Coverage on the paths that matter, not a percentage for the dashboard.
2. No branch older than five days. When one is, ask why the ticket was that big.
3. Flags for new user-facing work, and a rule that the flag gets removed.
4. Bring the branch lifetime down to a day or two. Large refactors go through an abstraction on `main`. Staging deploys from `main` without a person copying an artifact.

Teams that flip the rule overnight and skip the pipeline quit within a month. The pipeline was the actual constraint.

---

## Seeing what you shipped

You deploy more often, so you need the commit in the process, not in a spreadsheet.

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def process_payment(order_id: str, amount: float):
    with tracer.start_as_current_span("process_payment") as span:
        span.set_attribute("order.id", order_id)
        span.set_attribute("payment.amount", amount)
```

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

```python
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "version": "1.3.4",
        "commit": "a3f9c12",
    }
```

`/health` stays cheap. Do not call the database in it. Put dependency checks on readiness. The commit on the health response is how you confirm which trunk revision is actually serving.

---

## Who does what

Juniors get feedback the same day, on a change they still understand. The habit is to not go home with the only copy of the work on a laptop. Push it behind a flag if it is not done.

Mid-level people design the seam first. Merge the interface with a stub. Implement behind it. They also own flag cleanup, because they created the flag.

Seniors define what "deployable" means, in checks, not in a sentence. They keep the code separable so a change can land in pieces. They notice flags that have been off for a year. The metrics that tell you the practice is working are the DORA ones: how often you deploy, how long from commit to production, how often a deploy hurts, how long you take to recover. If those do not move, the branch rule is theater.

| Metric | Elite range |
|--------|-------------|
| Deployment frequency | Several times a day |
| Lead time for changes | Under an hour |
| Change failure rate | 0–5% |
| Mean time to recover | Under an hour |

Smaller changes move all four. They ship more often, the blast radius is smaller, and rollback is a flag or a one-commit revert.

Trunk-based is not "push broken code." A red trunk means the practice failed. It is not "skip review." It is not reserved for large companies, and a three-person team can do it. It is not the same thing as deploying every commit.

```
Integrate to main at least once a day
Branch lifetime under two days
Trunk always deployable
Unfinished work behind a flag
Large refactors by abstraction, on main
Schema changes expand, then migrate, then contract
Red trunk gets fixed before anything else
Release by tagging main, or a branch cut from main
```

If you are on Git Flow today, start with CI and the tests. Then shorten branches. Then add flags. The order is the practice.
