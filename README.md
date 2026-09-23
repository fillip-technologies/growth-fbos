# FBOS Services

A lightweight, high-performance microservice built with [FastAPI](https://fastapi.tiangolo.com/).

---

## 🚀 Features

- **FastAPI** with asynchronous request handling
- Automatic interactive API documentation via Swagger UI (`/docs`) & ReDoc (`/redoc`)
- Configuration management with **Pydantic Settings** & `.env`
- Inter-service communication support via **HTTPX**
- Async unit & integration testing with **pytest**

---

## 📋 Prerequisites

- Python 3.10+
- `pip`

---

## 🛠️ Getting Started

### 1. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
# Install dependencies for a specific service (e.g., Identity)
pip install -r src/v1/01_identity/requirements.txt
```

### 3. Environment configuration

Every service under `src/v1/` reads its own `.env` file (gitignored). Each one ships a tracked
`.env.example` with working docker-compose defaults, so setup is copy-paste — no values need
editing to run locally against Docker:

```bash
# All 10 services at once
for d in src/v1/*/; do cp "$d.env.example" "$d.env"; done

# Root .env, used by the `db` container in docker-compose
cp .env.docker.example .env
```

Then bring everything up:

```bash
docker compose up --build
```

| Variable | Description | Default |
| :--- | :--- | :--- |
| `APP_ENV` | Application environment (`development`, `production`) | `development` |
| `PORT` | Service port | `8000` |
| `HOST` | Bind host address | `0.0.0.0` |

### 4. Run the application

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

The service will be live at `http://localhost:8000`.

---

## 📖 API Documentation

Once the service is running, explore and test the endpoints via:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 🧪 Running Tests

Execute test suite using `pytest`:

```bash
pytest
```