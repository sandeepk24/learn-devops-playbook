# Branch strategies

Two people are in the same repo. One is fixing production. The other has a feature that will not ship for three weeks. They are touching the same files. If the team never agreed how code moves, you get overwritten work, a broken deploy, and a Slack thread that does not help.

A branch strategy is that agreement. Which branches exist, how code gets to production, who merges, and what a hotfix does. Pick one that matches how often you actually ship. Then enforce it. A wiki page nobody reads is not a strategy.

---

## Trunk versus long-lived branches

There are two shapes.

**Trunk-based.** Everyone integrates into one branch. Conflicts show up small, because the drift is small.

**Branch-heavy.** Work sits on long-lived branches. The merge is an event. The longer the branches live apart, the worse that event is.

Neither is the default. Release cadence, how many versions you have to keep alive, and whether CI is actually fast decide it.

---

## Trunk-based development

One branch, `main`. It stays deployable. Feature branches, if you use them, live hours to a couple of days.

```
main ─────────────────────────────────────────────►
       ↑   ↑   ↑   ↑   ↑   ↑   ↑   ↑   ↑
      (small, frequent commits from everyone)
```

People commit slices of work, often more than once a day. Unfinished features sit behind flags so the code can be on the trunk without being in front of users. CI runs on every commit. If the trunk is red, that is the work.

```bash
git pull origin main
git add .
git commit -m "add input validation to payment form"
git push origin main
```

Pushing straight to `main` is fine on a small team with CI. Most teams I work with still open a short PR so someone else sees the diff. The branch still dies the same day.

This fits teams that release more than once a day, and small services with a small owning team. It also fits when you are tired of merging a sprint's worth of work on Friday.

TBD makes a weak pipeline obvious. Slow or flaky tests hurt immediately. Teams that say they are "not ready" for trunk-based usually need a faster test suite, not a more elaborate branch model. The practice is what forces the suite to get fixed.

Without flags, half-built features ship. Someone has to break work into commits that leave `main` green. Juniors need help with that split. It is a skill, not a personality trait.

The longer write-up is [trunk-based development](./trunk-based-development.md).

---

## GitHub Flow

One long-lived branch. Short-lived feature branches. The pull request is the gate. Merge to `main` is the deploy.

```
main ──────────────────────────────────────────────►
         ↑                    ↑
    feature/login         fix/checkout-bug
    ─────────────         ────────────────
    (PR → review → merge) (PR → review → merge)
```

```bash
git checkout -b feature/user-authentication
git push origin feature/user-authentication
```

CI runs on the PR. Someone approves. Merge deploys.

This is the right shape for a web app that ships on every merge, for a team of roughly 2 to 20, and for open source where outsiders send PRs.

It assumes `main` is always deployable and that merge triggers a deploy. If you still deploy by hand, or you promote through a staging environment with a human gate, GitHub Flow is missing a step and people will invent one. If CI is weak, broken code lands on `main` with a green checkbox that did not mean much.

There is no staging branch in the model. Teams bolt one on and then they are not on GitHub Flow anymore. It also does not help when you have to keep two released versions alive. Review becomes the bottleneck if PRs sit.

---

## Git Flow

`main` and `develop` live forever. `feature/*`, `release/*`, and `hotfix/*` are temporary. Code walks through those stages before production.

```
main     ─────────────────────────────────────────────►
                    ↑                    ↑  (hotfix) ↑
release             │     release/1.2    │            │
develop  ────────────────────────────────────────────►
              ↑         ↑
          feature/A   feature/B
```

| Branch | Lives | What it is |
|--------|-------|------------|
| `main` | Forever | Production. A commit here is a release. |
| `develop` | Forever | The next release, accumulating. |
| `feature/*` | Days to weeks | Branched from `develop`. |
| `release/*` | Days | Cut from `develop`. Merges to `main` and back to `develop`. |
| `hotfix/*` | Hours | Cut from `main`. Merges to `main` and `develop`. |

```bash
git checkout develop
git checkout -b feature/payment-refund
git checkout develop
git merge --no-ff feature/payment-refund
git branch -d feature/payment-refund

git checkout -b release/2.1.0
git commit -m "bump version to 2.1.0"
git checkout main
git merge --no-ff release/2.1.0
git tag -a v2.1.0

git checkout develop
git merge --no-ff release/2.1.0
git branch -d release/2.1.0

git checkout main
git checkout -b hotfix/critical-payment-bug
git checkout main
git merge --no-ff hotfix/critical-payment-bug
git checkout develop
git merge --no-ff hotfix/critical-payment-bug
```

Use this when the product has a version people install: mobile, embedded, a library, enterprise software with a QA cycle and more than one supported release.

Git Flow is from 2010 and it matches that world. It is a bad fit for a service you deploy on every merge. `develop` is a buffer. If you deploy every PR, the buffer is overhead, and the long-lived branches are where the conflicts come from. Bugs sit on the release branch until someone calls them urgent. `develop` goes red and stays red because nothing deploys from it.

---

## GitLab Flow

GitHub Flow plus branches that match environments, or release branches for versioned software.

```
main        ──────────────────────────────────────────►
                ↓         ↓
pre-production  ──────────────────────────────────────►
                              ↓
production      ──────────────────────────────────────►
```

Feature branches come off `main`. A merge to `main` can deploy to a dev environment. Merging `main` into `pre-production` deploys staging. Merging that into `production` goes live.

For versioned software you keep `release/2-3-stable`, `release/2-4-stable`, and so on. Hotfixes land on the release branch and get cherry-picked to `main`.

```bash
git checkout -b feature/dark-mode
# PR to main deploys to dev
# merge main into pre-production when QA wants it
# merge pre-production into production when it checks out
```

This fits a real staging environment, a QA sign-off, or a compliance gate that has to be a merge and not just a button in the pipeline.

The failure mode is drift. Someone cherry-picks a fix onto `production` and never brings it back. Production and pre-production stop being the same code, and staging stops telling you anything. Code moves one direction, downstream. If a fix has to exist on an older release, it is written on `main` first and cherry-picked out.

---

## Forking

Each contributor has their own server-side copy. They push there and open a PR into the repo you actually ship from.

```
Blessed repo (origin)
        ↑         ↑         ↑
    fork/alice  fork/bob  fork/carol
```

```bash
git clone https://github.com/alice/project.git
git remote add upstream https://github.com/org/project.git
git checkout -b fix/broken-link
git push origin fix/broken-link
```

This is about trust, not about branches. You use it when you cannot give push access: open source, or a repo that takes changes from people outside the team. An internal team of employees does not need forks. Keeping a fork current with upstream is extra work and it buys you nothing if those people already have a PR workflow inside the repo.

---

## A branch per environment

`dev`, `staging`, and `production` are all long-lived, and deploying means merging into the next one.

```
production  ──────────────────────────────────────────►
staging     ──────────────────────────────────────────►
dev         ──────────────────────────────────────────►
                ↑
           feature branches merge here
```

I would not start here. The branches diverge. A hotfix on production does not make it back. Staging is no longer production's code, so a pass on staging does not mean the artifact you will ship. The merge is large. You find the bug on the production merge.

You still see this where "deploy" means merging because there is no pipeline. Fix the automation. The branches exist to stand in for it. Changing the diagram without a pipeline just renames the mess.

---

## Side by side

| Strategy | Complexity | Release cadence | Where it fits | The cost |
|----------|------------|-----------------|---------------|----------|
| Trunk-based | Low | Continuous | Any size, if CI is fast and people use flags | Weak tests show up immediately |
| GitHub Flow | Low | Continuous | Small to medium, one production version | No built-in staging or versioning |
| Git Flow | High | Scheduled, versioned | More than one supported release | Overhead if you ship daily |
| GitLab Flow | Medium | Continuous, with environment gates | Staging and a promotion step | Branches drift if merges go upstream |
| Forking | Medium | Whatever the upstream uses | Untrusted contributors | Useless friction inside one company |

---

## Picking one

**How often do you deploy?**

- Several times a day: trunk-based or GitHub Flow.
- Weekly or monthly: GitLab Flow, or Git Flow if you also version it.
- A versioned release on a calendar: Git Flow.

**More than one version in production?**

- Yes: Git Flow, or GitLab Flow with release branches.
- No: trunk-based or GitHub Flow.

**What does CI actually do?**

- Fast, trusted, and it deploys: trunk-based.
- Tests are real, deploy is still a person: GitHub Flow or GitLab Flow.
- Mostly manual: Git Flow matches that, and it will keep matching it until the pipeline exists.

**How many people?**

- A handful: GitHub Flow or trunk-based.
- Up to about twenty: GitHub Flow. Git Flow only if the releases are versioned.
- Larger: trunk-based with flags. Git Flow if you are supporting old versions and you have owners for `develop`.

**Who sends code?**

- Strangers: forking into the blessed repo.
- Employees: a branch in the same repo.

---

## What you still do, on any of these

### Flags

Flags are how unfinished work lands on the trunk without landing on users. That is the mechanism trunk-based depends on.

```python
def show_new_checkout_flow(user):
    return feature_flags.is_enabled("new_checkout", user_id=user.id)

if show_new_checkout_flow(current_user):
    render_new_checkout()
else:
    render_old_checkout()
```

The code can sit on `main` until you turn the flag on. Delete the flag after the rollout. A flag from two years ago is a branch you forgot to merge in your head.

### Names

```
feature/JIRA-123-user-auth
fix/JIRA-456-payment-timeout
hotfix/critical-null-pointer
release/2.4.0
chore/update-dependencies
```

The prefix is something the pipeline can branch on. `hotfix/*` can skip the slow suite you run on `release/*`. If the name is `misc-updates`, you cannot do that.

### Commit messages

```bash
git commit -m "fix: prevent null reference in payment processor when card is expired"
git commit -m "feat: add retry logic to webhook delivery (max 3 attempts)"
git commit -m "chore: upgrade Django from 4.1 to 4.2"
```

`fix stuff` is useless the night you are bisecting. [Conventional Commits](https://www.conventionalcommits.org/) is enough of a spec that a changelog can be generated from it. Adopt it if you want that. Do not adopt it as a style argument.

### Protected branches

```yaml
# main
# - at least one approving review
# - required status checks
# - branch up to date before merge
# - restrict who can push
# - signed commits if you already have a reason
```

Turn this on in the host. If it only lives in the README, it is optional.

### Short branches

- Feature work: one to three days. A week is already long.
- Release branches: days.
- Hotfixes: hours.

A feature branch that is three weeks old is a ticket that should have been several tickets.

---

## What goes wrong

People pick Git Flow because they have heard of it, including teams that deploy ten times a day. Match the model to the release, not to the blog post.

Long-lived feature branches make the conflict, the review, and the rollback all bigger. Split the work.

In Git Flow, `develop` is supposed to be shippable. If it is not, the tests are the problem.

If branch protection, required checks, and a PR template are not on, the strategy is a suggestion.

A model that worked at five people often does not work at twenty-five. Revisit it when the team, the cadence, or the deploy path changes.

The model matters less than whether `main` stays green, branches die quickly, and someone reviews the diff while it is still small. A team with that will survive a mediocre diagram. A team without it will not be saved by the right one.
