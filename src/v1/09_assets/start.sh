#!/bin/sh
set -e

echo "Running Alembic migrations for assets service..."
alembic upgrade head

echo "Starting assets service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
