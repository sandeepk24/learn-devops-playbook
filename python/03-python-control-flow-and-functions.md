# Python Control Flow and Functions for DevOps Engineers
### Stage 2 of the [Python roadmap](./README.md)

> Goal of this file: write conditionals, loops, and functions that read clearly, plus enough error handling that your scripts fail loudly instead of silently doing the wrong thing.

---

## 1. Conditionals

```python
status_code = 503

if status_code == 200:
    print("healthy")
elif status_code >= 500:
    print("server error — page someone")
elif status_code >= 400:
    print("client error — probably not your fault")
else:
    print("unexpected status")
```

### Comparison and boolean operators

```python
replicas == 3          # equal
replicas != 3           # not equal
replicas > 0 and replicas < 10     # both must be true
replicas < 1 or cpu_usage > 90     # either can be true
not is_healthy                      # negation

# `and` / `or` in Python are spelled out — no &&, ||
```

### Truthy and falsy values — the thing that trips up almost everyone

Python treats more than just `True`/`False` as truthy or falsy in an `if` check. This is genuinely useful once you know it, and a source of confusing bugs until then.

```python
# All of these are "falsy" — an if check treats them as False
if []:        pass   # empty list — falsy
if {}:        pass   # empty dict — falsy
if "":        pass   # empty string — falsy
if 0:         pass   # zero — falsy
if None:      pass   # None — falsy

# Anything else is "truthy"
if ["web-01"]:   pass   # non-empty list — truthy
if "prod":        pass   # non-empty string — truthy
```

In practice:

```python
unhealthy_nodes = []

# Both of these do the same thing — the second is the idiomatic Python way
if len(unhealthy_nodes) == 0:
    print("all clear")

if not unhealthy_nodes:
    print("all clear")
```

The gotcha: this means `0` and `""` are treated the same as "missing" by a plain `if`, even though a replica count of `0` or an empty string might be a perfectly valid, meaningful value you actually need to check for. When that distinction matters, compare explicitly: `if replica_count is not None:` rather than `if replica_count:`.

---

## 2. Loops

### `for` — iterate over anything iterable

```python
servers = ["web-01", "web-02", "web-03"]

for server in servers:
    print(f"Checking {server}")

# range() — for when you need a count, not real items
for i in range(5):          # 0, 1, 2, 3, 4
    print(i)

for i in range(2, 10, 2):   # start, stop (exclusive), step → 2, 4, 6, 8
    print(i)
```

### `enumerate()` — when you need the index and the value

```python
for index, server in enumerate(servers):
    print(f"{index}: {server}")
# 0: web-01
# 1: web-02
# 2: web-03
```

### `zip()` — loop over two lists together

```python
names = ["web-01", "web-02"]
statuses = ["healthy", "degraded"]

for name, status in zip(names, statuses):
    print(f"{name} is {status}")
```

### `while` — loop until a condition changes

```python
attempts = 0
max_attempts = 5

while attempts < max_attempts:
    print(f"Attempt {attempts + 1}")
    attempts += 1   # Python has no ++ — this is how you increment
```

### `break` and `continue`

```python
for server in servers:
    if server == "web-02":
        continue   # skip this one, keep going
    if server == "web-03":
        break       # stop the loop entirely
    print(server)
```

> **Watch for this:** a `while` loop with a condition that never becomes false is an infinite loop that will happily eat 100% CPU until you kill it. Always be sure something inside the loop moves it toward the exit condition.

---

## 3. Functions

```python
def restart_service(service_name, force=False):
    """Restart the named service. Set force=True to skip the health check."""
    if not force:
        print(f"Checking health of {service_name}...")
    print(f"Restarting {service_name}")
    return True

result = restart_service("checkout-api")
result = restart_service("checkout-api", force=True)
result = restart_service(service_name="checkout-api", force=True)   # named args
```

### Default arguments, `*args`, and `**kwargs`

```python
def scale_service(name, replicas=1):     # replicas defaults to 1 if not passed
    print(f"Scaling {name} to {replicas} replicas")

def tag_resources(*resource_ids):         # collects any number of positional args into a tuple
    for r in resource_ids:
        print(f"Tagging {r}")

tag_resources("i-001", "i-002", "i-003")

def create_deployment(name, **labels):    # collects any number of keyword args into a dict
    print(f"Creating {name} with labels: {labels}")

create_deployment("web-app", env="prod", team="platform")
# Creating web-app with labels: {'env': 'prod', 'team': 'platform'}
```

You'll see `*args` and `**kwargs` constantly in library code (they let a function accept "whatever you throw at it" and forward it along) even if you rarely need to write them yourself early on.

### Return values

```python
def check_disk_usage(percent_used):
    if percent_used > 90:
        return "critical"
    if percent_used > 75:
        return "warning"
    return "ok"

# A function with no explicit return gives back None
def log_only(message):
    print(message)

result = log_only("hi")
print(result)   # None
```

Functions can return multiple values — Python packs them into a tuple automatically:

```python
def get_connection_info():
    return "10.0.0.5", 5432    # returns a tuple

host, port = get_connection_info()   # unpacked directly
```

### Lambda functions — small, anonymous, use sparingly

```python
square = lambda x: x * x
square(4)   # 16

# Most common real use: as the sort key
servers = [{"name": "web-01", "cpu": 80}, {"name": "web-02", "cpu": 45}]
servers.sort(key=lambda s: s["cpu"])
```

If the logic is more than one short expression, write a normal `def` function instead and give it a name. A named function is documentation; a lambda is a shrug.

---

## 4. Error handling

A script that crashes with a raw traceback in the middle of a pipeline is bad. A script that catches every possible error and silently swallows it is worse — it hides real failures. The goal is to catch specific, expected failures and let everything else surface loudly.

```python
try:
    response = call_deploy_api(service_name)
except ConnectionError:
    print("Could not reach the deployment API — is it up?")
except TimeoutError:
    print("Deployment API timed out")
else:
    print("Call succeeded, no exception raised")
finally:
    print("This always runs — cleanup goes here")
```

- `try` — the code that might fail
- `except` — what to do for a specific error type
- `else` — runs only if no exception was raised (rarely used, but exists)
- `finally` — always runs, whether it succeeded or failed — the place for cleanup like closing a connection

### Why bare `except:` is a trap

```python
# Don't do this
try:
    deploy(service)
except:
    pass   # silently swallows EVERYTHING, including Ctrl+C and typos in your own code

# Do this instead
try:
    deploy(service)
except (ConnectionError, TimeoutError) as e:
    print(f"Deployment failed: {e}")
    raise    # re-raise if you can't actually recover — don't pretend it's fine
```

A bare `except:` catches things you never meant to catch — including `KeyboardInterrupt` when someone hits Ctrl+C, and `SyntaxError`-adjacent issues in code you're dynamically evaluating. Always name the exception type you're expecting.

### Raising your own errors

```python
def scale_service(name, replicas):
    if replicas < 0:
        raise ValueError(f"replicas cannot be negative, got {replicas}")
    if replicas > 100:
        raise ValueError(f"replicas cannot exceed 100, got {replicas}")
    print(f"Scaling {name} to {replicas}")

scale_service("web-app", -1)
# ValueError: replicas cannot be negative, got -1
```

### Custom exceptions — worth it once your scripts get bigger

```python
class DeploymentError(Exception):
    """Raised when a deployment fails for a reason the caller should handle specifically."""
    pass

def deploy(service_name):
    if service_name == "":
        raise DeploymentError("service_name cannot be empty")
    # ...

try:
    deploy("")
except DeploymentError as e:
    print(f"Deployment-specific failure: {e}")
```

This matters once you have more than one kind of failure a caller might want to react to differently — a custom exception type lets `except DeploymentError` catch exactly your errors without accidentally swallowing unrelated bugs.

### A pattern you'll use constantly: retry with backoff

```python
import time

def call_flaky_api(max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            return do_api_call()
        except ConnectionError as e:
            if attempt == max_retries:
                raise   # out of retries, let the caller know it really failed
            wait_seconds = 2 ** attempt   # 2, 4, 8...
            print(f"Attempt {attempt} failed ({e}), retrying in {wait_seconds}s")
            time.sleep(wait_seconds)
```

This is the manual version of what libraries like `tenacity` do for you — worth understanding by hand before you reach for the library.

---

## Cheatsheet

```python
# Conditionals
if x > 0:
    ...
elif x == 0:
    ...
else:
    ...

# Falsy: [], {}, "", 0, None, False
# Truthy: everything else

# Loops
for item in items: ...
for i, item in enumerate(items): ...
for a, b in zip(list_a, list_b): ...
while condition: ...
break / continue

# Functions
def f(a, b=1, *args, **kwargs):
    return a + b

# Error handling
try:
    risky()
except SpecificError as e:
    handle(e)
finally:
    cleanup()

raise ValueError("clear message about what went wrong")
```

---

**Next:** [`04-python-modules-packages-and-environments.md`](./04-python-modules-packages-and-environments.md) — `pip`, virtual environments, and imports without breaking your system Python.
