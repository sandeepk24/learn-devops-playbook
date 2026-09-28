# GitLab CI, from the first pipeline to ECS and EKS

GitLab runs the pipeline from `.gitlab-ci.yml` in the repo root. The runner is the machine that executes jobs. A stage is an ordered phase. Jobs in the same stage run in parallel. A pipeline is one run of that file.

CI is the build and the tests on every push. Continuous delivery stops at an environment and waits for a person. Continuous deployment does not wait. Most production services I ship are delivery, not deployment. The button is there because the rollback story is not automatic yet.

GitLab also gives you a container registry, environment history, and scanners. You do not need Jenkins beside it to get a pipeline.

---

## The file, the runner, the stage

```
your-repo/
├── .gitlab-ci.yml
├── app/
├── Dockerfile
└── requirements.txt
```

Shared runners are GitLab.com's machines. The free tier has a minute quota. A self-hosted runner is your host, registered to the project. Use one when the job has to reach a private network, when the minutes matter, or when the code cannot leave your account. A shell executor on the server you used to rsync onto will deploy for you. Prefer the Docker executor once more than one project shares that host. Shell executors share a filesystem, and the next job inherits whatever the last one installed.

```yaml
stages:
  - build
  - test
  - package
  - deploy
```

```yaml
run-unit-tests:
  stage: test
  script:
    - pip install -r requirements.txt
    - pytest tests/
```

Pipelines show up under **CI/CD → Pipelines**. A job that never appears was excluded by `rules`, or no runner picked up its tags.

---

## A pipeline that tests and deploys

`rules` decide whether the job is created. `only` and `except` still parse. They cannot express "manual, and only on this tag."

```yaml
stages:
  - test
  - deploy

run-tests:
  stage: test
  image: python:3.11-slim
  script:
    - pip install -r requirements.txt
    - python -m pytest tests/ -v
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy-to-server:
  stage: deploy
  script:
    - rsync -avz --delete ./app/ user@your-server:/var/www/myapp/
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

`when: manual` is on the rule. A `when` on the job, beside a `rules` list, does not apply to the rule that matched. That rule defaults to `on_success` and the deploy runs on its own. Manual inside `rules` also defaults `allow_failure` to false, so the pipeline stays blocked until someone runs it or you set `allow_failure: true` on that rule.

```bash
git add .gitlab-ci.yml
git commit -m "Add initial CI pipeline"
git push origin main
```

### A runner on the host

Create the runner in **Settings → CI/CD → Runners**. GitLab gives you an authentication token. The old registration token is not how GitLab.com creates runners anymore.

```bash
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt-get install -y gitlab-runner

sudo gitlab-runner register \
  --url "https://gitlab.com" \
  --token "GLRT-YOUR_RUNNER_TOKEN" \
  --executor "docker" \
  --docker-image "alpine:latest" \
  --description "ubuntu-docker-runner" \
  --tag-list "ubuntu,docker" \
  --run-untagged="false" \
  --locked="true"
```

`--run-untagged=false` means jobs without `tags:` will not land on this machine. That is what you want for a production host. A shell executor is the one that matches "rsync to this box" with no Docker. It is also the one that makes two projects share a home directory. Move off it when a second project shows up.

---

## What the keywords are for

```yaml
default:
  image: python:3.11-slim
  before_script:
    - pip install -r requirements.txt

variables:
  APP_NAME: "my-application"
  DOCKER_DRIVER: overlay2

stages:
  - build
  - test
  - deploy

.python-base:
  image: python:3.11-slim
  before_script:
    - pip install -r requirements.txt

build-app:
  extends: .python-base
  stage: build
  script:
    - python setup.py build
  artifacts:
    paths:
      - dist/
    expire_in: 1 hour

unit-tests:
  extends: .python-base
  stage: test
  script:
    - pytest tests/unit/ --cov=app --cov-report=xml
  coverage: '/TOTAL.*\s+(\d+%)$/'
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage.xml

deploy-staging:
  stage: deploy
  script:
    - ./scripts/deploy.sh staging
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy-production:
  stage: deploy
  script:
    - ./scripts/deploy.sh production
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

`extends` is the merge you want. YAML anchors (`<<: *python-base`) work until someone includes another file and the anchor is out of scope. Hidden jobs, the ones whose names start with `.`, are not created as jobs.

| Keyword | What it does |
|---------|----------------|
| `image` | Container the job runs in |
| `stage` | Which phase |
| `script` | The commands |
| `before_script` / `after_script` | Setup, and cleanup that runs even on failure |
| `artifacts` | Files passed to later jobs, or reports GitLab can parse |
| `cache` | Best-effort reuse across pipelines. Not a handoff |
| `rules` | Whether this job exists in this pipeline |
| `needs` | Start when these jobs finish, without waiting for the whole stage |
| `allow_failure` | Red job, green pipeline |
| `timeout` | Kill it |
| `tags` | Which runner is allowed to take it |
| `resource_group` | One job at a time across pipelines. Use this on production deploys |

Predefined variables you will actually use:

```bash
$CI_COMMIT_BRANCH
$CI_COMMIT_SHA
$CI_COMMIT_SHORT_SHA
$CI_COMMIT_TAG
$CI_PIPELINE_ID
$CI_JOB_NAME
$CI_PROJECT_NAME
$CI_REGISTRY
$CI_REGISTRY_IMAGE
$CI_REGISTRY_USER
$CI_REGISTRY_PASSWORD
$CI_ENVIRONMENT_NAME
$CI_PROJECT_DIR
$CI_MERGE_REQUEST_ID
```

`$CI_REGISTRY_PASSWORD` is a job token for the GitLab registry. It is not an AWS secret. It is already in the job. You do not add it as a CI variable.

---

## Variables and secrets

Precedence, highest first: job variables in the YAML, pipeline variables from the trigger, project variables, group variables, instance variables.

Secrets go in **Settings → CI/CD → Variables**. Masked hides a value that matches GitLab's mask pattern (it will refuse values that do not). Protected injects the variable only on protected branches and protected tags. A production database URL is both. A masked variable that is not protected is present on a feature branch, and a job that prints the environment will have it one `env` away from the log.

```yaml
variables:
  APP_PORT: "8080"

deploy-to-ecs:
  stage: deploy
  script:
    - aws ecs update-service --cluster "$ECS_CLUSTER" --service "$ECS_SERVICE" --force-new-deployment
```

`$AWS_ACCESS_KEY_ID` in that job would come from the UI, not from this file. Prefer OIDC, later in this note. Keys are what you are replacing.

Scope the same key to each environment. The job's `environment: name` selects the value. The script keeps reading `$DATABASE_URL`.

```
DATABASE_URL
  staging     → postgres://staging-db:5432/app
  production  → postgres://prod-db:5432/app   masked, protected
```

---

## Artifacts and cache

Artifacts are the contract between jobs. Cache is a speedup. Cache can miss. If the next job needs the file, it is an artifact.

```yaml
build:
  stage: build
  script:
    - python setup.py bdist_wheel
  artifacts:
    name: "$CI_COMMIT_SHORT_SHA-build"
    paths:
      - dist/*.whl
    expire_in: 7 days
    when: on_success

test:
  stage: test
  needs:
    - job: build
      artifacts: true
  script:
    - pip install dist/*.whl
    - pytest
  artifacts:
    reports:
      junit: test-results.xml
```

JUnit and coverage reports are how the merge request shows failures without someone opening the log.

```yaml
default:
  cache:
    key:
      files:
        - requirements.txt
    paths:
      - .pip-cache/
    policy: pull-push

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.pip-cache"
```

`policy: pull` on the jobs that should not refresh the cache. The job that installs dependencies is the one that pushes.

`needs` is how you stop waiting for an unrelated job in the same stage. `interruptible: true` lets a newer pipeline cancel this one on the same ref. Leave production deploys non-interruptible.

```yaml
run-python-tests:
  rules:
    - changes:
        - "**/*.py"
        - requirements.txt
      when: on_success
    - when: never
```

`rules:changes` is true when GitLab has no push to compare, which includes tag pipelines and scheduled pipelines. Those jobs will run. Add a branch or tag rule in front of `changes` if that surprises you.

---

## Images

Push to the GitLab registry unless the runtime is ECS or EKS, in which case the registry is ECR and this section is only the build.

```yaml
variables:
  IMAGE_TAG: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

build-docker-image:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  variables:
    DOCKER_TLS_CERTDIR: "/certs"
  before_script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"
  script:
    - docker build -t "$IMAGE_TAG" .
    - docker push "$IMAGE_TAG"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

Pin `docker:24.0` to a digest when this is the production build. `dind` needs the privileged runner or a rootless setup you have actually tested. A Kubernetes runner without a privileged dind service fails with a daemon socket error that looks like "docker: not found."

Install dependencies in a venv and copy the venv. `pip install --user` into `/root/.local`, then `USER appuser`, leaves the app user unable to see the packages.

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS production
RUN groupadd -r appuser && useradd -r -g appuser appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY --chown=appuser:appuser ./app .
USER appuser
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

The final stage needs `curl` installed if the health check calls it. Slim does not include curl. Install it, or health-check with a Python one-liner that is already in the image.

```yaml
include:
  - template: Security/Container-Scanning.gitlab-ci.yml

container_scanning:
  variables:
    CS_IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
```

Container scanning on the free tier is the template. It has to be able to pull the image. A scan of an image that was never pushed does not run.

---

## ECS

```
push → test → build → push the SHA to ECR → register a task definition → update the service
```

The service, the task definition family, and the ECR repo exist before this pipeline does. CI does not create the cluster. The IAM permission set for a key-based user is the ECR push actions, `ecs:DescribeTaskDefinition`, `ecs:RegisterTaskDefinition`, `ecs:UpdateService`, `ecs:DescribeServices`, and `iam:PassRole` on the task roles only. `RegisterTaskDefinition` does not accept a resource ARN. `PassRole` is the permission you scope.

OIDC is the setup to use. Assume the role inside the job that calls AWS. Do not write the session keys into a dotenv artifact. Artifacts get stored, and a short-lived key in an artifact is still a key you can download.

GitLab.com's issuer is `https://gitlab.com`. The `aud` on the `id_tokens` entry has to match the trust policy. The `sub` claim looks like `project_path:group/project:ref_type:branch:ref:main`, or the environment form if you scope it that way. Read the claim out of a failed `AssumeRoleWithWebIdentity` before you open the trust up. `token.actions.githubusercontent.com` is GitHub's issuer. It will not validate a GitLab token.

```yaml
.aws-oidc:
  id_tokens:
    GITLAB_OIDC_TOKEN:
      aud: https://gitlab.com
  before_script:
    - |
      creds=$(aws sts assume-role-with-web-identity \
        --role-arn "$AWS_ROLE_ARN" \
        --role-session-name "GitLabCI-$CI_PIPELINE_ID" \
        --web-identity-token "$GITLAB_OIDC_TOKEN" \
        --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
        --output text)
      export AWS_ACCESS_KEY_ID=$(echo "$creds" | awk '{print $1}')
      export AWS_SECRET_ACCESS_KEY=$(echo "$creds" | awk '{print $2}')
      export AWS_SESSION_TOKEN=$(echo "$creds" | awk '{print $3}')
```

Export them in the job. They die with the job. The deploy template below still shows `aws configure` from key variables so you can see the shape. Swap that `before_script` for `.aws-oidc` and delete the keys.

Variables, all masked, production ones protected:

```
AWS_ROLE_ARN
AWS_DEFAULT_REGION
ECR_REGISTRY
ECR_REPOSITORY
ECS_CLUSTER
ECS_SERVICE
ECS_CONTAINER_NAME
```

If you are still on keys, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` sit in the same screen. Rotate them and delete them once the role works.

```yaml
stages:
  - test
  - build
  - push
  - deploy

variables:
  DOCKER_DRIVER: overlay2
  DOCKER_TLS_CERTDIR: "/certs"
  IMAGE_URI: $ECR_REGISTRY/$ECR_REPOSITORY

unit-tests:
  stage: test
  image: python:3.11-slim
  script:
    - pip install -r requirements.txt
    - pytest tests/ -v --junitxml=test-results.xml
  artifacts:
    reports:
      junit: test-results.xml

build-image:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build
        --build-arg GIT_COMMIT=$CI_COMMIT_SHA
        -t "$IMAGE_URI:$CI_COMMIT_SHORT_SHA"
        .
    - docker save "$IMAGE_URI:$CI_COMMIT_SHORT_SHA" > image.tar
  artifacts:
    paths:
      - image.tar
    expire_in: 1 hour
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

push-to-ecr:
  stage: push
  image: docker:24.0
  services:
    - docker:24.0-dind
  needs:
    - job: build-image
      artifacts: true
  before_script:
    - apk add --no-cache aws-cli
  script:
    - aws ecr get-login-password --region "$AWS_DEFAULT_REGION" |
        docker login --username AWS --password-stdin "$ECR_REGISTRY"
    - docker load < image.tar
    - docker push "$IMAGE_URI:$CI_COMMIT_SHORT_SHA"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

.ecs-deploy:
  image:
    name: amazon/aws-cli:latest
    entrypoint: [""]
  before_script:
    - yum install -y python3
    - aws configure set aws_access_key_id "$AWS_ACCESS_KEY_ID"
    - aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY"
    - aws configure set default.region "$AWS_DEFAULT_REGION"
  script:
    - |
      aws ecs describe-task-definition \
        --task-definition "$TASK_FAMILY" \
        --query taskDefinition > task-definition.json
      python3 - <<'PY'
      import json, os
      td = json.load(open("task-definition.json"))
      image = os.environ["IMAGE"]
      name = os.environ["ECS_CONTAINER_NAME"]
      for c in td["containerDefinitions"]:
          if c["name"] == name:
              c["image"] = image
      for key in (
          "taskDefinitionArn", "revision", "status", "requiresAttributes",
          "compatibilities", "registeredAt", "registeredBy",
      ):
          td.pop(key, None)
      json.dump(td, open("task-definition-new.json", "w"))
      PY
    - |
      NEW_ARN=$(aws ecs register-task-definition \
        --cli-input-json file://task-definition-new.json \
        --query taskDefinition.taskDefinitionArn --output text)
      aws ecs update-service \
        --cluster "$ECS_CLUSTER" \
        --service "$ECS_SERVICE_NAME" \
        --task-definition "$NEW_ARN"
      aws ecs wait services-stable \
        --cluster "$ECS_CLUSTER" \
        --services "$ECS_SERVICE_NAME"

deploy-staging:
  extends: .ecs-deploy
  stage: deploy
  needs: [push-to-ecr]
  variables:
    TASK_FAMILY: my-app
    ECS_SERVICE_NAME: my-app-staging
    IMAGE: $IMAGE_URI:$CI_COMMIT_SHORT_SHA
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy-production:
  extends: .ecs-deploy
  stage: deploy
  needs: [deploy-staging]
  variables:
    TASK_FAMILY: my-app
    ECS_SERVICE_NAME: my-app-production
    IMAGE: $IMAGE_URI:$CI_COMMIT_SHORT_SHA
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

Production deploys the same `$CI_COMMIT_SHORT_SHA` that staging ran. `update-service --force-new-deployment` without a new task definition restarts whatever revision is already current. That is a restart, not a release.

`aws ecs wait services-stable` waits until the service settles or the waiter gives up (about ten minutes). If the circuit breaker rolls the service back, the waiter can still succeed once the old tasks are stable. Check the deployment rollout state, not only the waiter exit code, before you call the deploy good.

Rollback is an explicit revision, not "current revision minus one." Someone may have registered a revision you never deployed.

```yaml
rollback-production:
  stage: deploy
  image:
    name: amazon/aws-cli:latest
    entrypoint: [""]
  script:
    - aws ecs update-service
        --cluster "$ECS_CLUSTER"
        --service my-app-production
        --task-definition "$PREVIOUS_TASK_DEFINITION"
        --force-new-deployment
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
  variables:
    PREVIOUS_TASK_DEFINITION: ""
```

Set `PREVIOUS_TASK_DEFINITION` as a pipeline variable when you run the job, or look up the last stable revision and paste the ARN. An empty default makes the job fail until you fill it in. That is the behavior you want.

---

## EKS

Same build and the same ECR push. The deploy is `kubectl` or Helm against a namespace. Staging and production are namespaces or clusters, not branches named after environments.

Authenticate with the same OIDC role, then `aws eks update-kubeconfig`. A base64 kubeconfig in a CI variable is a long-lived admin credential. It expires, it gets copied, and it is harder to scope than a role.

```yaml
.kubectl-setup:
  image:
    name: alpine/k8s:1.29.2
    entrypoint: [""]
  before_script:
    - aws eks update-kubeconfig --region "$AWS_DEFAULT_REGION" --name "$EKS_CLUSTER_NAME"
```

The image tag has to match a kubectl that the API server will talk to. Being one or two minors off usually works. Being many minors off fails in ways that look like auth.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
spec:
  replicas: 2
  selector:
    matchLabels:
      app: my-app
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: my-app
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
      containers:
        - name: my-app
          image: IMAGE_PLACEHOLDER
          ports:
            - containerPort: 8080
          resources:
            requests:
              cpu: "100m"
              memory: "128Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
          readinessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 10
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: my-app-secrets
                  key: DATABASE_URL
```

`maxUnavailable: 0` keeps the old pods until the new ones are ready. It also means a bad readiness probe stalls the rollout instead of taking you down. That is the trade you want.

`sed` on a manifest in the job works once. It fights with anything else that renders the same file, and the image placeholder is one missed replace away from a pod that tries to pull `IMAGE_PLACEHOLDER`. Helm `--set image.tag=$CI_COMMIT_SHORT_SHA` is the version I would leave in the repo.

```yaml
deploy-staging:
  stage: deploy
  extends: .kubectl-setup
  script:
    - helm upgrade --install my-app ./helm/my-app
        --namespace staging
        --create-namespace
        --values helm/my-app/values-staging.yaml
        --set image.repository=$IMAGE_URI
        --set image.tag=$CI_COMMIT_SHORT_SHA
        --wait
        --timeout 5m
        --atomic
  environment:
    name: staging
    url: https://staging.myapp.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy-production:
  stage: deploy
  extends: .kubectl-setup
  needs: [deploy-staging]
  script:
    - helm upgrade --install my-app ./helm/my-app
        --namespace production
        --values helm/my-app/values-production.yaml
        --set image.repository=$IMAGE_URI
        --set image.tag=$CI_COMMIT_SHORT_SHA
        --wait
        --timeout 10m
        --atomic
  environment:
    name: production
    url: https://myapp.com
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual

rollback-production:
  stage: deploy
  extends: .kubectl-setup
  script:
    - helm rollback my-app --namespace production
  environment:
    name: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

`--atomic` rolls the Helm release back if the wait times out. `kubectl rollout undo` does the same for a Deployment and does not know about the rest of the release. Use the tool that applied the manifests.

`environment: action: stop` is how you delete a review app. It is not how you roll back production. A stop job on the production environment is a button that tears the environment down.

Review apps are a deploy on the merge request, a namespace named from `$CI_COMMIT_REF_SLUG`, `auto_stop_in`, and an `on_stop` job with `action: stop`. They cost real money if nothing stops them. Set the timer.

---

## Several environments, one template

Build on `main` or on a tag. Deploy by calling the same job with different variables. The structure note is [part 1](./gitlab-ci-pipeline-part1-structure.md). Who is allowed to click is [part 2](./gitlab-ci-pipeline-part2-security-rollback.md).

```yaml
.deploy-template:
  stage: deploy
  image:
    name: amazon/aws-cli:latest
    entrypoint: [""]
  script:
    - aws ecs update-service
        --cluster "$ECS_CLUSTER_NAME"
        --service "my-app-$DEPLOY_ENV"
        --force-new-deployment
    - aws ecs wait services-stable
        --cluster "$ECS_CLUSTER_NAME"
        --services "my-app-$DEPLOY_ENV"

deploy-dev:
  extends: .deploy-template
  variables:
    DEPLOY_ENV: dev
    ECS_CLUSTER_NAME: dev-cluster
  environment:
    name: development
  rules:
    - if: '$CI_COMMIT_BRANCH == "develop"'

deploy-production:
  extends: .deploy-template
  variables:
    DEPLOY_ENV: production
    ECS_CLUSTER_NAME: prod-cluster
  environment:
    name: production
    url: https://myapp.com
  resource_group: production
  rules:
    - if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
      when: manual
```

`resource_group: production` stops two prod deploys from running at once. Without it, two tags clicked a minute apart will fight over the service.

This template force-deploys the current task definition. It does not change the image. Use it only after a job has already registered a revision with the SHA, or you will redeploy last week's image and the pipeline will be green.

GitLab records who deployed which SHA to which environment. The environment URL is what you click. The history is the audit. It is not a substitute for the task definition ARN in the job log.

---

## Secrets, pins, and the role

Do not commit a key. The example `AKIAIOSFODNN7EXAMPLE` is AWS's documented fake key. A real one in the YAML is in git history even after you delete the line.

Protect `main` and the tag pattern that deploys. Mark production variables protected so a branch pipeline cannot read them.

Pin images. `python:latest` changes under you. `python:3.11.9-slim-bookworm` does not, until you choose to move it.

```yaml
include:
  - template: Security/SAST.gitlab-ci.yml
  - template: Security/Secret-Detection.gitlab-ci.yml
  - template: Security/Dependency-Scanning.gitlab-ci.yml
  - template: Security/Container-Scanning.gitlab-ci.yml
```

The task role on ECS and IRSA or Pod Identity on EKS are how the process gets AWS credentials at runtime. The pipeline role is a different role. The pipeline can deploy. The task can read its secret. Neither can do both.

---

## Keeping the YAML from spreading

Split the file when you cannot find a job. Includes from the same repo, or from a project that holds the templates:

```yaml
include:
  - local: '.gitlab/ci/test.yml'
  - local: '.gitlab/ci/deploy.yml'
  - project: 'company/shared-pipelines'
    ref: v2.1.0
    file: '/templates/docker-build.yml'
```

Pin `ref` to a tag. `ref: main` means the shared project can break every service on their next push.

Production deploys get a timeout, a resource group, and a protected environment. Tests get `parallel` or a matrix when the suite is too slow to run as one job. A canary is a separate Deployment or a traffic weight you can set back, with a metric you agreed would abort it. A second `kubectl set image` you run by hand and then stare at is not a canary.

---

## When the job is red

Turn the trace on for the run you are debugging. Take it back out. `set -x` will print the expanded command, including a secret that was on the same line.

| What you see | What it usually is |
|---|---|
| Stuck, no runner | Tags on the job do not match a runner, or the runner is paused |
| `docker: not found` | The job image has no client, or dind is not a service |
| ECR `403` | The role cannot push, or the login region does not match the registry |
| `kubectl` unauthorized | The role is not in the cluster access entries, or kubeconfig is for another cluster |
| Artifact missing | `needs` without `artifacts: true`, or the producer job did not run |
| Masked variable rejected | The value contains a character GitLab will not mask. Fix the value. Do not unmask it |

Pipeline health that is worth watching: success rate, duration, and how long a bad deploy takes to undo. A duration over fifteen minutes is a suite or an image build you have not split. A success rate you do not measure will be blamed on "GitLab" when it is a flaky test.

```yaml
notify-failure:
  stage: .post
  image: curlimages/curl:latest
  script:
    - |
      curl -X POST "$SLACK_WEBHOOK_URL" \
        -H 'Content-type: application/json' \
        -d "{\"text\": \"Production deploy failed: $CI_PIPELINE_URL\"}"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: on_failure
```

`.post` runs after the other stages. `when: on_failure` on the rule is what makes this job exist only when something failed. A job-level `when: on_failure` next to `rules` has the same problem as manual: the rule wins, and the rule said `on_success`.

---

## Runners

| | Shared, GitLab.com | Self-hosted |
|---|---|---|
| Setup | None | You install and patch it |
| Cost | Included minutes, then paid | The instance |
| AWS | A role via OIDC | A role via OIDC, or an instance profile if the runner itself is on EC2 |
| Where the code runs | GitLab's infra | Yours |

An instance profile on the runner is convenient and broad. Every project that can schedule a job on that runner can use that profile. Prefer OIDC per project unless the runner is locked to one project.

```yaml
deploy-production:
  tags:
    - production
  script:
    - ./deploy.sh
```

Executors: `shell` on the host, `docker` for a clean container per job, `kubernetes` for a pod per job. Docker is the default I would register. Shell is how a compromised job reads the next job's environment off disk.

---

## A file you can start from

```yaml
stages: [test, build, deploy]

variables:
  IMAGE: $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA

test:
  stage: test
  image: python:3.11-slim
  script:
    - pip install -r requirements.txt
    - pytest
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "main"'

build:
  stage: build
  image: docker:24.0
  services: [docker:24.0-dind]
  script:
    - docker login -u "$CI_REGISTRY_USER" -p "$CI_REGISTRY_PASSWORD" "$CI_REGISTRY"
    - docker build -t "$IMAGE" .
    - docker push "$IMAGE"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

deploy-production:
  stage: deploy
  script: [./deploy.sh production]
  environment:
    name: production
  resource_group: production
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'
      when: manual
```

```yaml
- if: '$CI_COMMIT_BRANCH == "main"'
- if: '$CI_MERGE_REQUEST_ID'
- if: '$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/'
- changes: ["**/*.py", "requirements.txt"]
- if: '$CI_PIPELINE_SOURCE == "schedule"'
  when: never
```

```bash
aws ecs update-service \
  --cluster "$ECS_CLUSTER" \
  --service "$ECS_SERVICE" \
  --task-definition "$TASK_DEFINITION_ARN"

kubectl rollout status deployment/my-app -n production
kubectl rollout history deployment/my-app -n production
kubectl rollout undo deployment/my-app -n production
```

The order I would actually follow: tests on every push, a Docker executor runner, the image tagged with the SHA in ECR, staging deploying that SHA, production manual against the same SHA, then OIDC so the keys can be deleted. EKS is the same pipeline with Helm at the end. It is not a different discipline.
