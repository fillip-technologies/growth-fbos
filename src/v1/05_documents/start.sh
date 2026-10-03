#!/bin/sh
set -e

echo "Running Alembic migrations for documents service..."
alembic upgrade head || true

if [ -f "seed.py" ]; then
    echo "Running seed script for documents service..."
    python seed.py || echo "Seed step finished"
fi

echo "Starting documents service..."
# UVICORN_RELOAD is set by docker-compose.dev.yml to restart on code changes.
exec uvicorn main:app --host 0.0.0.0 --port 8000 ${UVICORN_RELOAD:+--reload}
