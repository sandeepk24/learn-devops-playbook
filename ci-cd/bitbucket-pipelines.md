# Bitbucket Pipelines

I ended up in Bitbucket because the tickets were already in Jira and the repo was not going to move. The pipeline file is `bitbucket-pipelines.yml` in the root. The part that took me a week to believe is that every step is a new container. The files I wrote in the test step were gone when the build step started, unless I had named them as artifacts.

That is the whole model. A step has an image, a script, and optionally a list of paths to keep. Caches are a speedup I do not promise to the next step. Artifacts are the promise.

## What runs

`default` runs for branches that do not have their own pipeline. I put a deploy on `default` once. Every feature branch deployed. The deploy belongs on `branches: main`, or on a tag, and the pull request pipeline only tests.

```yaml
image: python:3.12-slim

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
          name: Build
          script:
            - docker build -t myapp:$BITBUCKET_COMMIT .
          services:
            - docker
```

A push to a branch that already has an open pull request ran both the branch pipeline and the pull-request pipeline. I paid for two builds of the same SHA until I noticed. Tests can live in both. The image push and the deploy stay on `main`.

`BITBUCKET_COMMIT` is the full SHA. `BITBUCKET_BUILD_NUMBER` increments per build in the repo. I have used the build number as an image tag. It is unique and it is also meaningless the day you need to find the commit. Tag the image with the commit. The digest note is [the same rule on the other hosts](./promote-the-image-digest.md).

## Artifacts and caches

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

The next step in that pipeline receives `dist/` and `test-reports/`. A venv I built and left off the list is gone with the container. A Docker image I built and did not push is gone with it. A later manual step, and a redeploy from the deployments screen, both need the artifacts from the step that produced them, and those artifacts expire after 14 days. I have had a redeploy fail two weeks later because the artifact was gone and the step assumed it would be there. Push the image to a registry in the build step. The deploy step pulls it. I keep reports and small outputs as artifacts.

`pip` is a built-in cache. A custom cache is declared under `definitions` and then named on the step. The pip cache survives across builds when the key matches. I have also restored a poisoned or stale cache and lost an hour. If the lockfile changed and the cache key did not, the cache is lying. Delete it from the UI and fix the key before you trust the green build.

## Docker in the step

The step image and the Docker service share the step's memory. A build that was fine on my laptop was killed in Pipelines because the daemon and the build were splitting 4 GB. I raised the step size, and I gave the docker service an explicit memory value, after I had already blamed the Dockerfile.

```yaml
definitions:
  services:
    docker:
      memory: 2048

pipelines:
  branches:
    main:
      - step:
          size: 2x
          services:
            - docker
          script:
            - docker build -t "$IMAGE" .
            - docker push "$IMAGE"
```

`size: 2x` costs more minutes. I use it for the build step and leave tests on the default size. Pin the step image. `atlassian/default-image:latest` moved under me the same way `python:latest` does.

The Docker service lives for that step. The next step starts from its own image and pulls from ECR or from the workspace's container registry.

## What I stopped putting in the file

A deploy script on `default`. A test step that `scp`s to a server because that was how we used to ship. A cache used as the only copy of a build output.

The file is short when the steps have one job each and the handoff is an artifact path or a registry digest. It gets long when each environment is a copy of the previous step with a different hostname. Those copies are [deployment environments](./bitbucket-deployments.md), and the variables belong there, not in a second copy of the script.
