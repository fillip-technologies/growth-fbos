#!/bin/sh
set -e

echo "Running Alembic migrations for doc_notify_audit service..."
alembic upgrade head

echo "Starting doc_notify_audit service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
