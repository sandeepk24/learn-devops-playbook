# GitLab CI for dev, QA, stage, and production

A `.gitlab-ci.yml` you did not write is often four hundred lines. `deploy-to-qa`, `deploy_qa2`, `deploy-stage-OLD`, and a comment that says the next person who edits it will break prod. Nobody can tell you what deleting a job does. It got there one reasonable commit at a time, because each environment was added as a copy.

This is the model that keeps the file readable after you have dev, QA, stage, and production. [Part 2](./gitlab-ci-pipeline-part2-security-rollback.md) is protected environments, scoped variables, and rollback. The YAML below is the structure. It is not a pipeline you paste over a cluster you have not looked at.

## Environments are not stages

`dev`, `qa`, `stage`, and `production` are not stages. A stage is a phase: `build`, `test`, `deploy`. An environment is where a deploy lands. If you make each environment a stage, you get three deploy jobs that started identical and drifted the first time someone patched one of them on a deadline.

```
stages:
  - build
  - test
  - deploy

environments:
  dev   → auto, every merge to develop
  qa    → auto, same artifact, different namespace
  stage → manual, release-candidate tag
  prod  → manual, protected, release tag
```

One deploy stage. One deploy template. `rules:` decide which copy runs.

## Build once

If the pipeline rebuilds the image for dev, again for QA, again for stage, and again for prod, you are not promoting a build. You are testing a sibling of the thing you will ship, compiled later, maybe with different dependency resolution. "It worked in staging" only counts when staging ran the same digest prod will run.

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

`$CI_COMMIT_SHORT_SHA` is the id that moves from dev to prod. Whether QA passed is a comparison of that string, not a guess about which pipeline built which environment.

Tag `latest` as well if a human needs it. Do not deploy `latest`. Deploy the SHA.

## One template, four jobs

`extends` is how the four jobs stay the same deploy. The hidden job defines the shape. Each environment overrides the namespace, the URL, and the rule.

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

When the deploy changes, you change `.deploy_template`. Moving from `kubectl set image` to Helm is one edit. Four copied jobs means you will update three of them.

`bitnami/kubectl:latest` is fine in a sketch. Pin it once this is a pipeline you run. `latest` will change the kubectl version on you.

## rules, not only/except

`only` and `except` still run. They cannot say "manual, but only on this tag." `rules` can. Put `when: manual` on the matching rule. A `when` sitting on the job, next to a `rules` block, does not apply to the rule that matched. The rule with no `when` of its own defaults to `on_success`, and the job runs by itself. `when: manual` inside `rules` also defaults `allow_failure` to false, so the pipeline waits. Job-level `when: manual` defaults `allow_failure` to true, and the pipeline goes green while prod never shipped.

Dev and QA deploy on merge to `develop`. Nobody clicks anything. That is why those environments exist. Stage and prod wait for a person, and the tag pattern is what makes "a person" mean "a release," not "any commit on the branch."

| Environment | Trigger | Who has to act |
|---|---|---|
| dev | merge to `develop` | nobody |
| qa | merge to `develop` | nobody |
| stage | tag matching `v1.2.3-rc` | someone clicks |
| production | tag matching `v1.2.3` | someone who is allowed to, see part 2 |

`when: manual` stops an accident. It does not stop a new hire with Developer access from clicking the button. Protected environments are that control. That is [part 2](./gitlab-ci-pipeline-part2-security-rollback.md).
