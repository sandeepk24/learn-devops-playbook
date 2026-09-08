# 🚀 Python FastAPI — The Complete DevOps Engineer's Guide
### From Zero to Production-Grade APIs in the AI DevOps World

> **Who this is for:**  DevOps engineers picking up Python for the first time, and advanced DevOps engineers looking to build solid, production-ready APIs for infrastructure automation, AI pipelines, internal tooling, and microservices.

---

## Table of Contents

1. [Why FastAPI Matters in the DevOps World](#1-why-fastapi-matters-in-the-devops-world)
2. [Python Fundamentals You Must Know First](#2-python-fundamentals-you-must-know-first)
3. [FastAPI Basics — Your First API](#3-fastapi-basics--your-first-api)
4. [Request & Response Models with Pydantic](#4-request--response-models-with-pydantic)
5. [Path, Query, and Body Parameters](#5-path-query-and-body-parameters)
6. [HTTP Methods & Status Codes](#6-http-methods--status-codes)
7. [Dependency Injection](#7-dependency-injection)
8. [Authentication & Security](#8-authentication--security)
9. [Database Integration](#9-database-integration)
10. [Async Programming in FastAPI](#10-async-programming-in-fastapi)
11. [Background Tasks & Scheduling](#11-background-tasks--scheduling)
12. [Middleware](#12-middleware)
13. [File Uploads & Streaming](#13-file-uploads--streaming)
14. [WebSockets](#14-websockets)
15. [Testing FastAPI Applications](#15-testing-fastapi-applications)
16. [Structuring Large Projects](#16-structuring-large-projects)
17. [FastAPI in AI/ML DevOps Pipelines](#17-fastapi-in-aiml-devops-pipelines)
18. [Containerizing FastAPI with Docker](#18-containerizing-fastapi-with-docker)
19. [Kubernetes Deployment Patterns](#19-kubernetes-deployment-patterns)
20. [Observability — Logging, Metrics & Tracing](#20-observability--logging-metrics--tracing)
21. [CI/CD for FastAPI Applications](#21-cicd-for-fastapi-applications)
22. [Performance Tuning & Production Hardening](#22-performance-tuning--production-hardening)
23. [Senior-Level Patterns & Architecture](#23-senior-level-patterns--architecture)
24. [Quick Reference Cheatsheet](#24-quick-reference-cheatsheet)

---

## 1. Why FastAPI Matters in the DevOps World

Modern DevOps is no longer just Bash scripts and YAML files. The AI DevOps world demands that engineers build:

- **Internal APIs** — for infrastructure automation (triggering deployments, querying cluster states)
- **AI Model Serving** — exposing ML models as HTTP endpoints
- **Event-driven microservices** — Kafka consumers, webhook receivers, event routers
- **Data pipelines** — lightweight ingestion and transformation APIs
- **Observability backends** — custom metrics collectors and log processors

**FastAPI is the tool for all of this.** Here's why it dominates:

| Feature | FastAPI | Flask | Django REST |
|---|---|---|---|
| Performance | ⚡ Async-native | 🐢 Sync by default | 🐢 Sync by default |
| Auto Docs (Swagger) | ✅ Built-in | ❌ Plugin needed | ❌ Plugin needed |
| Type Safety | ✅ Pydantic v2 | ❌ Manual | ⚠️ Partial |
| Production Readiness | ✅ Yes | ⚠️ Setup needed | ✅ Yes |
| Learning Curve | 🟢 Low | 🟢 Low | 🔴 High |
| AI/ML Ecosystem Fit | ✅ Excellent | ⚠️ Okay | ⚠️ Okay |

> **The DevOps Reality:** FastAPI is used in production by Netflix, Uber, and Microsoft to serve ML models and internal tooling. It's the backbone of tools like LangServe (LangChain's serving layer) and is the de-facto standard for AI API development.

---

## 2. Python Fundamentals You Must Know First

Before diving in, these Python concepts are prerequisites. Master them.

### 2.1 Type Hints

FastAPI is built entirely on Python type hints. They are not optional.

```python
# Basic types
name: str = "devops-engineer"
port: int = 8080
is_healthy: bool = True
latency: float = 0.042

# Collections
servers: list[str] = ["node-1", "node-2"]
config: dict[str, str] = {"env": "prod", "region": "us-east-1"}

# Optional values (can be None)
from typing import Optional
replica_count: Optional[int] = None  # or: int | None (Python 3.10+)

# Union types
from typing import Union
status: Union[str, int] = "running"  # can be string or int
```

### 2.2 Async/Await

FastAPI is async-first. If you don't understand this, you'll write slow code.

```python
import asyncio

# Synchronous — blocks the thread
def fetch_metrics_sync():
    import time
    time.sleep(2)  # ❌ Blocks everything while waiting
    return {"cpu": 80}

# Asynchronous — yields control while waiting
async def fetch_metrics_async():
    await asyncio.sleep(2)  # ✅ Other requests can run during this wait
    return {"cpu": 80}

# Running an async function
async def main():
    result = await fetch_metrics_async()
    print(result)

asyncio.run(main())
```

### 2.3 Pydantic Basics (Data Validation)

```python
from pydantic import BaseModel, Field

class Server(BaseModel):
    hostname: str
    ip_address: str
    port: int = Field(default=22, ge=1, le=65535)  # ge=greater-equal, le=less-equal
    tags: list[str] = []

# Pydantic auto-validates on instantiation
server = Server(hostname="web-01", ip_address="10.0.0.1", port=443)
print(server.model_dump())  # {'hostname': 'web-01', 'ip_address': '10.0.0.1', 'port': 443, 'tags': []}

# This will raise a ValidationError
bad_server = Server(hostname="web-01", ip_address="10.0.0.1", port=99999)  # ❌ port > 65535
```

### 2.4 Decorators

FastAPI uses decorators heavily. You need to understand how they work.

```python
import functools

# A decorator wraps a function to add behavior
def require_auth(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Pre-logic: check auth
        print("Checking authentication...")
        result = func(*args, **kwargs)
        # Post-logic
        return result
    return wrapper

@require_auth
def deploy_service(name: str):
    print(f"Deploying {name}")

deploy_service("nginx")
# Output:
# Checking authentication...
# Deploying nginx
```

---

## 3. FastAPI Basics — Your First API

### Installation

```bash
# Core installation
pip install fastapi uvicorn

# With all optional extras (recommended for production)
pip install "fastapi[all]"

# Verify
python -c "import fastapi; print(fastapi.__version__)"
```

### Your First Endpoint

```python
# main.py
from fastapi import FastAPI

app = FastAPI(
    title="DevOps Automation API",
    description="Internal API for infrastructure automation",
    version="1.0.0"
)

@app.get("/")
def root():
    return {"message": "DevOps API is alive", "status": "healthy"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
```

### Running the Server

```bash
# Development — auto-reload on file change
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Production — multiple workers
uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000

# Using Gunicorn with Uvicorn workers (recommended for production)
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Auto-Generated Documentation

Once your server is running, FastAPI gives you **free** interactive docs:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI JSON:** `http://localhost:8000/openapi.json`

> 🧠 **Senior Tip:** Export the OpenAPI spec and use it to auto-generate client SDKs with tools like `openapi-generator`. Your platform team will love you for it.

---

## 4. Request & Response Models with Pydantic

This is where FastAPI truly shines. Pydantic models define the shape of your data and provide automatic validation, serialization, and documentation.

### Request Models

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from enum import Enum

app = FastAPI()

class DeploymentEnvironment(str, Enum):
    development = "development"
    staging = "staging"
    production = "production"

class DeploymentRequest(BaseModel):
    service_name: str = Field(..., min_length=2, max_length=64, pattern=r'^[a-z0-9-]+$')
    image_tag: str = Field(..., description="Docker image tag, e.g. v1.2.3 or sha256:abc123")
    environment: DeploymentEnvironment
    replicas: int = Field(default=1, ge=1, le=20)
    cpu_limit: str = Field(default="500m", description="Kubernetes CPU limit")
    memory_limit: str = Field(default="512Mi", description="Kubernetes memory limit")
    annotations: dict[str, str] = {}
    rollout_strategy: Optional[str] = "RollingUpdate"

    # Custom validation
    @field_validator("image_tag")
    @classmethod
    def validate_image_tag(cls, v: str) -> str:
        if v == "latest" :
            raise ValueError("'latest' tag is not allowed in deployments. Use a specific version.")
        return v

@app.post("/deploy")
def create_deployment(deployment: DeploymentRequest):
    # FastAPI automatically parses and validates the JSON body
    return {
        "status": "queued",
        "service": deployment.service_name,
        "environment": deployment.environment.value,
        "replicas": deployment.replicas
    }
```

### Response Models

```python
from pydantic import BaseModel
from datetime import datetime

class DeploymentResponse(BaseModel):
    deployment_id: str
    service_name: str
    status: str
    created_at: datetime
    estimated_completion_seconds: int

    model_config = {"from_attributes": True}  # Allows creating from ORM objects

# response_model enforces what data is returned (strips extra fields, validates output)
@app.post("/deploy", response_model=DeploymentResponse, status_code=202)
def create_deployment(deployment: DeploymentRequest):
    return DeploymentResponse(
        deployment_id="dep-abc123",
        service_name=deployment.service_name,
        status="in_progress",
        created_at=datetime.utcnow(),
        estimated_completion_seconds=120
    )
```

### Nested Models

```python
class ContainerSpec(BaseModel):
    image: str
    tag: str
    environment_variables: dict[str, str] = {}
    ports: list[int] = []

class ServiceSpec(BaseModel):
    name: str
    containers: list[ContainerSpec]  # Nested list of models
    labels: dict[str, str] = {}

# FastAPI handles deeply nested JSON automatically
@app.post("/services")
def create_service(spec: ServiceSpec):
    return {"created": spec.name, "container_count": len(spec.containers)}
```

---

## 5. Path, Query, and Body Parameters

Understanding the three types of parameters is fundamental.

### Path Parameters

Path parameters are **part of the URL path**. They identify a specific resource.

```python
from fastapi import Path

@app.get("/clusters/{cluster_id}/nodes/{node_id}")
def get_node(
    cluster_id: str = Path(..., description="The cluster identifier"),
    node_id: str = Path(..., description="The node identifier", min_length=5)
):
    return {"cluster": cluster_id, "node": node_id}

# GET /clusters/prod-us-east/nodes/node-001
```

### Query Parameters

Query parameters come **after the `?` in the URL**. They filter, sort, or paginate.

```python
from fastapi import Query
from typing import Optional

@app.get("/pods")
def list_pods(
    namespace: str = Query(default="default", description="Kubernetes namespace"),
    status: Optional[str] = Query(default=None, enum=["Running", "Pending", "Failed"]),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    label_selector: Optional[str] = Query(default=None, description="e.g. app=nginx,tier=frontend")
):
    return {
        "namespace": namespace,
        "status_filter": status,
        "pagination": {"limit": limit, "offset": offset}
    }

# GET /pods?namespace=production&status=Running&limit=10
```

### Body Parameters

Body parameters are sent as the **JSON body** of the request.

```python
from fastapi import Body

@app.patch("/nodes/{node_id}/labels")
def update_node_labels(
    node_id: str,
    labels: dict[str, str] = Body(..., example={"env": "prod", "team": "platform"})
):
    return {"node": node_id, "labels_updated": labels}
```

### Mixing All Three

```python
@app.post("/namespaces/{namespace}/deployments")
def create_namespaced_deployment(
    namespace: str,                                        # Path param
    dry_run: bool = Query(default=False),                  # Query param
    deployment: DeploymentRequest = Body(...)              # Body param
):
    if dry_run:
        return {"dry_run": True, "would_deploy": deployment.service_name}
    return {"namespace": namespace, "deployed": deployment.service_name}
```

---

## 6. HTTP Methods & Status Codes

### All HTTP Methods

```python
from fastapi import FastAPI, status

app = FastAPI()

# GET — Retrieve resource(s)
@app.get("/services/{service_id}")
def get_service(service_id: str):
    return {"id": service_id}

# POST — Create a new resource
@app.post("/services", status_code=status.HTTP_201_CREATED)
def create_service(service: ServiceSpec):
    return {"created": service.name}

# PUT — Full replacement of a resource
@app.put("/services/{service_id}")
def replace_service(service_id: str, service: ServiceSpec):
    return {"replaced": service_id}

# PATCH — Partial update
@app.patch("/services/{service_id}")
def update_service(service_id: str, updates: dict):
    return {"updated": service_id}

# DELETE — Remove a resource
@app.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_service(service_id: str):
    return None  # 204 No Content returns no body

# HEAD — Like GET but returns only headers (used for health checks)
@app.head("/health")
def health_head():
    return {}
```

### Custom HTTP Responses

```python
from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response, PlainTextResponse

# Raising HTTP errors
@app.get("/services/{service_id}")
def get_service(service_id: str):
    service = db.find_service(service_id)
    if not service:
        raise HTTPException(
            status_code=404,
            detail=f"Service '{service_id}' not found",
            headers={"X-Error-Code": "SERVICE_NOT_FOUND"}
        )
    return service

# Custom response with headers
@app.get("/metrics")
def get_metrics():
    return JSONResponse(
        content={"cpu": 72, "memory": 68},
        headers={"Cache-Control": "max-age=15"},
        status_code=200
    )

# Plain text response (useful for /metrics in Prometheus format)
@app.get("/metrics/prometheus", response_class=PlainTextResponse)
def prometheus_metrics():
    return "# HELP http_requests_total\nhttp_requests_total 1234\n"
```

---

## 7. Dependency Injection

This is one of FastAPI's most powerful features. Dependencies are reusable components that are automatically injected into route handlers.

### Basic Dependencies

```python
from fastapi import Depends, FastAPI, HTTPException, Request
import time

app = FastAPI()

# Simple function-based dependency
def get_request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID", "unknown")

@app.get("/data")
def get_data(request_id: str = Depends(get_request_id)):
    return {"request_id": request_id, "data": [...]}
```

### Class-Based Dependencies (Reusable Configurations)

```python
class PaginationParams:
    def __init__(self, page: int = 1, page_size: int = Query(default=20, le=100)):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size

@app.get("/deployments")
def list_deployments(pagination: PaginationParams = Depends(PaginationParams)):
    return {
        "page": pagination.page,
        "page_size": pagination.page_size,
        "offset": pagination.offset
    }
```

### Database Session Dependency

```python
from sqlalchemy.orm import Session
from database import SessionLocal  # Your DB session factory

def get_db():
    db = SessionLocal()
    try:
        yield db          # Yield makes this a context manager
    finally:
        db.close()        # Always close, even on errors

@app.get("/services")
def get_services(db: Session = Depends(get_db)):
    return db.query(Service).all()
```

### Chained Dependencies

```python
# Auth dependency
async def get_current_user(token: str = Depends(oauth2_scheme)):
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

# Role dependency that chains off auth
async def require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# Route uses the end of the chain
@app.delete("/services/{service_id}")
async def delete_service(
    service_id: str,
    admin: User = Depends(require_admin)   # This implicitly also checks auth
):
    return {"deleted": service_id, "by": admin.username}
```

---

## 8. Authentication & Security

### API Key Authentication

```python
from fastapi import Security
from fastapi.security import APIKeyHeader, APIKeyQuery

API_KEY = "your-secret-key"  # In production, read from env var
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
api_key_query = APIKeyQuery(name="api_key", auto_error=False)

async def get_api_key(
    api_key_header: str = Security(api_key_header),
    api_key_query: str = Security(api_key_query),
) -> str:
    key = api_key_header or api_key_query
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return key

@app.get("/protected", dependencies=[Depends(get_api_key)])
def protected_endpoint():
    return {"message": "You have access"}
```

### JWT Authentication

```python
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from datetime import datetime, timedelta
from passlib.context import CryptContext

SECRET_KEY = "your-secret-key-from-env"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    return username

# Login endpoint
@app.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # Verify user from DB here...
    access_token = create_access_token(data={"sub": form_data.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/me")
async def read_me(current_user: str = Depends(get_current_user)):
    return {"user": current_user}
```

---

## 9. Database Integration

### SQLAlchemy (Relational DBs)

```python
# database.py
from sqlalchemy import create_engine, Column, String, Integer, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/devops_db")

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ORM Model
class DeploymentModel(Base):
    __tablename__ = "deployments"

    id = Column(String, primary_key=True)
    service_name = Column(String, nullable=False)
    environment = Column(String, nullable=False)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Async SQLAlchemy (For High Performance)

```python
# For async database access — critical for high-throughput APIs
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

ASYNC_DATABASE_URL = "postgresql+asyncpg://user:pass@localhost/devops_db"

async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session

@app.get("/deployments")
async def list_deployments(db: AsyncSession = Depends(get_async_db)):
    from sqlalchemy import select
    result = await db.execute(select(DeploymentModel))
    return result.scalars().all()
```

---

## 10. Async Programming in FastAPI

Understanding when to use `async def` vs `def` is critical.

```python
import httpx
import asyncio
from fastapi import FastAPI

app = FastAPI()

# ✅ Use async def when:
# - Making HTTP calls to external services
# - Querying databases with async drivers
# - Reading/writing files with aiofiles
# - Any I/O-bound operation

@app.get("/cluster-health")
async def get_cluster_health():
    async with httpx.AsyncClient() as client:
        # These requests run CONCURRENTLY, not sequentially!
        responses = await asyncio.gather(
            client.get("http://node-1:9090/health"),
            client.get("http://node-2:9090/health"),
            client.get("http://node-3:9090/health"),
        )
    return {
        f"node-{i+1}": r.json()
        for i, r in enumerate(responses)
    }

# ✅ Use regular def when:
# - CPU-bound work (calculations, data processing)
# - Calling sync libraries (boto3, kubernetes client)
# FastAPI runs sync functions in a thread pool automatically

@app.post("/compute-checksum")
def compute_checksum(data: dict):
    import hashlib
    import json
    checksum = hashlib.sha256(json.dumps(data).encode()).hexdigest()
    return {"checksum": checksum}
```

### Async Context Managers (Lifespan Events)

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: runs before the app starts accepting requests
    print("🚀 Starting up: connecting to database...")
    await database.connect()
    print("✅ Database connected")
    
    yield  # App is running here
    
    # Shutdown: runs when the app is stopping
    print("🔴 Shutting down: closing connections...")
    await database.disconnect()
    print("✅ Cleanup complete")

app = FastAPI(lifespan=lifespan)
```

---

## 11. Background Tasks & Scheduling

### FastAPI Background Tasks

```python
from fastapi import BackgroundTasks
import smtplib
import logging

logger = logging.getLogger(__name__)

def send_slack_notification(channel: str, message: str):
    """This runs AFTER the response is already sent to the client."""
    # Non-blocking: client doesn't wait for this
    import time
    time.sleep(2)  # Simulating Slack API call
    logger.info(f"Slack notification sent to {channel}: {message}")

def update_deployment_status(deployment_id: str, status: str):
    logger.info(f"Updating deployment {deployment_id} to {status}")

@app.post("/deploy", status_code=202)
def trigger_deployment(
    deployment: DeploymentRequest,
    background_tasks: BackgroundTasks
):
    deployment_id = "dep-" + uuid4().hex[:8]
    
    # These run after the response is returned
    background_tasks.add_task(
        send_slack_notification,
        "#deployments",
        f"Deployment {deployment_id} triggered for {deployment.service_name}"
    )
    background_tasks.add_task(
        update_deployment_status,
        deployment_id,
        "in_progress"
    )
    
    return {"deployment_id": deployment_id, "status": "accepted"}
```

### Celery Integration (Production Task Queue)

```python
# celery_worker.py
from celery import Celery
import os

celery_app = Celery(
    "devops_tasks",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0")
)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_terraform_apply(self, workspace: str, variables: dict):
    try:
        import subprocess
        result = subprocess.run(
            ["terraform", "apply", "-auto-approve"],
            cwd=f"/terraform/{workspace}",
            capture_output=True, text=True
        )
        return {"status": "success", "output": result.stdout}
    except Exception as exc:
        raise self.retry(exc=exc)

# In your FastAPI route:
@app.post("/terraform/apply")
def apply_terraform(workspace: str, variables: dict):
    task = run_terraform_apply.delay(workspace, variables)
    return {"task_id": task.id, "status": "queued"}

@app.get("/terraform/status/{task_id}")
def get_task_status(task_id: str):
    task = run_terraform_apply.AsyncResult(task_id)
    return {"task_id": task_id, "status": task.status, "result": task.result}
```

---

## 12. Middleware

Middleware runs for **every request and response**. Use it for cross-cutting concerns.

### CORS Middleware

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://internal-dashboard.company.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

### Custom Middleware

```python
from fastapi import Request
import time
import uuid

@app.middleware("http")
async def request_id_and_timing_middleware(request: Request, call_next):
    # Before the request
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.time()
    
    # Process request
    response = await call_next(request)
    
    # After the response
    process_time = (time.time() - start_time) * 1000
    
    # Inject headers into the response
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time-Ms"] = f"{process_time:.2f}"
    
    # Log every request
    logger.info(
        f"method={request.method} path={request.url.path} "
        f"status={response.status_code} duration={process_time:.2f}ms "
        f"request_id={request_id}"
    )
    
    return response
```

### Rate Limiting Middleware

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/deploy")
@limiter.limit("10/minute")  # Max 10 deploys per minute per IP
async def deploy(request: Request):
    return {"status": "deploying"}
```

---

## 13. File Uploads & Streaming

```python
from fastapi import UploadFile, File
from fastapi.responses import StreamingResponse
import aiofiles
import io

# Single file upload
@app.post("/upload/kubeconfig")
async def upload_kubeconfig(file: UploadFile = File(...)):
    if not file.filename.endswith((".yaml", ".yml", ".json")):
        raise HTTPException(400, "Only YAML/JSON files are accepted")
    
    content = await file.read()
    
    # Save to disk
    async with aiofiles.open(f"/configs/{file.filename}", "wb") as f:
        await f.write(content)
    
    return {"filename": file.filename, "size_bytes": len(content)}

# Multiple file uploads
@app.post("/upload/terraform-modules")
async def upload_modules(files: list[UploadFile] = File(...)):
    results = []
    for file in files:
        content = await file.read()
        results.append({"filename": file.filename, "size": len(content)})
    return {"uploaded": results}

# Streaming large file downloads
@app.get("/logs/{pod_name}")
async def stream_pod_logs(pod_name: str):
    async def log_generator():
        async with aiofiles.open(f"/var/log/pods/{pod_name}.log", "r") as f:
            async for line in f:
                yield line.encode()
    
    return StreamingResponse(
        log_generator(),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={pod_name}.log"}
    )
```

---

## 14. WebSockets

WebSockets enable real-time, bidirectional communication — perfect for live log streaming, deployment progress, and monitoring dashboards.

```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import list

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/ws/deployments/{deployment_id}/logs")
async def deployment_logs_ws(websocket: WebSocket, deployment_id: str):
    await manager.connect(websocket)
    try:
        while True:
            # Simulate sending real-time log lines
            await asyncio.sleep(1)
            log_line = f"[{datetime.utcnow().isoformat()}] deployment/{deployment_id}: Waiting for pods..."
            await websocket.send_text(log_line)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

---

## 15. Testing FastAPI Applications

Testing is non-negotiable for production APIs. FastAPI makes this easy.

### Unit Tests with TestClient

```python
# test_main.py
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

# Basic test
def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# Test with authentication
def test_protected_endpoint_requires_auth():
    response = client.get("/protected")
    assert response.status_code == 403

def test_protected_endpoint_with_valid_key():
    response = client.get("/protected", headers={"X-API-Key": "your-secret-key"})
    assert response.status_code == 200

# Test POST with body
def test_create_deployment():
    payload = {
        "service_name": "my-service",
        "image_tag": "v1.0.0",
        "environment": "staging",
        "replicas": 2
    }
    response = client.post("/deploy", json=payload)
    assert response.status_code == 202
    assert "deployment_id" in response.json()

# Test validation
def test_deployment_rejects_latest_tag():
    payload = {
        "service_name": "my-service",
        "image_tag": "latest",  # Should be rejected
        "environment": "production"
    }
    response = client.post("/deploy", json=payload)
    assert response.status_code == 422  # Unprocessable Entity
```

### Async Tests

```python
import pytest
import pytest_asyncio
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_async_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/cluster-health")
    assert response.status_code == 200
```

### Mocking Dependencies

```python
from unittest.mock import MagicMock, AsyncMock

def test_with_mocked_db():
    mock_db = MagicMock()
    mock_db.query.return_value.all.return_value = [
        {"id": "1", "name": "my-service"}
    ]
    
    # Override the dependency for this test
    app.dependency_overrides[get_db] = lambda: mock_db
    
    response = client.get("/services")
    assert response.status_code == 200
    
    # Clean up
    app.dependency_overrides.clear()
```

---

## 16. Structuring Large Projects

For a single-file app, `main.py` is fine. For production services, you need a real structure.

```
my-devops-api/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app creation, middleware, lifespan
│   ├── config.py             # Settings (Pydantic Settings)
│   ├── dependencies.py       # Shared dependencies (auth, db session)
│   ├── database.py           # DB engine, session factory
│   │
│   ├── routers/              # Route handlers, grouped by domain
│   │   ├── __init__.py
│   │   ├── deployments.py
│   │   ├── clusters.py
│   │   ├── monitoring.py
│   │   └── auth.py
│   │
│   ├── models/               # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── deployment.py
│   │   └── user.py
│   │
│   ├── schemas/              # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── deployment.py
│   │   └── user.py
│   │
│   └── services/             # Business logic (pure Python, no FastAPI)
│       ├── __init__.py
│       ├── deployment_service.py
│       └── kubernetes_service.py
│
├── tests/
│   ├── conftest.py           # Shared test fixtures
│   ├── test_deployments.py
│   └── test_auth.py
│
├── alembic/                  # Database migrations
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

### Routers

```python
# app/routers/deployments.py
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(
    prefix="/deployments",
    tags=["deployments"],
    dependencies=[Depends(get_current_user)]  # All routes require auth
)

@router.get("/")
def list_deployments():
    return []

@router.post("/", status_code=201)
def create_deployment(deployment: DeploymentRequest):
    return {}

@router.get("/{deployment_id}")
def get_deployment(deployment_id: str):
    return {}

# app/main.py
from app.routers import deployments, clusters, auth

app = FastAPI()
app.include_router(auth.router, prefix="/api/v1")
app.include_router(deployments.router, prefix="/api/v1")
app.include_router(clusters.router, prefix="/api/v1")
```

### Configuration Management

```python
# app/config.py
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # App
    app_name: str = "DevOps Automation API"
    environment: str = "development"
    debug: bool = False
    
    # Database
    database_url: str = "postgresql://localhost/devops"
    
    # Auth
    secret_key: str
    access_token_expire_minutes: int = 30
    
    # External Services
    slack_webhook_url: str = ""
    kubernetes_api_url: str = "https://kubernetes.default.svc"
    
    class Config:
        env_file = ".env"  # Reads from .env file automatically

@lru_cache()  # Singleton — only created once
def get_settings() -> Settings:
    return Settings()

# Usage in routes
@app.get("/config-check")
def check_config(settings: Settings = Depends(get_settings)):
    return {"environment": settings.environment}
```

---

## 17. FastAPI in AI/ML DevOps Pipelines

This is the real reason you're here. FastAPI is the standard for serving AI models.

### Serving an ML Model

```python
from fastapi import FastAPI
from pydantic import BaseModel
import joblib
import numpy as np
from contextlib import asynccontextmanager

# Global model reference
model = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    print("Loading ML model...")
    model = joblib.load("models/anomaly_detector.pkl")
    print("Model loaded!")
    yield
    model = None

app = FastAPI(lifespan=lifespan)

class MetricPayload(BaseModel):
    cpu_usage: float
    memory_usage: float
    request_rate: float
    error_rate: float
    latency_p99: float

class PredictionResponse(BaseModel):
    is_anomaly: bool
    confidence: float
    recommendation: str

@app.post("/predict/anomaly", response_model=PredictionResponse)
async def detect_anomaly(metrics: MetricPayload):
    features = np.array([[
        metrics.cpu_usage,
        metrics.memory_usage,
        metrics.request_rate,
        metrics.error_rate,
        metrics.latency_p99
    ]])
    
    prediction = model.predict(features)[0]
    probability = model.predict_proba(features)[0].max()
    
    return PredictionResponse(
        is_anomaly=bool(prediction == -1),
        confidence=float(probability),
        recommendation="Scale up replicas" if prediction == -1 else "System healthy"
    )
```

### LLM-Powered DevOps Automation

```python
from openai import AsyncOpenAI
from pydantic import BaseModel

client = AsyncOpenAI()

class IncidentRequest(BaseModel):
    error_logs: str
    service_name: str
    environment: str

class IncidentAnalysis(BaseModel):
    root_cause: str
    severity: str
    remediation_steps: list[str]
    estimated_resolution_time: str

@app.post("/ai/incident-analysis", response_model=IncidentAnalysis)
async def analyze_incident(incident: IncidentRequest):
    prompt = f"""
    You are a senior SRE. Analyze this incident:
    
    Service: {incident.service_name}
    Environment: {incident.environment}
    Error Logs:
    {incident.error_logs}
    
    Respond in JSON with: root_cause, severity (P1/P2/P3/P4), 
    remediation_steps (list), estimated_resolution_time
    """
    
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )
    
    import json
    result = json.loads(response.choices[0].message.content)
    return IncidentAnalysis(**result)
```

### Streaming AI Responses (Server-Sent Events)

```python
from fastapi.responses import StreamingResponse
import json

@app.post("/ai/generate-runbook")
async def generate_runbook(service_name: str, incident_type: str):
    async def stream_runbook():
        async with client.chat.completions.stream(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": f"Generate a detailed runbook for {incident_type} in {service_name}"
            }]
        ) as stream:
            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    # Server-Sent Events format
                    data = json.dumps({"content": chunk.choices[0].delta.content})
                    yield f"data: {data}\n\n"
        
        yield "data: [DONE]\n\n"
    
    return StreamingResponse(
        stream_runbook(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )
```

---

## 18. Containerizing FastAPI with Docker

### Dockerfile (Production-Grade)

```dockerfile
# Dockerfile
# Stage 1: Builder
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim AS runtime

# Create non-root user (security best practice)
RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser ./app ./app

USER appuser

ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Healthcheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "4", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

### Docker Compose (Local Development)

```yaml
# docker-compose.yml
version: "3.9"

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/devops
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=dev-secret-key
      - ENVIRONMENT=development
    volumes:
      - ./app:/app/app  # Hot reload in dev
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    command: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: devops
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  celery_worker:
    build: .
    command: celery -A app.celery_app worker --loglevel=info --concurrency=4
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis

volumes:
  postgres_data:
```

---

## 19. Kubernetes Deployment Patterns

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: devops-api
  namespace: platform
  labels:
    app: devops-api
    version: "1.0.0"
spec:
  replicas: 3
  selector:
    matchLabels:
      app: devops-api
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 1
  template:
    metadata:
      labels:
        app: devops-api
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
        prometheus.io/port: "8000"
    spec:
      serviceAccountName: devops-api-sa
      containers:
        - name: api
          image: your-registry/devops-api:v1.0.0
          imagePullPolicy: Always
          ports:
            - containerPort: 8000
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: devops-api-secrets
                  key: database-url
            - name: SECRET_KEY
              valueFrom:
                secretKeyRef:
                  name: devops-api-secrets
                  key: secret-key
          resources:
            requests:
              memory: "256Mi"
              cpu: "100m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: devops-api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: devops-api
  minReplicas: 2
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## 20. Observability — Logging, Metrics & Tracing

### Structured Logging

```python
import structlog
import logging

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer() if os.getenv("ENV") == "development"
        else structlog.processors.JSONRenderer()
    ]
)

logger = structlog.get_logger()

@app.post("/deploy")
async def create_deployment(deployment: DeploymentRequest):
    log = logger.bind(
        service=deployment.service_name,
        environment=deployment.environment,
        action="deployment_requested"
    )
    
    log.info("Deployment request received")
    
    try:
        result = await deploy_service(deployment)
        log.info("Deployment successful", deployment_id=result.id)
        return result
    except Exception as e:
        log.error("Deployment failed", error=str(e), exc_info=True)
        raise HTTPException(500, "Deployment failed")
```

### Prometheus Metrics

```python
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Histogram, Gauge

# Auto-instrument all endpoints
Instrumentator().instrument(app).expose(app)

# Custom metrics
deployment_counter = Counter(
    "deployments_total",
    "Total number of deployments",
    ["environment", "service", "status"]
)

deployment_duration = Histogram(
    "deployment_duration_seconds",
    "Time taken for deployments",
    ["environment", "service"]
)

active_deployments = Gauge(
    "active_deployments",
    "Number of currently active deployments",
    ["environment"]
)

@app.post("/deploy")
async def create_deployment(deployment: DeploymentRequest):
    with deployment_duration.labels(
        environment=deployment.environment,
        service=deployment.service_name
    ).time():
        active_deployments.labels(environment=deployment.environment).inc()
        
        try:
            result = await deploy_service(deployment)
            deployment_counter.labels(
                environment=deployment.environment,
                service=deployment.service_name,
                status="success"
            ).inc()
            return result
        except Exception:
            deployment_counter.labels(
                environment=deployment.environment,
                service=deployment.service_name,
                status="failed"
            ).inc()
            raise
        finally:
            active_deployments.labels(environment=deployment.environment).dec()
```

### OpenTelemetry Tracing

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Setup
provider = TracerProvider()
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://otel-collector:4317"))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

# Auto-instrument FastAPI
FastAPIInstrumentor.instrument_app(app)

# Manual spans
tracer = trace.get_tracer(__name__)

async def deploy_to_kubernetes(service_name: str, image: str):
    with tracer.start_as_current_span("kubernetes.deploy") as span:
        span.set_attribute("k8s.service", service_name)
        span.set_attribute("k8s.image", image)
        
        # Your k8s deployment logic here...
        await asyncio.sleep(0.1)
        
        span.set_attribute("k8s.result", "success")
```

---

## 21. CI/CD for FastAPI Applications

### GitHub Actions Pipeline

```yaml
# .github/workflows/cicd.yml
name: CI/CD Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: test_db
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: password
        options: >-
          --health-cmd pg_isready
          --health-interval 10s

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov

      - name: Run tests
        env:
          DATABASE_URL: postgresql://postgres:password@localhost/test_db
          SECRET_KEY: test-secret-key
        run: |
          pytest tests/ -v --cov=app --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: |
            your-registry/devops-api:latest
            your-registry/devops-api:${{ github.sha }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - name: Deploy to Kubernetes
        run: |
          kubectl set image deployment/devops-api \
            api=your-registry/devops-api:${{ github.sha }} \
            --namespace=platform
          kubectl rollout status deployment/devops-api --namespace=platform
```

---

## 22. Performance Tuning & Production Hardening

### Worker Configuration

```bash
# Formula: (2 * CPU cores) + 1 for I/O-bound workloads
# For a 4-core machine: 9 workers
gunicorn app.main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 9 \
  --worker-connections 1000 \
  --max-requests 1000 \
  --max-requests-jitter 50 \
  --timeout 120 \
  --keepalive 5 \
  --bind 0.0.0.0:8000
```

### Connection Pooling

```python
# Always configure connection pools — default settings are too small for production
engine = create_engine(
    DATABASE_URL,
    pool_size=20,          # Number of persistent connections
    max_overflow=30,       # Extra connections when pool is full
    pool_timeout=30,       # Wait time before giving up
    pool_recycle=3600,     # Recycle connections after 1 hour
    pool_pre_ping=True,    # Test connections before using them
)
```

### Caching with Redis

```python
import redis.asyncio as redis
import json
from functools import wraps

redis_client = redis.from_url("redis://localhost:6379", decode_responses=True)

def cache(ttl_seconds: int = 60, key_prefix: str = ""):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try cache first
            cached = await redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
            
            # Cache miss: call function and store result
            result = await func(*args, **kwargs)
            await redis_client.setex(cache_key, ttl_seconds, json.dumps(result))
            return result
        return wrapper
    return decorator

@app.get("/clusters/{cluster_id}/nodes")
@cache(ttl_seconds=30, key_prefix="clusters")
async def list_cluster_nodes(cluster_id: str):
    # This expensive call is cached for 30 seconds
    return await kubernetes_client.list_nodes(cluster_id)
```

---

## 23. Senior-Level Patterns & Architecture

### Repository Pattern (Clean Architecture)

```python
# Separates data access from business logic
from abc import ABC, abstractmethod

class DeploymentRepository(ABC):
    @abstractmethod
    async def create(self, deployment: DeploymentCreate) -> Deployment:
        pass
    
    @abstractmethod
    async def get_by_id(self, deployment_id: str) -> Deployment | None:
        pass
    
    @abstractmethod
    async def list_by_service(self, service_name: str) -> list[Deployment]:
        pass

class PostgresDeploymentRepository(DeploymentRepository):
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, deployment: DeploymentCreate) -> Deployment:
        db_obj = DeploymentModel(**deployment.model_dump())
        self.db.add(db_obj)
        await self.db.commit()
        return Deployment.model_validate(db_obj)
    
    # ... other methods

# Easy to swap for testing
class InMemoryDeploymentRepository(DeploymentRepository):
    def __init__(self):
        self._store: dict[str, Deployment] = {}
    
    async def create(self, deployment: DeploymentCreate) -> Deployment:
        obj = Deployment(id=str(uuid4()), **deployment.model_dump())
        self._store[obj.id] = obj
        return obj
```

### Event-Driven Patterns with Kafka

```python
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
import json

KAFKA_BOOTSTRAP = "kafka:9092"

# Event producer — publish deployment events
async def publish_deployment_event(event_type: str, payload: dict):
    producer = AIOKafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP)
    await producer.start()
    try:
        event = {"type": event_type, "timestamp": datetime.utcnow().isoformat(), **payload}
        await producer.send_and_wait("deployment-events", json.dumps(event).encode())
    finally:
        await producer.stop()

# Event consumer — runs as a background service
async def consume_deployment_events():
    consumer = AIOKafkaConsumer(
        "deployment-events",
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id="devops-api-consumer"
    )
    await consumer.start()
    try:
        async for message in consumer:
            event = json.loads(message.value)
            await handle_deployment_event(event)
    finally:
        await consumer.stop()
```

### Circuit Breaker Pattern

```python
import asyncio
from enum import Enum
from datetime import datetime, timedelta

class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Failing, reject requests fast
    HALF_OPEN = "half_open" # Testing if service recovered

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 60):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.timeout = timeout_seconds
        self.last_failure_time = None
    
    async def call(self, func, *args, **kwargs):
        if self.state == CircuitState.OPEN:
            if datetime.utcnow() - self.last_failure_time > timedelta(seconds=self.timeout):
                self.state = CircuitState.HALF_OPEN
            else:
                raise HTTPException(503, "Service circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.utcnow()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN

# Usage
k8s_circuit_breaker = CircuitBreaker(failure_threshold=5, timeout_seconds=30)

@app.get("/cluster/{cluster_id}")
async def get_cluster(cluster_id: str):
    return await k8s_circuit_breaker.call(
        kubernetes_client.get_cluster,
        cluster_id
    )
```

---

## 24. Quick Reference Cheatsheet

```python
# ─── INSTALLATION ────────────────────────────────────────────────────────────
# pip install "fastapi[all]" gunicorn

# ─── APP CREATION ────────────────────────────────────────────────────────────
from fastapi import FastAPI
app = FastAPI(title="API", version="1.0.0")

# ─── ROUTES ──────────────────────────────────────────────────────────────────
@app.get("/path")          # GET
@app.post("/path")         # POST (201 Created)
@app.put("/path/{id}")     # PUT
@app.patch("/path/{id}")   # PATCH
@app.delete("/path/{id}")  # DELETE

# ─── PARAMETERS ──────────────────────────────────────────────────────────────
from fastapi import Path, Query, Body, Depends

# Path:  /items/{item_id}          → item_id: str = Path(...)
# Query: /items?limit=10           → limit: int = Query(default=10)
# Body:  JSON body                 → item: ItemModel (Pydantic model)
# Dep:   Reusable logic            → user = Depends(get_current_user)

# ─── RESPONSES ───────────────────────────────────────────────────────────────
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

raise HTTPException(status_code=404, detail="Not found")
return JSONResponse(content={}, status_code=200)

# ─── PYDANTIC MODEL ───────────────────────────────────────────────────────────
from pydantic import BaseModel, Field
class Item(BaseModel):
    name: str
    value: float = Field(gt=0)
    tags: list[str] = []

# ─── ASYNC ───────────────────────────────────────────────────────────────────
@app.get("/async-route")
async def async_route():
    result = await some_async_function()
    return result

# ─── AUTH ────────────────────────────────────────────────────────────────────
from fastapi.security import APIKeyHeader
api_key = APIKeyHeader(name="X-API-Key")

# ─── BACKGROUND TASKS ────────────────────────────────────────────────────────
from fastapi import BackgroundTasks
@app.post("/action")
def action(bg: BackgroundTasks):
    bg.add_task(some_function, arg1, arg2)
    return {"status": "accepted"}

# ─── STARTUP/SHUTDOWN ────────────────────────────────────────────────────────
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(app):
    # startup
    yield
    # shutdown
app = FastAPI(lifespan=lifespan)

# ─── ROUTERS ─────────────────────────────────────────────────────────────────
from fastapi import APIRouter
router = APIRouter(prefix="/api/v1", tags=["myrouter"])
app.include_router(router)

# ─── RUNNING ─────────────────────────────────────────────────────────────────
# Dev:  uvicorn main:app --reload
# Prod: gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker
```

---

## Final Words

Going from junior to senior DevOps engineer in the AI era runs straight through Python and FastAPI. Here's the progression:

**Junior Level** → Build CRUD endpoints, understand Pydantic models, run with Docker, write basic tests.

**Mid Level** → Dependency injection, JWT auth, async patterns, database integration, structured logging.

**Senior Level** → Architecture patterns (Repository, Circuit Breaker), event-driven design, performance tuning, observability, AI/ML serving, Kubernetes-native deployments.

FastAPI is not just a web framework — it's the glue between your infrastructure, your AI models, your data pipelines, and your teams. Master it, and you've mastered the language of modern platform engineering.

---

*Built with ❤️ for DevOps Engineers working through the AI-native infrastructure world.*
*FastAPI version referenced: 0.115.x | Python 3.12+ | Pydantic v2*
