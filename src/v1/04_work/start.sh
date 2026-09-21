#!/bin/sh
set -e

echo "Running Alembic migrations for work service..."
alembic upgrade head

echo "Starting work service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
