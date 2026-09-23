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

## 📖 API Specification

The authoritative contract for every endpoint, request/response schema, error code, and event is the HTML reference file at the repo root:

```
fbos-api-reference (1).html
```

**Always read this file before implementing or reviewing any endpoint.** It defines exact field names, required vs optional constraints, nested object shapes, permitted enum values, HTTP status codes, idempotency behaviour, and published events. The implementation must match it precisely — any deviation is a bug.

---

## 🗺️ Service–Spec Mapping

The repository uses fine-grained directories for independent deployment. Each directory maps to a logical service defined in the HTML spec. Use this table to navigate between code and spec.

| Directory | Spec service name | Base path | Spec modules covered | Endpoints | Port |
|-----------|------------------|-----------|----------------------|-----------|------|
| `01_identity/` | **Identity** | `/api/identity/v1` | Authentication · Organization and access | 39 | 8000 |
| `02_revenue/` | **Revenue** | `/api/revenue/v1` | Commercial (CRM) · Billing | 42 | 8001 |
| `03_billing/` | _(part of Revenue)_ | `/api/revenue/v1` | Billing sub-module only | — | 8002 |
| `04_work/` | **Delivery** | `/api/delivery/v1` | Work units | 60 total | 8003 |
| `05_workflow/` | **Delivery** | `/api/delivery/v1` | Workflow engine | (shared) | 8004 |
| `06_task/` | **Delivery** | `/api/delivery/v1` | Tasks · Handovers · Time entries | (shared) | 8005 |
| `07_approval/` | **Control** | `/api/control/v1` | Approvals · SLA | 17 | 8006 |
| `08_doc_notify_audit/` | **Documents** + **Communication** + **Insight** (audit) | `/api/documents/v1` · `/api/communication/v1` · `/api/insight/v1` | Documents · Notifications/inbox/webhooks · Audit trail | 9+13+3 | 8007 |
| `09_res_plan_perf/` | **Management** | `/api/management/v1` | Planning · Performance (KPIs) · Resources and capacity | 11 | 8008 |
| `10_asset_analytic/` | **Assets** + **Insight** (analytics) | `/api/assets/v1` · `/api/insight/v1` | Assets/credentials · Dashboards/metrics/reports | 6+4 | 8009 |

> **Note:** `02_commercial/` is a stale directory superseded by `02_revenue/`. Do not add code to it.
>
> **Note:** The spec defines a single **Delivery service** (`/api/delivery/v1`, 60 endpoints) covering work units, workflow and tasks. The three directories `04_work/`, `05_workflow/`, `06_task/` implement it as separate deployable units — treat their combined routes as one spec service when doing gap analysis.
>
> **Note:** Similarly, `08_doc_notify_audit/` implements three distinct spec services (Documents, Communication, Insight-audit); `10_asset_analytic/` implements two (Assets, Insight-analytics). Keep their route prefixes distinct.

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
  # Identity service — spec: identity (/api/identity/v1) — port 8000
  uvicorn main:app --app-dir src/v1/01_identity --reload --host 0.0.0.0 --port 8000

  # Revenue service — spec: revenue (/api/revenue/v1) — port 8001
  # Covers CRM (clients, leads, opportunities, quotations, contracts)
  # + Billing (invoices, payments, collections)
  uvicorn main:app --app-dir src/v1/02_revenue --reload --host 0.0.0.0 --port 8001

  # Billing sub-service — part of revenue spec service — port 8002
  uvicorn main:app --app-dir src/v1/03_billing --reload --host 0.0.0.0 --port 8002

  # Delivery service — Work units module — port 8003
  uvicorn main:app --app-dir src/v1/04_work --reload --host 0.0.0.0 --port 8003

  # Delivery service — Workflow engine module — port 8004
  uvicorn main:app --app-dir src/v1/05_workflow --reload --host 0.0.0.0 --port 8004

  # Delivery service — Tasks, handovers & time entries module — port 8005
  uvicorn main:app --app-dir src/v1/06_task --reload --host 0.0.0.0 --port 8005

  # Control service — spec: control (/api/control/v1) — port 8006
  # Covers approvals + SLA clocks
  uvicorn main:app --app-dir src/v1/07_approval --reload --host 0.0.0.0 --port 8006

  # Documents + Communication + Insight-audit — port 8007
  # spec: documents (/api/documents/v1)
  #       communication (/api/communication/v1)
  #       insight-audit (/api/insight/v1 — audit endpoints only)
  uvicorn main:app --app-dir src/v1/08_doc_notify_audit --reload --host 0.0.0.0 --port 8007

  # Management service — spec: management (/api/management/v1) — port 8008
  # Covers planning, KPI performance tracking, resources and capacity
  uvicorn main:app --app-dir src/v1/09_res_plan_perf --reload --host 0.0.0.0 --port 8008

  # Assets + Insight-analytics — port 8009
  # spec: assets (/api/assets/v1)
  #       insight-analytics (/api/insight/v1 — dashboards/metrics/reports)
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
├── 01_identity/          # Identity service — /api/identity/v1 (port 8000)
│   ├── main.py           # FastAPI app entrypoint
│   ├── config.py         # Pydantic settings (reads .env)
│   ├── router.py         # Aggregates all route modules
│   ├── dependencies.py   # FastAPI injectable dependencies
│   ├── exceptions.py     # Service-specific HTTP exceptions (RFC 7807)
│   ├── models/           # SQLAlchemy ORM models
│   ├── schemas/          # Pydantic request & response schemas
│   ├── services/         # Business logic layer
│   ├── routes/           # Route handlers
│   ├── utils/            # Utility functions (hashing, tokens, etc.)
│   └── requirements.txt  # Service-specific dependencies
│
├── 02_revenue/           # Revenue service — /api/revenue/v1 (port 8001)
│                         # Modules: Commercial CRM + Billing
│
├── 02_commercial/        # ⚠️  STALE — superseded by 02_revenue. Do not modify.
│
├── 03_billing/           # Billing sub-service — part of revenue spec (port 8002)
│
├── 04_work/              # Delivery service (work units) — /api/delivery/v1 (port 8003)
│
├── 05_workflow/          # Delivery service (workflow engine) — /api/delivery/v1 (port 8004)
│
├── 06_task/              # Delivery service (tasks/handovers/time) — /api/delivery/v1 (port 8005)
│
├── 07_approval/          # Control service — /api/control/v1 (port 8006)
│                         # Modules: Approvals + SLA
│
├── 08_doc_notify_audit/  # Documents + Communication + Insight-audit (port 8007)
│                         # Specs: /api/documents/v1 + /api/communication/v1 + /api/insight/v1 (audit)
│
├── 09_res_plan_perf/     # Management service — /api/management/v1 (port 8008)
│                         # Modules: Planning + Performance (KPIs) + Resources/capacity
│
└── 10_asset_analytic/    # Assets + Insight-analytics (port 8009)
                          # Specs: /api/assets/v1 + /api/insight/v1 (dashboards/metrics/reports)
```

---

## 🔌 Common Patterns (all services)

Every service implements these shared contracts, also defined in the spec under **"Every service"** (`/api/{service}/v1`):

| Pattern | How it works |
|---------|-------------|
| **Pagination** | Keyset cursor via `page.next_cursor`; `limit` 1–100 default 25 |
| **Concurrency** | Optimistic locking: `ETag` on reads, `If-Match` on writes → `412` on mismatch, `428` if header missing |
| **Idempotency** | `Idempotency-Key` UUID header on all `POST` mutations; replayed responses carry `Idempotent-Replayed: true` |
| **Errors** | RFC 7807 Problem Details: `{type, title, status, code, detail, instance, request_id, retryable}` |
| **Events** | Every mutation publishes a domain event (e.g. `identity.user.invited.v1`) |
| **Internal** | `POST /internal/events` · `GET /internal/deliveries` · `POST /internal/deliveries/{id}/replay` |
| **Health** | `GET /health` → `{"status": "ok", "service": "<name>"}` |

- `.agents/` — Core architecture, Python, and REST guidelines
