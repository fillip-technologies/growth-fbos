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

  # Commercial service (port 8001)
  uvicorn main:app --app-dir src/v1/02_commercial --reload --host 0.0.0.0 --port 8001
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
├── 01_identity/          # Identity & authentication service
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
└── 02_commercial/        # Commercial service (same structure)
```

- `.agents/` — Core architecture, Python, and REST guidelines
