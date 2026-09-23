#!/bin/sh
set -e

echo "Running Alembic migrations for management service..."
alembic upgrade head

echo "Starting management service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
