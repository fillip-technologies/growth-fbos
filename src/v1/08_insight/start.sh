#!/bin/sh
set -e

echo "Running Alembic migrations for insight service..."
alembic upgrade head

echo "Starting insight service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
