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
- **Configure environment files** — each service reads its own `.env` (gitignored); every
  service ships a tracked `.env.example` with working docker-compose defaults, so onboarding is
  copy-paste:
  ```bash
  for d in src/v1/*/; do cp "$d.env.example" "$d.env"; done
  cp .env.docker.example .env   # root .env, used by the `db` container in docker-compose
  ```
  The defaults already point at the `db` service's docker-compose hostname/credentials, so
  `docker compose up` works immediately after copying — no values need editing for local dev.
- **Run a Service**:
  ```bash
  # Gateway service (port 8000) — BFF: routing, aggregated screens
  uvicorn main:app --app-dir src/v1/00_gateway --reload --host 0.0.0.0 --port 8000

  # Identity service (port 8001) — Authentication, Organization and access
  uvicorn main:app --app-dir src/v1/01_identity --reload --host 0.0.0.0 --port 8001

  # Revenue service (port 8002) — Commercial (CRM), Billing
  uvicorn main:app --app-dir src/v1/02_revenue --reload --host 0.0.0.0 --port 8002

  # Delivery service (port 8003) — Work units, Workflow, Tasks
  uvicorn main:app --app-dir src/v1/03_delivery --reload --host 0.0.0.0 --port 8003

  # Control service (port 8004) — Approvals, SLA
  uvicorn main:app --app-dir src/v1/04_control --reload --host 0.0.0.0 --port 8004

  # Documents service (port 8005)
  uvicorn main:app --app-dir src/v1/05_documents --reload --host 0.0.0.0 --port 8005

  # Communication service (port 8006) — Notifications, inbox and webhooks
  uvicorn main:app --app-dir src/v1/06_communication --reload --host 0.0.0.0 --port 8006

  # Management service (port 8007) — Planning, Performance (KPIs), Resources and capacity
  uvicorn main:app --app-dir src/v1/07_management --reload --host 0.0.0.0 --port 8007

  # Insight service (port 8008) — Audit, Analytics
  uvicorn main:app --app-dir src/v1/08_insight --reload --host 0.0.0.0 --port 8008

  # Assets service (port 8009)
  uvicorn main:app --app-dir src/v1/09_assets --reload --host 0.0.0.0 --port 8009
  ```
- **Run Tests** (per service — tests must be run from within the service directory):
  ```bash
  cd src/v1/01_identity && pytest
  ```

---

## 📂 Project Architecture

Each service under `src/v1/` is independently runnable. All imports within a service are
top-level (non-relative) because `--app-dir` adds the service root to `sys.path`.

The 10 services and their base paths mirror `ref/fbos-api-reference (1).html` ("The 10 services"
table) exactly — module boundaries, not just names, were aligned to that spec:

```
src/v1/
├── 00_gateway/           # Gateway service (port 8000) — /api/bff/v1 — Aggregated screens
│   ├── main.py           # FastAPI app entrypoint
│   ├── config.py         # Pydantic settings (reads .env)
│   ├── router.py         # Aggregates all route modules
│   ├── dependencies.py   # FastAPI injectable dependencies
│   ├── exceptions.py     # Service-specific HTTP exceptions
│   ├── schemas/          # Pydantic request & response schemas
│   ├── services/         # Business logic layer
│   ├── routes/           # Route handlers
│   ├── utils/            # Utility functions
│   └── requirements.txt  # Service-specific dependencies
├── 01_identity/          # Identity service (port 8001) — /api/identity/v1 — Authentication, Organization and access
│   └── ...                 (same structure as above, plus models/ and database/ — every service below follows it)
├── 02_revenue/           # Revenue service (port 8002) — /api/revenue/v1 — Commercial (CRM), Billing
├── 03_delivery/          # Delivery service (port 8003) — /api/delivery/v1 — Work units, Workflow, Tasks
├── 04_control/           # Control service (port 8004) — /api/control/v1 — Approvals, SLA
├── 05_documents/         # Documents service (port 8005) — /api/documents/v1 — Documents
├── 06_communication/     # Communication service (port 8006) — /api/communication/v1 — Notifications, inbox and webhooks
├── 07_management/        # Management service (port 8007) — /api/management/v1 — Planning, Performance (KPIs), Resources and capacity
├── 08_insight/           # Insight service (port 8008) — /api/insight/v1 — Audit, Analytics
└── 09_assets/            # Assets service (port 8009) — /api/assets/v1 — Assets
```

- `.agents/` — Core architecture, Python, and REST guidelines
- `ref/fbos-api-reference (1).html` — source-of-truth API spec; service/module boundaries, base
  paths and ports above are derived from it. Every service's `router.py` mounts routes at both
  `/v1` and its documented `/api/<service>/v1` base path.



