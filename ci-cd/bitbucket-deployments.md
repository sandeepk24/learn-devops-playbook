# Bitbucket deployment environments

A step that runs `./deploy.sh production` is a script with an argument. It will run anywhere, for anyone, with whatever variables happen to be in scope, and Bitbucket will record nothing about it except that a step ran.

A step with `deployment: production` is different. It is a row on the Deployments screen. It takes the environment lock. It sees the production variables. It can be refused by branch rules and by permissions. I treated those two things as the same for about a year, right up until a branch I had never intended to ship ran a script with `production` as an argument and Bitbucket had no reason to stop it, because as far as Bitbucket was concerned it was just a script.

## The names

Turn on Pipelines and three environments exist: `test`, `staging`, `production`. Lowercase. That casing matters, because the string in the YAML has to match the name on the settings screen exactly, and I once renamed one to `Production` in the UI while the YAML still said `production` and spent a while reading an error that was telling me the truth the whole time.

Order matters too. In a single pipeline the deployment steps go test, then staging, then production, which sounds like bureaucracy until you put production above staging by accident and the file is rejected before anything runs, at which point you realize the ordering rule just saved you from a pipeline that tests after it ships.

There is a second key now. `environment:`. It gives a step the environment's variables and its branch and admin checks without the dashboard row and without the lock, which is useful for exactly the steps that need production-shaped configuration but are not themselves the deploy, like a smoke test that reads the same API URL, and the settings live on the same screen as the deployment environments, so there is nothing new to configure.

Short version: `deployment:` ships. `environment:` borrows.

## Manual steps

`trigger: manual` parks the pipeline at that step until someone clicks. Not anyone. Someone with write access to the repo. And never as the first step, because a pipeline that starts paused is a pipeline that never starts.

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

Manual is a pause. It is not a permission. Anyone with write access can press the button, which I learned watching a new hire deploy to production because it was the next green button in the list, and the pipeline was doing exactly what I had told it to do, which was to wait for anybody.

Real restriction lives on the environment. Two controls, when the plan includes them. Who may deploy. Which branches may deploy. Both of those were Premium on the workspaces where I used them, and on a Standard workspace the only control I actually had was `trigger: manual`, which is worth knowing before you promise anyone that production is locked.

The symptom of a branch rule doing its job is a grayed-out deploy button. Hover it. It tells you the branch is not allowed. I have seen `develop` build a step called production with valid YAML and a green test run, and the environment refused it, which was the system working, not the system broken.

Schedules pause too. A midnight deploy to production becomes a paused step waiting for a human once the environment requires approval, and I have been paged by a stale staging the morning after because nobody mentioned that the schedule that used to ship now waits, so if you add approval to an environment that a schedule targets, tell the people who watch the schedule.

## One deployment per pipeline

Two steps in the same pipeline cannot both say `deployment: production`. Bitbucket rejects the file. That feels limiting the first time you need a migration and an app rollout to share the lock and the variables, and the answer is a stage, which holds one deployment across several steps.

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

Note the placement. A manual stage cannot be the first item in the pipeline, so the test step sits above it, and that is not decoration, it is a requirement, because a pipeline that opens with a paused stage would have no successful step before the pause and Bitbucket refuses to start there.

While one pipeline holds the environment, another pipeline aimed at the same environment waits. That wait used to sit there until a human resumed it. `concurrency-group` is the newer queue that moves on its own, one step at a time, first in first out, and it can sit on the same step as `deployment:` when you want both things at once: the dashboard row and a queue that does not need babysitting.

```yaml
- step:
    name: Production
    deployment: production
    concurrency-group: production
    script:
      - ./deploy.sh
```

Use the environment name as the group name. Keeps it obvious. A group name that means something else is a second naming scheme to remember, and nobody remembers it at 2 AM.

## Variables, and the order they win

A variable is just a name and a value that shows up in the step as an environment variable, so `$API_URL` in the script is whatever Bitbucket injected for that step, and the for-beginners part is this: the same name can exist in several places at once, and Bitbucket picks one by a fixed order, every time, without warning you that the others exist.

The order, highest priority first:

1. Pipeline variables, set for one specific run.
2. Deployment variables, for one environment.
3. Repository variables, for the whole repo.
4. Workspace variables, for every repo in the workspace.
5. Defaults Bitbucket provides, like `BITBUCKET_COMMIT`.

Deployment variables show up only on steps that selected that environment, through `deployment:` or through `environment:`. A test step with neither key does not see them. It sees the repository value, if some helpful person set one, and I have been that helpful person, promoting a missing production variable up to the repository level to "fix" a failing test step, after which every branch build in the repo carried the production database host, which worked right up until it did not.

Two variables worth knowing by name: `BITBUCKET_DEPLOYMENT_ENVIRONMENT` tells the step which environment it is in, and `BITBUCKET_DEPLOYMENT_ENVIRONMENT_UUID` is the same thing as an ID for API calls. Both exist only on deployment steps. A script that branches on the environment name without checking it is set will do something surprising on a non-deployment step, so I pass the environment explicitly or I check.

## Secured variables

Tick the secured box and Bitbucket encrypts the value and masks it in logs. That is real. It also has edges that have bitten me, so here they are in one place.

Masking matches the exact value. Transform it and the mask misses. `set -x` on a script that echoes the key prints the key. Base64-encoding it first and echoing that prints something the mask does not recognize, which is still the key, just wearing a costume. I stopped debugging deployment steps with tracing on.

Secured variables cannot be passed into a child pipeline. The build fails. Not a warning. A failure. I read them only in the deployment step that needs them and stopped trying to thread them through.

They cannot be used for YAML templating with `${{ }}` either. Templates expand before the step runs, from workspace, repository, and a few default variables, and secured values are excluded from that expansion on purpose, so a step image of `${{SECRET_IMAGE}}` will not resolve, and the error will not explain why in terms you recognize.

## Workspace variables

Workspace variables land in every repository in the workspace, for anyone with write access on each repo. Read that as an access statement, not a convenience statement, because it means a sandbox repo in the same workspace receives the same values as production on its next build, and I have watched a personal experiment repo print a shared read-only token that was scoped for exactly this kind of leak in every way except the one that mattered.

Shared belongs at the workspace level when every repo there is allowed to have it. Otherwise it lives at the repository or deployment level, narrower, closer to the step that needs it, and the sandbox never sees it.

## The dashboard, and what redeploy actually does

The Deployments screen is the history: what went where, from which pipeline, clicked by whom. On a bad night it answers the first question, which is what is running out there, the same way the GitHub environment history does, except it is not the source of truth for the running bytes. The task definition, the manifest, whatever the platform reads: that is what is running. The dashboard is the record of how it got there.

Redeploy reruns the deployment step from that build with that build's artifacts. Artifacts expire after 14 days. Past that, the button fails, and on the workspaces where I have had the permission, redeploy itself was gated, so a redeploy that "should just work" can be refused twice over: once by expiry, once by role.

Design for that. If the step pulls the image by digest from the registry, a redeploy fourteen months later still works, because the registry is the durable copy and the artifact was only ever the small stuff. If the step depends on the artifact holding the deployable, the redeploy is a button that fails, and you will discover it during the incident, which is the worst possible time to discover anything.

## The actual lock

Settings, not YAML. Branch restrictions, deployment permissions, the environment itself: those are configured on the environment screen, and the YAML only selects the environment by name, which means a pull request that adds `trigger: manual` and claims to lock production has added a pause, not a lock, and I have sent that pull request back with the comment that the lock is the environment and the YAML is just choosing it.

How that choice reaches AWS, through the deployment UUID inside an OIDC subject, is [the OIDC note](./bitbucket-oidc-aws.md). Read the trust policy section there with this note open. They are the same decision in two places.
