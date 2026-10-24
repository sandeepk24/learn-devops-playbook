# ECS guard

`ecs_guard.py` checks that ECS services are healthy and exits non-zero when they are not. It needs Python 3.9+ and `boto3`. It does not need Terraform.

Use it two ways:

| Mode | When | Command |
|---|---|---|
| Watchdog | Scheduled job, every 15 minutes | `python ecs_guard.py --cluster prod --fix` |
| Deploy gate | Last step of the deploy pipeline | `python ecs_guard.py --cluster prod --services api --expect-task-def api:42 --wait 600` |

[`ecs-guard.workflow.example.yml`](./ecs-guard.workflow.example.yml) wires both into GitHub Actions. For GitLab, Bitbucket, or Jenkins, run the same commands on a schedule and as the last deploy step.

## What it checks

Per service:

| Check | Result |
|---|---|
| Service is `ACTIVE` | FAIL if not |
| Running count is below desired, and no deploy is in progress | FAIL |
| Latest deployment is `FAILED` (circuit breaker tripped) | FAIL |
| Serving a different task definition than `--expect-task-def` | FAIL. This is how a silent rollback shows up. |
| Load balancer has no healthy targets | FAIL |
| Some targets are unhealthy | WARN |
| Several tasks stopped for a bad reason in the last 30 minutes (OOM, crash, failed health check) | WARN |
| `minimumHealthyPercent` below 100, circuit breaker off, fewer than 3 tasks, grace period 0 | WARN. Drift from the zero-downtime settings. |

Tasks that ECS stops during a deploy or scale-in are ignored, as are normal `SIGTERM` exits (code 143).

## What it changes

Nothing, unless you pass `--fix`. With `--fix` it forces a new deployment on a service that is running fewer tasks than desired, and only when no deploy is in progress and the last rollout did not fail. That replaces the stuck tasks and lets the scheduler start again.

It never edits service settings. Drift is reported, and you fix it in Terraform at the next change, so state and reality do not diverge.

## Flags

| Flag | Meaning |
|---|---|
| `--cluster` | Required. |
| `--services` | Comma-separated. Default is every service in the cluster. |
| `--expect-task-def` | `family:revision` the service must be serving. Needs a single service. |
| `--wait SECONDS` | Wait for the rollout to finish or fail before checking. Use `600` after a deploy. |
| `--fix` | Force a new deployment when running < desired. |
| `--strict` | Exit non-zero on WARN as well as FAIL. |
| `--stopped-window`, `--stopped-threshold` | Defaults: 30 minutes, 3 tasks. |

Exit code is `0` when healthy and `1` on any FAIL. If `SLACK_WEBHOOK_URL` is set, failures are posted there. Under GitHub Actions the findings are also written to the job summary.

## IAM

Read-only for the watchdog and the gate:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ecs:ListServices", "ecs:DescribeServices",
      "ecs:ListTasks", "ecs:DescribeTasks",
      "elasticloadbalancing:DescribeTargetHealth"
    ],
    "Resource": "*"
  }]
}
```

For `--fix`, add `ecs:UpdateService`, scoped to the service ARNs:

```json
{
  "Effect": "Allow",
  "Action": "ecs:UpdateService",
  "Resource": "arn:aws:ecs:us-east-1:123456789012:service/prod/*"
}
```

Use an OIDC role for the pipeline rather than stored access keys. See [Bitbucket OIDC to AWS](../../ci-cd/bitbucket-oidc-aws.md) for the pattern.

## Limits

- It is a check on a schedule, not monitoring. A 15-minute watchdog finds a problem within 15 minutes. Keep CloudWatch alarms for anything faster.
- `--fix` cannot repair a bad image or a broken dependency. If the new tasks keep failing, the next run reports the failure and the circuit breaker stays tripped. A person has to look.
- The check for tasks that keep stopping only sees what ECS still lists, roughly the last hour.
