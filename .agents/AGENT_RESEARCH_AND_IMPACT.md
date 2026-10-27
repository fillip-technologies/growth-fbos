# Evidence-First Investigation & Impact Analysis Guidelines

## Purpose

This document defines the mandatory protocol for investigating bugs, analyzing architecture, and performing code modifications across FBOS backend services.

---

## 1. Do Not Guess Upfront

Never jump directly into speculative coding or guess how an external library, database constraint, or framework feature works.
Always ground every hypothesis in empirical evidence from the codebase.

---

## 2. Inspect Code and Dependency Versions First

Before writing, modifying, or reviewing code:
1. **Identify the exact language version**: Python 3.10 / 3.12 / 3.14.
2. **Identify exact library versions**: Check `requirements.txt` in the active service (e.g., `FastAPI>=0.115.0`, `pydantic>=2.8.0`, `sqlalchemy[asyncio]>=2.0.0`, `alembic>=1.13.0`, `httpx>=0.27.0`).
3. **Trace actual models and schemas**:
   - Check SQLAlchemy model definitions (`models/`) and Alembic migration history (`migrations/versions/`).
   - Check Pydantic request and response schemas (`schemas/`).
   - Trace route dependencies and permission guards.

---

## 3. Read Official & Internal Documentation

1. Review internal project documents (`CLAUDE.md`, `DEPLOY_AAPANEL.md`, and integration specs in `docs/`).
2. Consult the official documentation for the **exact version** in use (e.g., Pydantic v2 migration docs, FastAPI lifespan event docs, SQLAlchemy 2.0 Async Session patterns).
3. If the official documentation specifies the recommended pattern, follow it.

---

## 4. Search External References (If Not in Docs)

If an issue is an undocumented edge case, complex library interaction, or subtle runtime behavior:
1. Search the web for the exact error message or stack trace.
2. Review GitHub issues, discussions, and verified source code repositories for related fixes.

---

## 5. Self-Thinking & Deduction is LAST

Independent reasoning and problem formulation must take place **only after** empirical evidence from code, versions, documentation, and external references has been collected. 

Do not invent custom abstractions or workarounds when a standard, documented solution exists.

---

## 6. Blast-Radius & Cross-Feature Impact Analysis

Before applying any change to backend code:
1. **Inter-Service Boundaries**: Will this change affect API Gateway proxying, Identity authorization (`/internal/authz/actor`), Documents subject checks, or Communication event ingestion?
2. **Frontend Wire Shape**: Will altering an endpoint's JSON payload or status code break the React frontend consoles (`superadmin`, `clientadmin`) or Fixly clients?
3. **Database & Migrations**: Does this change require an Alembic schema migration? Is it backward-compatible with live data?
4. **Permissions**: Does the route enforce the required permission in `AGENT_PERMISSIONS.md`?

---

## 7. Careful, Surgical Modifications

1. Keep diffs focused strictly on the problem.
2. Always write defensive code with appropriate error handling and specific exception catching (see `AGENT_PYTHON.md`).
3. Verify every change with isolated tests:
   ```bash
   PYTHONPATH=. pytest <service_directory>/tests
   ```
