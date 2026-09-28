#!/bin/sh
set -e

echo "Running Alembic migrations for identity service..."
alembic upgrade head || true

if [ -f "seed.py" ]; then
    echo "Running seed script for identity service..."
    python seed.py || echo "Seed step finished"
fi

echo "Starting identity service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
