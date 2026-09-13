# Python for DevOps Engineers — A Roadmap from Zero to Comfortable

> **Who this is for:** DevOps and cloud engineers who can write a Bash script and a Terraform module but freeze a little when someone says "just write a quick Python script for that." This series gets you from nothing to genuinely comfortable — enough to read other people's code, write your own automation, and follow the more advanced guides already in this repo.

---

## Why bother with Python if Bash already works

Bash is fine for "run these three commands in order." It falls apart fast once you need real data structures, error handling that doesn't involve grepping exit codes, or anything that talks to an API and does something with the JSON that comes back. Python is the language almost every tool in your stack is either written in or scriptable from — Ansible, AWS CDK, the `kubernetes` and `boto3` clients, most CI/CD glue code, and every LLM/agent SDK you'll touch this year. You don't need to become a software engineer. You need enough Python to stop copy-pasting Stack Overflow snippets you don't understand.

This series is deliberately narrow. It skips the trivia that Python courses love (metaclasses, operator overloading, the finer points of the descriptor protocol) and spends the time instead on the things that show up constantly in DevOps work: parsing config files, calling APIs, writing scripts that don't fall over, and structuring code well enough that the next person (probably you, in six months) can read it.

---

## The roadmap

| Stage | File | What you'll be able to do after |
|---|---|---|
| 0 | [`01-python-basics-and-setup.md`](./01-python-basics-and-setup.md) | Install Python properly, run a script, use variables and basic types without guessing |
| 1 | [`02-python-data-structures.md`](./02-python-data-structures.md) | Work with lists, dicts, tuples, and sets — the shapes almost all real data comes in (JSON, YAML, API responses) |
| 2 | [`03-python-control-flow-and-functions.md`](./03-python-control-flow-and-functions.md) | Write loops, conditionals, and functions that don't turn into 200-line messes |
| 3 | [`04-python-modules-packages-and-environments.md`](./04-python-modules-packages-and-environments.md) | Use `pip`, virtual environments, and imports without breaking your system Python |
| 4 | [`05-python-oop-files-and-error-handling.md`](./05-python-oop-files-and-error-handling.md) | Read and write files/JSON/YAML, group related data with classes and dataclasses, and handle errors instead of letting scripts explode |
| 5 | [`06-python-scripting-for-devops-automation.md`](./06-python-scripting-for-devops-automation.md) | Write a real automation script: CLI args, `subprocess`, logging, HTTP calls, exit codes that CI/CD actually respects |

That's "basics to intermediate." Once you're through stage 5, you're ready for the production-grade material already in this folder:

| Stage | File | What it adds |
|---|---|---|
| 6 | [`python_pydantic_devops_guide.md`](./python_pydantic_devops_guide.md) | Type-safe data validation for configs, API payloads, and infra models |
| 7 | [`what-devops-engineers-should-know-about-fastapi-in-production.md`](./what-devops-engineers-should-know-about-fastapi-in-production.md) | Building and shipping real internal APIs and model-serving endpoints |
| 8 | [`uvicorn-vs-gunicorn-explained.md`](./uvicorn-vs-gunicorn-explained.md) | What actually runs your API in production, and how to size it |

And if you're heading toward building agents rather than just APIs, the [`agentic-ai/`](../agentic-ai/README.md) series picks up from there.

---

## A realistic weekly plan

Nobody learns a language from a table of contents. Here's a pace that works if you've got an hour or two a day and you actually type the examples instead of reading them like a novel.

| Week | Focus | Goal by end of week |
|---|---|---|
| 1 | Files 01–02 | You can open a script, declare variables, and manipulate a list or dict without looking it up every time |
| 2 | Files 03–04 | You can write a function with a loop inside it, and you've created and used a virtual environment without panicking |
| 3 | Files 05–06 | You can write a script that reads a config file, calls an API, logs what happened, and exits with the right code |
| 4 | Pydantic + FastAPI guides | You can read (and start writing) the kind of Python that shows up in a real internal tool or automation API |
| 5 | Build something real | Pick a task you already do manually — checking service health, tagging untagged resources, summarizing a log file — and script it end to end |

Week 5 is the part people skip and shouldn't. Reading about `subprocess` and actually needing `subprocess` to solve a real annoyance are two different levels of understanding.

---

## Prerequisites

None, honestly. If you can write a `for` loop in Bash or read a Terraform `.tf` file, you already have more of the right instincts than you think — variables, conditionals, and "do this for each item in a list" exist in every language, just with different punctuation.

You'll want:
- A terminal (you already have one)
- Python 3.11+ (file 01 covers installing it properly)
- A text editor with Python support (VS Code, Cursor, PyCharm — anything that shows you errors as you type)

---

## How to use this series

Go in order the first time. Each file assumes you've read the ones before it and stops explaining things it already covered. After that, it's a reference — jump straight to the file that answers your immediate question and use the cheatsheet at the bottom of each one.

Every code example is meant to be run, not just read. Type it in, break it, change a value and see what happens. That's where the actual learning happens — not from staring at a code block.

---

*Part of the [learn-devops-playbook](https://github.com/sandeepk24/learn-devops-playbook) series.*
