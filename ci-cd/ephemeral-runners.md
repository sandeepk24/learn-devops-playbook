# Ephemeral runners

GitHub-hosted runners are a new machine per job. Use them until you have a constraint they cannot meet: a private network, a licensed build tool, a GPU, or an allow-listed egress IP. A self-hosted runner exists for that constraint. It should still live for one job.

GitHub's guidance on autoscaling is the same rule. Persistent runners are not recommended, because a job can be assigned while the machine is shutting down. An ephemeral runner accepts one job and then deregisters. The next job gets a machine that did not run the previous job.

## What survives on a persistent runner

The workspace, the tool cache, Docker images, and whatever a step wrote outside `_work`. A job that dumps an environment to a file in `$HOME` leaves it for the next job. A job that is compromised is resident until someone rebuilds the host. Labels make this worse. A self-hosted runner tagged `ubuntu-latest` can take jobs that the author thought were GitHub-hosted.

Register with `--ephemeral` if you are not on a scale set. The service deregisters the runner after one job. Your automation deletes the VM or the container. If the automation reuses the disk, you have built a persistent runner with extra steps.

```bash
./config.sh --url https://github.com/your-org/your-repo --token "$RUNNER_TOKEN" --ephemeral --labels private-build
./run.sh
```

The token from the registration UI is short-lived. Put it in the boot script from your secret store. A token baked into an AMI is a runner anyone who can read the image can register.

## Scale sets

On Kubernetes, Actions Runner Controller is the implementation GitHub documents. You install the scale set chart. The installation name is what `runs-on` selects.

```yaml
jobs:
  build:
    runs-on: arc-runner-set
    steps:
      - uses: actions/checkout@v4
      - run: make build
```

The listener patches an ephemeral runner set. Each runner pod gets a just-in-time config, runs one job, and is deleted. `minRunners: 0` scales to nothing when the queue is empty. Cold start is the cost. A warm minimum is for a suite that cannot wait for image pull, and those idle pods are still one-job runners, not a shared build box.

Run the scale set in its own cluster, or at least its own node pool, away from production workloads. A workflow runs arbitrary code. Sharing a node with the service you deploy means a job can see the node's network, and sometimes the node's IAM role.

Keep the controller logs and the runner logs. The pod is gone when you want them. The controller exposes `gha_controller_failed_ephemeral_runners`. Alert on that before you alert on queue time. A failed runner looks like a stuck job.

`runs-on` must be the scale set name or a label you set on that set. A job with no matching runner waits until GitHub gives up. It does not fall back to a GitHub-hosted runner.

## The role on the machine

An instance profile or a node role is shared by every job that lands there. Any workflow allowed to use the runner can call AWS as that role. I do not put the deploy role on the runner. The job assumes a role with OIDC, and the trust policy names the workflow file. That split is [the Actions note](./01_GITHUB_DEVOPS_FUNDAMENTALS.md). The runner's own role can pull its image and write logs. It cannot register a task definition.

Org-level runners belong to a runner group limited to the repositories that need the private network. A public repository on an org runner with a path to production is a job anyone can schedule by opening a pull request, subject to your fork approval settings. Private, internal, and the group restriction are the controls. "We trust the workflow" is not a control if the workflow can be changed by the people you do not mean to trust. Who can change it is [the workflow file](./workflow-is-production.md).

## GitLab

A GitLab shared runner on GitLab.com gives the job a fresh container. A project runner with the shell executor on a long-lived VM is the persistent case: the next job inherits packages, files, and environment from the last one. The Docker executor is closer to one container per job, and the host underneath still accumulates images and still has the Docker socket if you mounted it.

Use the Docker or Kubernetes executor. Set `run-untagged` off so a job that forgot its tags does not land on the production builder. The registration flow is in [GitLab CI](./gitlab-cicd-101.md). The part that matters here is that the runner process and the job's filesystem are not the same lifetime.

## When the hosted runner is enough

Most application pipelines fit on GitHub-hosted or GitLab-hosted runners. The minute quota and the cold cache are cheaper than a fleet you have to patch. Move a job off the hosted runner when you can name the constraint. Write the constraint in the pull request that adds the scale set. A runner fleet without that sentence becomes the default, and then every job, including the fork you did not review, is a guest on your network.
