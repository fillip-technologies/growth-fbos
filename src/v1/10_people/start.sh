#!/bin/sh
set -e

if [ -f "alembic.ini" ]; then
    echo "Running Alembic migrations for people service..."
    alembic upgrade head || true
fi

echo "Starting people service..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 ${UVICORN_RELOAD:+--reload}
