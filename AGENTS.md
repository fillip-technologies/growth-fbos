# Agent Guidelines & Project Instructions

This repository contains strict standards and design principles that all AI coding assistants and agents must follow. Before planning, generating, modifying, or reviewing any code, you **must read and adhere to the guidelines** located in the [`.agents/`](.agents/) folder:

---

## 📚 Mandatory Agent Guidelines

1. **[Core Development Guidelines](.agents/AGENT_DEV.md)** (`.agents/AGENT_DEV.md`)
   - Primary directive: **"Make the next change easier."**
   - Keep execution paths visible (early returns over deep nesting).
   - Ensure high testability, low coupling, and modular architecture.
   - Design for failure recovery, clear errors, and safe future modifications.

2. **[Python Coding Standards](.agents/AGENT_PYTHON.md)** (`.agents/AGENT_PYTHON.md`)
   - Never catch broad or unhandled exceptions (`except:` or bare `except Exception:`).
   - Catch only specific expected errors in minimal `try` blocks.
   - Use built-in Python idioms (`str.startswith`, `enumerate`, `any`, `dict.get`, etc.) instead of reinventing logic.
   - Favor readability and reduced cognitive load over unnecessary cleverness.

3. **[REST API Design Guidelines](.agents/AGENT_RESTAPI.md)** (`.agents/AGENT_RESTAPI.md`)
   - Design around **resources (nouns)**, not actions (verbs).
   - Maintain predictable and consistent URL structures (`/resources/{id}`).
   - Use standard HTTP verbs properly (`GET`, `POST`, `PUT`, `PATCH`, `DELETE`).
   - Use standard HTTP status codes and structured error responses.

---

## 🛠️ Project Reference

- **Service Framework**: FastAPI
- **Entrypoint**: `src/main.py`
- **Dependency Management**: `requirements.txt`
- **Environment Config**: `.env` (derived from `.env.example`)

### Key Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest
```

---

## 🎯 Rules for Agent Actions

- **Always verify against `.agents/` rules** before finalizing code.
- If any proposed code or refactor violates rules in `.agents/`, revise it before presenting it to the user.
- Keep changes concise, well-documented, and fully typed.
