#!/bin/sh
set -e

echo "Running Alembic migrations for communication service..."
alembic upgrade head

echo "Starting communication service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
