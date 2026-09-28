#!/bin/sh
set -e

echo "Running Alembic migrations for revenue service..."
alembic upgrade head || true

if [ -f "seed.py" ]; then
    echo "Running seed script for revenue service..."
    python seed.py || echo "Seed step finished"
fi

echo "Starting revenue service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
