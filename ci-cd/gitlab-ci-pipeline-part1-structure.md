# Structuring a Clean GitLab CI Pipeline for Dev, QA, Stage, and Production (Part 1: Structure & Rules)

Here's a moment every DevOps engineer eventually lives through: you open a `.gitlab-ci.yml` you didn't write, and it's 400 lines long. There's a `deploy-to-qa`, a `deploy_qa2`, a `deploy-stage-OLD`, and a comment that says `# don't touch, breaks prod`. Nobody on the team can tell you with confidence what happens if you delete that comment. That file didn't get born this way — it was built one reasonable, well-intentioned commit at a time, by people solving the problem in front of them without a model for where the next environment would go.

That's really what this two-part series is about: the model. Not a list of YAML snippets to copy, but the handful of decisions that, made early, keep a pipeline legible even after it's grown to cover dev, QA, stage, and production. If you're a couple of years into DevOps and you've only ever *inherited* pipelines like the one above, this is the piece that explains why they end up that way — and what the alternative actually looks like in practice.

Part 1 covers the structural side: how environments relate to stages (they're not the same thing, and treating them as one is where most of the mess starts), why you build an artifact exactly once, and how GitLab's `extends` keyword turns four near-identical deploy jobs into one template and four small diffs. [Part 2](./gitlab-ci-pipeline-part2-security-rollback.md) picks up where structure stops being enough — protected environments, environment-scoped secrets, and rollback.

## The core problem: environments aren't stages

Here's the mistake almost everyone makes once, usually without noticing: treating `dev`, `qa`, `stage`, and `production` as **stages** in the pipeline sense. They're not, and the distinction matters more than it sounds like it should. A stage in GitLab CI (`build`, `test`, `deploy`) describes a *phase of work* — what's happening. An environment describes *where that work lands*. Collapse the two and you get a `deploy-to-qa` stage sitting next to a `deploy-to-stage` stage sitting next to a `deploy-to-prod` stage — three jobs that are 90% identical, each one drifting slightly further from the others every time someone patches just one of them under deadline pressure. Six months later, that's your 400-line file.

The cleaner mental model:

```
stages:
  - build
  - test
  - deploy

environments:
  dev  → auto-deploy on every merge to develop
  qa   → auto-deploy on every merge to develop (same artifact, different target)
  stage → manual promotion of a tagged/release-candidate artifact
  prod  → manual promotion, protected, requires approval
```

One `deploy` stage, one `deploy` job template, parameterized by environment. Everything else is `rules:` controlling *when* each environment's instance of that job runs.

## Build once, deploy everywhere

Quick gut-check before we get to YAML: does your pipeline rebuild the application separately for dev, for QA, for stage, and for prod? If yes, that's worth fixing before anything else in this article, because it undermines the entire point of having those environments. You want exactly **one** build artifact — a container image, a compiled binary, a packaged bundle — that gets promoted through environments unchanged. Rebuild per environment and you're no longer testing the thing that ships to prod. You're testing a sibling of it, compiled at a slightly different moment, possibly against slightly different dependency resolution. "It worked in staging" stops meaning anything once staging and prod were never actually the same artifact.

```yaml
build:
  stage: build
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "develop"'
    - if: '$CI_COMMIT_TAG'
```

The tag `$CI_COMMIT_SHORT_SHA` becomes the single identifier that travels from dev through prod. When someone asks "is this the same build that passed QA," the answer should be a diff of one string, not an archaeology project.

## A template-first job structure

If you take one thing from this article and skip the rest, make it this: GitLab's `extends` keyword is the single biggest lever for keeping a multi-environment pipeline readable. Define the *shape* of a deploy job exactly once, then extend it per environment with only the handful of things that actually differ. Everything else inherits automatically — which means it can't quietly drift out of sync the way copy-pasted jobs always do.

```yaml
.deploy_template:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl set image deployment/$APP_NAME
        $APP_NAME=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
        --namespace=$K8S_NAMESPACE
    - kubectl rollout status deployment/$APP_NAME --namespace=$K8S_NAMESPACE

deploy-dev:
  extends: .deploy_template
  environment:
    name: dev
    url: https://dev.example.com
  variables:
    K8S_NAMESPACE: dev
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy-qa:
  extends: .deploy_template
  environment:
    name: qa
    url: https://qa.example.com
  variables:
    K8S_NAMESPACE: qa
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy-stage:
  extends: .deploy_template
  environment:
    name: stage
    url: https://stage.example.com
  variables:
    K8S_NAMESPACE: stage
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+-rc/'
      when: manual

deploy-prod:
  extends: .deploy_template
  environment:
    name: production
    url: https://example.com
  variables:
    K8S_NAMESPACE: production
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: manual
```

Notice what's different across the four jobs: the namespace, the environment URL, and the rule governing when they're eligible to run. Everything else — the actual deploy mechanics — lives in one place. When your deploy logic changes (say, you move from `kubectl set image` to a Helm upgrade), you change it once.

## Rules, not only/except

If your pipeline still uses `only:`/`except:`, that's worth migrating away from independent of the environment question. `rules:` gives you ordered, composable conditions and — more importantly — lets you attach `when: manual`, `when: on_success`, and `allow_failure` per condition instead of bolting them onto the job as a whole.

The pattern worth internalizing: **auto-deploy pre-production, gate production behind an explicit human action.** Dev and QA should update on every merge without anyone touching a button — that's the point of having them. Stage and prod should require someone to look at what's about to happen and press go.

| Environment | Trigger | Approval | Typical audience |
|---|---|---|---|
| dev | merge to `develop` | none | engineers, fast feedback |
| qa | merge to `develop` | none | QA team, automated test suites |
| stage | release-candidate tag | manual | QA sign-off, stakeholder demos |
| production | release tag | manual, protected | on-call, release manager |

Look closely at that "protected" in the last column, though, because it's doing more work than it looks like. `when: manual` only stops someone from deploying to prod *by accident* — it says nothing about who's allowed to click the button in the first place. If your pipeline stops here, "manual approval" is really just a suggestion enforced by good manners. Making it an actual control boundary — one where the answer to "could a new hire on the team accidentally push to prod" is a hard no — is what Part 2 is for.

---

*Continue to [Part 2: Security & Rollback](./gitlab-ci-pipeline-part2-security-rollback.md). Part of the [Learn DevOps Playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*
