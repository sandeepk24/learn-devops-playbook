# Terraform in CI

Plan on the pull request. Apply on main, from the workflow, with a lock. A laptop apply against production is how state and the cloud diverge from the commit you think you reviewed.

Use one state per environment directory. Workspaces share a backend and make it easy to point staging credentials at the production key. Directories do not.

```
terraform/
├── modules/
└── envs/
    ├── staging/
    └── prod/
```

The module is where the resources live. The environment directory is the backend key, the account, and the variables. [Part 3](./github-devops-production-03.md) has the ECS resources. This note is how those files get applied.

## State

Version the bucket. Encrypt it. One key per environment.

Terraform 1.10 and later can lock that key in S3. You do not need a DynamoDB table on a backend you are creating now.

```hcl
terraform {
  required_version = ">= 1.10.0"

  backend "s3" {
    bucket       = "org-terraform-state"
    key          = "prod/app/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

A backend that already has `dynamodb_table` is the same rule: two applies, one lock, the second waits or fails. Leave it until you mean to migrate. `terraform force-unlock` is a person with the lock id from the error. It is not a step in the workflow. An apply killed by a cancelled job is the usual reason the lock is stuck.

Commit `.terraform.lock.hcl`. The workflow and the laptop use the same Terraform version. `setup-terraform` wants an exact version. Pin the one you actually run.

## What the plan role can do

`terraform plan` refreshes by default, and a refresh writes state. A pull request that can refresh can rewrite the state file. I do not want a branch to do that.

The pull request plan runs with `-refresh=false`. It diffs the configuration against the state you already have. Drift will not show up there. A scheduled plan on main, with the apply role, is where drift shows up.

`plan` still takes the state lock. With `use_lockfile` the lock is a sibling object, the state key plus `.tflock`, and the plan role needs `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on that object. It needs `s3:GetObject` on the state key. It does not need `s3:PutObject` on the state key, and it cannot change the account. If a refresh-less plan tries to write state anyway, the job fails, and that failure is the signal.

The apply role can write state and change the account. Trust it from the workflow file on `main`, not from every workflow that happens to run on `main`.

```hcl
condition {
  test     = "StringLike"
  variable = "token.actions.githubusercontent.com:job_workflow_ref"
  values   = [
    "your-org/your-repo/.github/workflows/terraform-apply.yml@refs/heads/main",
  ]
}
```

The plan workflow's subject is `repo:your-org/your-repo:pull_request`. Fork pull requests do not get that role. GitHub withholds secrets and the OIDC token path you care about from fork `pull_request` runs. The fix people reach for is `pull_request_target`, which runs the fork's code with the base repository's token. Leave forks on a pipeline that does not talk to AWS.

OIDC itself is [the Actions note](./01_GITHUB_DEVOPS_FUNDAMENTALS.md). The plan role and the apply role are two roles.

## The pull request

`hashicorp/setup-terraform` wraps the binary unless you turn that off. The wrapper swallows `-detailed-exitcode`. Turn it off or the step will not tell you the difference between an error and a diff.

Exit codes: `0` means no diff, `2` means a diff, `1` means the plan failed.

```yaml
name: Terraform plan
on:
  pull_request:
    paths:
      - "terraform/**"

permissions:
  id-token: write
  contents: read
  pull-requests: write

jobs:
  plan:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: terraform/envs/prod
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_TERRAFORM_PLAN_ROLE }}
          aws-region: us-east-1
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.10.0"
          terraform_wrapper: false
      - run: terraform init -input=false
      - id: plan
        run: |
          set +e
          terraform plan -refresh=false -input=false -no-color -detailed-exitcode -out=tfplan
          code=$?
          if [ "$code" -ne 0 ] && [ "$code" -ne 2 ]; then
            exit "$code"
          fi
          echo "exitcode=$code" >> "$GITHUB_OUTPUT"
      - name: Fail on destroys
        if: steps.plan.outputs.exitcode == '2'
        run: |
          destroys=$(terraform show -json tfplan | jq '[.resource_changes[]? | select(any(.change.actions[]; . == "delete"))] | length')
          if [ "$destroys" != "0" ]; then
            echo "$destroys delete actions in the plan"
            exit 1
          fi
```

A replace is `delete` plus `create` in the plan JSON. I want that to fail the pull request until someone looks at it. Add a label and a matching `if` when a destroy is the change you meant.

Post the no-color plan to the pull request if reviewers will not open the log. Mark variables `sensitive` or the plan text contains the values. The plan file itself stays in the job. It contains the same values, and it goes stale as soon as main moves. I do not apply the pull request's plan file.

## Apply

The apply job runs on `main`, plans again with refresh, and applies that file. `terraform apply tfplan` refuses to run if the state changed since the plan. That is the property you want.

```yaml
name: Terraform apply
on:
  push:
    branches: [main]
    paths:
      - "terraform/envs/prod/**"
      - "terraform/modules/**"

concurrency:
  group: terraform-prod
  cancel-in-progress: false

permissions:
  id-token: write
  contents: read

jobs:
  apply:
    runs-on: ubuntu-latest
    environment: production
    defaults:
      run:
        working-directory: terraform/envs/prod
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_TERRAFORM_APPLY_ROLE }}
          aws-region: us-east-1
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: "1.10.0"
          terraform_wrapper: false
      - run: terraform init -input=false
      - id: plan
        run: |
          set +e
          terraform plan -input=false -no-color -detailed-exitcode -out=tfplan
          code=$?
          if [ "$code" -ne 0 ] && [ "$code" -ne 2 ]; then
            exit "$code"
          fi
          echo "exitcode=$code" >> "$GITHUB_OUTPUT"
      - if: steps.plan.outputs.exitcode == '2'
        run: |
          destroys=$(terraform show -json tfplan | jq '[.resource_changes[]? | select(any(.change.actions[]; . == "delete"))] | length')
          if [ "$destroys" != "0" ]; then
            echo "$destroys delete actions. Apply this from a reviewed change that allows it."
            exit 1
          fi
          terraform apply -input=false tfplan
```

`cancel-in-progress: false` because cancelling an apply is how you get a lock and a half-applied state. The `environment` is the reviewers gate from [Actions](./01_GITHUB_DEVOPS_FUNDAMENTALS.md) if you want a person in front of production. Staging can apply without one.

The plan on main can differ from the plan on the pull request. Main moved, or refresh saw drift. A [merge queue](./merge-queues.md) keeps main from moving under the review. The apply log is still the plan that ran. Read it when the diff is not the one you remember.

`TF_IN_AUTOMATION=1` is worth exporting. It tells Terraform to skip prompts you already disabled with `-input=false`, and it turns off the fancy UI that looks like a hang in a log.

## What I do not put in the workflow

`-target`, except in a break-glass run you delete afterwards. A targeted apply teaches state to forget the rest of the graph.

`-auto-approve` on a pull request. The pull request does not apply.

A single state key for every account. A bad plan should not be able to lock, or destroy, a directory it did not touch. Split the keys by blast radius: network, platform, and the application. The application key is the one that changes weekly. The network key should be boring.
