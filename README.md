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

Create a `.env` file from `.env.example`:

```bash
cp .env.example .env
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