# Platform engineering and the DevOps model you already have

"You build it, you run it" works while the number of stacks is small. Past that, every team re-solves CI, registries, dashboards, and deploy scripts. The solutions are close enough to confuse you during an incident and different enough that you cannot fix them once.

Platform engineering is a team that owns those shared pieces as a product. Application teams consume them. The name for the product is an internal developer platform. The useful part is not the name. It is that the interface is self-service, the defaults are safe, and the platform team is on the hook when the shared path breaks.

This does not replace DevOps. It is what you do with DevOps practices when fifty teams would otherwise each write their own pipeline. The people who are good at it are usually the ones who got tired of fixing the same module in eight repos.

| | Each team owns its stack | A platform team owns the shared path |
|---|---|---|
| What you touch | Terraform, Helm, Jenkins, as written by that team | A portal, a template, an API |
| Pipelines | One per team | A few templates |
| How load grows | More services, more ops work, linear | The template gets better once |
| On call | Each team for its infra and its app | Platform for the platform, app team for the service |
| Guardrails | Whatever that team implemented | Policy in CI and admission, same rules everywhere |

---

## What you see in production

**Without a platform.** The on-call for payments has to read checkout's Terraform to debug a peering issue both of them use. One ECS deploy takes 45 minutes, another takes 12, and they do the same thing. One team is three AMIs behind because their Packer job broke and nobody owned it.

**With one.** The platform team owns the network. When it breaks, that team already knows the module. App teams file the ticket against an SLA instead of paging a person who wrote the module two jobs ago. Every service deploys through the same template, so a faster build helps all of them. Base images get rebuilt in one place. Teams that need this month's image change a variable, they do not rebase a Packer repo they do not understand.

Numbers I actually compare:

- Time to first production deploy of a new service. Weeks, or a day or two once the template exists.
- Hours spent on work that is not the product. If that is still a third of the week, the platform is not being used, or it is harder than the old way.
- How many pipeline variants exist. One per team is the "you build it" outcome. A handful of templates is the other one.
- Lead time at p90 across teams. If it does not converge, you have a platform and a pile of exceptions, and the exceptions are where the incidents are.

---

## What goes in the platform

**Catalog and templates.** Backstage is the usual open source choice: service catalog, software templates, docs next to the service. Port and Cortex are the hosted versions. Pick one. Running two catalogs means nobody trusts either.

**Infra that teams can request.** Crossplane if you want app teams to stay in Kubernetes CRDs and you are willing to operate it. Terraform with Atlantis if the company already lives in Terraform. AWS Service Catalog if the vended thing is an account-level product and not a manifest. Do not wrap a service in a CRD the first time one team needs it. Wait until three teams have built the same thing badly.

**The golden path.** Cookiecutter, Copier, or a Backstage template. One command, and the repo has a Dockerfile, a pipeline, a chart, and the log group. The pipeline itself is a reusable workflow or a GitLab include, not a file they are expected to maintain. See [golden paths](./golden-paths-for-application-deployment.md).

**Policy.** Gatekeeper or Kyverno so a non-compliant workload does not land. Conftest in CI so they find out before the apply. SCPs and permission boundaries so a pipeline role cannot wander into an account it does not own. Policy without an escape hatch becomes a ticket to the platform team for every sidecar. Write the off-ramp down.

**Whether it is working.** DORA numbers for the teams who consume the platform, not for the platform team. Deployment frequency, lead time, change fail rate, restore time. A satisfaction survey is useful once a quarter. It is not a substitute for the deploy numbers.

---

## How the pieces sit

```
Developer portal
  catalog, templates, docs, scorecards
        │
        ├── golden-path CI
        ├── infra they can request (Crossplane or Terraform)
        └── telemetry defaults
                │
        policy: admission, Conftest, SCPs, scanners in CI
                │
        EKS or ECS, network, data stores, secrets
        owned by the platform team
```

In Team Topologies terms the platform team is a platform team, app teams are stream-aligned, and the interaction you want is X-as-a-service. They use an interface. They do not pair with you to edit the VPC.

Done means an app engineer ships a service without writing an ALB from scratch and without filing a ticket for the standard case. The ticket is for the exception.

---

## How platform teams fail

They build what is interesting to them. The portal is polished and unused. Talk to the teams, look at what they still do by hand, and hold office hours. If adoption is flat, the thing you shipped is harder than the workaround.

They abstract too early. A CRD for every AWS service, before anyone asked, lags the real use case and hides the cloud API the day someone needs a setting you did not expose. Abstract the third copy, not the first.

No way off the path. Edge cases wait on five approvers. The teams go around you. Every path needs a written off-ramp.

They measure platform uptime and not the consumers' lead time. Up is the minimum. Faster deploys for the other teams is the job.

They do not treat the platform as production software. Untested modules, unversioned charts, breaking changes with no changelog. The platform has CI, tags, and a deprecation window. Your consumers are downstream services.

They staff it with whoever was left over. This is product work. The people on it have to want the developer experience problem. A team of engineers who wanted a product team and did not get one will build a gate.

---

## Finding the first thing to build

Ask where the hours go before you pick a tool. The script below is the shape of that audit. Replace the sample rows with tickets or a survey. The score is hours times how many teams hit the same gap. Build that first.

```python
from dataclasses import dataclass
from collections import Counter
import json

@dataclass
class ToilEntry:
    team: str
    category: str
    description: str
    hours_per_week: float
    recurrence: str

TOIL_DATA: list[ToilEntry] = [
    ToilEntry("payments", "ci_cd", "Manually updating Dockerfile base images", 3.0, "weekly"),
    ToilEntry("payments", "security", "Rotating API keys in Jenkins credentials store", 2.0, "monthly"),
    ToilEntry("checkout", "ci_cd", "Debugging flaky Jenkinsfile stages", 4.0, "weekly"),
    ToilEntry("checkout", "infra", "Manually scaling ECS tasks during peak hours", 5.0, "weekly"),
    ToilEntry("identity", "onboarding", "Setting up new service repo from scratch", 8.0, "monthly"),
    ToilEntry("identity", "observability", "Creating CloudWatch dashboards manually per service", 3.0, "monthly"),
    ToilEntry("catalog", "infra", "Writing Terraform for new RDS instance", 6.0, "monthly"),
    ToilEntry("catalog", "security", "Rotating API keys in Jenkins credentials store", 2.0, "monthly"),
    ToilEntry("recommendations", "ci_cd", "Debugging flaky Jenkinsfile stages", 4.0, "weekly"),
    ToilEntry("recommendations", "onboarding", "Setting up new service repo from scratch", 8.0, "monthly"),
]

def normalize_hours_weekly(entry: ToilEntry) -> float:
    multipliers = {"daily": 5.0, "weekly": 1.0, "monthly": 0.25}
    return entry.hours_per_week * multipliers.get(entry.recurrence, 1.0)

def audit_toil(entries: list[ToilEntry]) -> dict:
    category_hours: Counter = Counter()
    category_teams: dict[str, set] = {}
    for e in entries:
        weekly = normalize_hours_weekly(e)
        category_hours[e.category] += weekly
        category_teams.setdefault(e.category, set()).add(e.team)
    report = []
    for cat, hours in category_hours.most_common():
        teams = category_teams[cat]
        report.append({
            "capability_gap": cat,
            "total_weekly_hours_wasted": round(hours, 1),
            "teams_affected": sorted(teams),
            "team_count": len(teams),
            "platform_roi_score": round(hours * len(teams), 1),
        })
    return {
        "capability_gaps": report,
        "total_weekly_toil_hours": round(sum(category_hours.values()), 1),
    }

if __name__ == "__main__":
    result = audit_toil(TOIL_DATA)
    print(json.dumps(result, indent=2))
```

On this sample, CI shows up first. That is common. It is not a reason to start with a portal. Start with the workflow those hours are spent on.

A Backstage template is how a team requests the standard service without a ticket. This one scaffolds an ECS Python service. The skeleton repo it fetches is the part you have to maintain. The YAML alone does nothing.

```yaml
apiVersion: scaffolder.backstage.io/v1beta3
kind: Template
metadata:
  name: ecs-python-service
  title: ECS Python Microservice
  description: Python FastAPI service on ECS Fargate, using the standard path
  tags: [python, ecs, fargate, golden-path]
spec:
  owner: platform-team
  type: service
  parameters:
    - title: Service Identity
      required: [service_name, team_name, aws_account_id]
      properties:
        service_name:
          title: Service Name
          type: string
          pattern: '^[a-z][a-z0-9-]{2,30}$'
        team_name:
          title: Owning Team
          type: string
          enum: [payments, checkout, identity, catalog, recommendations]
        aws_account_id:
          title: Target AWS Account ID
          type: string
    - title: Service Configuration
      properties:
        cpu:
          title: Fargate CPU Units
          type: integer
          default: 256
          enum: [256, 512, 1024, 2048, 4096]
        memory:
          title: Fargate Memory (MB)
          type: integer
          default: 512
          enum: [512, 1024, 2048, 4096, 8192]
        enable_rds:
          title: Needs RDS PostgreSQL?
          type: boolean
          default: false
  steps:
    - id: fetch-base
      name: Fetch Base Template
      action: fetch:template
      input:
        url: ./skeleton
        values:
          service_name: ${{ parameters.service_name }}
          team_name: ${{ parameters.team_name }}
          aws_account_id: ${{ parameters.aws_account_id }}
          cpu: ${{ parameters.cpu }}
          memory: ${{ parameters.memory }}
          enable_rds: ${{ parameters.enable_rds }}
    - id: publish
      name: Publish to GitHub
      action: publish:github
      input:
        allowedHosts: ['github.com']
        description: "ECS service: ${{ parameters.service_name }}"
        repoUrl: github.com?owner=my-org&repo=${{ parameters.service_name }}
        defaultBranch: main
    - id: register
      name: Register in Catalog
      action: catalog:register
      input:
        repoContentsUrl: ${{ steps.publish.output.repoContentsUrl }}
        catalogInfoPath: '/catalog-info.yaml'
  output:
    links:
      - title: Repository
        url: ${{ steps.publish.output.remoteUrl }}
      - title: Open in Catalog
        entityRef: ${{ steps.register.output.entityRef }}
```

Policy belongs in CI, not in a review comment. Conftest against a rendered chart:

```bash
brew install conftest
```

```rego
package main

deny contains msg if {
  container := input.spec.template.spec.containers[_]
  not container.resources.limits
  msg := sprintf("Container '%s' has no resource limits", [container.name])
}

deny contains msg if {
  container := input.spec.template.spec.containers[_]
  not container.resources.requests
  msg := sprintf("Container '%s' has no resource requests", [container.name])
}
```

```bash
helm template my-service ./charts/my-service | conftest test -
```

The `deny contains` form is Rego v1. The older `deny[msg] { ... }` form still runs on Conftest for now. If you copy a policy off an old blog and it parses and then never fires, check which Rego you are on.

A chart that fails here does not reach the cluster. That is the point of putting it in the pipeline instead of in a platform review meeting.

---

## Talking to the people who fund it

I do not pitch the org chart. I count pipelines, hours on undifferentiated work, and the spread in lead time between the fastest team and the slowest. In the orgs I have seen, that spread is large, and a lot of senior time is the same Terraform written again. A small platform team that removes that duplicate work gives the product teams the hours back. Say the hours. Skip the multiple. People can divide.

The way this becomes a bottleneck is a ticket for every request. Self-service is the interface. If the golden path requires an approval to use, you added an ops team. A developer should get from an empty repo to a running standard service without asking. Exceptions get the off-ramp, and the off-ramp is not "open a ticket and wait."

Three checks. DORA across the consuming teams. If only the platform team got faster, you optimized the wrong pipeline. Adoption of the current path versus custom infra. Low adoption means it does not solve the pain, or it is harder than the custom thing. And the survey question about time on work that is not the product. Adoption without the DORA movement means they use it and it is not helping. DORA movement without adoption means one team got better and you are telling a platform story about it.

---

## Reading the ticket queue

You can classify incoming asks and see which gap repeats. A model is fine for a weekly sort of the backlog. Read the tickets it ranks high before you put them on a sprint. The categories below are the ones I use. Change them to match your platform. A category list that does not match the work will produce a confident chart of the wrong problem.

```python
import json
from collections import Counter

import anthropic

client = anthropic.Anthropic()

DEVELOPER_REQUESTS = [
    "How do I add a new environment variable to my ECS task without redeploying?",
    "Can someone help me set up a CloudWatch alarm for my Lambda? I've done this 3 times already.",
    "Our deployment pipeline takes 28 minutes. Is there a way to parallelize the Docker build?",
    "I need to onboard a new microservice. Where do I start? I've been asking around for 2 days.",
    "How do I get Secrets Manager access for my ECS task role?",
    "Our Helm chart keeps failing OPA policy checks. Can a platform engineer review it?",
    "Is there a standard way to do blue/green deploys for our ECS service?",
    "How do I add a new RDS read replica? Do I need to modify the shared Terraform module?",
]

SYSTEM_PROMPT = """You are a platform engineering analyst. Classify each developer request.

Categories:
- self_service_infra
- ci_cd_friction
- observability_gap
- secrets_and_config
- documentation_gap
- policy_friction
- onboarding

Return a JSON array. Each item has:
- request: original text, truncated to 60 characters
- category: one category
- urgency: high, medium, or low
- platform_action: one sentence on what to build so this ask stops arriving
"""

def detect_capability_gaps(requests: list[str]) -> list[dict]:
    user_content = "Analyze these developer requests:\n\n" + "\n".join(
        f"{i+1}. {r}" for i, r in enumerate(requests)
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
    )
    text = response.content[0].text
    start = text.find("[")
    end = text.rfind("]") + 1
    return json.loads(text[start:end])

def summarize_gaps(gaps: list[dict]) -> dict:
    category_counts = Counter(g["category"] for g in gaps)
    high_urgency = [g for g in gaps if g["urgency"] == "high"]
    return {
        "total_requests_analyzed": len(gaps),
        "top_gap_category": category_counts.most_common(1)[0][0],
        "high_urgency_count": len(high_urgency),
        "category_breakdown": dict(category_counts),
        "immediate_platform_actions": [g["platform_action"] for g in high_urgency],
    }
```

Run it on real tickets. If the top category is "how do I onboard a service," the template is missing or nobody can find it. If it is "the policy blocked me," the policy is missing a path, not a stricter rule.

The order I would use: measure the toil, build the one workflow that removes the top of the list, put policy in CI for that path, then put a template in front of it. A portal with nothing behind it is a catalog of services you still deploy by hand.
