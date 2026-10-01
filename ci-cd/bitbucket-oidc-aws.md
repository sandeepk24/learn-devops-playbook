# Bitbucket Pipelines and AWS

I stored `AWS_ACCESS_KEY_ID` as a secured repository variable and rotated it when someone left. The key was still valid on the weekends nobody remembered. Pipelines can assume a role with OIDC. The token exists only for that step, and only if the step asks for it.

Repository settings, Pipelines, OpenID Connect. Copy the identity provider URL and the audience from that page into IAM. The workspace in that URL is the slug. The audience is `ari:cloud:bitbucket::workspace/` plus the workspace UUID, without braces. I have assembled both from a blog and mixed the slug with the UUID. The page is the source. Paste both.

`oidc: true` on the step is what populates `BITBUCKET_STEP_OIDC_TOKEN`. Without it the assume-role call fails in a way that looks like a bad role ARN. I check the flag before I touch the trust policy.

## The claim AWS will actually enforce

The token carries `branchName`, `repositoryUuid`, and `deploymentEnvironment`. The claim AWS will match in the trust policy is `sub`. Bitbucket builds `sub` as the repository UUID, then the deployment environment UUID when the step is a deployment, then the step UUID. The UUIDs include the braces you see in the UI. Paste them. A policy with the braces stripped never matches.

A step with no `deployment:` gets `{repository-uuid}:{step-uuid}`. A production deployment step gets `{repository-uuid}:{production-environment-uuid}:{step-uuid}`. That middle field is why the production role is assumable from the production deployment step. A test step in the same pipeline, with `oidc: true` and no deployment, carries the repository and the step. `environment: production` loads the variables and the branch check. The assume-role step still has `deployment: production`, because that is the shape this trust policy is written for. How those two keys differ is [the deployments note](./bitbucket-deployments.md).

```hcl
data "aws_iam_policy_document" "bitbucket_deploy" {
  statement {
    effect = "Allow"

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.bitbucket.arn]
    }

    actions = ["sts:AssumeRoleWithWebIdentity"]

    condition {
      test     = "StringEquals"
      variable = "api.bitbucket.org/2.0/workspaces/YOUR_WORKSPACE/pipelines-config/identity/oidc:aud"
      values   = ["ari:cloud:bitbucket::workspace/YOUR_WORKSPACE_UUID"]
    }

    condition {
      test     = "StringLike"
      variable = "api.bitbucket.org/2.0/workspaces/YOUR_WORKSPACE/pipelines-config/identity/oidc:sub"
      values   = ["{REPO_UUID}:{PRODUCTION_ENV_UUID}:*"]
    }
  }
}
```

The provider URL's host and path, without `https://`, is the prefix on those condition keys. A workspace-wide trust, which is what you get if you stop after the IAM wizard, lets every repository in the workspace assume the role. I have found a demo repo in the same workspace that could deploy production. The repository UUID in `sub` is the fix, and the environment UUID is the second fix.

Atlassian's example sometimes puts a `*` immediately after the repository UUID. I keep the colon. A prefix match is how a second repository with a similar id would slip through, and the colon is what the token actually contains.

## The step

Write the token to a file and point the AWS CLI at the file. Do not `set -x` on that line. Do not pass the token as an artifact. The file is in the step's workspace, and a broad `artifacts:` glob will publish it.

```yaml
pipelines:
  branches:
    main:
      - step:
          name: Deploy production
          deployment: production
          trigger: manual
          oidc: true
          image: amazon/aws-cli
          script:
            - export AWS_REGION=us-east-1
            - export AWS_ROLE_ARN=arn:aws:iam::111122223333:role/bitbucket-production-deploy
            - export AWS_WEB_IDENTITY_TOKEN_FILE="$BITBUCKET_CLONE_DIR/web-identity-token"
            - printf '%s' "$BITBUCKET_STEP_OIDC_TOKEN" > "$AWS_WEB_IDENTITY_TOKEN_FILE"
            - aws sts get-caller-identity
            - aws ecs update-service --cluster prod --service api --task-definition "$TASK_DEF_ARN"
```

`deployment: production` is doing two jobs here. It selects the deployment variables and it puts the environment UUID into `sub`, which is what the trust policy is waiting for. `trigger: manual` on a step with no deployment key is a button. The role it can assume is whatever you trusted for every step in the repo. The shape of the ECS deploy is the same one in [the GitHub note](./01_GITHUB_DEVOPS_FUNDAMENTALS.md). The token's subject is the part that is Bitbucket's.

`get-caller-identity` is the check I run before the deploy. If the account or the role name is wrong, I want to see it before `update-service`. If assume-role says the audience is wrong, the audience in IAM is not the audience on the OpenID Connect page. I have yet to see that error mean anything else.

The deploy role can register a task definition and update the service. Account administration stays off it. Pulling from ECR in the same step needs `ecr:GetAuthorizationToken` and the layer reads. Pushing an image is a different role, on the build step, trusted for the repository UUID alone. The production deploy role stays off the pull request build.
