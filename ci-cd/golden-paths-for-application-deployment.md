# Golden Paths for Application Deployment

**Level:** Intermediate to Principal  
**Why this matters:** Golden paths reduce the cognitive load on developers by providing opinionated, pre-approved deployment patterns that embed security, reliability, and compliance by default. Teams that build golden paths stop playing whack-a-mole with snowflake configurations and start shipping faster. For principal-level engineers, defining golden paths is the transition from "fix incidents" to "prevent entire classes of problems at the platform layer."

---

## 1. Core Concept

A golden path is a well-lit, paved road for how an application gets from code to production. It is not a policy document or a runbook — it is an opinionated, automated, end-to-end workflow that a developer can follow without becoming a DevOps expert.

The term was popularized by Spotify's internal platform team. The idea: instead of forcing every team to design their own CI/CD pipeline, container strategy, secrets management approach, and monitoring setup, the platform team builds one excellent, tested, maintained version of each and makes it easy to adopt.

**What a golden path covers:**

- Code structure and repo bootstrapping (cookiecutter / scaffolding)
- CI pipeline definition (lint, test, build, scan)
- Image build and push strategy (Docker multi-stage, ECR lifecycle)
- Deployment target selection (ECS vs EKS, Fargate vs EC2)
- Environment promotion logic (dev → staging → prod)
- Secrets injection pattern (Secrets Manager or Parameter Store integration)
- Observability defaults (structured logging, CloudWatch metrics, tracing)
- Health check and readiness probe configuration
- Auto-scaling baseline (target tracking, min/max)
- Cost controls (resource limits, rightsizing recommendations)

**What a golden path is NOT:**

- A mandatory standard enforced by gatekeeping tickets
- A one-size-fits-all straitjacket
- A replacement for team autonomy on business logic

The key mental model: golden paths make the right thing the easy thing. Deviation should be possible, but it should require a deliberate choice and a documented reason.

---

## 2. Production Engineering View

At FAANG-scale, golden paths are the primary mechanism for shipping reliably across hundreds of teams. What separates a mature golden path from a wiki page:

**Paved vs. Unpaved:** A paved golden path means the scaffolding generates working code, pipelines, dashboards, and alerts — not documentation explaining how to configure them. When a team runs `platform new-service --type api --lang python`, they get a repo with a working GitHub Actions workflow, a Dockerfile, a Helm chart or ECS task definition, a CloudWatch dashboard, and a Secrets Manager policy — ready to deploy on day one.

**Versioned and upgradeable:** Golden paths must be versioned like software. When the security team mandates Trivy scanning in all pipelines, the platform team bumps the golden path version and all services can opt into the upgrade. Teams on old versions receive an automated PR or a Dependabot-style notification.

**SLA ownership is clear:** The platform team owns the golden path SLA, not individual service teams. If the shared pipeline pattern breaks, the platform team fixes it once — not 80 teams independently.

**Escape hatch pattern:** Production teams will always need to deviate. The golden path must have a documented escape hatch — e.g., `platform override --component ci-pipeline --reason "needs GPU build node"` — that creates an audit log entry and notifies the platform team. This is better than silent deviation.

**Real signals to track:**
- Golden path adoption rate (% of services using the current version)
- Mean time to first deploy (how long from new service creation to first prod deploy)
- Deployment success rate by path version
- Number of custom pipeline configurations in the org (proxy for unpaved paths)

---

## 3. Tools and Technologies

| Layer | Tool Options |
|---|---|
| Scaffolding | Cookiecutter, Backstage Software Templates, Projen, Yeoman |
| CI/CD | GitHub Actions (reusable workflows), Jenkins shared libraries, Tekton pipelines |
| Container registry | Amazon ECR, JFrog Artifactory, Harbor |
| Deployment | Helm + ArgoCD, AWS CDK, Pulumi, Terraform modules |
| Secrets | AWS Secrets Manager, HashiCorp Vault, AWS Parameter Store |
| Observability | OpenTelemetry collector, CloudWatch EMF, Datadog Agent sidecar |
| Policy enforcement | OPA/Gatekeeper, Kyverno, AWS SCP |
| Developer portal | Backstage, Cortex, Port |

**GitHub Actions reusable workflow** is the most practical starting point for most orgs — it lets you publish a centrally maintained workflow that service repos call with a single `uses:` reference.

---

## 4. Architecture Pattern

```
┌────────────────────────────────────────────────────────────┐
│                   Developer Workflow                        │
│  1. platform new-service --type api                        │
│     ↓ generates repo with golden path wired in             │
│  2. git push → CI triggers (reusable workflow)             │
│     ↓ lint → test → build → scan → push to ECR            │
│  3. PR merge → ArgoCD / CodePipeline picks up image tag    │
│     ↓ deploys to staging, runs smoke tests                 │
│  4. Promotion gate: manual approval or automated SLO check │
│     ↓ deploys to prod with canary rollout                  │
│  5. CloudWatch dashboard auto-provisioned via CDK          │
│     ↓ PagerDuty alert routing wired from Terraform module  │
└────────────────────────────────────────────────────────────┘

Platform Team Responsibilities:
  - Maintain golden path templates in platform-templates repo
  - Version and publish reusable workflow versions
  - Monitor adoption metrics via platform dashboard
  - Provide self-service escape hatch with audit trail
```

**Reusable GitHub Actions workflow pattern:**

```yaml
# .github/workflows/golden-path-api.yml (in platform-templates repo)
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
        run: |
          docker build -t ${{ inputs.ecr_repo }}:${{ github.sha }} .
      - name: Scan with Trivy
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ inputs.ecr_repo }}:${{ github.sha }}
          exit-code: 1
          severity: CRITICAL,HIGH
      - name: Push to ECR
        run: |
          docker push ${{ inputs.ecr_repo }}:${{ github.sha }}
          docker tag ${{ inputs.ecr_repo }}:${{ github.sha }} \
                     ${{ inputs.ecr_repo }}:latest
          docker push ${{ inputs.ecr_repo }}:latest
```

**Service repo uses it with three lines:**

```yaml
# .github/workflows/ci.yml (in service repo)
jobs:
  deploy:
    uses: my-org/platform-templates/.github/workflows/golden-path-api.yml@v2
    with:
      service_name: payments-api
      ecr_repo: 123456789.dkr.ecr.us-east-1.amazonaws.com/payments-api
    secrets:
      AWS_ROLE_ARN: ${{ secrets.PLATFORM_DEPLOY_ROLE }}
```

---

## 5. Common Mistakes

**Building a golden path as documentation instead of automation.** A wiki page titled "How to set up your CI/CD pipeline" is not a golden path — it's homework. The golden path must run. If a developer still has to manually configure anything, the path has gaps.

**Not versioning the golden path.** When you update the shared pipeline and it breaks five services, you'll wish you had semver. Treat golden path templates exactly like a Python package: tag releases, write changelogs, don't break consumers without a deprecation period.

**Monolithic golden paths.** One path that covers web apps, batch jobs, data pipelines, and machine learning models will satisfy none of them. Build composable building blocks (a "lint module", a "scan module", a "deploy-to-ecs module") and assemble them into path variants.

**Ignoring the escape hatch.** If teams can't deviate from the path without a 3-week process, they'll fork silently. Silent forks are worse than documented deviations. Build the escape hatch before you need it.

**Treating golden paths as a one-time project.** Every new AWS service, every security requirement change, every new language version creates drift. Assign a dedicated platform team with a clear mandate to keep paths current or they will rot.

**Not measuring adoption.** If you don't know what percentage of services use the current golden path version, you don't know if your platform is working. Build the measurement into the platform from day one.

---

## 6. Hands-on Lab

**Goal:** Build a minimal golden path for a Python FastAPI service on ECS Fargate, using a reusable GitHub Actions workflow and a Terraform module for infrastructure.

**Step 1: Create the platform-templates repo structure**

```bash
mkdir -p platform-templates/.github/workflows
mkdir -p platform-templates/terraform/modules/ecs-service

cat > platform-templates/.github/workflows/python-api-golden-path.yml << 'EOF'
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
      - run: ruff check . || true
      - run: pytest -q || echo "No tests found"
      - run: echo "BUILD ${{ inputs.service_name }}:${{ github.sha }} → ECR (simulated)"
EOF
```

**Step 2: Create the Terraform ECS module**

```hcl
# platform-templates/terraform/modules/ecs-service/main.tf
variable "service_name" {}
variable "image_uri" {}
variable "cpu" { default = 256 }
variable "memory" { default = 512 }
variable "desired_count" { default = 2 }
variable "container_port" { default = 8080 }

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
        "awslogs-group"         = "/ecs/${var.service_name}"
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

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.service_name}"
  retention_in_days = 30
}

output "task_definition_arn" {
  value = aws_ecs_task_definition.this.arn
}
```

**Step 3: Bootstrap a new service using the golden path**

```bash
# Simulating the scaffolding step a developer would run
mkdir payments-api && cd payments-api

cat > main.py << 'EOF'
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"service": "payments-api", "version": "1.0.0"}
EOF

cat > Dockerfile << 'EOF'
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn --no-cache-dir
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
EOF

cat > .github/workflows/ci.yml << 'EOF'
jobs:
  deploy:
    uses: my-org/platform-templates/.github/workflows/python-api-golden-path.yml@v1
    with:
      service_name: payments-api
    secrets:
      AWS_ROLE_ARN: ${{ secrets.PLATFORM_DEPLOY_ROLE }}
EOF

# Run locally to verify
docker build -t payments-api:local .
docker run -p 8080:8080 payments-api:local &
curl http://localhost:8080/health
# {"status": "ok"}
```

**Step 4: Track adoption with a Python script**

```python
import subprocess
import json

def check_golden_path_adoption(org_repos: list[str]) -> dict:
    """
    Checks which repos use the platform golden path workflow.
    In production, this would query GitHub API for workflow files.
    """
    results = {"using_golden_path": [], "not_using": [], "unknown": []}
    
    golden_path_marker = "platform-templates/.github/workflows"
    
    for repo in org_repos:
        # In production: GET /repos/{org}/{repo}/contents/.github/workflows
        # Simulated here
        print(f"Checking {repo}...")
        results["unknown"].append(repo)
    
    return results

# Run with real GitHub API
import httpx

def get_adoption_metrics(org: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    
    with httpx.Client() as client:
        repos = client.get(f"https://api.github.com/orgs/{org}/repos?per_page=100", 
                          headers=headers).json()
        
        using_golden_path = 0
        total = len(repos)
        
        for repo in repos:
            try:
                workflows = client.get(
                    f"https://api.github.com/repos/{org}/{repo['name']}/contents/.github/workflows",
                    headers=headers
                ).json()
                
                for wf in workflows:
                    content_resp = client.get(wf["download_url"]).text
                    if "platform-templates" in content_resp:
                        using_golden_path += 1
                        break
            except Exception:
                pass
        
        return {
            "org": org,
            "total_repos": total,
            "using_golden_path": using_golden_path,
            "adoption_rate": f"{(using_golden_path/total)*100:.1f}%" if total > 0 else "0%"
        }
```

---

## 7. Interview Talking Points

**"Tell me about a time you improved developer experience at scale."**

The strongest answer here centers on a golden path initiative. Describe the before state: developers spent their first two weeks bootstrapping pipelines, each team made different security choices, incidents were caused by missing health checks or misconfigured log groups. Then describe the platform intervention: you designed a composable golden path with a reusable GitHub Actions workflow, a Terraform ECS module with opinionated defaults (health checks, log retention, auto-scaling), and a scaffolding tool that generated new services in minutes. Measure the outcome: time to first production deploy dropped from two weeks to two days, Trivy scan coverage went from 40% to 95% of services, and the number of unique pipeline configurations across the org dropped by 60%. This framing shows you understand where the real impact comes from — the platform layer — and can operate at principal-architect scope.

**"How do you balance standardization with team autonomy?"**

Golden paths are the answer. The key insight is that standardization and autonomy operate at different layers. The platform team owns infrastructure and deployment patterns — that is where standardization pays off most. Application logic, language choice, and service architecture remain team decisions. The escape hatch mechanism is critical: teams that need to deviate can do so by logging a documented reason, which creates visibility without creating friction. At FAANG scale, this is sometimes called "paved roads vs. off-road" — you build the best paved road possible and make it cheaper to stay on it than to go off-road, but you don't prevent off-roading for legitimate needs.

**"How do you measure platform engineering success?"**

Vanity metrics (number of services onboarded, lines of Terraform) are common traps. The metrics that matter are: adoption rate of the current golden path version (high adoption means the path is actually good), mean time to first production deploy (captures the full developer onboarding experience), deployment frequency per team (healthy golden paths increase this), and the ratio of platform-caused incidents to total incidents (the platform team should be reducing their blast radius over time, not increasing it). These metrics connect directly to engineering organization health and are the kind of data that gets presented to VPs.

---

## 8. AI DevOps / AIOps / LLMOps Angle

AI can enhance golden paths in three ways: generating scaffolding, auditing deviation, and recommending path improvements.

**AI-powered golden path compliance checker** — uses Claude to review a service's workflow YAML and identify whether it deviates from the golden path pattern, and explains why the deviation matters:

```python
import anthropic
import httpx
import base64

def audit_pipeline_compliance(
    workflow_yaml: str,
    golden_path_yaml: str,
    service_name: str
) -> dict:
    """
    Uses Claude to audit whether a service pipeline follows the golden path.
    Returns structured compliance report.
    """
    client = anthropic.Anthropic()

    prompt = f"""You are a senior platform engineer auditing CI/CD pipelines for golden path compliance.

Golden Path Reference Workflow:
```yaml
{golden_path_yaml}
```

Service Pipeline Being Audited ({service_name}):
```yaml
{workflow_yaml}
```

Analyze the service pipeline and produce a JSON compliance report with:
1. "compliant": true/false
2. "compliance_score": 0-100
3. "missing_steps": list of steps present in golden path but absent in service
4. "custom_steps": list of steps added by the team that are not in the golden path
5. "security_gaps": any security checks (scanning, SAST, secret detection) that are missing
6. "recommendations": list of specific, actionable fixes ranked by priority
7. "escalation_needed": true if any critical security controls are bypassed

Return only valid JSON, no markdown.
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )

    import json
    return json.loads(response.content[0].text)


def batch_audit_org_pipelines(
    org_workflows: list[dict],
    golden_path_yaml: str
) -> list[dict]:
    """
    Audits all service pipelines in an org and returns sorted compliance report.
    """
    results = []
    for svc in org_workflows:
        report = audit_pipeline_compliance(
            workflow_yaml=svc["yaml"],
            golden_path_yaml=golden_path_yaml,
            service_name=svc["name"]
        )
        report["service"] = svc["name"]
        results.append(report)
    
    # Sort by compliance score ascending (worst first)
    return sorted(results, key=lambda x: x.get("compliance_score", 0))


# Example usage
if __name__ == "__main__":
    golden_path = """
jobs:
  lint-and-test:
    steps: [checkout, setup-python, ruff, pytest]
  build-and-scan:
    steps: [checkout, aws-credentials, ecr-login, docker-build, trivy-scan, ecr-push]
"""

    service_pipeline = """
jobs:
  build:
    steps: [checkout, docker-build, ecr-push]
"""

    report = audit_pipeline_compliance(service_pipeline, golden_path, "legacy-payments-api")
    print(f"Compliance Score: {report['compliance_score']}/100")
    print(f"Security Gaps: {report['security_gaps']}")
    print(f"Recommendations: {report['recommendations']}")
```

**Use cases by maturity:**
- **Level 1:** Claude reviews PR descriptions and flags when a developer is deviating from the golden path
- **Level 2:** Claude generates the golden path YAML for a new service type based on its detected language and framework
- **Level 3:** Claude analyzes deployment failure patterns across services and recommends golden path improvements — "Services using Node 18 base image are failing Trivy scans 3x more often than Node 20; recommend bumping the golden path base image."

---

> What does your golden path look like? 👇"

---

## 10. What I Should Practice Next

**Immediate (this week):**
- Build a reusable GitHub Actions workflow that at minimum covers: lint, test, Trivy scan, ECR push. Use `workflow_call` so service repos can reference it.
- Create a Terraform ECS module with opinionated defaults: health check, log group with 30-day retention, target tracking auto-scaling, task definition with resource limits.

**Near-term (this month):**
- Add a Backstage software template or a Cookiecutter template that scaffolds a Python FastAPI service with the workflow already wired in.
- Write the compliance checker script against your real GitHub org and run it — the findings will tell you exactly where your golden path gaps are.

**Principal-level thinking:**
- Design the versioning and upgrade strategy: how will you communicate breaking changes? How will services opt into new versions?
- Define the escape hatch process: what is the documented path for a team that legitimately needs to deviate? Build the audit log before the first deviation happens.
- Instrument adoption: build a simple dashboard that shows golden path adoption rate by team, and put it in front of engineering leadership monthly.

---

**Suggested git commit message:**

```
docs(platform-engineering): add golden paths for application deployment

Covers golden path design philosophy, reusable GitHub Actions workflow
pattern, Terraform ECS module, AI compliance checker with Anthropic SDK,
and principal-level interview framing. Hands-on lab produces a deployable
Python API scaffold wired to the golden path on day one.
```
