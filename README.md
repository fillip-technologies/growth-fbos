# FBOS Services (Fillip Business Operating System)

A distributed enterprise microservice platform built with **FastAPI**, **SQLAlchemy (Async)**, and **MySQL 8.0**, adhering to the FBOS API specification.

---

## 🏛️ Architecture & Services

The platform consists of **10 specialized microservices** plus a shared MySQL database container:

| Port | Service Name | Directory | Responsibilities |
|:---:|:---|:---|:---|
| **8000** | **00_gateway** | `src/v1/00_gateway` | API Gateway, Backend-For-Frontend (BFF), Home screen aggregation |
| **8001** | **01_identity** | `src/v1/01_identity` | Authentication, user-based access control, Users, OrgUnits, Calendars |
| **8002** | **02_revenue** | `src/v1/02_revenue` | Commercial CRM, Clients, Deals, Offerings, Invoices, Payments |
| **8003** | **03_delivery** | `src/v1/03_delivery` | Work Units, Workflow definitions, Tasks, Time tracking |
| **8004** | **04_control** | `src/v1/04_control` | Approval requests, Delegations, SLA policies, Breaches |
| **8005** | **05_documents** | `src/v1/05_documents` | Document storage (S3/presigned), Versions, Categories, Shares |
| **8006** | **06_communication** | `src/v1/06_communication` | Inbox, Notifications dispatch, Webhook subscriptions |
| **8007** | **07_management** | `src/v1/07_management` | Strategic planning, KPI targets, Resources & Capacity |
| **8008** | **08_insight** | `src/v1/08_insight` | Audit logs, Compliance, Analytics dashboards |
| **8009** | **09_assets** | `src/v1/09_assets` | Asset tracking, Vendor accounts, Credential vault |
| **3307** | **db (MySQL 8.0)** | `docker/init.sql` | 9 isolated databases (`fbos_identity`, `fbos_revenue`, etc.) |

> 📖 **Frontend Developers**: Check out the comprehensive [Frontend Integration & API Guide](docs/FRONTEND_INTEGRATION_GUIDE.md) for full endpoint specifications, request/response models, authentication flows, and a ready-to-use TypeScript/Axios client.

---

## ⚙️ Prerequisites & Initial Setup

- **Docker** and **Docker Compose** installed (no `sudo` needed if user is in `docker` group)
- Python 3.10+ (for local development or running tests outside Docker)

### 1. Initialize Environment Files

Copy the example configurations into working `.env` files for each service and the root docker-compose:

```bash
# 1. Copy root environment config (used by MySQL container)
cp .env.docker.example .env

# 2. Copy .env for all 10 microservices at once
for d in src/v1/*/; do cp "$d.env.example" "$d.env"; done
```

---

## 🚀 Docker Build & Run Commands

### 1. Build and Start All Containers (First Time or Code Changes)

Build all 10 service images and start the entire stack in the background (detached mode):

```bash
docker compose up -d --build
```

### 2. Start Without Rebuilding

If images are already built:

```bash
docker compose up -d
```

### 3. Start or Rebuild a Single Service

```bash
# Rebuild and restart only one service (e.g., identity or revenue)
docker compose up -d --build identity
docker compose up -d --build revenue
docker compose up -d --build documents
```

### 4. Check Container Status and Health

```bash
docker compose ps
```
*All healthy containers will display `Up (healthy)`.*

### 5. View Logs

```bash
# Stream live logs for all services:
docker compose logs -f

# Stream live logs for a specific service:
docker compose logs -f identity
docker compose logs -f revenue
docker compose logs -f documents
docker compose logs -f db
```

### 6. Stop Containers

```bash
# Stop running containers (preserves database data volume):
docker compose down

# Stop and wipe database volume completely (100% fresh state):
docker compose down -v
```

### 7. Development Mode (Live Reload, No Rebuilds)

By default the code is copied into each image at build time, so a code change only takes effect after `docker compose up -d --build <service>`. For day-to-day development, use the dev override instead: it mounts each service's source folder into its container and runs uvicorn with `--reload`, so **saving a `.py` file restarts that service within a couple of seconds**.

```bash
# Start (or switch) the whole stack in dev mode:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Or just one service:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d revenue
```

To avoid typing both files every time, set them once in your shell (or put `COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml` in the root `.env`):

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml   # bash/zsh
set -x COMPOSE_FILE docker-compose.yml:docker-compose.dev.yml   # fish
docker compose up -d
```

| You changed... | What to do |
|---|---|
| Python code (`routes/`, `services/`, `schemas/`, `models/`…) | Nothing — the service reloads automatically |
| A new Alembic migration | `docker compose restart <service>` (migrations and seeds run on container start) |
| `requirements.txt` or a `Dockerfile` | `docker compose up -d --build <service>` |
| A service's `.env` | `docker compose up -d <service>` (recreates the container) |

Check that a service reloaded with `docker compose logs -f <service>` — you'll see `WatchFiles detected changes ... Reloading...`.

To go back to the normal (baked-in) mode, run `docker compose up -d` without the dev file (and unset `COMPOSE_FILE` if you set it).

> Dev mode is for local development only — production uses `docker-compose.prod.yml` and never mounts source code.

---

## 🌱 Database Seeding Commands

Seed scripts populate the databases with realistic test data (Organization, Users, Passwords, Clients, Offerings, Deals, Documents). All seed scripts are **idempotent** (safe to run multiple times).

### Method A: Automated Seeding on Boot
Each service's `start.sh` automatically detects and executes `seed.py` on container startup. When you start with `docker compose up -d --build`, databases are seeded automatically!

### Method B: Seed Running Containers On-Demand (Helper Script)
If containers are already running and you want to trigger seeds without restarting:

```bash
./scripts/seed_docker.sh
```

### Method C: Seed Individual Containers via Docker Exec
```bash
# Seed Identity (Organization, OrgUnits, Users, Roles, Credentials)
docker compose exec identity python seed.py

# Seed Revenue (Clients, Contacts, Offerings, Leads, Deals)
docker compose exec revenue python seed.py

# Seed Documents (Retention policies, Categories, Documents, Links)
docker compose exec documents python seed.py
```

### Method D: Seed Directly from Host Machine (via Exposed Port 3307)
```bash
# Identity tables come from Alembic only — migrate before seeding.
(cd src/v1/01_identity && DATABASE_URL="mysql+aiomysql://root:fbos_root_password@localhost:3307/fbos_identity" \
  python3 -m alembic upgrade head)
DATABASE_URL="mysql+aiomysql://root:fbos_root_password@localhost:3307/fbos_identity" \
  PYTHONPATH=src/v1/01_identity python3 src/v1/01_identity/seed.py

DATABASE_URL="mysql+aiomysql://root:fbos_root_password@localhost:3307/fbos_revenue" \
  PYTHONPATH=src/v1/02_revenue python3 src/v1/02_revenue/seed.py

DATABASE_URL="mysql+aiomysql://root:fbos_root_password@localhost:3307/fbos_documents" \
  PYTHONPATH=src/v1/05_documents python3 src/v1/05_documents/seed.py
```

---

## 🔑 Seeded Test Credentials

| Field | Value |
|---|---|
| **Organization Code** | `FILLIP` |
| **Admin User** | `aarav.sharma@example.com` |
| **Sales User** | `sarah.connor@example.com` |
| **Password** | `Password@123` |
| **Admin User UUID** | `0191f3a2-0015-7015-8093-000000218f0d` |
| **Default Org UUID** | `0191f3a2-0011-7011-8077-0000001b2aa9` |

---

## 🧪 Live Verification & Testing

Verify that services and seeded data are accessible:

### A. Via API Gateway (Port 8000 — Recommended Single Entrypoint)
```bash
# 1. Gateway Health Check
curl http://localhost:8000/health

# 2. Authenticate / Login (proxied to Identity)
curl -X POST http://localhost:8000/api/identity/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "aarav.sharma@example.com", "password": "Password@123"}'

# 3. Retrieve Seeded Clients (proxied to Revenue)
curl http://localhost:8000/api/revenue/v1/clients

# 4. Retrieve Seeded Documents (proxied to Documents)
curl http://localhost:8000/api/documents/v1/documents

# 5. Retrieve JWKS Public Keys (proxied to Identity)
curl http://localhost:8000/.well-known/jwks.json
```

### B. Direct Microservice Access (Isolated Ports for Debugging)
You can also bypass the gateway to query any microservice directly on its exposed port:
```bash
# Identity Service directly
curl http://localhost:8001/health

# Revenue Service directly
curl http://localhost:8002/api/revenue/v1/clients

# Documents Service directly
curl http://localhost:8005/api/documents/v1/documents
```

### Interactive API Documentation (Swagger / OpenAPI)
Every running service exposes interactive documentation:
- **Gateway**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Identity**: [http://localhost:8001/docs](http://localhost:8001/docs)
- **Revenue**: [http://localhost:8002/docs](http://localhost:8002/docs)
- **Delivery**: [http://localhost:8003/docs](http://localhost:8003/docs)
- **Control**: [http://localhost:8004/docs](http://localhost:8004/docs)
- **Documents**: [http://localhost:8005/docs](http://localhost:8005/docs)
- **Communication**: [http://localhost:8006/docs](http://localhost:8006/docs)
- **Management**: [http://localhost:8007/docs](http://localhost:8007/docs)
- **Insight**: [http://localhost:8008/docs](http://localhost:8008/docs)
- **Assets**: [http://localhost:8009/docs](http://localhost:8009/docs)

---

## 💻 Local Development (Outside Docker)

To run or debug a specific service locally with hot-reloading:

```bash
# 1. Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies for the target service
pip install -r src/v1/01_identity/requirements.txt

# 3. Run the service
cd src/v1/01_identity
uvicorn main:app --reload --host 0.0.0.0 --port 8001
```

### Running Automated Tests
```bash
# Run documents test suite:
PYTHONPATH=. pytest src/v1/05_documents/tests

# Run identity test suite:
PYTHONPATH=. pytest src/v1/01_identity/tests

# Run revenue test suite:
PYTHONPATH=. pytest src/v1/02_revenue/tests
```