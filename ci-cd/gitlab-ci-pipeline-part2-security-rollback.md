# GitLab CI for dev, QA, stage, and production: who can deploy

[Part 1](./gitlab-ci-pipeline-part1-structure.md) is the shape: environments are not stages, one artifact, one deploy template. That keeps the YAML readable. It does not stop the wrong person from shipping.

`when: manual` stops a mis-click. Anyone who can run the pipeline can still press the button. Protected environments, protected tags, and variables scoped to those environments are the actual gate. Rollback is the same deploy job pointed at the previous revision, not a script someone writes during the incident.

## Protected environments and protected tags

Mark `production` as a protected environment and assign it to the people who are allowed to deploy. In current GitLab that is **Settings → CI/CD → Protected environments**. Separately, protect the tag pattern that triggers prod, usually `v*`, under **Settings → Repository → Protected tags**.

Those are different gates. One controls who may create the tag that makes a prod job exist. The other controls who may run the job. A manual job on an unprotected environment is a convention. A protected environment is a permission.

Do this before the pipeline is interesting. It is easy to skip because a demo works without it, and then the first real prod deploy is whoever was in the project.

## Variables per environment

Same key, different scope, under **Settings → CI/CD → Variables**.

```
DATABASE_URL   scope: dev
DATABASE_URL   scope: qa
DATABASE_URL   scope: stage
DATABASE_URL   scope: production   masked, protected
```

The job reads `$DATABASE_URL`. GitLab picks the value from the job's `environment:` key. The script does not contain the connection string, and it does not switch on the environment name.

Production values are **masked** and **protected**. Masked keeps them out of the log if the value matches GitLab's mask pattern. Protected means the variable is only injected on protected branches or protected tags. A masked variable that is not protected is still present on a feature-branch pipeline. That is the pairing people miss. Protected variables without a protected tag or branch do nothing useful, because the prod job never sees them, or worse, you unprotect the branch so the job will run.

Do not put the value in `.gitlab-ci.yml`. A masked variable that has already been committed is not masked.

## Rollback is a job

If deploy is `kubectl set image` to a SHA, rollback is that job with an older SHA, or `kubectl rollout undo` when the previous ReplicaSet is still the one you want. Keep the job in the same file as `deploy-prod`. At 2 a.m. you want the button next to the one you just pressed.

```yaml
rollback-prod:
  extends: .deploy_template
  environment:
    name: production
  variables:
    K8S_NAMESPACE: production
  script:
    - kubectl rollout undo deployment/$APP_NAME --namespace=$K8S_NAMESPACE
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: manual
```

`environment:action: stop` is the wrong knob here. `stop` is for tearing down a review app. Rollback is a deploy to production. It uses the same protected environment, so the same people who can ship can roll back, and nobody else can. A looser rollback rule means the gate on deploy does not matter.

`rollout undo` goes to the previous revision Kubernetes still has. If that revision's image was already expired from the registry, undo succeeds at the API and the pods stay in `ImagePullBackOff`. Know the retention on the registry before you trust undo as the only path. Re-running deploy with the last good SHA is the path that still works after the ReplicaSet history is gone.

## What the file looks like when this holds

```
.gitlab-ci.yml
├── stages: build → test → deploy
├── .deploy_template
├── deploy-dev      auto, develop
├── deploy-qa       auto, develop
├── deploy-stage    manual, rc tags
├── deploy-prod     manual, protected environment, release tags
└── rollback-prod   manual, same protected environment
```

A new environment is an `extends` plus a `rules` block. It is not a paste of the deploy script. Who can click is in GitLab's settings, not in a comment at the top of the file.

If the next person can tell which job ships prod and who is allowed to run it without asking you, the structure is doing its job.
