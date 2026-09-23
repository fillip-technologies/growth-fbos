#!/bin/sh
set -e

echo "Running Alembic migrations for control service..."
alembic upgrade head

echo "Starting control service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
