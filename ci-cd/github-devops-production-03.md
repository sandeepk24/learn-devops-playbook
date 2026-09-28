# Fargate, alarms, and what you check when it will not start

[Part 1](./01_GITHUB_DEVOPS_FUNDAMENTALS.md) is the workflow and OIDC. [Part 2](./github-devops-implementation-02.md) is the image and the deploy job. This is the stack that job updates: two AZs, tasks in private subnets, an ALB in the public ones, a service that can roll back, and the alarms that tell you the rollback should have happened.

Two NAT gateways is the production default so one AZ does not take outbound with it. It is also the line item people are surprised by. If this is a dev account, one NAT is enough and you accept the AZ dependency. Do not learn that from the bill.

The task definition in this file uses `:latest`. The deploy workflow in part 2 replaces that with the commit SHA at deploy time. Leave `:latest` as the Terraform initial image and you will eventually apply Terraform and roll every task back to whatever `:latest` happens to be. Ignore changes on the task definition image, or stop managing the task definition revision from Terraform once CI owns it.

`deployment_maximum_percent` and `deployment_minimum_healthy_percent` are arguments on the service. The `deployment_configuration` block is for the strategy (`ROLLING`, `BLUE_GREEN`, `LINEAR`, `CANARY`), not for those percentages. Putting `maximum_percent` inside that block is an error on the current AWS provider. `minimum_healthy_percent = 100` and `maximum_percent = 200` is what keeps a load-balanced service from going to zero healthy targets during a deploy. Dropping the floor to 50 is how a small service serves traffic with half its tasks while the new ones are still booting.

## Complete Terraform Infrastructure

### VPC and Networking

**terraform/vpc.tf:**
```hcl
# Data source for availability zones
data "aws_availability_zones" "available" {
  state = "available"
}

# VPC
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.app_name}-vpc-${var.environment}"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.app_name}-igw-${var.environment}"
  }
}

# Public Subnets (for ALB)
resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.${count.index + 10}.0/24"
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.app_name}-public-subnet-${count.index + 1}-${var.environment}"
    Type = "Public"
  }
}

# Private Subnets (for ECS tasks)
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 1}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.app_name}-private-subnet-${count.index + 1}-${var.environment}"
    Type = "Private"
  }
}

# Elastic IPs for NAT Gateways
resource "aws_eip" "nat" {
  count  = 2
  domain = "vpc"

  tags = {
    Name = "${var.app_name}-nat-eip-${count.index + 1}-${var.environment}"
  }

  depends_on = [aws_internet_gateway.main]
}

# NAT Gateways (for outbound internet access from private subnets)
resource "aws_nat_gateway" "main" {
  count         = 2
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${var.app_name}-nat-${count.index + 1}-${var.environment}"
  }

  depends_on = [aws_internet_gateway.main]
}

# Public Route Table
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.app_name}-public-rt-${var.environment}"
  }
}

# Private Route Tables (one per AZ)
resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = {
    Name = "${var.app_name}-private-rt-${count.index + 1}-${var.environment}"
  }
}

# Route Table Associations
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}
```

### Security Groups

**terraform/security.tf:**
```hcl
# ALB Security Group
resource "aws_security_group" "alb" {
  name        = "${var.app_name}-alb-sg-${var.environment}"
  description = "Security group for Application Load Balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP from anywhere"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS from anywhere"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-alb-sg-${var.environment}"
  }
}

# ECS Tasks Security Group
resource "aws_security_group" "ecs_tasks" {
  name        = "${var.app_name}-ecs-tasks-sg-${var.environment}"
  description = "Security group for ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Allow traffic from ALB"
    from_port       = var.app_port
    to_port         = var.app_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.app_name}-ecs-tasks-sg-${var.environment}"
  }
}
```

### Application Load Balancer

**terraform/alb.tf:**
```hcl
# Application Load Balancer
resource "aws_lb" "main" {
  name               = "${var.app_name}-alb-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id

  enable_deletion_protection       = var.environment == "production" ? true : false
  enable_http2                     = true
  enable_cross_zone_load_balancing = true
  idle_timeout                     = 60

  tags = {
    Name = "${var.app_name}-alb-${var.environment}"
  }
}

# Target Group
resource "aws_lb_target_group" "app" {
  name        = "${var.app_name}-tg-${var.environment}"
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = var.health_check_path
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 3
  }

  deregistration_delay = 30

  tags = {
    Name = "${var.app_name}-tg-${var.environment}"
  }
}

# HTTP Listener
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}

# HTTPS Listener (uncomment and configure ACM certificate)
# resource "aws_lb_listener" "https" {
#   load_balancer_arn = aws_lb.main.arn
#   port              = "443"
#   protocol          = "HTTPS"
#   ssl_policy        = "ELBSecurityPolicy-TLS-1-2-2017-01"
#   certificate_arn   = var.certificate_arn
#
#   default_action {
#     type             = "forward"
#     target_group_arn = aws_lb_target_group.app.arn
#   }
# }
```

### ECS Cluster and Service

**terraform/ecs.tf:**
```hcl
# ECR Repository
resource "aws_ecr_repository" "app" {
  name                 = var.app_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.app_name}-ecr-${var.environment}"
  }
}

# ECR Lifecycle Policy
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        description  = "Remove untagged images after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${var.app_name}-${var.environment}"
  retention_in_days = 7

  tags = {
    Name = "${var.app_name}-logs-${var.environment}"
  }
}

# ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "${var.app_name}-cluster-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.app.name
      }
    }
  }

  tags = {
    Name = "${var.app_name}-cluster-${var.environment}"
  }
}

# ECS Cluster Capacity Providers
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 4
  }
}

# ECS Task Definition
resource "aws_ecs_task_definition" "app" {
  family                   = "${var.app_name}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.fargate_cpu
  memory                   = var.fargate_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name      = var.app_name
      image     = "${aws_ecr_repository.app.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = var.app_port
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "ENVIRONMENT"
          value = var.environment
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "PORT"
          value = tostring(var.app_port)
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.app.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:${var.app_port}${var.health_check_path} || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  tags = {
    Name = "${var.app_name}-task-def-${var.environment}"
  }
}

# ECS Service
resource "aws_ecs_service" "app" {
  name            = "${var.app_name}-service-${var.environment}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.app.arn
  desired_count   = var.app_count

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
    base              = 1
  }

  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 4
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.app.arn
    container_name   = var.app_name
    container_port   = var.app_port
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  enable_execute_command = true

  depends_on = [aws_lb_listener.http]

  tags = {
    Name = "${var.app_name}-service-${var.environment}"
  }
}

# Auto Scaling Target
resource "aws_appautoscaling_target" "ecs" {
  max_capacity       = 10
  min_capacity       = var.app_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.app.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

# Auto Scaling Policy - CPU
resource "aws_appautoscaling_policy" "ecs_cpu" {
  name               = "${var.app_name}-cpu-scaling-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# Auto Scaling Policy - Memory
resource "aws_appautoscaling_policy" "ecs_memory" {
  name               = "${var.app_name}-memory-scaling-${var.environment}"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value       = 80.0
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
```

### IAM Roles

**terraform/iam.tf:**
```hcl
# ECS Task Execution Role
resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.app_name}-ecs-task-execution-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.app_name}-ecs-task-execution-${var.environment}"
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ECS Task Role
resource "aws_iam_role" "ecs_task" {
  name = "${var.app_name}-ecs-task-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name = "${var.app_name}-ecs-task-${var.environment}"
  }
}

# Task role policies (customize based on your app needs)
resource "aws_iam_role_policy" "ecs_task_cloudwatch" {
  name = "cloudwatch-logs"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.app.arn}:*"
      }
    ]
  })
}
```

### Outputs

**terraform/outputs.tf:**
```hcl
output "alb_dns_name" {
  description = "DNS name of the load balancer"
  value       = aws_lb.main.dns_name
}

output "alb_url" {
  description = "URL of the application"
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecr_repository_url" {
  description = "ECR repository URL"
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "ECS service name"
  value       = aws_ecs_service.app.name
}

output "cloudwatch_log_group" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.app.name
}
```

---

## Fargate and Fargate Spot

| | Fargate | Fargate Spot |
|---|---|---|
| Price | On-demand vCPU and memory | Discount, often large, not a contract |
| Interruption | No | Two-minute SIGTERM, then the task is gone |
| SLA | The Fargate SLA | None |
| Put it under | The request path | Workers, batch, extra capacity behind a base of on-demand |

### What 0.5 vCPU and 1 GB costs if it runs all month

Prices move. Check the region before you quote these. The shape of the comparison does not.

```
Fargate Regular:
- vCPU: 0.5 × $0.04048 = $0.02024/hour
- Memory: 1 × $0.004445 = $0.004445/hour
- Total: $0.024685/hour
- Monthly: $0.024685 × 730 hours = $18.02/month

Fargate Spot (70% discount):
- Total: $0.024685 × 0.30 = $0.007406/hour
- Monthly: $0.007406 × 730 hours = $5.41/month
- Savings: $12.61/month (70%)
```

### Capacity providers

`base = 1` on FARGATE means one on-demand task before any weight is applied. Weight 1 and 4 after that is one on-demand for every four Spot, once you are past that base. That is a reasonable mix for a stateless API that can lose a task. It is a bad mix for a single-task service. Spot will take that task, and the two-minute warning is your outage.
```hcl
capacity_provider_strategy {
  capacity_provider = "FARGATE"
  weight            = 1
  base              = 1  # Always at least 1 regular Fargate task
}

capacity_provider_strategy {
  capacity_provider = "FARGATE_SPOT"
  weight            = 4  # 80% on Spot when scaling
}
```

### Handling Spot Interruptions

```python
# app/signals.py
import signal
import sys
import structlog

logger = structlog.get_logger()

def handle_sigterm(signum, frame):
    """
    Gracefully handle SIGTERM from Fargate Spot interruption.
    AWS gives 120 seconds notice before termination.
    """
    logger.warning(
        "received_sigterm",
        message="Fargate Spot interruption - initiating graceful shutdown",
        signal=signum
    )
    
    # 1. Stop accepting new requests
    # 2. Finish processing current requests
    # 3. Close database connections
    # 4. Flush logs
    # 5. Exit cleanly
    
    sys.exit(0)

# Register signal handler
signal.signal(signal.SIGTERM, handle_sigterm)
```

---

## Monitoring and Observability

### CloudWatch Dashboards

**terraform/monitoring.tf:**
```hcl
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.app_name}-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ECS", "CPUUtilization", {
              stat   = "Average"
              period = 300
            }],
            [".", "MemoryUtilization", {
              stat   = "Average"
              period = 300
            }]
          ]
          region = var.aws_region
          title  = "ECS Resource Utilization"
          period = 300
          yAxis = {
            left = {
              min = 0
              max = 100
            }
          }
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", {
              stat   = "Average"
              period = 60
            }],
            [".", "RequestCount", {
              stat   = "Sum"
              period = 60
            }]
          ]
          region = var.aws_region
          title  = "ALB Performance"
          period = 60
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          metrics = [
            ["AWS/ApplicationELB", "HTTPCode_Target_2XX_Count", {
              stat   = "Sum"
              period = 60
            }],
            [".", "HTTPCode_Target_4XX_Count", {
              stat   = "Sum"
              period = 60
            }],
            [".", "HTTPCode_Target_5XX_Count", {
              stat   = "Sum"
              period = 60
            }]
          ]
          region = var.aws_region
          title  = "HTTP Response Codes"
          period = 60
        }
      }
    ]
  })
}
```

### CloudWatch Alarms

```hcl
# SNS Topic for Alerts
resource "aws_sns_topic" "alerts" {
  name = "${var.app_name}-alerts-${var.environment}"

  tags = {
    Name = "${var.app_name}-alerts-${var.environment}"
  }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "devops@example.com"
}

# High CPU Alarm
resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "${var.app_name}-cpu-high-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "CPUUtilization"
  namespace           = "AWS/ECS"
  period              = "300"
  statistic           = "Average"
  threshold           = "80"
  alarm_description   = "ECS CPU utilization is too high"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.app.name
  }
}

# High Memory Alarm
resource "aws_cloudwatch_metric_alarm" "memory_high" {
  alarm_name          = "${var.app_name}-memory-high-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = "300"
  statistic           = "Average"
  threshold           = "85"
  alarm_description   = "ECS memory utilization is too high"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.app.name
  }
}

# High 5XX Error Rate
resource "aws_cloudwatch_metric_alarm" "http_5xx_high" {
  alarm_name          = "${var.app_name}-5xx-high-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "2"
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = "300"
  statistic           = "Sum"
  threshold           = "10"
  alarm_description   = "High 5XX error rate detected"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }
}

# Unhealthy Hosts
resource "aws_cloudwatch_metric_alarm" "unhealthy_hosts" {
  alarm_name          = "${var.app_name}-unhealthy-hosts-${var.environment}"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = "60"
  statistic           = "Average"
  threshold           = "0"
  alarm_description   = "Unhealthy hosts detected"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }
}
```

---

## Cost Optimization

### 1. Scheduled Scaling for Predictable Traffic

```hcl
# Scale down during off-hours
resource "aws_appautoscaling_scheduled_action" "scale_down_night" {
  name               = "${var.app_name}-scale-down-night"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = "ecs:service:DesiredCount"
  schedule           = "cron(0 22 * * ? *)"  # 10 PM UTC

  scalable_target_action {
    min_capacity = 1
    max_capacity = 3
  }
}

# Scale up for business hours
resource "aws_appautoscaling_scheduled_action" "scale_up_morning" {
  name               = "${var.app_name}-scale-up-morning"
  service_namespace  = "ecs"
  resource_id        = aws_appautoscaling_target.ecs.resource_id
  scalable_dimension = "ecs:service:DesiredCount"
  schedule           = "cron(0 6 * * ? *)"  # 6 AM UTC

  scalable_target_action {
    min_capacity = 3
    max_capacity = 10
  }
}
```

### 2. Right-Sizing Containers

```bash
# Analyze actual resource usage
aws cloudwatch get-metric-statistics \
  --namespace AWS/ECS \
  --metric-name CPUUtilization \
  --dimensions Name=ServiceName,Value=myapp-service Name=ClusterName,Value=production-cluster \
  --start-time 2024-01-01T00:00:00Z \
  --end-time 2024-01-08T00:00:00Z \
  --period 3600 \
  --statistics Average,Maximum

# If consistently under 50% CPU, consider downsizing
```

### 3. Cost Monitoring

```hcl
# Cost and Usage Budget
resource "aws_budgets_budget" "ecs_monthly" {
  name              = "${var.app_name}-ecs-monthly-budget"
  budget_type       = "COST"
  limit_amount      = "100"
  limit_unit        = "USD"
  time_period_start = "2024-01-01_00:00"
  time_unit         = "MONTHLY"

  cost_filters = {
    Service = "Amazon Elastic Container Service"
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = ["devops@example.com"]
  }
}
```

---

## Troubleshooting Guide

### Common Issues

#### 1. Service Not Starting

**Symptoms:** Tasks fail to start or keep restarting

**Diagnosis:**
```bash
# Check service events
aws ecs describe-services \
  --cluster production-cluster \
  --services myapp-service \
  --query 'services[0].events[0:10]' \
  --output table

# Check task stopped reason
aws ecs list-tasks \
  --cluster production-cluster \
  --service-name myapp-service \
  --desired-status STOPPED

aws ecs describe-tasks \
  --cluster production-cluster \
  --tasks <task-arn> \
  --query 'tasks[0].{StoppedReason:stoppedReason,Containers:containers[0].reason}'
```

**Common Causes & Fixes:**

| Issue | Cause | Solution |
|-------|-------|----------|
| `CannotPullContainerError` | ECR permissions | Check task execution role has ECR access |
| `Essential container exited` | Application crash | Check CloudWatch logs for errors |
| `Health check failed` | App not responding | Verify health endpoint works |
| `Resource unavailable` | Insufficient capacity | Try different AZ or use Fargate regular |

#### 2. Health Check Failures

**Fix Health Endpoint:**
```python
@app.get("/health")
async def health_check():
    # Always return quickly (< 5 seconds)
    # Don't check external dependencies in health checks
    return {"status": "healthy"}

@app.get("/ready")
async def readiness_check():
    # Check dependencies here (database, redis, etc.)
    try:
        await db.execute("SELECT 1")
        return {"status": "ready"}
    except Exception:
        raise HTTPException(status_code=503, detail="Not ready")
```

#### 3. OIDC Authentication Errors

**Error:** "AssumeRoleWithWebIdentity failed"

**Diagnosis:**
```bash
# Check OIDC provider exists
aws iam list-open-id-connect-providers

# Check role trust policy
aws iam get-role --role-name GitHubActionsDeployRole \
  --query 'Role.AssumeRolePolicyDocument'
```

**Fix:** Ensure trust policy matches your repository:
```json
{
  "StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:your-org/your-repo:*"
  }
}
```

#### 4. Deployment Stuck

**Issue:** New deployment not progressing

**Quick Fix:**
```bash
# Force new deployment
aws ecs update-service \
  --cluster production-cluster \
  --service myapp-service \
  --force-new-deployment

# If still stuck, scale to 0 and back
aws ecs update-service \
  --cluster production-cluster \
  --service myapp-service \
  --desired-count 0

# Wait 30 seconds
sleep 30

aws ecs update-service \
  --cluster production-cluster \
  --service myapp-service \
  --desired-count 3
```

### Debugging Commands

```bash
# View real-time logs
aws logs tail /ecs/myapp-production --follow

# Execute command in running container
aws ecs execute-command \
  --cluster production-cluster \
  --task <task-id> \
  --container app \
  --command "/bin/sh" \
  --interactive

# Get task details
aws ecs describe-tasks \
  --cluster production-cluster \
  --tasks <task-arn> \
  --output json | jq '.tasks[0]'

# Check security group rules
aws ec2 describe-security-groups \
  --group-ids sg-xxx \
  --query 'SecurityGroups[0].IpPermissions'
```

---

## Advanced Deployment Patterns

### Blue/Green Deployment with CodeDeploy

```hcl
# Two target groups for blue/green
resource "aws_lb_target_group" "blue" {
  name        = "${var.app_name}-blue-${var.environment}"
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  # ... health check configuration
}

resource "aws_lb_target_group" "green" {
  name        = "${var.app_name}-green-${var.environment}"
  port        = var.app_port
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  # ... health check configuration
}

# CodeDeploy application
resource "aws_codedeploy_app" "app" {
  compute_platform = "ECS"
  name             = "${var.app_name}-${var.environment}"
}

# CodeDeploy deployment group
resource "aws_codedeploy_deployment_group" "app" {
  app_name               = aws_codedeploy_app.app.name
  deployment_config_name = "CodeDeployDefault.ECSAllAtOnce"
  deployment_group_name  = "${var.app_name}-dg-${var.environment}"
  service_role_arn       = aws_iam_role.codedeploy.arn

  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]
  }

  blue_green_deployment_config {
    deployment_ready_option {
      action_on_timeout = "CONTINUE_DEPLOYMENT"
    }

    terminate_blue_instances_on_deployment_success {
      action                           = "TERMINATE"
      termination_wait_time_in_minutes = 5
    }
  }

  deployment_style {
    deployment_option = "WITH_TRAFFIC_CONTROL"
    deployment_type   = "BLUE_GREEN"
  }

  ecs_service {
    cluster_name = aws_ecs_cluster.main.name
    service_name = aws_ecs_service.app.name
  }

  load_balancer_info {
    target_group_pair_info {
      prod_traffic_route {
        listener_arns = [aws_lb_listener.http.arn]
      }

      target_group {
        name = aws_lb_target_group.blue.name
      }

      target_group {
        name = aws_lb_target_group.green.name
      }
    }
  }
}
```

---

The service is not done when `terraform apply` goes green. It is done when a bad deploy rolls back on its own, the 5xx alarm pages a person, and you can read the task logs without SSHing anywhere. The workflows that push the image are in [part 2](./github-devops-implementation-02.md). The role they assume is in [part 1](./01_GITHUB_DEVOPS_FUNDAMENTALS.md).

- [ECS best practices](https://docs.aws.amazon.com/AmazonECS/latest/bestpracticesguide/)
- [GitHub Actions](https://docs.github.com/en/actions)
- [AWS provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)
