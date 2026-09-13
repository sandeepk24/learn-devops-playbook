# Python Modules, Packages, and Environments for DevOps Engineers
### Stage 3 of the [Python roadmap](./README.md)

> Goal of this file: use `import`, `pip`, and virtual environments correctly, and understand why "it works on my machine" happens so often with Python specifically.

---

## 1. Imports — using code someone else already wrote

```python
import os                          # import the whole module, access with os.something
print(os.getcwd())

from datetime import datetime      # import one specific thing from a module
now = datetime.now()

import json as j                   # alias — useful for long names, common convention (numpy as np, pandas as pd)
data = j.loads('{"a": 1}')

from pathlib import Path           # import a class directly
config_path = Path("/etc/myapp/config.yaml")
```

A **module** is just a `.py` file. A **package** is a folder of modules (with an `__init__.py`, though modern Python doesn't strictly require it). When you `import requests`, you're importing a package someone published; when you `import my_helpers` and you have a `my_helpers.py` sitting next to your script, you're importing your own module the exact same way.

### The standard library — what ships with Python for free

You don't need to install anything for these, and they cover an enormous amount of DevOps scripting:

| Module | What it's for |
|---|---|
| `os` | Environment variables, file paths, process info |
| `sys` | Command-line args, exit codes, interpreter details |
| `pathlib` | Modern, object-oriented file path handling |
| `json` | Parsing and writing JSON |
| `datetime` | Dates and times |
| `subprocess` | Running shell commands from Python |
| `re` | Regular expressions |
| `logging` | Proper logging instead of scattered `print()` calls |
| `argparse` | Parsing command-line flags for real CLI tools |

File 06 in this series covers `subprocess`, `argparse`, and `logging` in depth — this file is just the "how do I even get code into my script" layer underneath them.

---

## 2. `pip` — installing other people's code

```bash
pip install requests                # install the latest version
pip install requests==2.31.0        # pin an exact version — do this for anything real
pip install "requests>=2.28,<3.0"   # a version range
pip uninstall requests
pip show requests                   # see what's installed and where
pip list                             # everything installed in the current environment
```

### `requirements.txt` — pinning what your project needs

```
# requirements.txt
requests==2.31.0
pydantic==2.7.1
fastapi==0.115.0
```

```bash
pip install -r requirements.txt      # install everything listed
pip freeze > requirements.txt         # dump your current environment's exact versions
```

Pin your versions. "It worked yesterday" is a very common Python support ticket, and it's almost always an unpinned dependency that shipped a breaking change overnight.

---

## 3. Virtual environments — the single most important habit in this file

Here's the problem virtual environments solve: if you `pip install` everything globally, every project on your machine shares one pool of packages. Project A needs `requests==2.20`, Project B needs `requests==2.31`, and now you can't have both — something you'd never accept from Terraform provider versions, but people accept constantly from Python without a second thought.

A **virtual environment** is an isolated, project-specific install location for packages. Every real Python project gets one.

```bash
# Create a virtual environment (creates a .venv/ folder in your project)
python -m venv .venv

# Activate it — this changes your shell so `python` and `pip` point inside .venv/
source .venv/bin/activate         # macOS/Linux
# .venv\Scripts\activate           # Windows

# Your prompt changes to show you're inside it
(.venv) $ pip install requests    # installs into .venv/, not globally

# Deactivate when you're done
deactivate
```

> **The #1 beginner mistake:** running `pip install` without activating the virtual environment first, so packages land globally, and then wondering why the script "can't find" a package that's clearly installed — it's installed somewhere else. Get in the habit of checking `which python` and confirming it points inside `.venv/` before installing anything.

### A typical project layout

```
my-project/
├── .venv/                  # the virtual environment — never commit this
├── .gitignore              # should include .venv/
├── requirements.txt
├── main.py
└── README.md
```

```bash
# .gitignore
.venv/
__pycache__/
*.pyc
.env
```

### Modern alternatives worth knowing about

`venv` + `pip` is the built-in, always-available baseline, and it's what this series teaches because it needs zero extra tooling. In practice, a lot of teams now reach for faster, more opinionated tools once a project grows:

- **`uv`** — a much faster drop-in replacement for `pip`/`venv`, written in Rust. Increasingly the default recommendation in 2026.
- **`poetry`** — dependency management plus packaging in one tool, driven by a `pyproject.toml` file instead of `requirements.txt`.

Learn `venv`/`pip` first. They're the concepts every other tool is built on top of — `uv` and `poetry` just make the same ideas faster and more convenient.

---

## 4. A quick mental model, if you're coming from another ecosystem

| Concept | Python | Node.js | Terraform |
|---|---|---|---|
| Package installer | `pip` | `npm` | provider registry |
| Dependency file | `requirements.txt` / `pyproject.toml` | `package.json` | `.tf` provider blocks |
| Isolated environment | virtual environment (`venv`) | `node_modules/` (implicit, per-project) | `.terraform/` |
| Lockfile | (`uv.lock`, `poetry.lock` with modern tools) | `package-lock.json` | `.terraform.lock.hcl` |

The instinct you already have — "pin your versions, isolate your dependencies per project, don't install things globally if you can avoid it" — transfers directly. Python just makes you set the isolation up by hand with plain `venv`, instead of it happening automatically the way `node_modules/` does.

---

## Cheatsheet

```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# Confirm you're in it
which python   # should point inside .venv/

# Install and pin dependencies
pip install requests==2.31.0
pip freeze > requirements.txt
pip install -r requirements.txt

# Leave the environment
deactivate
```

```python
# Imports
import os
from datetime import datetime
import json as j
from pathlib import Path
```

---

**Next:** [`05-python-oop-files-and-error-handling.md`](./05-python-oop-files-and-error-handling.md) — reading/writing files, and grouping related data with classes.
