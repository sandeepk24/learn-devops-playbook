# Flaky tests

A required check that fails and then passes on a rerun of the same SHA did not become more correct. The suite is non-deterministic, and the merge button is a retry loop. [Merge queues](./merge-queues.md) will merge that pass. The queue cannot tell a fixed race from a patient click.

I keep unit tests required. I take a flaky test out of the required set the day I see the second unexplained failure on an unchanged SHA. It keeps running, in a job that cannot block the merge, with an owner and a date. A quarantine with no owner is a second suite.

## What counts

Same commit. First run red, rerun green, no code change in between. That is a flake.

A failure that reproduces on a second run is a broken test or a broken change. Treat it as a failure. Rerunning until the network cooperates trains the team to ignore the first red build, and then they ignore a real one.

Order and time are the usual causes. Tests that share a database, a clock, a port, or a file in `/tmp`. Tests that assert on a list that has no sort. Tests that wait a fixed number of milliseconds for a container. The fix is in the test. A longer sleep moves the flake to a busier hour.

## Split the required job

One job named `test` that runs everything means you cannot un-require the flake without un-requiring the unit tests. Split them.

```yaml
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/unit -q

  integration:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/integration -q
```

Branch protection requires `unit`. `integration` is required only while it is deterministic. The day it is not, it stops being a required check. It still runs on the pull request so the log exists. A required check that you rerun three times is not a check.

On GitLab the same split is two jobs. The flaky one gets `allow_failure: true` until it is fixed, so a red run does not fail the pipeline or the merge train. `allow_failure: true` on the job that deploys is a different decision. Leave deploy strict. See [who can deploy](./gitlab-ci-pipeline-part2-security-rollback.md).

## Quarantine

Move the test to a file the required job does not collect. Keep running it.

```python
import pytest

@pytest.mark.quarantine
def test_webhook_delivery_order():
    ...
```

```bash
pytest tests/unit -q -m "not quarantine"
pytest tests/unit -q -m quarantine
```

The second command is its own job. It is not in the required checks. The job log is the data. A marker with no ticket is how the file grows to a hundred tests and nobody remembers why.

Each quarantined test has an owner and a removal date. Two weeks is enough to fix a race or delete the test. I delete on the date. A test that has been quarantined for a quarter is not documentation. It is a test you are afraid to run.

Do not add `pytest-rerunfailures` to the required job. A rerun that flips the required job to green is the flake shipping. If you need one retry to survive a known external dependency, put that retry on the non-required job and fail the job's summary when a retry happened, so the count is visible. The number you want is retries per week, per test name, going down.

## Rerun failed jobs

GitHub's "Re-run failed jobs" on a pull request is a person deciding the failure was the runner. Once, on a job that died before the tests started, that is reasonable. A second rerun of the same SHA means the test failed and you are negotiating with it.

The merge queue has a related switch. Unchecking "Only merge non-failing pull requests" lets a pull request with a failed individual check stay in the group when the combined run passed. That setting is aimed at this problem. Using it instead of quarantine means the queue merges code whose own checks were red. I leave the box checked and fix the test.

## What I measure

Count, for the required jobs only:

- Failures on a SHA that later passed with no new commit
- Time the required job spends running
- Tests still marked quarantine, and how old the oldest one is

The first number is the flake rate. If you cannot name the test, the job is too coarse. Split it until the failure is one test. The second number is why people rerun instead of reading the log. A required job over about ten minutes will be bypassed. The third number is whether quarantine is a queue or a drawer.

A deploy job does not get a retry. A failed deploy is either rolled back or left failed until a person looks. Retrying `terraform apply` or an ECS deploy from a red button hides a partial apply. The test suite is where retries feel cheap. They are not cheap. They change what green means.
