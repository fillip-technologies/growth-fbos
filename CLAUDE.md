# CLAUDE.md

Guidelines and instructions for Claude Code and related AI assistants working on this repository.

---

## 🚨 Mandatory Instructions — Read `.agents/` First

Before analyzing, writing, modifying, or reviewing any code in this repository, **you must read and strictly adhere to all guideline documents in the [`.agents/`](.agents/) directory**:

1. **[Core Development Guidelines](.agents/AGENT_DEV.md)** (`.agents/AGENT_DEV.md`):
   - Principle: **"Make the next change easier."**
   - Main execution path must be visible (prefer early returns, avoid deep nesting).
   - Keep components modular, decoupled, and easy to unit test.
   - Design for failure modes and clear errors.

2. **[Python Coding Standards](.agents/AGENT_PYTHON.md)** (`.agents/AGENT_PYTHON.md`):
   - **No bare or broad exceptions**: Never use `except:` or catch `Exception` blindly. Always catch specific exceptions with minimal scope.
   - **Use built-in idioms**: Avoid reinventing loops or string checks; use `enumerate`, `any`, `dict.get`, `str.startswith`, etc.
   - Clean, typed, maintainable Python with low cognitive load.

3. **[REST API Guidelines](.agents/AGENT_RESTAPI.md)** (`.agents/AGENT_RESTAPI.md`):
   - **Resource-based URLs**: Use nouns, not verbs (e.g. `POST /orders`, never `/createOrder`).
   - **Predictable routes**: Plural nouns for collections (`/users`, `/users/{id}`).
   - **Standard HTTP methods**: `GET` for retrieval, `POST` for creation, `PUT`/`PATCH` for updates, `DELETE` for removal.
   - Proper status codes (e.g. 200, 201, 204, 400, 401, 403, 404, 422, 500).

---

## ⚙️ Development Commands

- **Environment Setup**:
  ```bash
  python -m venv .venv
  source .venv/bin/activate  # Windows: .venv\Scripts\activate
  ```
- **Install Dependencies** (per service):
  ```bash
  pip install -r src/v1/01_identity/requirements.txt
  ```
- **Run a Service**:
  ```bash
  # Identity service (port 8000)
  uvicorn main:app --app-dir src/v1/01_identity --reload --host 0.0.0.0 --port 8000

  # Revenue service (port 8001)
  uvicorn main:app --app-dir src/v1/02_revenue --reload --host 0.0.0.0 --port 8001


  # Billing service (port 8002)
  uvicorn main:app --app-dir src/v1/03_billing --reload --host 0.0.0.0 --port 8002

  # Work service (port 8003)
  uvicorn main:app --app-dir src/v1/04_work --reload --host 0.0.0.0 --port 8003

  # Workflow service (port 8004)
  uvicorn main:app --app-dir src/v1/05_workflow --reload --host 0.0.0.0 --port 8004

  # Task service (port 8005)
  uvicorn main:app --app-dir src/v1/06_task --reload --host 0.0.0.0 --port 8005

  # Approval service (port 8006)
  uvicorn main:app --app-dir src/v1/07_approval --reload --host 0.0.0.0 --port 8006

  # Document, Notification & Audit service (port 8007)
  uvicorn main:app --app-dir src/v1/08_doc_notify_audit --reload --host 0.0.0.0 --port 8007

  # Resource, Planning & Performance service (port 8008)
  uvicorn main:app --app-dir src/v1/09_res_plan_perf --reload --host 0.0.0.0 --port 8008

  # Asset, Analytics & Platform service (port 8009)
  uvicorn main:app --app-dir src/v1/10_asset_analytic --reload --host 0.0.0.0 --port 8009
  ```
- **Run Tests** (per service — tests must be run from within the service directory):
  ```bash
  cd src/v1/01_identity && pytest
  ```

---

## 📂 Project Architecture

Each service under `src/v1/` is independently runnable. All imports within a service are
top-level (non-relative) because `--app-dir` adds the service root to `sys.path`.

```
src/v1/
├── 01_identity/          # Identity & authentication service (port 8000)
│   ├── main.py           # FastAPI app entrypoint
│   ├── config.py         # Pydantic settings (reads .env)
│   ├── router.py         # Aggregates all route modules
│   ├── dependencies.py   # FastAPI injectable dependencies
│   ├── exceptions.py     # Service-specific HTTP exceptions
│   ├── models/           # Domain models (dataclasses / ORM)
│   ├── schemas/          # Pydantic request & response schemas
│   ├── services/         # Business logic layer
│   ├── routes/           # Route handlers
│   ├── utils/            # Utility functions (hashing, tokens, etc.)
│   └── requirements.txt  # Service-specific dependencies
├── 02_revenue/           # Revenue service (port 8001, same structure)

├── 03_billing/           # Billing & invoicing service (port 8002, same structure)
├── 04_work/              # Work & delivery service (port 8003, same structure)
├── 05_workflow/          # Workflow & automation service (port 8004, same structure)
├── 06_task/              # Task & effort service (port 8005, same structure)
├── 07_approval/          # Approval & delegation service (port 8006, same structure)
├── 08_doc_notify_audit/  # Document, notification & audit service (port 8007, same structure)
├── 09_res_plan_perf/     # Resource, planning & performance service (port 8008, same structure)
└── 10_asset_analytic/    # Asset, analytics & platform service (port 8009, same structure)
```

- `.agents/` — Core architecture, Python, and REST guidelines



