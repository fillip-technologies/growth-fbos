#!/bin/sh
set -e

echo "Running Alembic migrations for billing service..."
alembic upgrade head

echo "Starting billing service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
