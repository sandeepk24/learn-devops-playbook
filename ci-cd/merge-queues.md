# Merge queues

A required check on a pull request runs against that branch. Main moves while the review sits. The merge then combines two trees that never ran together. That is the red build on main that nobody's PR failed.

"Require branches to be up to date" re-runs the checks after every merge. It works. It also turns the queue into a line: each PR updates, CI starts over, and the next person waits. A merge queue tests the combination that is about to land, in order, and merges that result.

GitHub calls it a merge queue. GitLab calls the same idea a merge train, and the smaller version of it is a merged-results pipeline. Turn one of them on when more than a couple of people merge to the same branch in a day. Below that, up-to-date branches are enough and the queue is ceremony.

## What the check has to run on

The pull request head is the wrong commit. The commit that matters is the temporary merge: main, plus the pull requests already in the queue, plus this one.

On GitHub the workflow has to listen for `merge_group`. A workflow that only listens for `pull_request` never reports a check on the queue commit. The queue waits until it gives up, and the pull request comes back out.

```yaml
name: CI
on:
  pull_request:
  merge_group:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pytest tests/
```

The required check name in branch protection or in the ruleset is the job name, `test` here. The same job has to report on the merge group. A `paths` filter that skips the job on the queue commit leaves the requirement unmet. Required jobs always run for `merge_group`.

`github.sha` on that event is the temporary merge. `github.ref` starts with `gh-readonly-queue/`. Nothing in that workflow deploys. Deploy stays on `push` to `main`, after the result has landed.

```yaml
concurrency:
  group: ci-${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

Cancel the old run when someone pushes to the pull request. Leave the merge group run alone. The queue is waiting on that check. A cancelled run does not report success, and the entry sits until the status check timeout treats the silence as a failure.

## What you configure

On the protected branch, require the merge queue and require the status checks. A wildcard branch pattern cannot enable the queue. Pull requests enter the queue instead of merging directly.

GitHub builds a temporary branch per pull request. The first contains main plus that pull request. The next contains main, the pull requests ahead of it, and itself. CI runs on each of those branches. Build concurrency is how many of those runs you allow at once. When they pass, GitHub merges the speculative result, which already contains the earlier pull requests. The minimum and maximum merge limits control how many land on the branch together after the checks pass. They do not combine the CI builds. If merging to main deploys, a high maximum is a large deploy.

A failing required check removes that pull request. GitHub rebuilds the temporary branches behind it without the failure, and those runs start over. A flake costs that rebuild. Unchecking "Only merge non-failing pull requests" lets a pull request whose own checks failed stay in the group when the combined group's checks passed. GitHub documents that for intermittent tests. I would rather quarantine the test. A required check that retries until green will go green in the queue too.

## GitLab

Two switches, in **Settings → Merge requests**.

Merged results pipelines run the merge request pipeline on the result of merging the source branch into the target. You see the conflict with main before you click merge. `CI_PIPELINE_SOURCE` is still `merge_request_event`. The commit you are testing is a merge commit that may never be pushed. Build and test it. Do not tag a release from it, and do not deploy it. That SHA will not be the commit that lands if the train moves.

Merge trains are the queue. When the merge request is ready, GitLab adds it, and the pipeline runs on a result that includes the merge requests ahead of it. `CI_MERGE_REQUEST_EVENT_TYPE` is `merge_train` for that run and `merged_result` for the earlier one.

```yaml
test:
  script:
    - pytest tests/
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'

deploy-production:
  stage: deploy
  script:
    - ./deploy.sh
  resource_group: production
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
      when: manual
```

A deploy rule of `merge_request_event` will deploy the speculative merge. Production listens for the default branch only. The train is busy enough without a second writer. `resource_group` is the same idea as a concurrency group: one production deploy at a time. See [who can deploy](./gitlab-ci-pipeline-part2-security-rollback.md).

## What still fails with a queue

The queue serializes merges. It does not speed up a 40-minute suite. If the suite is slow, the queue grows and people bypass it. Shorten the required checks. The rest can run after merge.

A required check that is skipped, or a check name that changed in the workflow file, stalls the queue. The UI says the pull request is waiting on a check that will never be reported. Read the check name on the merge group commit before you rename a job.

A flake fails that merge group, removes the pull request, and rebuilds everyone behind it. After the second unexplained removal in a week, the test is the work.

The merge commit on main is the first time that exact tree exists as a branch. Build the artifact there, once, and promote that digest. The pull request pipeline proved the code. It did not produce the thing you ship. That split is [promote the digest](./promote-the-image-digest.md).
