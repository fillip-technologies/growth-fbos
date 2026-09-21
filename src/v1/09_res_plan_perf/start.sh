#!/bin/sh
set -e

echo "Running Alembic migrations for res_plan_perf service..."
alembic upgrade head

echo "Starting res_plan_perf service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
