#!/bin/sh
set -e

echo "Running Alembic migrations for delivery service..."
alembic upgrade head

echo "Starting delivery service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
