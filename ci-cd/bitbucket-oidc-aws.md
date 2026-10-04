# Bitbucket Pipelines and AWS

I used to store `AWS_ACCESS_KEY_ID` as a secured repository variable. It worked. It also never expired, survived every offboarding checklist, and stayed valid through weekends nobody remembered, which is the short version of why long-lived keys in CI are a liability even when they are encrypted, masked, and rotated on a schedule someone wrote down once.

Pipelines can assume an AWS role instead. No stored key. A token that exists for one step and then stops existing. That is the whole pitch, and the rest of this note is the wiring that makes it true.

## The idea in thirty seconds

For anyone new to this: OIDC lets Bitbucket prove to AWS that a running step is who it claims to be, without a shared password, by signing a short-lived token (a JWT, which is just a JSON document with an expiry that Bitbucket signs) and handing it to AWS, which checks the signature against Bitbucket's identity provider and, if the claims inside match the trust policy on the role, hands back temporary credentials that die on their own.

Three pieces. The provider in IAM, which says Bitbucket is allowed to vouch. The role, whose trust policy says which vouches to believe. The step, which asks for the token and trades it in. Miss any one and the error points at the other two, so I set them up in that order and test in that order.

## The provider

In Bitbucket, go to repository settings, Pipelines, OpenID Connect. Two values sit on that page: the identity provider URL and the audience. Copy them. Do not reconstruct them from a blog post. I once assembled the URL from memory, swapped the workspace slug for the workspace UUID, and debugged IAM for an hour before looking at the page that had both values printed on it.

The URL contains the workspace slug, the short human name. The audience looks like `ari:cloud:bitbucket::workspace/` followed by the workspace UUID, the long hex ID, without braces. Slug in one place. UUID in the other. They are not interchangeable, and the error when you mix them up reads like a permissions problem rather than a typo, which is why I am belaboring something that sounds obvious.

In IAM, add an OpenID Connect provider with those two values. If AWS asks for a thumbprint, the documented one for this provider is `a031c46782e6e6c662c2c87c76da9aa62ccabd8e`, taken from the root CA the same way the AWS docs describe, though in practice the console usually handles it, and I mention it only so you recognize it when it appears rather than wondering whether it is a secret you need to protect. It is not. It is a fingerprint of a public certificate.

## The token

The step gets the token by asking for it. That is what `oidc: true` does: it tells Bitbucket to mint the step's JWT and expose it as `BITBUCKET_STEP_OIDC_TOKEN`, and without that flag the variable is empty and the assume-role call fails with an error shaped exactly like a bad role ARN, so I check the flag before I touch the trust policy, every time, because I have edited a working trust policy to fix a missing flag and then had two problems.

Short version: no flag, no token.

The token carries claims: `branchName`, `repositoryUuid`, `deploymentEnvironment`, the step and pipeline UUIDs. AWS trust policies cannot match most of those. The one they can match is `sub`, the subject, and Bitbucket builds it from UUIDs in a fixed shape: the repository UUID, then the deployment environment UUID when the step is a deployment, then the step UUID.

A plain step gets `{repository-uuid}:{step-uuid}`. A production deployment step gets `{repository-uuid}:{production-environment-uuid}:{step-uuid}`. That middle field is the entire reason the production role can be assumable from the production step and from nothing else, because a test step in the same pipeline, even with `oidc: true`, carries the repository and its own step UUID but not the environment, and the trust policy below will refuse it, which is the behavior I want, enforced by string matching rather than by my memory of which steps are safe.

Keep the braces. The UUIDs as shown in the Bitbucket UI include `{` and `}`, and the trust policy must include them too. Strip them to "clean it up" and the policy matches nothing, silently, forever. Keep the colon after the repository UUID as a literal colon. Atlassian's own example sometimes shows a `*` glued directly to the repo UUID, and a prefix match there is how a second repository with a similar leading ID could slip through, whereas the colon is what the token actually contains, so I match the colon.

## The trust policy

Two conditions. The audience, matched exactly. The subject, matched as a pattern. Everything else is standard federated-role shape.

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

Read the condition keys left to right. The host and path of the provider URL, without `https://`, then `:aud` or `:sub`. If the provider URL ever changes shape, these keys change with it, and a trust policy copied from another workspace will fail closed, which is the safe direction, but confusing at midnight, so I compare the key prefix against the provider URL character by character before assuming anything else is wrong.

The trailing `*` covers the step UUID, which is different on every run. Pinning a full `sub` with a real step UUID would trust exactly one historical build, which is precise and useless. The `*` is doing real work. Leave it.

What the IAM wizard creates by default, if you stop after clicking through, is a workspace-wide trust: anyone in the workspace with a token can assume the role. That includes the demo repo someone made three years ago and the sandbox that prints secrets for fun. I found one of those able to deploy production. The repository UUID in `sub` is the fix. The environment UUID is the second fix, narrowing it from the repo to the production step in that repo. Two fields. Each one removes a class of caller I never meant to authorize.

Where do the UUIDs come from? The repository UUID is on the OpenID Connect settings page and in `BITBUCKET_REPO_UUID` during a build. The environment UUID is on the deployments settings screen, and it appears in the token as well. I copy them from the UI rather than from a build log, because logs get the braces stripped by helpful formatters and then nothing matches.

## The step

Write the token to a file. Point the AWS CLI at the file. Never print the token. Never ship it as an artifact.

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

Line by line, for the person reading this in their first month. `deployment: production` selects the production variables and, critically, puts the environment UUID into `sub`, which is what the trust policy above is waiting for. `trigger: manual` parks the step until a human with write access clicks it. `oidc: true` mints the token. The image is the AWS CLI, pinned by digest in a real file because `amazon/aws-cli` without a tag moves under you the same way every other floating tag does. `printf` writes the token to a file without adding a trailing newline that `echo` would add, and the CLI reads the file, trades the token for temporary credentials, and uses those for every call after.

Two things I do not do on that page. I do not run `set -x` on the lines that touch the token, because tracing prints expansions, and masking does not reliably catch a value that has been written to a file and read back. And I do not list the token file, or anything near it, under `artifacts:`, because a broad glob like `**` will publish the credential to the next step and to anyone who can download artifacts, which is everyone who can see the build.

`deployment: production` is doing double duty here and I want that explicit, since it confuses every newcomer and confused me for months: it selects the deployment variables for the step and it shapes the token subject that AWS matches, so a step with `environment: production` instead would load the same variables and pass the same branch checks but would not carry the environment UUID in `sub`, and this trust policy would refuse it. That is by design. How the two keys differ is [the deployments note](./bitbucket-deployments.md), and the ECS call at the end is shaped like [the GitHub deploy](./01_GITHUB_DEVOPS_FUNDAMENTALS.md), because the AWS side does not care which CI host minted the token.

## Checking it

`aws sts get-caller-identity` runs before the deploy. Cheap. Fast. If the account or role name is wrong, I learn it here, before `update-service` has done half a rollout. If assume-role complains about the audience, the audience in IAM is not the audience on the OpenID Connect page, and in three years I have yet to see that error mean anything else, so I stop debugging the policy and compare the two strings.

Common failures, in the order I check them. Empty token: the step is missing `oidc: true`. Access denied with a valid-looking token: the `sub` pattern does not match, usually stripped braces, a slug where the UUID goes, or a missing environment segment because the step has no `deployment:`. Audience mismatch: copied from the wrong workspace, or from a blog. Forbidden on the AWS action itself, after assume-role succeeded: the role's permission policy, not its trust policy, which is a different document and a different fix, and conflating the two is how a trust-policy edit breaks something that was already working.

## Least privilege, concretely

The deploy role registers task definitions and updates the service. Nothing else. No account administration, no IAM writes, no ability to touch another service's task definition, because a role that can update any service in the cluster is a production deploy role for every team at once, and I scope it to the cluster, service, and task family this pipeline owns.

Pulling from ECR in the same step needs `ecr:GetAuthorizationToken` plus the image-layer reads on the repository. Pushing is a different role on the build step, trusted for the repository UUID alone, without the production environment segment, because the build step is not a deployment and must never satisfy a production trust policy. The production deploy role stays off the pull request build entirely. A pull request pipeline that can assume the production role is a deploy button labeled "test", available to every branch, and the trust policy is the last place that mistake gets caught, so I make sure it gets caught there.
