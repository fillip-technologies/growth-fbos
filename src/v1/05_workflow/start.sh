#!/bin/sh
set -e

echo "Running Alembic migrations for workflow service..."
alembic upgrade head

echo "Starting workflow service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
