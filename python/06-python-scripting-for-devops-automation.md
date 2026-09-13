# Python Scripting for DevOps Automation
### Stage 5 of the [Python roadmap](./README.md) — the capstone

> Goal of this file: put everything from files 01–05 together into the shape of a real automation script — one that takes arguments, runs shell commands, logs properly, calls an API, and exits with the right code so your CI/CD pipeline knows whether it actually worked.

By the end of this file you're through the "basics to intermediate" roadmap. What's left after this is production depth — [Pydantic](./python_pydantic_devops_guide.md), [FastAPI](./what-devops-engineers-should-know-about-fastapi-in-production.md), and [Uvicorn/Gunicorn](./uvicorn-vs-gunicorn-explained.md) — plus, if agents are where you're headed next, the [agentic-ai](../agentic-ai/README.md) series.

---

## 1. Reading input: environment variables and CLI arguments

You already saw `os.getenv()` in file 01. The other input source every real script needs is command-line arguments — and `sys.argv` gets painful fast once you need more than one flag.

```python
import sys
print(sys.argv)
# python deploy.py --service checkout-api --replicas 3
# ['deploy.py', '--service', 'checkout-api', '--replicas', '3']
```

That's raw and unparsed — no validation, no help text, no defaults. `argparse` (standard library, no install needed) is the real answer:

```python
import argparse

parser = argparse.ArgumentParser(description="Deploy a service")
parser.add_argument("--service", required=True, help="Service name to deploy")
parser.add_argument("--replicas", type=int, default=1, help="Number of replicas")
parser.add_argument("--dry-run", action="store_true", help="Print what would happen without doing it")

args = parser.parse_args()

print(f"Deploying {args.service} with {args.replicas} replicas")
if args.dry_run:
    print("(dry run — no changes made)")
```

```bash
python deploy.py --service checkout-api --replicas 3
python deploy.py --help              # argparse generates this for free
python deploy.py                      # errors clearly: "the following arguments are required: --service"
```

`argparse` gives you validation, types, defaults, and a `--help` message for free — the same set of expectations you already have for any decent CLI tool.

---

## 2. `subprocess` — running shell commands from Python

Almost every DevOps script eventually needs to run something like `kubectl`, `terraform`, or `aws`. `subprocess` is how you do that without shelling out to a Bash script that calls Python that calls Bash again.

```python
import subprocess

# Run a command and capture its output
result = subprocess.run(
    ["kubectl", "get", "pods", "-n", "production"],
    capture_output=True,
    text=True,        # decode output as text instead of bytes
    check=True,        # raise an exception if the command exits non-zero
)

print(result.stdout)
print(result.returncode)   # 0 on success
```

### The `shell=True` trap

```python
# Dangerous if user_input comes from outside your control:
subprocess.run(f"kubectl get pods {user_input}", shell=True)

# Safe — pass arguments as a list, no shell string interpolation involved
subprocess.run(["kubectl", "get", "pods", user_input])
```

Passing a list instead of a shell string is the equivalent of using parameterized SQL queries instead of string-concatenating user input into a query — `shell=True` with untrusted input is a straightforward command-injection hole. Default to the list form unless you specifically need shell features like pipes or globbing, and never mix `shell=True` with anything a user or an external system supplied.

### Handling failures

```python
try:
    result = subprocess.run(
        ["terraform", "apply", "-auto-approve"],
        capture_output=True,
        text=True,
        check=True,
        timeout=300,     # don't let a hung command block your pipeline forever
    )
except subprocess.CalledProcessError as e:
    print(f"terraform apply failed with exit code {e.returncode}")
    print(e.stderr)
    sys.exit(1)
except subprocess.TimeoutExpired:
    print("terraform apply timed out after 5 minutes")
    sys.exit(1)
```

---

## 3. Logging — why `print()` stops being enough

`print()` is fine for a ten-line script. The moment your script runs in a cron job, a CI pipeline, or anything unattended, you need timestamps, severity levels, and the ability to turn verbosity up or down without editing code.

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

logger.debug("This won't show at INFO level")
logger.info("Starting deployment for checkout-api")
logger.warning("Retrying after a transient error")
logger.error("Deployment failed after 3 retries")
logger.critical("Rollback also failed — paging on-call")
```

```
2026-09-13 00:15:02 INFO Starting deployment for checkout-api
2026-09-13 00:15:04 WARNING Retrying after a transient error
```

The levels exist for a reason: `DEBUG` for details you only want when actively troubleshooting, `INFO` for normal operation milestones, `WARNING` for "handled it, but worth knowing," `ERROR` for "this failed," `CRITICAL` for "this failed in a way that needs a human now." Setting `level=logging.INFO` in production means `DEBUG` calls cost you nothing at runtime but stay available the moment you need to flip verbosity up.

---

## 4. Calling APIs — the `requests` library

The standard library has `urllib`, but nobody uses it by choice. `requests` (`pip install requests`) is the practical default for HTTP calls.

```python
import requests

response = requests.get("https://api.example.com/health", timeout=5)
response.raise_for_status()    # raises an exception if status is 4xx/5xx
data = response.json()          # parses the JSON body straight into a dict
print(data["status"])

# POST with a JSON body
response = requests.post(
    "https://api.example.com/deployments",
    json={"service": "checkout-api", "replicas": 3},
    headers={"Authorization": "Bearer some-token"},
    timeout=10,
)
```

Always set a `timeout`. Without one, a hung server on the other end can freeze your script indefinitely — the network equivalent of forgetting a `LIMIT` on a query against a table nobody knows the size of. This library, and how it fits into building real APIs rather than just calling them, is covered in far more depth in the [FastAPI guide](./what-devops-engineers-should-know-about-fastapi-in-production.md) once you're ready for that.

---

## 5. Exit codes — how your script talks to CI/CD

A script's exit code is the only thing most pipelines actually check. `0` means success, anything else means failure — this is true in Bash, and it's true in Python too.

```python
import sys

def main():
    if not deployment_succeeded():
        print("Deployment failed")
        sys.exit(1)     # non-zero — CI/CD will mark this step failed
    print("Deployment succeeded")
    sys.exit(0)          # explicit success — optional, 0 is the default if you don't call sys.exit at all

if __name__ == "__main__":
    main()
```

`if __name__ == "__main__":` is the standard guard that means "only run this block when the file is executed directly, not when it's imported by another script." You'll see this in almost every real Python file — it's what lets a file be both a runnable script and an importable module without the two uses fighting each other.

---

## 6. Putting it together: a capstone script

A small cluster health checker that reads a list of endpoints from a YAML file, checks each one, logs the results, and exits non-zero if anything's unhealthy — exactly the kind of thing that replaces a "run this and eyeball the output" manual check.

```yaml
# endpoints.yaml
endpoints:
  - name: checkout-api
    url: https://checkout.internal/health
  - name: auth-service
    url: https://auth.internal/health
```

```python
#!/usr/bin/env python3
"""Check the health of a list of services defined in a YAML file."""

import argparse
import logging
import sys

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_endpoints(config_path):
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config["endpoints"]


def check_endpoint(endpoint):
    name = endpoint["name"]
    url = endpoint["url"]
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        logger.info(f"{name}: healthy ({response.status_code})")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"{name}: unhealthy — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Check health of services in a YAML config")
    parser.add_argument("--config", default="endpoints.yaml", help="Path to endpoints YAML file")
    args = parser.parse_args()

    endpoints = load_endpoints(args.config)
    results = [check_endpoint(e) for e in endpoints]

    unhealthy_count = results.count(False)
    if unhealthy_count > 0:
        logger.error(f"{unhealthy_count} of {len(results)} services are unhealthy")
        sys.exit(1)

    logger.info(f"All {len(results)} services healthy")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

```bash
python check_health.py --config endpoints.yaml
```

Every piece of this script is something covered in files 01–06: variables and f-strings, a list comprehension, a dict/YAML config, a function per responsibility, `try`/`except` around the risky network call, `argparse` for input, `logging` instead of `print`, and an exit code a pipeline can act on. That's the whole roadmap, in about 40 lines.

---

## Cheatsheet

```python
# CLI args
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--service", required=True)
args = parser.parse_args()

# subprocess — pass a list, not a shell string
import subprocess
result = subprocess.run(["kubectl", "get", "pods"], capture_output=True, text=True, check=True)

# logging — not print()
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("message")

# requests — always set a timeout
import requests
r = requests.get(url, timeout=5)
r.raise_for_status()
data = r.json()

# exit codes
import sys
sys.exit(1)   # non-zero = failure, for CI/CD to catch

if __name__ == "__main__":
    main()
```

---

**You're through the roadmap.** Next up: [Pydantic](./python_pydantic_devops_guide.md) for type-safe config and data validation, then [FastAPI](./what-devops-engineers-should-know-about-fastapi-in-production.md) for building real internal APIs. If agents and LLM-powered tooling are the actual destination, head to [agentic-ai/](../agentic-ai/README.md) once you've got those two down.
