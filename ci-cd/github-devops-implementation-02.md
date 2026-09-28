# The application, the image, and the workflows

[Part 1](./01_GITHUB_DEVOPS_FUNDAMENTALS.md) is OIDC, environments, and why the pipeline is ordered the way it is. This note is the code those workflows build and ship: a small FastAPI service, an image that does not run as root, CI that can fail, and a deploy that registers a new ECS task definition. [Part 3](./github-devops-production-03.md) is the VPC, the service, and the alarms.

The health endpoint below reports the database and Redis as ok without checking them. That is a stub. Do not ship it. A health check that always returns 200 will keep a broken task in the target group. Liveness stays cheap. Readiness is where the dependency checks go.

The security job installs `safety` and `bandit` and then ignores their exit codes with `|| true`. That is useful the week you are collecting a baseline. It is not a gate. Remove the `|| true` when a finding should block the merge.

## Application Code

### Project Structure

```
myapp/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration management
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── health.py
│   │   └── api.py
│   └── utils/
│       ├── __init__.py
│       └── logging.py
├── tests/
│   ├── __init__.py
│   ├── test_api.py
│   ├── test_health.py
│   └── conftest.py
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── terraform/
├── Dockerfile
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

### FastAPI Application

**app/main.py:**
```python
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import os
import time

from app.routes import health, api
from app.utils.logging import configure_logging

# Configure structured logging
configure_logging()
logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="MyApp API",
    version="1.0.0",
    description="Production-ready FastAPI application for AWS ECS deployment"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    response = await call_next(request)
    
    duration = time.time() - start_time
    logger.info(
        "http_request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration * 1000, 2),
        client_ip=request.client.host
    )
    
    return response

# Include routers
app.include_router(health.router)
app.include_router(api.router, prefix="/api/v1")

@app.get("/")
async def root():
    """Root endpoint"""
    logger.info("root_endpoint_accessed", environment=os.getenv("ENVIRONMENT"))
    return {
        "message": "Welcome to MyApp API",
        "version": "1.0.0",
        "environment": os.getenv("ENVIRONMENT", "unknown")
    }

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
        method=request.method
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_config=None  # Use our custom logging config
    )
```

**app/config.py:**
```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Application
    environment: str = "development"
    debug: bool = False
    port: int = 8000
    
    # Database
    database_url: str = "postgresql://localhost/myapp"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # AWS
    aws_region: str = "us-east-1"
    
    # CORS
    allowed_origins: str = "*"
    
    # Logging
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
```

**app/routes/health.py:**
```python
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
import structlog

router = APIRouter(tags=["health"])
logger = structlog.get_logger()

@router.get("/health")
async def health_check():
    """
    Health check endpoint for AWS ALB target group.
    Returns 200 if service is healthy, 503 if unhealthy.
    """
    try:
        # Add dependency checks here
        # Example: await db.execute("SELECT 1")
        # Example: await redis.ping()
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "healthy",
                "checks": {
                    "database": "ok",
                    "redis": "ok"
                }
            }
        )
    except Exception as e:
        logger.error("health_check_failed", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error": str(e)
            }
        )

@router.get("/readiness")
async def readiness_check():
    """Readiness probe for Kubernetes/ECS"""
    return {"status": "ready"}

@router.get("/liveness")
async def liveness_check():
    """Liveness probe for Kubernetes/ECS"""
    return {"status": "alive"}
```

**app/routes/api.py:**
```python
from fastapi import APIRouter, HTTPException
import structlog

router = APIRouter(tags=["api"])
logger = structlog.get_logger()

@router.get("/data")
async def get_data():
    """Sample API endpoint"""
    logger.info("data_endpoint_accessed")
    
    # Your business logic here
    data = {
        "items": [
            {"id": 1, "name": "Item 1"},
            {"id": 2, "name": "Item 2"},
            {"id": 3, "name": "Item 3"}
        ]
    }
    
    return data

@router.get("/data/{item_id}")
async def get_item(item_id: int):
    """Get specific item by ID"""
    logger.info("item_endpoint_accessed", item_id=item_id)
    
    if item_id > 100:
        raise HTTPException(status_code=404, detail="Item not found")
    
    return {"id": item_id, "name": f"Item {item_id}"}
```

**app/utils/logging.py:**
```python
import structlog
import logging
import sys

def configure_logging():
    """Configure structured logging with JSON output"""
    
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )
```

**requirements.txt:**
```txt
fastapi==0.109.0
uvicorn[standard]==0.27.0
pydantic==2.5.3
pydantic-settings==2.1.0
structlog==24.1.0
python-json-logger==2.0.7
```

**requirements-dev.txt:**
```txt
pytest==7.4.4
pytest-cov==4.1.0
pytest-asyncio==0.23.3
httpx==0.26.0
black==24.1.1
ruff==0.1.14
mypy==1.8.0
bandit==1.7.6
safety==3.0.1
```

### Test Suite

**tests/conftest.py:**
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

@pytest.fixture
def client():
    """FastAPI test client"""
    return TestClient(app)
```

**tests/test_health.py:**
```python
def test_health_check(client):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_readiness_check(client):
    """Test readiness endpoint"""
    response = client.get("/readiness")
    assert response.status_code == 200

def test_liveness_check(client):
    """Test liveness endpoint"""
    response = client.get("/liveness")
    assert response.status_code == 200
```

**tests/test_api.py:**
```python
def test_root_endpoint(client):
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert "message" in response.json()

def test_get_data(client):
    """Test data endpoint"""
    response = client.get("/api/v1/data")
    assert response.status_code == 200
    assert "items" in response.json()
    assert len(response.json()["items"]) > 0

def test_get_item(client):
    """Test get item by ID"""
    response = client.get("/api/v1/data/1")
    assert response.status_code == 200
    assert response.json()["id"] == 1

def test_get_item_not_found(client):
    """Test get non-existent item"""
    response = client.get("/api/v1/data/999")
    assert response.status_code == 404
```

---

## Docker Configuration

### Multi-Stage Dockerfile

**Dockerfile:**
```dockerfile
# Builder. Dependencies land in a venv we can copy.
# pip install --user writes to /root/.local, and /root is not
# readable by the user we drop to in the final stage.
FROM python:3.11-slim AS builder

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=1.0.0

LABEL org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.source="https://github.com/yourorg/myapp" \
      org.opencontainers.image.version=$VERSION \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.title="MyApp API"

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
COPY ./app /app/app

RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

EXPOSE 8000

HEALTHCHECK --interval=30s \
            --timeout=3s \
            --start-period=40s \
            --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**.dockerignore:**
```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
.venv/
*.egg-info/
dist/
build/

# Testing
.pytest_cache/
.coverage
htmlcov/
*.cover

# IDE
.vscode/
.idea/
*.swp
*.swo

# Git
.git/
.gitignore

# CI/CD
.github/

# Infrastructure
terraform/
*.tfstate
*.tfstate.backup

# Documentation
README.md
docs/

# Environment
.env
.env.local
```

---

## GitHub Actions Workflows

### Continuous Integration Workflow

**.github/workflows/ci.yml:**
```yaml
name: Continuous Integration

on:
  pull_request:
    branches: [main, develop]
  push:
    branches: [main, develop]

env:
  PYTHON_VERSION: '3.11'

jobs:
  lint:
    name: Code Quality Checks
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'
      
      - name: Install linting tools
        run: |
          pip install black ruff mypy isort
      
      - name: Check code formatting (Black)
        run: black --check --diff .
      
      - name: Check import sorting (isort)
        run: isort --check-only --diff .
      
      - name: Lint with Ruff
        run: ruff check . --output-format=github
      
      - name: Type checking (MyPy)
        run: mypy app/ --ignore-missing-imports

  test:
    name: Run Tests
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: testdb
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432
      
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: 'pip'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt
      
      - name: Run unit tests with coverage
        env:
          DATABASE_URL: postgresql://postgres:postgres@localhost:5432/testdb
          REDIS_URL: redis://localhost:6379/0
        run: |
          pytest tests/ \
            --cov=app \
            --cov-report=xml \
            --cov-report=html \
            --cov-report=term-missing \
            --junitxml=pytest-report.xml \
            --verbose
      
      - name: Upload coverage reports
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          flags: unittests
          name: codecov-umbrella
      
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: |
            pytest-report.xml
            htmlcov/

  security:
    name: Security Scanning
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      
      - name: Install security tools
        run: pip install safety bandit
      
      - name: Check dependencies for vulnerabilities
        run: |
          pip install -r requirements.txt
          safety check --json || true
      
      - name: Run Bandit security linter
        run: bandit -r app/ -f json -o bandit-report.json || true
      
      - name: Scan for secrets
        uses: trufflesecurity/trufflehog@main
        with:
          path: ./
          base: ${{ github.event.repository.default_branch }}
          head: HEAD
      
      - name: Upload security reports
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: security-reports
          path: |
            bandit-report.json

  build:
    name: Build Docker Image
    runs-on: ubuntu-latest
    needs: [lint, test, security]
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Build Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: false
          tags: myapp:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            BUILD_DATE=${{ github.event.head_commit.timestamp }}
            VCS_REF=${{ github.sha }}
      
      - name: Run Trivy vulnerability scanner
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: myapp:${{ github.sha }}
          format: 'sarif'
          output: 'trivy-results.sarif'
          severity: 'CRITICAL,HIGH'
      
      - name: Upload Trivy results to GitHub Security
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: 'trivy-results.sarif'
```

### Deployment Workflow

**.github/workflows/deploy.yml:**
```yaml
name: Deploy to AWS ECS

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      environment:
        description: 'Environment to deploy to'
        required: true
        default: 'staging'
        type: choice
        options:
          - staging
          - production

env:
  AWS_REGION: us-east-1
  ECR_REPOSITORY: myapp
  ECS_CLUSTER: production-cluster
  ECS_SERVICE: myapp-service
  CONTAINER_NAME: app

jobs:
  deploy:
    name: Deploy to ${{ github.event.inputs.environment || 'production' }}
    runs-on: ubuntu-latest
    environment: 
      name: ${{ github.event.inputs.environment || 'production' }}
      url: https://api.example.com
    
    permissions:
      id-token: write   # Required for OIDC
      contents: read
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Configure AWS credentials via OIDC
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
          role-session-name: GitHubActions-Deploy-${{ github.run_id }}
      
      - name: Login to Amazon ECR
        id: login-ecr
        uses: aws-actions/amazon-ecr-login@v2
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Build, tag, and push image to ECR
        id: build-image
        env:
          ECR_REGISTRY: ${{ steps.login-ecr.outputs.registry }}
          IMAGE_TAG: ${{ github.sha }}
        run: |
          # Build for linux/amd64 platform
          docker buildx build \
            --platform linux/amd64 \
            --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
            --build-arg VCS_REF=${{ github.sha }} \
            --build-arg VERSION=${{ github.ref_name }} \
            -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG \
            -t $ECR_REGISTRY/$ECR_REPOSITORY:latest \
            --push \
            .
          
          echo "image=$ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG" >> $GITHUB_OUTPUT
      
      - name: Download current task definition
        run: |
          aws ecs describe-task-definition \
            --task-definition ${{ env.ECS_SERVICE }} \
            --query taskDefinition \
            > task-definition.json
          
          # Clean up fields that can't be used in RegisterTaskDefinition
          cat task-definition.json | \
            jq 'del(
              .taskDefinitionArn,
              .revision,
              .status,
              .requiresAttributes,
              .compatibilities,
              .registeredAt,
              .registeredBy
            )' > task-def-clean.json
      
      - name: Update task definition with new image
        id: task-def
        uses: aws-actions/amazon-ecs-render-task-definition@v1
        with:
          task-definition: task-def-clean.json
          container-name: ${{ env.CONTAINER_NAME }}
          image: ${{ steps.build-image.outputs.image }}
      
      - name: Deploy updated task definition to ECS
        uses: aws-actions/amazon-ecs-deploy-task-definition@v1
        with:
          task-definition: ${{ steps.task-def.outputs.task-definition }}
          service: ${{ env.ECS_SERVICE }}
          cluster: ${{ env.ECS_CLUSTER }}
          wait-for-service-stability: true
          wait-for-minutes: 10
      
      - name: Verify deployment
        run: |
          echo "Image: ${{ steps.build-image.outputs.image }}"
          echo "Cluster: ${{ env.ECS_CLUSTER }}"
          echo "Service: ${{ env.ECS_SERVICE }}"
          echo "Region: ${{ env.AWS_REGION }}"

          aws ecs describe-services \
            --cluster ${{ env.ECS_CLUSTER }} \
            --services ${{ env.ECS_SERVICE }} \
            --query 'services[0].{
              Running:runningCount,
              Desired:desiredCount,
              Pending:pendingCount,
              Status:status
            }' \
            --output table
      
      - name: Create deployment summary
        run: |
          cat >> $GITHUB_STEP_SUMMARY <<EOF
          ## Deployment

          **Environment:** ${{ github.event.inputs.environment || 'production' }}

          | Detail | Value |
          |--------|-------|
          | Image | \`${{ steps.build-image.outputs.image }}\` |
          | Cluster | ${{ env.ECS_CLUSTER }} |
          | Service | ${{ env.ECS_SERVICE }} |
          | Region | ${{ env.AWS_REGION }} |
          | Deployed by | @${{ github.actor }} |
          | Commit | ${{ github.sha }} |

          [Service in the console](https://console.aws.amazon.com/ecs/v2/clusters/${{ env.ECS_CLUSTER }}/services/${{ env.ECS_SERVICE }})
          EOF

  smoke-test:
    name: Post-Deployment Smoke Tests
    needs: deploy
    runs-on: ubuntu-latest
    
    steps:
      - name: Wait for service stabilization
        run: sleep 30
      
      - name: Test health endpoint
        run: |
          ENDPOINT="https://api.example.com"
          
          echo "Testing health endpoint..."
          RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" $ENDPOINT/health)
          
          if [ $RESPONSE -eq 200 ]; then
            echo "Health check passed (HTTP $RESPONSE)"
          else
            echo "Health check failed (HTTP $RESPONSE)"
            exit 1
          fi
      
      - name: Test API endpoints
        run: |
          ENDPOINT="https://api.example.com"
          
          echo "Testing root endpoint..."
          curl -f $ENDPOINT/ || exit 1
          
          echo "Testing API endpoint..."
          curl -f $ENDPOINT/api/v1/data || exit 1
          
          echo "Smoke tests passed"

  rollback:
    name: Automatic Rollback
    needs: [deploy, smoke-test]
    if: failure()
    runs-on: ubuntu-latest
    
    permissions:
      id-token: write
      contents: read
    
    steps:
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_DEPLOY_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}
      
      - name: Rollback to previous task definition
        run: |
          echo "Rolling back to the previous task definition"
          
          # Get the current deployments
          DEPLOYMENTS=$(aws ecs describe-services \
            --cluster ${{ env.ECS_CLUSTER }} \
            --services ${{ env.ECS_SERVICE }} \
            --query 'services[0].deployments' \
            --output json)
          
          # Get the previous (stable) task definition
          PREVIOUS_TASK_DEF=$(echo $DEPLOYMENTS | jq -r '.[1].taskDefinition // empty')
          
          if [ -n "$PREVIOUS_TASK_DEF" ]; then
            echo "Rolling back to: $PREVIOUS_TASK_DEF"
            
            aws ecs update-service \
              --cluster ${{ env.ECS_CLUSTER }} \
              --service ${{ env.ECS_SERVICE }} \
              --task-definition $PREVIOUS_TASK_DEF \
              --force-new-deployment
            
            echo "Rollback requested: $PREVIOUS_TASK_DEF"
          else
            echo "No previous task definition to roll back to"
            exit 1
          fi
```

---

## Terraform Infrastructure

### Project Structure

```
terraform/
├── main.tf              # Main infrastructure
├── variables.tf         # Input variables
├── outputs.tf           # Output values
├── versions.tf          # Provider versions
├── vpc.tf              # Network infrastructure
├── ecs.tf              # ECS cluster and service
├── alb.tf              # Load balancer
├── iam.tf              # IAM roles
├── security.tf         # Security groups
└── monitoring.tf       # CloudWatch
```

### Main Configuration

**terraform/versions.tf:**
```hcl
terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  
  backend "s3" {
    bucket         = "myapp-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "terraform-lock"
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = var.app_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Repository  = "github.com/yourorg/myapp"
    }
  }
}
```

**terraform/variables.tf:**
```hcl
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, production)"
  type        = string
  default     = "production"
}

variable "app_name" {
  description = "Application name"
  type        = string
  default     = "myapp"
}

variable "app_port" {
  description = "Port exposed by the Docker container"
  type        = number
  default     = 8000
}

variable "app_count" {
  description = "Number of Docker containers to run"
  type        = number
  default     = 3
}

variable "fargate_cpu" {
  description = "Fargate instance CPU units (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 512
}

variable "fargate_memory" {
  description = "Fargate instance memory in MB (512, 1024, 2048, etc.)"
  type        = number
  default     = 1024
}

variable "health_check_path" {
  description = "Health check path for ALB"
  type        = string
  default     = "/health"
}
```

The Terraform here is the backend, the variables, and the provider tags. The VPC, the service, Fargate Spot, and the alarms are in [part 3](./github-devops-production-03.md).

The rollback job in the deploy workflow reads `services[0].deployments[1]` and assumes that entry is the previous stable task definition. During a deploy, ECS does not promise that order. Prefer the circuit breaker on the service (`rollback = true` in part 3), and keep a manual rollback that takes an explicit task definition ARN. Guessing the previous revision from a JSON array is how you roll forward.
