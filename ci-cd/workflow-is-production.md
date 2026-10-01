# The workflow file is production

A change to `.github/workflows` can assume the deploy role, push an image, and update the service. That file gets the same review as the task definition. A pull request that edits it is a production change that happens to be YAML.

[OIDC and environments](./01_GITHUB_DEVOPS_FUNDAMENTALS.md) are how the job gets into AWS. This note is who is allowed to change the job.

## Code owners

```
.github/workflows/** @org/platform
.github/actions/**   @org/platform
```

Turn on "Require review from Code Owners" for `main`. A pull request that touches a workflow waits for that team even when the rest of the diff is a typo in a README. Administrators can bypass branch protection. I leave that bypass off for this path. Break-glass is a second person in the platform group, not a skipped rule.

The same idea on GitLab is a CODEOWNERS entry for `.gitlab-ci.yml` and `.gitlab/ci/**`, plus protected branches so the file on the default branch is the one that runs. A merge train does not help if anyone can rewrite the train.

## The token

Set `permissions` on the workflow. The org or repo default is whatever someone picked in settings, and older repos still grant write. I set the workflow to nothing and grant the job what it uses.

```yaml
permissions: {}

jobs:
  test:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
      - run: pytest -q

  deploy:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
```

`id-token: write` is the OIDC token. It is not a GitHub write. `contents: write` on a deploy job is how a compromised step pushes to the repo. The deploy job reads the repo and assumes an AWS role. The AWS role is the one from the fundamentals note, scoped to the workflow file on `main`.

An action reads `github.token` even when the workflow never passes it. The `permissions` block is what that token can do. Narrow it before you add the action.

In the org settings, set the default `GITHUB_TOKEN` to read. Workflows that need more say so in the file, where the review can see it.

## Pin the action

A tag such as `@v4` moves when the maintainer moves it. The job runs whatever commit that tag points at today. Pin to the full commit SHA. The comment is for the human. The SHA is what runs.

GitHub can require that pin at the org or the repo: "Require actions to be pinned to a full-length commit SHA." Turn it on. It covers actions from your org and actions GitHub publishes. It does not cover reusable workflows. Those can still be called by tag. Pin them to a release tag, and keep `@main` off the `uses:` line. That exception is why [golden paths](./golden-paths-for-application-deployment.md) version the template.

Dependabot's `github-actions` ecosystem opens the pull request that bumps the SHA. The review is the point. Auto-merge on an action the deploy job uses is how a bad release becomes your next production deploy. Let that one wait for a person.

Allow-list actions at the org if you can. "Allow select actions" plus the pin policy is the pair. A workflow that references an action outside the list fails closed, which is what you want the first time someone pastes a Marketplace link.

## pull_request_target

`pull_request` from a fork runs the workflow from the merge commit, with a read-only token and no access to secrets. That is the right boundary for building and testing untrusted code.

`pull_request_target` runs the workflow file from the default branch and grants the base repository token and secrets. The default checkout is that same default branch. Used that way, it can label a pull request or comment on it.

The boundary breaks when the job checks out the pull request head and runs it. `npm install`, a Makefile, a composite action from that tree, or `run:` on a script in the pull request all execute the fork's code with the secrets. GitHub's own guidance is that the event is safe because the workflow and the default checkout come from the base branch. Keep it that way.

Fork pull requests that need a plan or a deploy comment get a workflow on `pull_request` with no cloud credentials. The terraform note already says this. Switching that job to `pull_request_target` so the fork can assume the plan role is the bug.

## What review is looking for

On a workflow diff I read four things.

The trigger. `pull_request_target`, `workflow_dispatch` without an environment, and `push` to every branch are the ones that widen who can start the job.

The `permissions` block. A new `write` scope needs a reason in the pull request. `contents: write` and `pull-requests: write` on a job that also has `id-token: write` is two privileges glued together.

The `uses:` lines. A new action, a tag instead of a SHA, or a reusable workflow on `@main`.

The environment. Production deploys name `environment: production`, and that environment has required reviewers. A job that assumes the production role without the environment is a deploy with the reviewers removed.

If those four are unchanged, the workflow review is the same as any other YAML review. If one of them moved, it is a production change.
