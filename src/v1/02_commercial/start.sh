#!/bin/sh
set -e

echo "Running Alembic migrations for commercial service..."
alembic upgrade head

echo "Starting commercial service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
