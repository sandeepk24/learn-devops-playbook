# Bitbucket deployment environments

A step that runs `./deploy.sh production` is a script with an argument. A step with `deployment: production` is the row on the Deployments screen, and it takes the environment's lock. I treated those as the same for a year.

Pipelines creates `test`, `staging`, and `production` when you turn it on. The string in the YAML is the name on that screen, including case. I renamed one to `Production` and the pipeline that still said `production` stopped matching it.

In one pipeline the deployment steps go test, then staging, then production. I put a production step above a staging step once. The file was rejected before it ran.

There is a second key, `environment:`, added so a step can take the variables and the branch and admin checks without the dashboard row and without the lock. I use `deployment:` on the step that actually ships, because that is the one I want recorded. I use `environment:` on a smoke step that needs the same variables and is allowed to run beside something else. The settings screen is the same one.

## One environment, one owner

```yaml
pipelines:
  branches:
    main:
      - step:
          name: Test
          script:
            - pytest -q
      - step:
          name: Staging
          deployment: staging
          script:
            - ./deploy.sh
      - step:
          name: Production
          deployment: production
          trigger: manual
          script:
            - ./deploy.sh
```

`trigger: manual` stops the pipeline at that step until someone with write access clicks. It cannot be the first step. The click is still anyone with write access, until the environment itself has a permission. I have watched a new hire press the production step because it was the next green button.

On the environment I set two things when the plan includes them. Who may deploy, and which branches may deploy. Both showed up for me on Premium. On the Standard workspace the control I actually had was `trigger: manual`. A grayed-out deploy button has meant, every time I have hovered it, that the branch was not on that allow-list. `develop` was building a step named production. The YAML was valid. The environment was doing its job.

A schedule that used to deploy production at midnight started sitting on a paused step once a person had to approve the environment. I wanted the pause. I wanted to find it before the staging environment had gone stale.

A second step in the same pipeline that also says `deployment: production` is rejected. When I needed the migration and the app rollout to share the lock and the variables, I put them in a stage, after a step that had already run. A manual stage cannot be the first item in the pipeline. The stage holds one deployment across its steps. Another pipeline aimed at the same environment waits. That wait used to sit there until someone resumed it. `concurrency-group` is the queue that resumes on its own, one step at a time, and it can sit next to `deployment:` when I want both the dashboard row and a queue that moves.

```yaml
- step:
    name: Test
    script:
      - pytest -q
- stage:
    name: Production
    deployment: production
    trigger: manual
    steps:
      - step:
          name: Migrate
          script:
            - ./migrate.sh
      - step:
          name: Roll out
          script:
            - ./deploy.sh
```

## Variables

The same name can exist at the workspace, the repository, and the deployment. The value the step sees is pipeline, then deployment, then repository, then workspace, then the default Bitbucket sets. Deployment variables are present on a step or stage that selected that environment, whether I selected it with `deployment:` or with `environment:`. A test step with neither key sees the repository value, if I was careless enough to set one. I have "fixed" a missing variable by promoting it to a repository variable. After that, every branch build had the production host.

Secured variables are masked in the log when the exact value appears. They are still expanded in the script. `set -x` and a value I then base64-encoded both got past the mask often enough that I stopped debugging that way. Secured variables cannot be passed into a child pipeline. The build fails. I stopped trying to be clever about it and read them only in the deployment step that needs them.

Workspace variables are injected into every repository in the workspace, for anyone with write access on that repo. I kept a shared read-only token there once. A personal sandbox repo in the same workspace received it on the next build. Shared belongs at the workspace when every repo in the workspace is allowed to have it.

## What the dashboard is for

The deployments view is the list of what went to production and who clicked. I use it on the night something is wrong, the way I use the GitHub environment history. The image digest in the task definition is still what production is running. Redeploy from that screen reruns the deployment step with the artifacts from that build, and those artifacts expire after 14 days. The redeploy permission was Premium on the workspaces where I had it. If the step cannot pull the image again by digest, the redeploy is a button that fails.

Branch restrictions and the list of people who can deploy live on the environment. I have reviewed a pull request that claimed to lock production by adding `trigger: manual` and nothing else. The lock is the environment. The YAML chooses it. How that choice shows up in an AWS role is [the OIDC note](./bitbucket-oidc-aws.md).
