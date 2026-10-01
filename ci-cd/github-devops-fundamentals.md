# GitHub Actions and AWS

GitHub is the repo, the review, and the workflow runner. For this kind of setup it is also the audit log: who merged, which workflow assumed which role, which SHA got deployed. The application in [part 2](./github-devops-implementation-02.md) and the Fargate stack in [part 3](./github-devops-production-03.md) hang off the decisions in this note.

Use OIDC to assume an IAM role. Do not put access keys in Actions secrets. Keys live until someone rotates them. A workflow token lives for the job.

---

## What a change walks through

```
push to a short-lived branch
  → pull request
  → tests, image build, review
  → merge to main
  → deploy staging
  → approval
  → deploy production
```

`main` stays deployable. Feature branches live a couple of days at most. Unfinished work is behind a flag, not behind a branch that has been open for three weeks. Branch protection is how you stop "we'll fix CI after merge."

```yaml
# required status checks on main
# tests
# coverage threshold you will actually enforce
# security scan
# one approval
# stale reviews dismissed on new commits
# linear history if you do not want merge commits in the blame
```

A layout that does not make the pipeline hunt for things:

```
my-app/
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   ├── deploy-staging.yml
│   │   └── deploy-prod.yml
│   ├── CODEOWNERS
│   └── dependabot.yml
├── terraform/
│   ├── environments/
│   └── modules/
├── docker/
├── src/
└── tests/
```

Trunk-based versus Git Flow is a separate decision. If you deploy more than once a day and you only have one production version, do not invent `develop`. See [branch strategies](./branch-strategies.md).

---

## A workflow

A workflow is YAML in `.github/workflows`. It runs on a GitHub-hosted runner or one you operate. `on` is the trigger. Jobs run in parallel unless `needs` says otherwise. Steps inside a job are sequential.

```yaml
name: CI Pipeline
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 2 * * *'
  workflow_dispatch:

env:
  PYTHON_VERSION: '3.11'

jobs:
  test:
    name: Run Tests
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - run: pytest tests/
```

Pin actions to a commit SHA once this is a production workflow. A floating `@v4` tag moves when the maintainer moves it. `@v4` is fine while you are learning the file. It is not fine as the only control on a job that can assume a deploy role.

| Trigger | When |
|---------|------|
| `push` | Something landed on a branch. Deploy from `main` here, not from every branch. |
| `pull_request` | Review. Run tests. Do not deploy prod. |
| `schedule` | Cron in UTC. Nightly scans, not deploys, unless you enjoy incidents at 02:00. |
| `workflow_dispatch` | A person, with inputs. |
| `release` | A GitHub release, not just a tag. |
| `workflow_call` | Another workflow called this one. |
| `repository_dispatch` | Something outside GitHub posted to the API. |

A matrix is how you run the same job on several versions. This one is twelve jobs. That is a lot of minutes if the test suite is slow. Use it when you actually support those versions.

```yaml
jobs:
  test:
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11', '3.12']
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pytest tests/
```

`fail-fast` defaults to true. One cell failing cancels the rest. Set `fail-fast: false` when you need the full matrix to see which versions broke.

---

## Environments

An environment is a deployment target with its own secrets, its own protection rules, and a URL that shows up on the commit.

```yaml
jobs:
  deploy-production:
    environment:
      name: production
      url: https://api.example.com
    steps:
      - run: ./deploy.sh
```

Protection that matters on production:

- Required reviewers. One to six people. If it is the whole company, it is nobody.
- A wait timer, if you want a window to cancel.
- Deployment branches. `main` only, or a release tag. Not every branch.
- Secrets that exist only on that environment. The staging database URL does not belong in the repo secrets next to the prod one.

`environment` is also what makes a job wait. The reviewers click in the Actions UI. It is not a Kubernetes environment and it is not a Terraform workspace. People mix those up and then wonder why the secret was empty.

---

## Secrets

Organization, then repository, then environment. The environment value wins when the name collides, which is what you want for `DATABASE_URL`.

```yaml
steps:
  - name: Deploy
    env:
      AWS_REGION: ${{ secrets.AWS_REGION }}
      DATABASE_URL: ${{ secrets.DATABASE_URL }}
    run: ./deploy.sh
```

GitHub masks secrets in logs when the exact value appears. It does not mask a transformed value. Do not print them. Do not pass them on a command line that `ps` can see if you can avoid it.

```yaml
# this shows up in the log, mask or not, often enough to regret
- run: echo "API Key is ${{ secrets.API_KEY }}"

- run: ./script.sh
  env:
    API_KEY: ${{ secrets.API_KEY }}

- name: Mask a value the job just created
  run: |
    TOKEN=$(generate_token)
    echo "::add-mask::$TOKEN"
    echo "TOKEN=$TOKEN" >> "$GITHUB_ENV"
```

Prefer OIDC over any long-lived cloud credential. If a third party only offers a token, put it in an environment secret, mark it, and rotate it. Ninety days is a policy. The policy is useless if nothing fails when the secret is 200 days old.

`GITHUB_TOKEN` is already there. Permissions are contents read unless you widen them. Set `permissions` on the workflow to the minimum. A deploy job that needs `id-token: write` does not also need `contents: write`.

---

## Reusable workflows

Put the deploy in one file. Call it with the environment name. Copy-pasted workflows drift the first time someone patches staging and not prod.

```yaml
# .github/workflows/deploy-template.yml
name: Deployment Template
on:
  workflow_call:
    inputs:
      environment:
        required: true
        type: string
      aws-region:
        required: false
        type: string
        default: 'us-east-1'
    secrets:
      aws-role:
        required: true
    outputs:
      deployment-url:
        description: Deployed application URL
        value: ${{ jobs.deploy.outputs.url }}

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    outputs:
      url: ${{ steps.deploy.outputs.url }}
    steps:
      - id: deploy
        run: echo "url=https://${{ inputs.environment }}.example.com" >> "$GITHUB_OUTPUT"
```

```yaml
# .github/workflows/deploy-prod.yml
name: Deploy Production
on:
  push:
    branches: [main]
jobs:
  deploy:
    uses: ./.github/workflows/deploy-template.yml
    with:
      environment: production
      aws-region: us-east-1
    secrets:
      aws-role: ${{ secrets.PROD_AWS_ROLE }}
```

Caller workflows need `permissions` if the called workflow assumes a role with OIDC. The token does not inherit a wide default from the caller the way people expect. Set `id-token: write` on the called workflow's job.

Pin reusable workflows from other repos to a tag or a SHA. `uses: org/repo/.github/workflows/deploy.yml@main` means their next push is your next deploy.

---

## GHCR, if you are not on ECR

ECR is the registry when the runtime is ECS. GHCR is reasonable for images that stay inside GitHub, or for public images you do not want to pay Docker Hub for.

```yaml
- uses: docker/login-action@v3
  with:
    registry: ghcr.io
    username: ${{ github.actor }}
    password: ${{ secrets.GITHUB_TOKEN }}

- run: |
    IMAGE_NAME=ghcr.io/${{ github.repository }}:${{ github.sha }}
    docker build -t "$IMAGE_NAME" .
    docker push "$IMAGE_NAME"
```

The job needs `packages: write`. Push the SHA. A `:latest` tag is a convenience for humans and a bug if production tracks it.

---

## Dependabot

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
    open-pull-requests-limit: 10
    labels: [dependencies, python]
  - package-ecosystem: docker
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
  - package-ecosystem: terraform
    directory: /terraform
    schedule:
      interval: weekly
```

Grouped updates matter once you have more than a few dependencies. Ten PRs a week that nobody merges is not a security program. Auto-merge only for patch updates on a library whose tests you trust. Do not auto-merge a major, and do not auto-merge an action that your deploy job uses, until someone has looked at the changelog.

---

## Order of the pipeline

Cheap checks first. The deploy last. A twenty-minute image build that runs before unit tests is how you wait to find a typo.

```
unit tests and lint on every push
  → integration tests and scans on the PR
  → staging on merge to main
  → production after a person, or after the staging checks you trust
```

Rough budgets I will actually argue for: unit tests in a few minutes, the PR pipeline under ten, staging deploy around fifteen including the health check. Past that, people stop watching and you find out from production.

---

## Ship an image, not a git pull

```yaml
# this is how a box drifts from the repo and from every other box
- run: |
    ssh production "cd /app && git pull"
    ssh production "pip install -r requirements.txt"
    ssh production "systemctl restart app"
```

Build an image tagged with the commit. Push it. Point the service at that tag. The same digest runs in staging and prod. Rollback is the previous digest. There is no "someone pip-installed a hotfix on the box."

```yaml
- run: |
    docker build -t "myapp:${{ github.sha }}" .
    docker push "myapp:${{ github.sha }}"
    aws ecs update-service \
      --cluster production \
      --service api \
      --task-definition "api:${{ github.sha }}"
```

That `update-service` sketch is incomplete on purpose. ECS does not accept a tag as a task definition. You render a new revision and deploy that. Part 2 has the real steps.

GitOps, in this setup, means the change is a commit and a workflow applies it. Nobody runs `terraform apply` from a laptop against production. Plan on the PR. Apply on merge, from the workflow, with the plan you reviewed. If apply can change more than the plan showed, you do not have the lock or the concurrency right.

---

## Scans on the PR

Catch the cheap stuff before merge. SAST, dependency vulnerabilities, secrets in the diff, the image, the Terraform.

```yaml
jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bandit -r src/ -ll
      - run: |
          pip install safety
          safety check
      - uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.pull_request.base.sha }}
          head: ${{ github.event.pull_request.head.sha }}
      - uses: aquasecurity/trivy-action@master
        with:
          image-ref: myapp:${{ github.sha }}
          severity: CRITICAL,HIGH
          exit-code: 1
      - uses: aquasecurity/tfsec-action@v1.0.0
```

`|| true` on these commands is how the job stays green while it finds things. If the finding should block, the exit code has to fail the job. Pin `trufflehog` and `trivy-action`. `@main` and `@master` are not pins.

A scan that only runs on `main` after the merge is a report, not a gate.

---

## Logs, metrics, traces

Do this in the app before the first prod deploy. Bolting it on during an incident means you are guessing.

Structured logs, one JSON object per line, with the fields you will query. A counter or a histogram for the request path, not a custom metric for every if-statement. A trace on the request so a slow checkout is a span and not a theory.

```python
logger.info(
    "user_login",
    user_id=123,
    method="oauth",
    duration_ms=45,
)
```

```python
from prometheus_client import Counter, Histogram

login_counter = Counter("user_logins_total", "Total user logins")
request_latency = Histogram("http_request_duration_seconds", "HTTP request latency")
```

The Prometheus client is the right call if you scrape it. On ECS the path of least resistance is CloudWatch EMF or the embedded metric format, or an OTel collector sidecar. Do not add a Prometheus server to scrape three tasks. Part 3 puts alarms on the ALB and the service. Those alarms are useless if the app does not fail health checks when it cannot serve.

---

## Blue/green and canary

Blue/green is two target groups. You shift traffic, watch, then drop the old tasks after you still have them for a rollback. On ECS that is CodeDeploy. A second service you update by hand is not blue/green. It is two services.

Canary is a small slice first. Five percent, watch error rate and latency, then half, then the rest. Roll back on a condition you wrote down before the deploy, not on a feeling in the moment. Error rate over one percent, p95 over the SLO, health checks failing. Pick numbers from the service's normal week. A threshold copied from a blog will page you on Tuesday traffic.

If you do not have the metrics, you do not have a canary. You have a small outage.

---

## OIDC into AWS

| | Access keys | OIDC |
|---|---|---|
| Lifetime | Until you rotate them | About an hour, per job |
| Where they live | GitHub secrets | Nowhere. AWS issues them after it trusts the token |
| Blast radius | Whatever the IAM user can do, until you notice | That role, for that repo, for that branch, until the job ends |
| CloudTrail | The IAM user | The role, with the workflow in the session name |

The flow is: Actions requests an OIDC token. The token's subject is the repo and the ref, or the environment. STS `AssumeRoleWithWebIdentity` checks the role's trust policy. The job gets temporary credentials. They die with the job.

One provider per account.

```hcl
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = [
    "sts.amazonaws.com",
  ]

  # Required by the resource. AWS validates GitHub's issuer
  # against its own trusted CAs. Keep the value AWS documents
  # for token.actions.githubusercontent.com.
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
  ]
}
```

The trust policy is the control. Audience is `sts.amazonaws.com`. Subject is locked to the repo and the ref. A subject of `repo:your-org/*` is every repository in the org. GitHub's subject for a branch looks like `repo:ORG/REPO:ref:refs/heads/BRANCH`. For an environment it is `repo:ORG/REPO:environment:NAME`.

```hcl
data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    effect = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    actions = ["sts:AssumeRoleWithWebIdentity"]

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = [
        "repo:your-org/your-repo:ref:refs/heads/main",
      ]
    }
  }
}

resource "aws_iam_role" "github_actions" {
  name               = "GitHubActionsDeployRole"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json
}
```

I keep production deploys on the environment subject, not only the branch. A branch rule lets any workflow that runs on `main` assume the deploy role, including a workflow someone added last week. An environment rule means they also had to target `environment: production`, which has reviewers.

```hcl
condition {
  test     = "StringEquals"
  variable = "token.actions.githubusercontent.com:sub"
  values   = ["repo:your-org/your-repo:environment:production"]
}
```

Separate roles for CI and for deploy. CI can push to ECR. Deploy can register a task definition and update the service. Neither is `AdministratorAccess`. `iam:PassRole` is limited to the task execution role and the task role, and only when the service is `ecs-tasks.amazonaws.com`. A deploy role that can pass any role is a deploy role that can become any role.

```hcl
resource "aws_iam_role_policy" "ecs_deploy" {
  name = "ECSDeploymentPolicy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:DescribeTaskDefinition",
          "ecs:RegisterTaskDefinition",
          "ecs:UpdateService",
          "ecs:DescribeServices",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = "iam:PassRole"
        Resource = [
          "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
          "arn:aws:iam::123456789012:role/ecsTaskRole",
        ]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      },
    ]
  })
}
```

`ecs:RegisterTaskDefinition` does not support resource-level permissions. `Resource = "*"` on that action is normal. Do not "fix" it with a fake ARN. Tighten `PassRole` instead. That is the privilege that matters.

```yaml
name: Deploy with OIDC
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::123456789012:role/GitHubActionsDeployRole
          aws-region: us-east-1
          role-session-name: GitHubActions-${{ github.run_id }}
      - run: aws sts get-caller-identity
      - id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      - env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t "$ECR_REGISTRY/myapp:$IMAGE_TAG" .
          docker push "$ECR_REGISTRY/myapp:$IMAGE_TAG"
```

`id-token: write` is what lets the job request the JWT. Without it, `configure-aws-credentials` fails in a way that looks like a bad role ARN. Check the permissions block first.

If a vendor or a legacy account forces keys, scope the IAM user to that workflow, store the keys as environment secrets, and put a rotation date where a human will see it. Treat it as debt. The trust policy above is the replacement, not a nice-to-have.

```yaml
- uses: aws-actions/configure-aws-credentials@v4
  with:
    aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
    aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
    aws-region: us-east-1
```

When assume-role fails, look at the subject in the workflow log and at the trust policy side by side. The usual mismatches are `refs/heads/main` versus an environment subject, a workflow in a different repo than the one in the condition, and a missing audience check that you then "fixed" by widening `sub` to `*`.

Part 2 is the application, the image, and the workflows that use this role. Part 3 is the VPC, the service, and what you look at when the tasks will not stay up.
