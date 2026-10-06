# Terraform in CI

Plan on the pull request. Apply on main. From the workflow. Never from a laptop against production.

That sentence is the whole note. Everything below is what breaks when you ignore part of it, and I have broken every part at least once, usually by being in a hurry, which is exactly when the lock and the second plan save you.

For anyone new: Terraform keeps a state file, which is its memory of what it built, and every plan compares your configuration against that memory and against the cloud, then proposes a diff. CI exists so that diff gets reviewed before it runs, and so the apply that runs it is the same diff you reviewed, not a slightly different one your laptop computed five minutes later with different credentials and a different Terraform version.

Use one state per environment directory. Not workspaces.

```
terraform/
├── modules/
└── envs/
    ├── staging/
    └── prod/
```

Workspaces share a backend and differ by a name you pass at runtime. Directories differ by a key, an account, and a variables file sitting on disk where you can read them. I have pointed staging credentials at the production key through a workspace mixup, which is a sentence I never want to write again, and directories make that mistake structurally harder, because the backend block in `envs/prod` says prod in plain text and nothing else will make it say staging.

The module holds the resources. The environment directory holds the backend key, the provider account, and the `.tfvars`. [Part 3](./github-devops-production-03.md) has the ECS resources. This note is how those files reach the cloud without someone running them by hand.

## State

Version the bucket. Encrypt it. One key per environment. Short sentences, because these three are not debatable and do not need paragraphs defending them.

Terraform 1.10 and later can lock the state key in S3 itself. No DynamoDB table on a backend you are creating now.

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

The lock is a sibling object. Same prefix as the state key, plus `.tflock`. When an apply holds it, a second apply waits or fails instead of writing over the first one, which is the difference between a queued deploy and two writers corrupting the only copy of what exists.

An older backend with `dynamodb_table` still works. Same rule underneath: two applies, one lock, the second one does not proceed. Leave it alone until you have a reason to migrate, because migrating a backend that people are actively applying through is how you discover which scripts hardcode the table name.

`terraform force-unlock` is a person pasting the lock ID from the error message. Deliberately. After checking that nobody is actually applying. It is not a workflow step, not a retry block, not something that runs on failure to "clean up", because an apply killed by a cancelled job is the usual reason a lock looks stuck, and auto-unlocking there is how you turn one interrupted apply into two concurrent ones.

Commit `.terraform.lock.hcl`. That file pins provider hashes, which means the workflow and your laptop resolve the same provider bytes, and when they do not, the error is loud and early instead of a subtle diff in behavior three resources deep. Pin the Terraform binary too. `setup-terraform` wants an exact version string, and I give it the one I actually run, not a range, because a range means the pull request planned with one version and main applied with another, and then the plan file refuses to apply or, worse, applies with a different understanding of the configuration.

## Refresh, and why the pull request skips it

`terraform plan` refreshes by default. Refresh means reading live cloud objects and writing the results into state, which surprises beginners who expected a plan to be read-only, since it sounds read-only and looks read-only right up until you learn that the state file changed underneath you.

A pull request that can refresh can rewrite state. I do not give branches that power.

So the pull request plans with `-refresh=false`. It diffs the configuration against the state as stored, without calling out to the cloud to update that stored picture first. Fast. Safe. Blind to drift, because drift by definition is the difference between the stored picture and reality, and we just told Terraform not to look at reality, which is a tradeoff I accept on the branch and compensate for on main, where a scheduled plan with the apply role runs with refresh on and tells me what moved outside Terraform.

The lock still matters on a refresh-less plan. `plan` takes the lock even when it is not refreshing, and with `use_lockfile` the plan role needs `s3:GetObject`, `s3:PutObject`, and `s3:DeleteObject` on the `.tflock` object, plus `s3:GetObject` on the state key itself. Note what is missing. `PutObject` on the state key. The plan role reads state and manages the lock, and if a refresh-less plan ever tries to write state anyway, the call is denied, the job fails, and that failure is the signal working as designed, not a permissions bug to widen away.

## Two roles

The apply role writes state and changes the account. The plan role does not. Two roles, two trust policies, and the apply one is narrow in a way that feels annoying until the day it stops something.

Trust the apply role from the apply workflow on `main`. Not from every workflow on `main`. Not from any branch. The OIDC subject for that is the workflow path pinned to the branch.

```hcl
condition {
  test     = "StringLike"
  variable = "token.actions.githubusercontent.com:job_workflow_ref"
  values   = [
    "your-org/your-repo/.github/workflows/terraform-apply.yml@refs/heads/main",
  ]
}
```

The plan workflow's subject is `repo:your-org/your-repo:pull_request`. Fork pull requests never get that role, because GitHub withholds secrets and the OIDC token from fork `pull_request` runs, which kills the plan step on forks, and the fix people reach for is `pull_request_target`, which runs the fork's code with the base repo's token and its secrets. Do not do that to get a plan on a fork. Leave forks on a pipeline that lints, formats, and validates without touching AWS. The OIDC shape behind both roles is [the Actions note](./01_GITHUB_DEVOPS_FUNDAMENTALS.md), and the plan role versus apply role split is the same idea as separate read and write credentials everywhere else.

## The pull request workflow

`hashicorp/setup-terraform` wraps the binary. The wrapper intercepts output and swallows `-detailed-exitcode`, which is the flag the whole workflow depends on, so I set `terraform_wrapper: false` and would notice immediately if someone removed it, because every plan would start reporting success with a diff and the destroy check below would never fire.

Exit codes, memorized once and never again: `0` means no diff, `2` means a diff, anything else means the plan failed. `1` is the common failure. `127` is a missing binary. Both are failures, and the step must treat both as failures, which is why the shell below checks for not-0 and not-2 rather than checking for exactly 1.

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

A replace shows up as `delete` plus `create` in the plan JSON. That check catches replaces too, which is intentional, because replacing a database or an ECS service is a destroy with extra steps, and I want a human to look at it before it merges. When a destroy is the change you meant, a label on the pull request plus a matching `if:` that skips the gate is the escape hatch, and the label is visible to reviewers, which a silent exception would not be.

Post the no-color plan as a pull request comment if your reviewers will not open workflow logs. They will not open workflow logs. Mark variables `sensitive` or the plan text carries the values in cleartext into that comment, where they sit for the lifetime of the repo. And the plan file itself stays in the job. It holds the same values, it goes stale the moment main moves, and I never apply a pull request's plan file, because applying a stale plan to a moved main is how you apply a diff nobody reviewed against a state nobody checked.

## Apply

The apply job runs on `main`. It plans again, this time with refresh, and applies that fresh plan file. `terraform apply tfplan` refuses to run if the state changed since the plan was made, and that refusal is the property the whole pipeline rests on: the diff that runs is the diff that was just computed, not a memory of one.

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

`cancel-in-progress: false`. Read it carefully. A second push queues behind the running apply instead of cancelling it, because cancelling an apply mid-write is how you get a stuck lock and a half-built graph, and the queue is slower but honest, whereas the cancellation is fast and leaves wreckage.

`environment: production` is the human gate from [Actions](./01_GITHUB_DEVOPS_FUNDAMENTALS.md), if you want one in front of prod. Required reviewers there mean the apply waits for a person even after main accepted the merge. Staging applies without it. Production waits. That asymmetry is deliberate, and flattening it "for consistency" is how staging process gets applied to production consequences.

Expect the main plan to differ from the pull request plan. Main moved. Refresh saw drift. Someone merged ahead of you. A [merge queue](./merge-queues.md) narrows the first case by testing the combination before it lands, but drift still shows up, and when the apply log differs from the diff you remember reviewing, read the apply log, because that is the diff that ran.

Export `TF_IN_AUTOMATION=1`. It tells Terraform to skip interactive prompts you already disabled with `-input=false` and to drop the fancy UI that looks like a hung job in a log stream. Small line. Removes a whole class of "is it stuck" messages.

## What I do not put in the workflow

`-target`. Except in a break-glass run you delete afterward and tell someone about. A targeted apply updates part of the graph and teaches state to forget the rest, which feels surgical and behaves like amnesia, because the next full plan then proposes to recreate everything the targeted run ignored, and the person reading that plan has to work out which half of it is real.

`-auto-approve` on a pull request. The pull request does not apply. Ever. The flag has no business being in a job that should never write, and its presence there means the next person to copy the job into an apply workflow carries the flag along silently.

One state key for every account. A bad plan should not be able to lock, let alone destroy, a directory it never touched. Split keys by blast radius: network, platform, application. The application key churns weekly. The network key should be boring enough that its apply log puts you to sleep, and when it is not boring, that is the one you read twice.
