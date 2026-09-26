# ECS

Notes on running services on Amazon ECS. They assume you already deploy containers and want the mechanics: what the scheduler does during a rollout, what `RUNNING` does and does not mean, and which settings decide whether a deploy drops traffic.

Read the four-part series first. The later notes use that model.

## The series

| Note | What's in it |
|---|---|
| [Part 1: fundamentals](./ecs-part-1-fundamentals.md) | Task definitions, tasks, and a Fargate app from a Dockerfile to a running service. |
| [Part 2: operations](./ecs-part-2-operations.md) | Services, logs, scaling, ECS Exec, deployments, and the failures you will actually debug. |
| [Part 3: ALB, networking, IAM](./ecs-part-3-deep-dives.md) | How a request reaches a task, the two health checks, `awsvpc`, and the kubectl mapping. |
| [Part 4: resource exhaustion](./ecs-part-4-resource-exhaustion.md) | OOM kills versus CPU throttling on Fargate, and how to reproduce each. |

## Deployments and health

| Note | What's in it |
|---|---|
| [Task health is not application health](./ecs-task-health-is-not-the-same-as-app-health.md) | `RUNNING` means the process started. What to check before a pipeline calls a deploy successful. |
| [Zero-downtime deployments](./ecs-zero-downtime-deployments.md) | Why a rolling deploy returns 503s, counted on a six-task service, and the clocks that have to agree. |
| [Deployment circuit breakers](./ecs-deployment-circuit-breakers.md) | Scheduler-side failure detection, rollback, and what the breaker does not catch. |

## Running a cluster

| Note | What's in it |
|---|---|
| [Reliability, part 1: building the cluster](./ecs-reliability-part1-building-the-cluster.md) | Launch type, AZs, capacity, placement, and the service settings you want before the first request. |
| [Reliability, part 2: keeping it alive](./ecs-reliability-part2-keeping-it-alive.md) | Metrics, alerts, the four common failure modes, and the day-2 routine. |
| [Task distribution and resource management](./ecs-task-distribution-guide.md) | How the scheduler places a task on EC2 and on Fargate. |
| [Cost and failure domains](./ecs-deep-dive-cost-and-failures.md) | Fargate versus EC2 on cost, and what an AZ failure does to a running service. |
| [CLI reference](./what-devops-engineers-should-understand-about-ecs.md) | Commands for clusters, services, tasks, logs, exec, and the kubectl equivalents. |
