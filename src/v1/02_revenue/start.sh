#!/bin/sh
set -e

echo "Running Alembic migrations for revenue service..."
alembic upgrade head

echo "Starting revenue service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
