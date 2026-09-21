#!/bin/sh
set -e

echo "Running Alembic migrations for identity service..."
alembic upgrade head

echo "Starting identity service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
