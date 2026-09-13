# Python OOP, Files, and Error Handling for DevOps Engineers
### Stage 4 of the [Python roadmap](./README.md)

> Goal of this file: read and write files (including JSON and YAML), and understand just enough classes and dataclasses to group related data cleanly instead of passing around five separate variables that all belong together.

---

## 1. Why classes matter even for scripts, not just "real software"

If you find yourself writing a function that takes `hostname, port, region, is_healthy` as four separate parameters, and another function that takes the exact same four things, that's a sign those four values are really one thing — a `Server` — and should travel together.

```python
class Server:
    def __init__(self, hostname, port, region, is_healthy=True):
        self.hostname = hostname
        self.port = port
        self.region = region
        self.is_healthy = is_healthy

    def describe(self):
        status = "healthy" if self.is_healthy else "unhealthy"
        return f"{self.hostname}:{self.port} ({self.region}) — {status}"

web01 = Server("web-01", 443, "us-east-1")
print(web01.describe())
# web-01:443 (us-east-1) — healthy
print(web01.hostname)   # attribute access
```

- `__init__` is the constructor — it runs when you create an instance (`Server(...)`) and sets up its initial state.
- `self` refers to "this specific instance." It's the first parameter of every method, and Python passes it automatically — you never pass it yourself when calling.
- A **method** is just a function that lives inside a class and operates on `self`.

### Inheritance, briefly

```python
class Server:
    def __init__(self, hostname):
        self.hostname = hostname

class DatabaseServer(Server):          # DatabaseServer "is a" Server, plus extras
    def __init__(self, hostname, engine):
        super().__init__(hostname)      # call the parent's __init__ first
        self.engine = engine

db = DatabaseServer("db-01", "postgres")
print(db.hostname, db.engine)   # db-01 postgres
```

Inheritance is worth recognizing when you read it, but resist reaching for deep class hierarchies in scripts — most DevOps automation doesn't need it. Composition (a class that holds other objects as attributes) solves more problems more simply than a tall inheritance tree.

---

## 2. Dataclasses — the shortcut you'll actually use

Writing `__init__` by hand for every attribute gets old fast. `dataclasses` (built into the standard library) generates it for you.

```python
from dataclasses import dataclass, field

@dataclass
class Server:
    hostname: str
    port: int
    region: str = "us-east-1"          # default value
    tags: list[str] = field(default_factory=list)   # safe way to default to a mutable type

web01 = Server(hostname="web-01", port=443)
print(web01)
# Server(hostname='web-01', port=443, region='us-east-1', tags=[])
```

Notice the type hints (`str`, `int`, `list[str]`) — they don't enforce anything at runtime by themselves, but they document intent and let your editor catch mistakes before you run the code. This is the exact same idea the [Pydantic guide](./python_pydantic_devops_guide.md) builds on — Pydantic is essentially "a dataclass, but it actually validates the types at runtime and rejects bad data." Get comfortable with plain dataclasses first; Pydantic will feel like a natural next step instead of a wall of new syntax.

**Rule of thumb:** reach for a dataclass the moment you're grouping 3+ related values. Reach for a full class with custom methods once that group also needs behavior attached to it (like `.describe()` above).

---

## 3. Files — reading and writing

```python
# Writing
with open("output.txt", "w") as f:
    f.write("deployment completed\n")
    f.write("status: success\n")

# Reading — the whole file at once
with open("output.txt", "r") as f:
    contents = f.read()

# Reading line by line — better for large files, avoids loading it all into memory
with open("output.txt", "r") as f:
    for line in f:
        print(line.strip())    # .strip() removes the trailing newline

# Appending instead of overwriting
with open("output.txt", "a") as f:
    f.write("another line\n")
```

### `with` is a context manager — always use it for files

```python
# Don't do this:
f = open("output.txt", "r")
contents = f.read()
f.close()          # easy to forget, and skipped entirely if an exception happens first

# Do this:
with open("output.txt", "r") as f:
    contents = f.read()
# file is automatically closed here, even if something inside the block raised an error
```

`with` guarantees cleanup happens no matter how the block exits — the same reasoning behind always using a `finally` block or a `trap` in Bash for cleanup, just built into the language here.

### JSON — read and write directly

```python
import json

data = {"service": "checkout-api", "replicas": 3}

# Write a Python dict to a JSON file
with open("config.json", "w") as f:
    json.dump(data, f, indent=2)

# Read a JSON file into a Python dict
with open("config.json", "r") as f:
    loaded = json.load(f)

# Convert to/from a JSON string directly (no file involved)
json_string = json.dumps(data)          # dict → string
parsed = json.loads(json_string)         # string → dict
```

`load`/`dump` work with file objects. `loads`/`dumps` work with strings. Mixing these up (`json.load()` on a string instead of a file) is a common, easy-to-fix error — the message will tell you it expected something with a `.read()` method.

### YAML — needs one extra package, otherwise identical shape

YAML isn't in the standard library — install `pyyaml` first (`pip install pyyaml`).

```python
import yaml

# Read a YAML file — comes back as the same nested dicts/lists as JSON
with open("values.yaml", "r") as f:
    config = yaml.safe_load(f)

print(config["replicaCount"])

# Write YAML
with open("output.yaml", "w") as f:
    yaml.safe_dump({"replicaCount": 3, "image": {"tag": "v1.2"}}, f)
```

Use `yaml.safe_load()`, not `yaml.load()`. Plain `yaml.load()` can execute arbitrary Python objects embedded in the file — a real security issue if the YAML ever comes from somewhere you don't fully control (a webhook, a PR, a config someone else wrote).

### `pathlib` — the modern way to handle file paths

```python
from pathlib import Path

config_dir = Path("/etc/myapp")
config_file = config_dir / "config.yaml"    # / actually joins paths — no manual string concatenation

print(config_file.exists())
print(config_file.name)          # config.yaml
print(config_file.parent)        # /etc/myapp
print(config_file.suffix)        # .yaml

for file in config_dir.glob("*.yaml"):     # list matching files
    print(file)

config_file.read_text()           # read a whole text file in one call
config_file.write_text("data")    # write a whole text file in one call
```

`pathlib` replaces most of what you'd otherwise do with `os.path.join()` and manual string slicing, and it reads closer to plain English.

---

## 4. Error handling, revisited with files

File operations fail constantly in the real world — permissions, missing files, disks that fill up mid-write. Handle it explicitly instead of letting the traceback speak for you in a pipeline log nobody reads carefully.

```python
from pathlib import Path

config_path = Path("/etc/myapp/config.yaml")

try:
    config = yaml.safe_load(config_path.read_text())
except FileNotFoundError:
    print(f"Config file not found at {config_path} — using defaults")
    config = {}
except yaml.YAMLError as e:
    print(f"Config file exists but isn't valid YAML: {e}")
    raise    # this one you probably can't safely recover from — let it stop the script
```

---

## Cheatsheet

```python
# Classes
class Server:
    def __init__(self, hostname, port):
        self.hostname = hostname
        self.port = port

# Dataclasses — the shortcut
from dataclasses import dataclass, field

@dataclass
class Server:
    hostname: str
    port: int
    tags: list[str] = field(default_factory=list)

# Files
with open("f.txt", "r") as f:
    contents = f.read()

# JSON
import json
json.load(file_obj)      # file -> dict
json.dump(data, file_obj) # dict -> file
json.loads(string)        # string -> dict
json.dumps(data)           # dict -> string

# YAML (pip install pyyaml)
import yaml
yaml.safe_load(text)       # text -> dict/list
yaml.safe_dump(data, file_obj)

# pathlib
from pathlib import Path
p = Path("/etc/app") / "config.yaml"
p.exists() / p.read_text() / p.write_text(...)
```

---

**Next:** [`06-python-scripting-for-devops-automation.md`](./06-python-scripting-for-devops-automation.md) — CLI args, `subprocess`, logging, and HTTP calls: turning everything so far into a real automation script.
