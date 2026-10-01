# CI/CD

These are the notes in the order I would hand them to someone. It is the order I wish I had read them. I have watched people skip ahead and do fine, and I have watched people collect the senior list while their required check was still a rerun button.

The split below is not a title and it is not a year count. In the teams I have been on, the job changed when other people's pipelines became my problem. Before that, I was trying to get one service from a merge to a running task without lying to myself about what had shipped.

Read one host deeply. I learned GitHub first. GitLab was the same decisions in different YAML. Reading both tracks front to back taught me the syntax twice and the judgment once.

## DevOps engineer

This is the stretch where I owned a service and the workflow that deployed it. The failures were local: a tag that moved, a test I reran, a runner that remembered the last job.

### One pipeline that can fail

I spent a month comparing tools before I had a pipeline that went red for a real reason. The comparison was not the work. The work was a merge that built an image, deployed it, and left a log I could read at night.

If the company is on GitHub and AWS, I would start here:

| Note | What I was missing when I wrote something like it |
|---|---|
| [GitHub Actions and AWS](./01_GITHUB_DEVOPS_FUNDAMENTALS.md) | I had access keys in a secret and a workflow that could not tell me which role it had assumed. |
| [The application, the image, and the workflows](./github-devops-implementation-02.md) | The health check returned 200 while the process could not serve, and the image dropped privileges onto packages it could not read. |
| [Fargate, alarms, and what you check when it will not start](./github-devops-production-03.md) | Apply had gone green and I still could not say why the new tasks were dying. |

If the company is on GitLab, I would start here instead:

| Note | What I was missing when I wrote something like it |
|---|---|
| [GitLab CI, from the first pipeline to ECS and EKS](./gitlab-cicd-101.md) | I had a runner on a server I used to rsync to, and I called that a pipeline. |
| [Environments are not stages](./gitlab-ci-pipeline-part1-structure.md) | Four copied deploy jobs, and I could not tell you what deleting one of them would do. |
| [Who can deploy](./gitlab-ci-pipeline-part2-security-rollback.md) | `when: manual` felt like a control. It was a button anyone in the project could press. |

If the company is on Bitbucket, I would start here instead. I got there because the tickets were already in Jira. The pipeline questions were the same ones.

| Note | What I was missing when I wrote something like it |
|---|---|
| [Bitbucket Pipelines](./bitbucket-pipelines.md) | I treated the next step as the same machine. It was a new container, and the files I had just written were gone. |
| [Bitbucket deployment environments](./bitbucket-deployments.md) | `trigger: manual` felt like a control. The environment was the permission, and only on the plan that had one. |
| [Bitbucket Pipelines and AWS](./bitbucket-oidc-aws.md) | I had an access key in a secured variable. The trust policy I wrote later matched every repository in the workspace. |

### How the code moves

I picked a branch model because I had seen the diagram. The model mattered less than whether `main` stayed deployable on the days we were tired.

| Note | What I learned after I had already chosen |
|---|---|
| [Branch strategies](./branch-strategies.md) | Git Flow fit a product with a version someone installed. It was overhead on a service we deployed every day, and I kept it for a year out of habit. |
| [Trunk-based development](./trunk-based-development.md) | I was not blocked by the branch rule. I was blocked by a test suite I did not trust enough to merge into daily. |

### The bytes you tested

Staging used to pass and production would fail on a build we had produced an hour later. I called that an environment problem. It was two artifacts.

| Note | What I learned after I had already chosen |
|---|---|
| [Promote the image digest](./promote-the-image-digest.md) | The tag was a name I could say out loud. The digest was the thing the task had pulled. I started deploying the second one after a rollback pointed at a tag that had moved. |

### Green meaning what it says

I treated a green rerun as close enough for a long time. The merge queue, once we had one, merged those reruns without asking me how I felt about it.

| Note | What I learned after I had already chosen |
|---|---|
| [Flaky tests](./flaky-tests.md) | The second unexplained failure on the same SHA was the test. Clicking rerun was me negotiating with it. |
| [Ephemeral runners](./ephemeral-runners.md) | I added a self-hosted runner because a job needed our network. I left it up for months. The next job inherited files from the last one, and I debugged the job. |

I would stay on hosted runners until I could name the constraint. The fleet came later, and it came with a sentence about why, or it became the default for jobs that did not need it.

## Senior DevOps engineer

The work changed when a workflow I had written showed up in another team's repo, slightly wrong. My pipeline being green was no longer the interesting question. The interesting question was what happened when forty copies of it drifted.

I do not think this list makes someone senior. I think I started needing it at about the time other people were shipping through something I had sketched.

### The merge you are about to land

A green pull request became a weak signal once several people were merging to the same branch in a day. The check I cared about was the combination with `main`, and with the pull requests already waiting.

| Note | What I had been trusting instead |
|---|---|
| [Merge queues](./merge-queues.md) | The pull request head from that morning. It was green. Main had moved. The red build belonged to nobody's PR. |

### State, and who can change the path

Two applies to the same state key, and a workflow anyone on the team could edit, were the incidents I stopped treating as bad luck.

| Note | What I had been trusting instead |
|---|---|
| [Terraform in CI](./terraform-in-ci.md) | A plan on the pull request, and an apply from a laptop that still had the old state in its head. |
| [The workflow file is production](./workflow-is-production.md) | Review on the application code, and a rubber stamp on the YAML that assumed the deploy role. |

### One path, maintained like a product

I have written the paved path as a wiki page. Teams thanked me and kept their own pipeline. The version that got used was the one a new service already called, pinned to a tag I could move on purpose.

| Note | What I had been trusting instead |
|---|---|
| [Golden paths](./golden-paths-for-application-deployment.md) | A document titled like a standard. Adoption was a feeling until I counted who referenced the current tag. |
| [Platform engineering and the model you already have](./platform-engineering-vs-traditional-devops.md) | "You build it, you run it" past the point where every team had re-solved the same deploy. I was tired of fixing the module in eight repos before I had a name for the alternative. |

The platform work went badly when I built what was interesting to me. It went better when I could point at hours teams were still spending by hand, and when leaving the path was a recorded exception rather than a silent fork.

## What I would not do with this list

I would not read it as a gate. I have worked with people who could debug a stuck ECS deploy and had never drawn a branch strategy, and they were more useful on the night than I was. I have also worked with people who could talk about golden paths and could not tell me which digest production was running.

If I were starting over on one service, I would stop after the first host's track, the branch notes, the digest, and the flake note. I would come back for the senior list when a second team asked to copy the workflow. That request was the point I stopped being able to keep the rules in my head.
