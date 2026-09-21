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
  source .venv/bin/activate
  ```
- **Install Dependencies**:
  ```bash
  pip install -r requirements.txt
  ```
- **Run Local Server**:
  ```bash
  uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
  ```
- **Run Tests**:
  ```bash
  pytest
  ```

---

## 📂 Project Architecture

- `src/` — Main application package
  - `src/api/` — API routes and routers
  - `src/core/` — Application configuration and settings
  - `src/models/` — Schemas (Pydantic) and data models
  - `src/services/` — Business logic layers
  - `src/main.py` — FastAPI initialization
- `.agents/` — Core architecture, Python, and REST guidelines
