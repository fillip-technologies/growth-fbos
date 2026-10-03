#!/bin/sh
set -e

echo "Running Alembic migrations for management service..."
alembic upgrade head

echo "Starting management service..."
# UVICORN_RELOAD is set by docker-compose.dev.yml to restart on code changes.
exec uvicorn main:app --host 0.0.0.0 --port 8000 ${UVICORN_RELOAD:+--reload}
