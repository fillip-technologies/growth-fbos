#!/bin/sh
set -e

echo "Running Alembic migrations for task service..."
alembic upgrade head

echo "Starting task service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
