# Structuring a Clean GitLab CI Pipeline for Dev, QA, Stage, and Production (Part 2: Security & Rollback)

[Part 1](./gitlab-ci-pipeline-part1-structure.md) covered the structural side of a multi-environment pipeline: treating environments as parameters rather than stages, building once and promoting the same artifact, and templating deploy jobs with `extends` so four environments don't mean four copies of the same logic.

Getting the structure right solves readability. It doesn't solve control. A `when: manual` flag stops an *accidental* production deploy — it does nothing to stop someone with push access from triggering one they weren't supposed to. That's what this part covers: locking the pipeline down for real, scoping secrets correctly per environment, and making rollback something the pipeline already knows how to do rather than something you improvise under pressure.

## Protected environments and protected branches are not optional

This is the part that gets skipped most often, usually because everything works fine in a demo without it. GitLab lets you mark an environment as **protected**, restricting who can trigger deployments to it — separate from who can merge code. Pair that with a **protected branch** (or protected tag pattern) for whatever triggers your prod deploy, and you get a real control boundary instead of a YAML convention that anyone with push access can bypass.

Settings → CI/CD → Protected environments: assign `production` to a specific group (release managers, senior engineers, whoever your process calls for). Settings → Repository → Protected tags: lock down the `v*` pattern so only authorized roles can push a release tag in the first place. Now "manual approval to deploy" and "manual approval to even create the thing that can be deployed" are two separate gates, which is usually what people mean when they say they want a controlled release process but don't say it explicitly.

## Handling secrets per environment

Each environment needs its own credentials, and GitLab's environment-scoped variables exist specifically so you don't hardcode a namespace or a connection string into the job. Under Settings → CI/CD → Variables, scope a variable to a specific environment rather than making it global:

```
DATABASE_URL   scoped to: dev
DATABASE_URL   scoped to: qa
DATABASE_URL   scoped to: stage
DATABASE_URL   scoped to: production   (masked, protected)
```

The variable name stays identical across environments — only the scope and value change. Your job script never needs to know which environment it's in beyond referencing `$DATABASE_URL`; GitLab resolves the correct value based on the `environment:` key on that job. For production specifically, mark the variable both **masked** and **protected** — protected variables are only exposed to pipelines running on protected branches or tags, which ties directly back into the protected-branch setup above. Without that pairing, a masked-but-unprotected variable is still readable from any branch, protected or not.

## Rollback is a pipeline feature, not an afterthought

If promotion is `kubectl set image` to a new tag, rollback is the same job pointed at the previous tag. Don't build a separate "rollback pipeline" as an afterthought — make the deploy job idempotent and parameterizable enough that re-running it with an older `$CI_COMMIT_SHORT_SHA` (or triggering it manually via the GitLab UI with a different tag) *is* the rollback.

```yaml
rollback-prod:
  extends: .deploy_template
  environment:
    name: production
    action: stop
  variables:
    K8S_NAMESPACE: production
  script:
    - kubectl rollout undo deployment/$APP_NAME --namespace=$K8S_NAMESPACE
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: manual
```

Having this job sit right next to `deploy-prod` in the same file means whoever is on call at 2 a.m. isn't hunting for a different pipeline definition — it's the button next to the one they just pushed. It should carry the same protections as the deploy job itself: same protected environment, same restricted group. Rollback authority shouldn't be looser than deploy authority.

## Putting it together: what "clean" actually looks like

A pipeline that's aged well usually has this shape:

```
.gitlab-ci.yml
├── stages: build → test → deploy
├── .build_template
├── .test_template  (lint, unit, integration — same for every branch)
├── .deploy_template
├── deploy-dev      (extends .deploy_template, auto)
├── deploy-qa       (extends .deploy_template, auto)
├── deploy-stage    (extends .deploy_template, manual, RC tags)
├── deploy-prod     (extends .deploy_template, manual, protected, release tags)
└── rollback-prod   (extends .deploy_template, manual, protected)
```

Four environments, five deploy-related jobs, and one template each for build/test/deploy. The line count doesn't stay flat as you add environments — but the *complexity* does, because every new environment is a template extension plus a rules block, not a new copy of the deploy logic. Add protected environments and scoped variables on top, and the security boundary lives in GitLab's settings rather than in tribal knowledge about who's supposed to click the button.

The engineers who inherit this file later won't need you to explain it. That's the actual test of whether the structure worked.

---

*Back to [Part 1: Structure & Rules](./gitlab-ci-pipeline-part1-structure.md). Part of the [Learn DevOps Playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*
