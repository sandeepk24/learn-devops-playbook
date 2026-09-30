# Promote the image digest

The thing you tested and the thing you deploy have to be the same bytes. A tag is a pointer. It moves when someone pushes again. A digest is the bytes. Staging and production get the digest.

[GitLab structure](./gitlab-ci-pipeline-part1-structure.md) says build once. This is what you do with the artifact after that build, on ECR and in the task definition.

## Tags move

`latest` moves. A git SHA tag moves too, if the repository is mutable and someone runs the build again for the same commit. ECR `image_tag_mutability = "IMMUTABLE"` stops a tag from being overwritten. It does not stop a deploy from tracking a tag that you have not pushed yet, and it does not tell you which bytes a running task pulled last week.

The image reference I put in a task definition:

```text
123456789012.dkr.ecr.us-east-1.amazonaws.com/myapp@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

The tag stays on the image so a human can find the commit. The service runs the digest.

## Build once, on main

The pull request pipeline builds to prove the Dockerfile. It does not produce the production artifact. The merge commit is the first tree that is actually on main, which is the point of a [merge queue](./merge-queues.md). Build there.

```yaml
name: Build
on:
  push:
    branches: [main]

permissions:
  id-token: write
  contents: read

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: myapp

jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      digest: ${{ steps.push.outputs.digest }}
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_ECR_PUSH_ROLE }}
          aws-region: ${{ env.AWS_REGION }}
      - id: login
        uses: aws-actions/amazon-ecr-login@v2
      - id: push
        env:
          REGISTRY: ${{ steps.login.outputs.registry }}
          SHA: ${{ github.sha }}
        run: |
          IMAGE="$REGISTRY/$ECR_REPOSITORY:$SHA"
          docker build -t "$IMAGE" .
          docker push "$IMAGE"
          DIGEST=$(aws ecr describe-images \
            --repository-name "$ECR_REPOSITORY" \
            --image-ids imageTag="$SHA" \
            --query 'imageDetails[0].imageDigest' \
            --output text)
          echo "digest=$DIGEST" >> "$GITHUB_OUTPUT"
          echo "Pushed $IMAGE"
          echo "Digest $DIGEST"
```

`describe-images` returns the digest ECR stored. `docker inspect` on the local image is the local manifest. For a single-platform build they match. For a multi-platform build, the digest you deploy is the manifest list ECR has, which is the query above.

Record the digest on the workflow run. The deploy jobs take it as an input. They do not build.

## Staging, then production

Staging deploys the digest this build just pushed. Production deploys a digest you name. If production builds, or production pulls `:latest`, staging did not approve anything.

```yaml
name: Deploy
on:
  workflow_call:
    inputs:
      digest:
        required: true
        type: string
      service:
        required: true
        type: string
      environment:
        required: true
        type: string

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    permissions:
      id-token: write
      contents: read
    steps:
      - name: Reject anything that is not a digest
        env:
          DIGEST: ${{ inputs.digest }}
        run: |
          if ! printf '%s' "$DIGEST" | grep -Eq '^sha256:[a-f0-9]{64}$'; then
            echo "Refusing to deploy '$DIGEST'. Expected sha256 and 64 hex characters."
            exit 1
          fi
```

The check is the full digest: `sha256:` and 64 hex characters. A tag, a short SHA, and `latest` all fail it.

The rest of the job is the task definition render from [part 2](./github-devops-implementation-02.md). The image field is `$REGISTRY/$REPO@${{ inputs.digest }}`. ECS accepts that form. The new revision is what you roll back to, by revision, because the digest is still in the registry.

Wire it so staging is the build's digest and production is a person choosing a digest that staging already ran:

```yaml
on:
  workflow_dispatch:
    inputs:
      digest:
        description: "sha256 digest already running in staging"
        required: true
        type: string

jobs:
  production:
    uses: ./.github/workflows/deploy.yml
    with:
      digest: ${{ inputs.digest }}
      service: myapp-production
      environment: production
    secrets:
      aws-role: ${{ secrets.PROD_AWS_ROLE }}
```

Look at the staging task definition before you dispatch. The digest in the input and the digest in `aws ecs describe-task-definition` for staging are the same string, or you are promoting something staging never ran.

## Lifecycle policies

A policy that expires images by age will delete the digest production is running, and the next scale-out fails with `CannotPullContainerError`. The task that is already running keeps going. The new task does not start. It looks like a capacity problem.

Keep the tags production can still be rolled back to. Expire untagged images, and expire SHA tags older than the oldest revision you are willing to roll back to. Thirty days is a guess. The real number is how far back your rollback runbook goes. If rollback is "the previous task definition," you need every digest that revision points at. Task definitions remember the digest. ECR has to still have the layers.

Immutable tags plus a lifecycle rule on `imageCountMoreThan` for the SHA prefix is the usual pair. Do not add a rule that expires everything tagged, because the digest and the tag are the same image.

## Attestation

Signing is the check that the digest was produced by the workflow, not by someone with a laptop and push access to ECR. The deploy role should not also be the only push role. CI pushes. Deploy pulls and registers a task definition.

GitHub artifact attestations bind the digest to the workflow run. Pin the action to a SHA when this leaves the sketch. The inputs that matter are the image name and the digest you just pushed.

```yaml
permissions:
  id-token: write
  contents: read
  attestations: write

steps:
  - uses: actions/attest-build-provenance@v2
    with:
      subject-name: ${{ steps.login.outputs.registry }}/myapp
      subject-digest: ${{ steps.push.outputs.digest }}
      push-to-registry: true
```

Verify at deploy time, before `register-task-definition`. A verify step that fails open is a log line. A verify step that fails the job is a control. Start by failing the production job only. Staging can warn while you find out which images were pushed by hand.

The deploy still names the digest. The attestation is how you know that digest came from main. The tag is how a person searches ECR. Three different jobs.
