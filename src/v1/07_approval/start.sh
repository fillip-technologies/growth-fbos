#!/bin/sh
set -e

echo "Running Alembic migrations for approval service..."
alembic upgrade head

echo "Starting approval service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
