# Python Data Structures for DevOps Engineers
### Stage 1 of the [Python roadmap](./README.md)

> Goal of this file: get fluent with lists, dicts, tuples, and sets. This is the single highest-leverage topic in this whole series — almost every piece of real data you touch (JSON API responses, YAML configs, `kubectl` output parsed as JSON, Terraform state) lands in Python as one of these four shapes.

---

## Why this matters more than it sounds like it should

A Kubernetes manifest, a Terraform plan in JSON, an AWS API response — strip away the YAML/JSON formatting and every one of them is just nested lists and dictionaries. Once you're fluent in reading and building lists and dicts, "parse this API response and pull out what I need" stops being a research project and becomes a two-line script.

```python
import json

response = json.loads('{"cluster": "prod-east", "nodes": [{"name": "node-1", "ready": true}]}')
print(response["cluster"])              # prod-east
print(response["nodes"][0]["name"])     # node-1
```

That's it. `json.loads()` turns JSON text into exactly the structures covered in this file. There's no separate "JSON type" to learn.

---

## 1. Lists — ordered, changeable, duplicates allowed

A list is your go-to for "a bunch of things in order." Think of it like an array, if you've used one in any other language.

```python
servers = ["web-01", "web-02", "web-03"]

# Indexing — zero-based, like almost everything in programming
print(servers[0])       # web-01
print(servers[-1])      # web-03  (negative index = count from the end)

# Slicing — [start:stop], stop is exclusive
print(servers[0:2])     # ['web-01', 'web-02']
print(servers[1:])      # everything from index 1 onward
print(servers[:-1])     # everything except the last item

# Length
len(servers)             # 3

# Membership check
"web-02" in servers      # True
```

### Modifying a list

```python
servers.append("web-04")          # add to the end
servers.insert(0, "web-00")       # add at a specific position
servers.remove("web-02")          # remove by value (first match)
popped = servers.pop()            # remove and return the last item
servers.pop(0)                    # remove and return item at index 0

servers.sort()                    # sort in place, alphabetically
servers.sort(reverse=True)        # descending
sorted_copy = sorted(servers)     # returns a new sorted list, leaves original alone

servers.extend(["web-05", "web-06"])   # merge another list in
```

### List comprehensions — the pattern you'll use everywhere

A list comprehension builds a new list by applying an expression to every item in an existing one — it replaces the "loop that appends to an empty list" pattern almost every time.

```python
node_names = ["node-1", "node-2", "node-3"]

# The long way
upper_names = []
for name in node_names:
    upper_names.append(name.upper())

# The comprehension way — same result, one line
upper_names = [name.upper() for name in node_names]

# With a filter condition
prod_nodes = ["node-1", "test-node-2", "node-3"]
real_nodes = [n for n in prod_nodes if not n.startswith("test-")]
# ['node-1', 'node-3']
```

Once this clicks, you'll reach for it constantly — filtering unhealthy pods out of a list, pulling just the names out of a list of dicts, converting a list of strings to ints.

---

## 2. Tuples — ordered, unchangeable

A tuple looks like a list but can't be modified after creation. Use it when the data represents a fixed, related group of values — coordinates, a (host, port) pair, a row you're not going to mutate.

```python
endpoint = ("10.0.0.5", 443)          # (host, port)
host, port = endpoint                  # unpacking — very common pattern
print(f"Connecting to {host} on {port}")

# This fails on purpose:
endpoint[0] = "10.0.0.6"
# TypeError: 'tuple' object does not support item assignment
```

**Rule of thumb:** if you're going to add, remove, or reorder items, use a list. If the shape and meaning of the data is fixed once created, a tuple communicates that intent — and stops anyone (including future you) from accidentally mutating it.

---

## 3. Dictionaries — key/value pairs

If lists are "things in order," dicts are "things you look up by name." This is the shape almost all structured config and API data takes.

```python
server = {
    "hostname": "web-01",
    "ip_address": "10.0.0.1",
    "port": 443,
    "is_active": True,
}

print(server["hostname"])          # web-01

# .get() is the safe way to read — no crash if the key is missing
print(server.get("region"))              # None
print(server.get("region", "us-east-1")) # us-east-1  (default if missing)

# Direct access crashes if the key doesn't exist — use it only when you're sure
server["region"]
# KeyError: 'region'
```

### Working with the whole dict

```python
server["region"] = "us-east-1"     # add or overwrite a key
del server["is_active"]             # remove a key

for key in server:                  # iterates over keys by default
    print(key)

for key, value in server.items():   # the pattern you'll use constantly
    print(f"{key}: {value}")

server.keys()                       # dict_keys(['hostname', 'ip_address', ...])
server.values()                     # dict_values(['web-01', '10.0.0.1', ...])
```

### Nested dicts — this is what real config looks like

```python
deployment = {
    "name": "checkout-api",
    "replicas": 3,
    "resources": {
        "cpu": "500m",
        "memory": "512Mi",
    },
    "containers": [
        {"name": "app", "image": "checkout:v1.2"},
        {"name": "sidecar", "image": "envoy:v1.28"},
    ],
}

print(deployment["resources"]["memory"])        # 512Mi
print(deployment["containers"][0]["image"])     # checkout:v1.2
```

This is exactly what a parsed Helm `values.yaml` or a Kubernetes manifest loaded as JSON looks like once it's in Python. Nothing special happens at the "nested" boundary — it's dicts and lists, all the way down.

### Dict comprehensions

```python
raw_ports = {"http": "80", "https": "443"}

# Convert every value from string to int
int_ports = {key: int(value) for key, value in raw_ports.items()}
# {'http': 80, 'https': 443}
```

---

## 4. Sets — unique values, no order

A set is a list with two rules: no duplicates, and it doesn't remember insertion order. Use it when you care about membership and uniqueness, not sequence.

```python
current_tags = {"env:prod", "team:platform", "tier:backend"}
required_tags = {"env:prod", "team:platform", "owner:sre"}

# Set operations — this is where sets earn their keep
missing_tags = required_tags - current_tags       # {'owner:sre'}
common_tags = required_tags & current_tags         # intersection
all_tags = required_tags | current_tags             # union
```

### A real use case: diffing two lists of servers

This is the kind of thing you'd otherwise write a clunky nested loop for:

```python
desired_servers = {"web-01", "web-02", "web-03", "web-04"}
running_servers = {"web-01", "web-02", "web-05"}

to_create = desired_servers - running_servers   # {'web-03', 'web-04'}
to_remove = running_servers - desired_servers   # {'web-05'}

print(f"Need to create: {to_create}")
print(f"Need to remove: {to_remove}")
```

That's the core idea behind every reconciliation loop you've ever depended on — a Kubernetes controller comparing desired state to actual state and closing the gap. Sets make the comparison trivial instead of a loop-and-a-half of bookkeeping.

---

## 5. Strings, revisited as sequences

Strings behave like a list of characters for indexing and slicing purposes, and they come with methods you'll use in almost every script that touches text.

```python
line = "  ERROR: connection refused  "

line.strip()                    # "ERROR: connection refused" — trims whitespace
line.strip().lower()            # "error: connection refused"
line.strip().split(":")         # ['ERROR', ' connection refused']
"-".join(["us", "east", "1"])   # "us-east-1"
line.replace("ERROR", "WARN")   # swap substrings
line.strip().startswith("ERROR")  # True
```

Parsing a log line, building a resource name, splitting a comma-separated env var — it all comes back to these five or six methods.

---

## 6. Choosing the right structure

| Need | Use |
|---|---|
| Order matters, values can repeat, might change | `list` |
| Order matters, fixed once created | `tuple` |
| Look things up by name | `dict` |
| Only care about uniqueness/membership, order doesn't matter | `set` |

---

## 7. The mutability trap

This one bites everyone eventually, usually while debugging something that "shouldn't be possible."

```python
def add_default_tag(tags=[]):     # ⚠️ mutable default argument — a classic trap
    tags.append("managed-by:script")
    return tags

print(add_default_tag())   # ['managed-by:script']
print(add_default_tag())   # ['managed-by:script', 'managed-by:script'] — wait, what?
```

The default list is created **once**, when the function is defined, and reused on every call that doesn't pass its own value — it isn't reset each time. Fix it like this:

```python
def add_default_tag(tags=None):
    if tags is None:
        tags = []
    tags.append("managed-by:script")
    return tags
```

The other side of this: assigning a list to a new variable doesn't copy it — both names point at the same list.

```python
original = ["web-01", "web-02"]
alias = original
alias.append("web-03")
print(original)   # ['web-01', 'web-02', 'web-03'] — original changed too!

# To actually copy:
real_copy = original.copy()          # or original[:] or list(original)
```

For nested structures (a list of dicts, a dict of lists), a shallow `.copy()` only copies the outer layer — use `copy.deepcopy()` from the standard library if you need a fully independent copy of nested data.

---

## Cheatsheet

```python
# List
servers = ["a", "b", "c"]
servers.append("d")
servers[0]              # "a"
servers[-1]             # "d"
[s.upper() for s in servers]

# Tuple
point = (10, 20)
x, y = point

# Dict
config = {"port": 8080}
config.get("port", 80)     # safe read with default
config["host"] = "0.0.0.0"
{k: v for k, v in config.items()}

# Set
a = {1, 2, 3}
b = {2, 3, 4}
a - b     # {1}
a & b     # {2, 3}
a | b     # {1, 2, 3, 4}

# Copying (don't just assign if you need an independent copy)
new_list = old_list.copy()
import copy
new_nested = copy.deepcopy(old_nested)
```

---

**Next:** [`03-python-control-flow-and-functions.md`](./03-python-control-flow-and-functions.md) — loops, conditionals, and writing functions that don't turn into spaghetti.
