#!/bin/sh
set -e

echo "Running Alembic migrations for asset_analytic service..."
alembic upgrade head

echo "Starting asset_analytic service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
