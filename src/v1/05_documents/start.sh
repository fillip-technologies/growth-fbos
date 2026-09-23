#!/bin/sh
set -e

echo "Running Alembic migrations for documents service..."
alembic upgrade head

echo "Starting documents service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
