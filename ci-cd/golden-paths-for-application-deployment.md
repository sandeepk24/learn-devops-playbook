# Golden paths

A golden path is the deploy workflow you would rather people use, already wired up. Scaffolding, CI, image build, scan, push, promotion, secrets, logs, health checks, a scaling default. A developer follows it without designing a pipeline.

Spotify's platform group is where the name stuck. The point is older than the name. If every team invents its own CI, its own base image, and its own idea of a health check, you will spend the year diffing those inventions during incidents.

It is not a wiki page and it is not a ticket queue. If someone still has to copy a Jenkinsfile out of Confluence, you wrote homework. Deviation stays possible. It should be a deliberate choice with a reason you can find later, not a silent fork.

What the path usually owns:

- Repo bootstrap
- Lint, test, build, scan
- Image build and the registry lifecycle
- Where it runs, and one promotion path from dev to prod
- How secrets get into the process
- Logs, metrics, a health check that means something
- A scaling baseline and a resource limit

What it does not own is the business logic, and it is not a rule that every workload is an HTTP API. A batch job that is forced through the API path will grow a fake `/health` and you will trust it.

The right way is the easy way. The other way exists, and it leaves a record.

---

## What "paved" means

A paved path generates working pieces. `platform new-service --type api --lang python` gives you a repo, a workflow, a Dockerfile, a chart or a task definition, a log group, and a role that can read the secrets it needs. Day one it deploys. A document that describes those files is not the path.

Version it like software. When scanning becomes mandatory, you bump the path and open a PR against the services, the way Dependabot does. You do not edit forty repos by hand and call it a rollout. Teams on the old version get the PR. They do not get a surprise red build on a Friday because you changed a template they pin with `@main`.

Pin consumers to a tag (`@v2`), not to a branch. `@main` means their next build runs your unreleased edit.

The platform team owns the path. If the shared workflow breaks, one group fixes it. Eighty teams do not each discover the same broken action pin.

People will need out. GPU builds, a language you do not template, a compliance constraint the path does not know. Give them an override that records who, what, and why, and tells the platform team. If the only way out is a three-week review, they will copy the workflow into the service repo and you will not hear about it until it is the one that pages.

Numbers that tell you whether this is real:

- Share of services on the current path version
- Time from new repo to first prod deploy
- Deploy success rate by path version
- Count of pipelines that do not call the shared workflow

Adoption of an old version is not adoption. It is a backlog.

---

## Tools

| Layer | What people use |
|---|---|
| Scaffolding | Cookiecutter, Backstage templates, Copier |
| CI | GitHub reusable workflows, GitLab CI includes, Jenkins shared libraries, Tekton |
| Registry | ECR, Artifactory, Harbor |
| Deploy | Helm with Argo CD, Terraform modules, CDK |
| Secrets | Secrets Manager, Parameter Store, Vault |
| Telemetry | OpenTelemetry, CloudWatch, a vendor agent if you already pay for one |
| Policy | OPA/Gatekeeper, Kyverno, SCPs, Conftest in CI |
| Catalog | Backstage, Cortex, Port |

A reusable workflow is the smallest thing that counts. Service repos call it with `uses:`. You stop reviewing copies.

---

## The shape

```
platform new-service --type api
  → repo with the path already referenced
git push
  → lint, test, build, scan, push to ECR
merge
  → staging, then smoke tests
promotion
  → a person, or an SLO check, then prod
  → dashboard and alerts come from the module, not from a follow-up ticket
```

The platform repo holds the templates, the workflow tags, and the escape hatch. Service repos hold the application and a thin workflow that calls the path.

```yaml
# platform-templates: .github/workflows/golden-path-api.yml
name: Golden Path - Python API
on:
  workflow_call:
    inputs:
      service_name:
        required: true
        type: string
      ecr_repo:
        required: true
        type: string
      aws_region:
        required: false
        type: string
        default: us-east-1
    secrets:
      AWS_ROLE_ARN:
        required: true

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff pytest
      - run: ruff check .
      - run: pytest --tb=short

  build-and-scan:
    needs: lint-and-test
    runs-on: ubuntu-latest
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: ${{ inputs.aws_region }}
      - uses: aws-actions/amazon-ecr-login@v2
      - name: Build image
        run: docker build -t ${{ inputs.ecr_repo }}:${{ github.sha }} .
      - name: Scan with Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ inputs.ecr_repo }}:${{ github.sha }}
          exit-code: 1
          severity: CRITICAL,HIGH
      - name: Push to ECR
        run: docker push ${{ inputs.ecr_repo }}:${{ github.sha }}
```

Push the SHA. Skip `:latest` on a path you expect people to deploy. A moving tag is how prod and staging stop being the same image while the YAML still says `latest`.

The service side is the call.

```yaml
# service repo: .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  pipeline:
    uses: my-org/platform-templates/.github/workflows/golden-path-api.yml@v2
    with:
      service_name: payments-api
      ecr_repo: 123456789.dkr.ecr.us-east-1.amazonaws.com/payments-api
    secrets:
      AWS_ROLE_ARN: ${{ secrets.PLATFORM_DEPLOY_ROLE }}
```

`workflow_call` only runs if the caller workflow has a trigger. A file that is only `jobs:` and a `uses:` never starts. The `on:` block stays in the service repo. That is the part teams forget when they copy a snippet.

Build one path per shape of workload. An API, a worker, a scheduled job. A single path that also tries to be a data pipeline will be wrong for all of them. Share steps (lint, scan, push) and assemble the variants out of those. Do not copy the whole workflow into each variant.

---

## Where paths rot

The path is a document. Developers still configure the scan themselves. Then you do not have a path.

The template is unversioned, or everyone tracks `@main`. The day you add a required input, every service build breaks, including the one that is mid-incident.

One path for every runtime. Teams that do not fit will fork, and the fork will be the one missing the scan.

No escape hatch. The fork is silent. A silent fork is worse than a logged exception, because you still think the scan coverage number is real.

Nobody owns updates. A new base image CVE sits until each team notices. Assign the ownership or the path is a snapshot from the quarter you wrote it.

You never count who is on the current version. Without that number you cannot tell a working platform from a repo people starred.

---

## A small version you can actually build

A Python API on Fargate. One reusable workflow, one Terraform module. This is the skeleton, not a production module. It has no execution role, no network, and no service. It is enough to see the seam.

```bash
mkdir -p platform-templates/.github/workflows
mkdir -p platform-templates/terraform/modules/ecs-service
```

```yaml
# platform-templates/.github/workflows/python-api-golden-path.yml
name: Python API Golden Path
on:
  workflow_call:
    inputs:
      service_name:
        required: true
        type: string
    secrets:
      AWS_ROLE_ARN:
        required: true
jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff pytest httpx fastapi uvicorn
      - run: ruff check .
      - run: pytest -q
```

`ruff check . || true` and `pytest || echo "No tests found"` look green when the repo is empty or broken. Do not do that on a path you want teams to trust. If there are no tests, fail the scaffolding, or fail the job. A path that cannot go red will be ignored the first time it should have caught something.

```hcl
# platform-templates/terraform/modules/ecs-service/main.tf
variable "service_name" {}
variable "image_uri" {}
variable "cpu" { default = 256 }
variable "memory" { default = 512 }
variable "container_port" { default = 8080 }

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.service_name}"
  retention_in_days = 30
}

resource "aws_ecs_task_definition" "this" {
  family                   = var.service_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.cpu
  memory                   = var.memory

  container_definitions = jsonencode([{
    name      = var.service_name
    image     = var.image_uri
    essential = true
    portMappings = [{ containerPort = var.container_port }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.this.name
        "awslogs-region"        = "us-east-1"
        "awslogs-stream-prefix" = "ecs"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "curl -f http://localhost:${var.container_port}/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 60
    }
  }])
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}
```

Create the log group in the module. A task definition that points at a group nobody created shows up as a running task with no logs, and you will debug the app.

The service repo stays thin.

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}
```

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn --no-cache-dir
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

```yaml
name: CI
on:
  pull_request:
  push:
    branches: [main]
jobs:
  pipeline:
    uses: my-org/platform-templates/.github/workflows/python-api-golden-path.yml@v1
    with:
      service_name: payments-api
    secrets:
      AWS_ROLE_ARN: ${{ secrets.PLATFORM_DEPLOY_ROLE }}
```

`/health` returning ok without checking dependencies is the right liveness behavior. Readiness is a different endpoint. Do not put the database in the container health check the ALB uses, or a database blip will drain every task.

Count adoption from the workflow files, not from a survey. This hits the GitHub API. It will miss private workflow files if the token cannot read them, and it will mis-count a repo that mentions the string in a comment. Treat the percentage as a lead, then open the outliers.

```python
import httpx

def get_adoption_metrics(org: str, token: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    with httpx.Client() as client:
        repos = client.get(
            f"https://api.github.com/orgs/{org}/repos?per_page=100",
            headers=headers,
        ).json()
        using_golden_path = 0
        total = len(repos)
        for repo in repos:
            try:
                workflows = client.get(
                    f"https://api.github.com/repos/{org}/{repo['name']}/contents/.github/workflows",
                    headers=headers,
                ).json()
                for wf in workflows:
                    content = client.get(wf["download_url"]).text
                    if "platform-templates/.github/workflows" in content:
                        using_golden_path += 1
                        break
            except Exception:
                continue
        rate = (using_golden_path / total) * 100 if total else 0
        return {
            "org": org,
            "total_repos": total,
            "using_golden_path": using_golden_path,
            "adoption_rate": f"{rate:.1f}%",
        }
```

---

## How I talk about it

When someone asks what changed for developers, I talk about the before: the first two weeks on a service were pipeline work, health checks were optional, and two teams scanning images meant two different severities. Then the path: one workflow, one module with a log group and a health check, a scaffold that already calls `@v2`. The numbers that matter are time to first prod deploy, how many services fail a scan that used to be skipped, and how many unique workflows are left. Lines of Terraform are not one of the numbers.

Standardize the platform seam. Leave the language and the domain model with the team. The escape hatch is how you avoid a cage. If leaving the path requires five approvals, you will get unofficial paths and a compliance dashboard that lies.

Uptime of the platform is not the success metric. A platform that is up and takes forty-five minutes to deploy has missed the point. Adoption of the current version, time to first deploy, deploy frequency of the teams using it, and how often the platform itself causes the incident. If adoption is low, the path is not the easy way. Fix the path before you write a policy that requires it.

---

## Checking drift with a model

A model can read a service workflow against the reference and list missing steps. It is a review aid. It is not a gate. Do not fail CI on the JSON. Models invent steps, and a gate that flakes because the prose changed is a path teams will disable.

Use it to sort a backlog: which services skipped the scan, which ones added a custom deploy you have never seen. Confirm with the file before you file anything.

The useful loop is boring. New services come out of the template. Existing services get a PR when the path version moves. Once a quarter, look at the ones that do not reference the template and decide if that exception is still real.
