# AGENT.md — Python Coding Standards

This file defines how this agent should write, review, and refactor Python code.
The guiding principle: **clean code isn't about looking pretty — it's about reducing
the amount of thinking required for the next person (or agent) to understand it.**
Prefer removing unnecessary complexity over adding clever complexity.

When writing or reviewing Python code, follow all seven rules below. If a rule is
violated, fix it before considering the task complete.

---

## 1. Never catch errors you don't understand

Do not use bare `except:` or overly broad `except Exception:` blocks to hide
problems. A bare `except` also swallows things like `KeyboardInterrupt` and
`SystemExit`, which you almost never want to suppress.

**Rules:**
- Catch the *specific* exception you expect, nothing broader.
- Keep the `try` block as small as possible — wrap only the line(s) that can
  actually raise the error.
- Never use exception handling to hide or paper over bugs. Use it only to
  handle failure cases you understand and intend to recover from.

**Bad:**
```python
def get_customer(customers, customer_id):
    try:
        return customers[customer_id]
    except:
        return None
```

**Good:**
```python
def get_customer(customers, customer_id):
    try:
        return customers[customer_id]
    except KeyError:
        return None
```

---

## 2. Use Python's built-in patterns instead of reinventing them

Python already provides expressive, well-tested tools for common operations.
Reach for them instead of writing manual logic — they also make intent clearer
to the reader.

| Instead of...                          | Use...                          |
|-----------------------------------------|----------------------------------|
| Manual string slicing to check a prefix | `str.startswith(...)`            |
| Manually tracking an index in a loop    | `enumerate(...)`                 |
| Looping to check if any item matches    | `any(...)`                       |
| `if key in dict: dict[key] else None`   | `dict.get(key)`                  |

**Bad:**
```python
found = False
for item in items:
    if item.status == "failed":
        found = True
        break
```

**Good:**
```python
found = any(item.status == "failed" for item in items)
```

This is not about memorizing every trick in the language — it's about being
familiar enough with Python's idioms that your code reads naturally.

---

## 3. Write code for the reader, not just the interpreter

Code must make sense to Python *and* to the human who opens it next. Avoid
vague names and clever-but-opaque expressions that force the reader to trace
through logic to understand intent.

**Bad:**
```python
def get_data(x):
    if x != None:
        ...
```

**Good:**
```python
def get_customer_orders(customer):
    if customer is not None:
        ...
```

Prefer the direct, idiomatic expression of a condition (`is not None`, not
`!= None`) over anything that requires a second look to parse.

---

## 4. Give variables and functions names that explain themselves

Short names are fast to type but expensive to read. A name should communicate
*what the thing is* or *what the function does* without requiring the reader
to inspect the implementation.

**Bad:**
```python
d = fetch(x)

def process(o):
    ...
```

**Good:**
```python
customer_data = fetch(customer_id)

def calculate_order_total(order):
    ...
```

Follow PEP 8: `lowercase_with_underscores` for functions and variables.
Good names don't need to be long — they need to be unambiguous. `customer` is
clear; `d` could mean data, delivery, or date.

---

## 5. Keep responsibilities clear — one job per function

A function that does everything is hard to read, hard to test, and hard to
change safely. Structure code so a high-level function tells the *story*,
while separate lower-level functions handle the *details*.

**Bad:**
```python
def create_order(data):
    # validates, builds, saves, emails, updates inventory, all inline
    ...
```

**Good:**
```python
def create_order(data):
    validated = validate_order(data)
    order = build_order(validated)
    save_order(order)
    send_confirmation(order)
    update_inventory(order)
    return order
```

The reader can understand `create_order` at a glance without needing to know
*how* validation or inventory updates work internally. This isn't about
making every function tiny — it's about giving each piece of code exactly one
clear responsibility.

Use context managers (`with ...`) for resource cleanup (files, connections,
locks) rather than manual open/close or try/finally boilerplate.

---

## 6. Keep imports clean and explicit

As a codebase grows, messy imports become a real cost.

**Rules:**
- Never use wildcard imports (`from module import *`) — they hide where a
  name actually came from.
- Import only what you need, explicitly.
- Group imports per PEP 8, in this order, separated by a blank line:
  1. Standard library
  2. Third-party packages
  3. Local/application imports

**Bad:**
```python
from utils import *
```

**Good:**
```python
import os
import sys

import requests

from myapp.models import Customer
```

---

## 7. Use comments to explain *why*, not to restate *what*

A comment that repeats what the code already says adds noise, not value.
Comments earn their place when they explain reasoning that isn't obvious from
the code itself — an unusual business rule, a workaround, a non-obvious
constraint.

**Bad:**
```python
count += 1  # increment count
```

**Good:**
```python
# Retry once: the upstream API occasionally returns a stale cache on
# the first call after deployment.
count += 1
```

Before adding a comment, ask: *does this explain something the code cannot
easily explain on its own?* If not, don't add the comment — consider making
the code itself clearer instead. Also watch for stale comments: a comment
that no longer matches the code it sits next to is worse than no comment.

---

## Summary checklist (apply on every write/review)

- [ ] No bare or overly broad `except` blocks — only catch what you understand
- [ ] Using Python's built-in idioms instead of manual reimplementations
- [ ] Code reads clearly for a human, not just valid for the interpreter
- [ ] Variable/function names are descriptive and unambiguous (PEP 8 casing)
- [ ] Each function has one clear responsibility; high-level functions tell the story
- [ ] Imports are explicit, no wildcards, grouped stdlib/third-party/local
- [ ] Comments explain *why*, not *what*; no stale comments

The underlying goal in all seven rules: **make intent obvious and remove
unnecessary complexity**, so someone opening this code in six months doesn't
need the original author sitting next to them to explain it.
