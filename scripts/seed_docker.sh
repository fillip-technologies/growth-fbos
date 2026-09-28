#!/bin/bash
# -----------------------------------------------------------------------------
# FBOS Microservices: On-demand Docker Seed Runner
# Runs seed scripts inside active Docker Compose containers.
# -----------------------------------------------------------------------------
set -e

echo "=========================================================="
echo "🌱 Seeding FBOS Microservices inside active Docker Compose"
echo "=========================================================="

# 1. Identity Service
if docker compose ps identity | grep -q "Up"; then
    echo "1. Seeding Identity service (01_identity)..."
    docker compose exec identity python seed.py
else
    echo "⚠️  identity container is not running, skipping..."
fi

# 2. Revenue Service
if docker compose ps revenue | grep -q "Up"; then
    echo "2. Seeding Revenue service (02_revenue)..."
    docker compose exec revenue python seed.py
else
    echo "⚠️  revenue container is not running, skipping..."
fi

# 3. Documents Service
if docker compose ps documents | grep -q "Up"; then
    echo "3. Seeding Documents service (05_documents)..."
    docker compose exec documents python seed.py
else
    echo "⚠️  documents container is not running, skipping..."
fi

echo "=========================================================="
echo "🎉 Seed execution finished!"
echo "=========================================================="
