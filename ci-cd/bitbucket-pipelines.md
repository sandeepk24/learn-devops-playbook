# Bitbucket Pipelines

I ended up here for a boring reason. The tickets were in Jira. The repo was in Bitbucket. Nobody was migrating.

Start simple. The file is `bitbucket-pipelines.yml` in the repo root, and if Bitbucket does not see it there, nothing runs, no matter how correct the YAML looks in a subdirectory you were testing in.

## A step is a container

Read that twice. Each step starts fresh, in its own container, from the image you named, and when the step ends, that filesystem is gone except for what you explicitly kept.

That surprises people coming from a laptop. On your machine, you run tests, then you run the build, and the files from the first command are still sitting there for the second one because it is the same machine, the same disk, the same afternoon. In Pipelines, the test step and the build step are different containers on different disks, possibly on different hosts, and the only things that travel between them are the ones you declared as artifacts, which means if you installed dependencies in step one and expected them in step two without declaring anything, step two starts empty and fails in a way that looks like your install was broken when it was actually your mental model that was broken.

A step has an image, a script, and a few optional lists. That is the whole vocabulary, and everything else in this note is a consequence of those three things interacting with a fresh filesystem each time.

```yaml
image: python:3.12-slim

pipelines:
  pull-requests:
    "**":
      - step:
          name: Test
          image: python:3.12-slim
          caches:
            - pip
          script:
            - pip install -r requirements.txt
            - pytest -q
```

The top-level `image:` is the default for steps that do not name their own. I name the image on the step anyway when it matters, because a default that changes later will change every step at once, and I would rather have that be a decision I make per step than a surprise I discover across the whole file.

## What runs, and when

Pipelines picks a section by what triggered the build. Learn these five. They cover almost everything you will run into in the first year.

`default` runs for any branch push that has no more specific pipeline. Think of it as the catch-all, the section that answers the question of what happens when you push a branch nobody wrote a rule for, and the answer had better not be a deploy, because I once put a deploy on `default` and watched every feature branch ship itself to staging, which was exactly what the YAML said to do and nothing like what I meant.

`branches` matches named branches or patterns. This is where `main` lives. This is where deploys live.

`pull-requests` runs on pull request activity. Tests live here. Deploys do not.

`tags` runs on tag pushes. I use it for releases, the kind where someone pushes `v1.4.2` and expects an artifact with that name to exist afterward.

`custom` runs only when someone clicks it in the UI or triggers it from the API. Manual jobs, one-off migrations, the script you want available but never automatic.

```yaml
pipelines:
  pull-requests:
    "**":
      - step:
          name: Test
          caches:
            - pip
          script:
            - pip install -r requirements.txt
            - pytest -q

  branches:
    main:
      - step:
          name: Test
          caches:
            - pip
          script:
            - pip install -r requirements.txt
            - pytest -q
      - step:
          name: Build and push
          services:
            - docker
          script:
            - docker build -t "$ECR_IMAGE:$BITBUCKET_COMMIT" .
            - docker push "$ECR_IMAGE:$BITBUCKET_COMMIT"
```

Push to a branch with an open pull request and both pipelines fire. Same SHA. Two builds. Two bills. I leave tests in both places because a branch pipeline that skips tests teaches people to ignore it, but the image push and the deploy stay on `main`, where there is exactly one of them per merge.

`BITBUCKET_COMMIT` is the full SHA that triggered the build. Use it. `BITBUCKET_BUILD_NUMBER` is a counter that increments per build in the repo, which is unique and also useless six months later when you are trying to work out which commit is actually running in production, so I tag images with the commit and let the build number stay what it is, a build counter, not an identity. The longer version of that argument is [the digest note](./promote-the-image-digest.md), and it applies here exactly the same as on the other hosts.

## Artifacts carry. Caches accelerate.

Two mechanisms. Different promises. Mixing them up is the most common Bitbucket mistake I have reviewed.

Artifacts are files you hand from one step to a later step in the same pipeline. You list paths under `artifacts:`, and the next step receives them, which for a beginner means this: if the file is not under a listed path, the next step cannot see it, period, and no amount of re-running will change that because the container that created it no longer exists.

```yaml
- step:
    name: Package
    script:
      - pytest -q
      - python -m build
    artifacts:
      - dist/**
      - test-reports/**
```

The next step gets `dist/` and `test-reports/`. It does not get the virtualenv. It does not get `/tmp/scratch.txt`. It does not get a Docker image that was built but never pushed, because an image lives in the step's local daemon, and the daemon leaves with the step.

Caches are different. A cache is a directory Bitbucket saves after the build and restores before the next one, keyed on something like the lockfile, and its only job is to make the next build faster by skipping downloads you have already done, which means a cache is a performance hint and never a correctness mechanism, so when the cache restores something stale or poisoned and the build goes green on lies, you delete the cache from the UI, fix the key, and move on.

`pip` is a built-in cache name. You just list it. A custom cache needs a definition first.

```yaml
definitions:
  caches:
    mynode: ~/.npm

pipelines:
  branches:
    main:
      - step:
          name: Build frontend
          image: node:20-slim
          caches:
            - node
            - mynode
          script:
            - npm ci
            - npm run build
          artifacts:
            - dist/**
```

Small rule. Never let a cache be the only copy of a build output. I have seen a pipeline where the deploy step restored the cache and shipped whatever happened to be in it, which worked until the cache expired or was cleared, at which point the deploy shipped nothing and called it success.

## Later steps, manual steps, redeploys

Artifacts expire after 14 days. That number matters in two places that look unrelated until they bite you on the same Friday.

First, a manual step later in the pipeline needs the artifacts from the step that produced them. Wait three weeks to click it and the files are gone. The step fails. Not flaky. Expired.

Second, a redeploy from the Deployments screen reuses the artifacts from that build. Same expiry. Same failure. I push the image to a registry in the build step and let the deploy step pull it by reference, because a registry does not expire in two weeks, and the artifact stays what it should be: reports, small outputs, the things a human reads, not the thing you ship.

## Docker inside the step

The `docker` service is a daemon that runs alongside your step. Your build and that daemon share the step's memory, which is the polite way of saying a Dockerfile that builds fine on your 32 GB laptop can be OOM-killed in Pipelines while you blame the Dockerfile for an hour before you check the step size.

```yaml
definitions:
  services:
    docker:
      memory: 2048

pipelines:
  branches:
    main:
      - step:
          name: Build and push
          size: 2x
          services:
            - docker
          script:
            - docker build -t "$ECR_IMAGE:$BITBUCKET_COMMIT" .
            - docker push "$ECR_IMAGE:$BITBUCKET_COMMIT"
```

`size: 2x` buys a bigger step. It costs more build minutes. I use it on the build step and leave tests on the default size, because paying double for `pytest` to sit in the same memory it always had is just a more expensive way to run the same tests.

Pin the image. `atlassian/default-image:latest` moves. `python:latest` moves. A build that broke with no diff in the repo is usually an image tag that meant something different this morning than it meant last month, and the fix is a tag with numbers in it.

And remember what the service is. Short version: temporary. Longer version: the daemon exists for that step, the image you built exists inside that daemon, and the next step starts from its own image and pulls from a registry, so `docker build` without `docker push` is a build you performed for an audience of one step, and then threw away.

## Parallel steps, and when I use them

Steps run in order by default. A `parallel` block runs its steps at the same time, which is how you stop waiting nine minutes for lint, unit tests, and a security scan that have nothing to do with each other.

```yaml
- parallel:
    - step:
        name: Lint
        script:
          - ruff check .
    - step:
        name: Unit tests
        script:
          - pytest -q -m "not integration"
```

Parallel steps each get the clone. They do not share files with each other. Artifacts from parallel steps merge into the pipeline for later steps, which is convenient until two parallel steps write the same artifact path, at which point one of them wins and the pipeline keeps going like nothing happened, so I keep their outputs in separate directories.

Total parallel steps per pipeline is capped. I fan out the three or four things that actually dominate wall-clock time and leave the rest sequential. Ten-way parallelism on a twenty-step pipeline is a diagram, not a speedup.

## Timeouts and sizes

A step has a maximum runtime. The default is generous. A hung integration test will find the limit eventually, and when it does, the log just stops, which looks like the runner died but is usually the step hitting its ceiling, so before I blame infrastructure I check how long the step ran.

Same with `size`. If only the Docker build step fails, and only on large images, and only with exit code 137 or the daemon complaining about memory, that is the step size. Bump it. Watch the minutes. Move on.

## What I stopped putting in the file

A deploy on `default`. Gone after the incident. A test step that `scp`d artifacts to a server, because that was how the team shipped before pipelines existed and the step was just the old habit wearing YAML. A cache used as the only copy of a build output, for the reasons above.

Short files survive. One job per step. Handoffs through artifact paths or registry references. The file gets long when each environment becomes a copy of the previous step with a different hostname baked in, and those copies are [deployment environments](./bitbucket-deployments.md), where the variables live in Bitbucket instead of in a second copy of the script.
