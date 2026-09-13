# Python Basics and Setup for DevOps Engineers
### Stage 0 of the [Python roadmap](./README.md)

> Goal of this file: get Python installed properly, run your first script, and understand variables and basic types well enough that they stop feeling like guesswork.

---

## 1. Installing Python without shooting yourself in the foot

Every OS ships with some version of Python already, and the first rule is: **don't use it for your own work.** macOS and most Linux distros use their system Python for internal tooling. Installing packages into it, or upgrading it, can quietly break parts of your OS. This is the DevOps equivalent of SSHing into a shared jump box and installing random packages as root — technically possible, professionally unwise.

Use a version manager instead so you can install and switch Python versions cleanly, the same way you'd use `nvm` for Node or `tfenv` for Terraform.

```bash
# macOS / Linux — pyenv is the standard choice
curl https://pyenv.run | bash

# Add to your shell profile (~/.zshrc or ~/.bashrc), then restart your shell
echo 'eval "$(pyenv init -)"' >> ~/.zshrc

# Install a real version and set it as your default
pyenv install 3.12.4
pyenv global 3.12.4

# Verify
python --version
# Python 3.12.4
```

If you're on a locked-down corporate machine where `pyenv` isn't an option, [python.org](https://www.python.org/downloads/) installers work fine too. Just don't touch `/usr/bin/python3`.

### Checking what you've got

```bash
python --version          # or python3 --version on some systems
which python               # confirm which binary you're actually running
pip --version               # your package installer, comes bundled with Python
```

> **Common gotcha:** on many systems `python` points to Python 2 (or nothing) and `python3` points to Python 3. If a command isn't found, try the `3` suffix before assuming something's broken.

---

## 2. Running Python code — three ways

**1. The REPL** (Read-Eval-Print Loop) — type `python` in your terminal and you get an interactive prompt. Great for testing a one-liner, terrible for anything you want to keep.

```bash
$ python
>>> 2 + 2
4
>>> exit()
```

**2. A script file** — the way you'll actually work.

```python
# hello.py
print("hello from a script")
```

```bash
python hello.py
```

**3. A shebang, for executable scripts** — the DevOps-native way to ship a Python script like you'd ship a shell script.

```python
#!/usr/bin/env python3
print("this file can run on its own")
```

```bash
chmod +x hello.py
./hello.py
```

---

## 3. Variables and types

Python is **dynamically typed** — you don't declare a type up front — but every value still has a type under the hood, and the language cares about it a lot when you try to mix them.

```python
service_name = "checkout-api"      # str
replica_count = 3                  # int
cpu_usage_percent = 42.7           # float
is_healthy = True                  # bool
last_deploy = None                 # NoneType — Python's "nothing here"

print(type(service_name))          # <class 'str'>
```

### The types you'll actually use

| Type | Example | Notes |
|---|---|---|
| `str` | `"prod-east-1"` | Text. Single or double quotes both work — be consistent. |
| `int` | `443` | Whole numbers. No size limit in Python (unlike most languages). |
| `float` | `99.9` | Decimal numbers. Watch for floating-point rounding surprises. |
| `bool` | `True` / `False` | Capitalized — `true` is not valid Python. |
| `NoneType` | `None` | Python's null. Not `0`, not `""`, not `False` — a distinct "no value." |

### Type coercion bites people

```python
port = "443"
port + 1
# TypeError: can only concatenate str (not "int") to str

port = int(port)   # explicit conversion first
port + 1            # 444, now it works
```

Bash will silently treat `"443"` as a number when it feels like it. Python won't guess for you — you convert explicitly with `int()`, `str()`, `float()`, `bool()`. This feels annoying on day one and saves you from an entire category of bugs by day thirty.

### f-strings — how you actually build strings

```python
service = "auth-service"
replicas = 3

# Don't do this:
message = "Service " + service + " has " + str(replicas) + " replicas"

# Do this:
message = f"Service {service} has {replicas} replicas"
print(message)
# Service auth-service has 3 replicas

# Expressions work inside the braces too
print(f"Half the replicas: {replicas // 2}")
```

You'll write f-strings constantly — in log messages, in generated YAML, in error messages. Get comfortable with them now.

---

## 4. Comments and docstrings

```python
# A single-line comment — explains the "why," not the "what"
replicas = 3  # inline comments work too, use sparingly

def restart_service(name):
    """
    Restarts the named service.

    This is a docstring — a comment that documents the function itself.
    Tools, IDEs, and help() all read this.
    """
    pass
```

Comment like you're leaving a note for the on-call engineer who's never seen this script before, at 2 a.m., under pressure. That's usually you, later.

---

## 5. Basic input and output

```python
print("plain output")
print("value:", 42)                      # print() can take multiple arguments
print("no newline", end="")              # suppress the trailing newline

# Reading user input (rare in automation scripts, common in interactive ones)
name = input("Enter environment name: ")

# Reading command-line arguments (the way real scripts take input — covered fully in file 06)
import sys
print(sys.argv)      # ['script.py', 'arg1', 'arg2', ...]
```

---

## 6. A first practical script

Something small enough to type in thirty seconds, but shaped like the scripts you'll actually write later:

```python
#!/usr/bin/env python3
import os

environment = os.getenv("ENVIRONMENT", "development")
debug_mode = os.getenv("DEBUG", "false").lower() == "true"

print(f"Starting up in {environment} mode")
if debug_mode:
    print("Debug logging is ON — don't leave this on in prod")
```

```bash
ENVIRONMENT=production python startup_check.py
# Starting up in production mode
```

This is the exact pattern behind every `Settings` class you'll see in the [Pydantic guide](./python_pydantic_devops_guide.md) later — read config from the environment, with a sane default.

---

## 7. Mistakes almost everyone makes in week one

- **Indentation is not decoration — it's syntax.** Python uses whitespace to define code blocks instead of `{}`. Mixing tabs and spaces will produce a confusing `IndentationError`. Set your editor to insert spaces, not tabs, and never mix them.
- **`=` vs `==`.** One assigns, one compares. `if status = "running":` is a syntax error on purpose — Python won't let you make this typo silently the way some languages do.
- **Case sensitivity.** `Environment` and `environment` are two different names. This trips up people coming from case-insensitive shell habits.
- **Forgetting the colon.** Every `if`, `for`, `while`, `def`, and `class` line ends in `:`. It's small enough to forget constantly for the first week.

---

## Cheatsheet

```python
# Variables — no declared type, but every value has one
name = "web-01"
port = 8080
ratio = 0.75
enabled = True
missing = None

# Type checks and conversion
type(port)          # <class 'int'>
str(port)            # "8080"
int("8080")          # 8080

# f-strings
f"{name}:{port}"     # "web-01:8080"

# Running scripts
# python script.py
# ./script.py   (needs #!/usr/bin/env python3 + chmod +x)
```

---

**Next:** [`02-python-data-structures.md`](./02-python-data-structures.md) — the shapes your data actually comes in: lists, dicts, tuples, and sets.
