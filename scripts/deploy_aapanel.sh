#!/bin/bash
# Rebuilds and restarts the backend on the aaPanel server. Run by scripts/fbos-deploy after it
# has fast-forwarded this checkout to origin/main (or by hand from the checkout).
# Fails if any service is not healthy within 3 minutes, so the CI/CD run shows red.
set -euo pipefail

cd "$(dirname "$0")/.."
compose() { docker compose -f docker-compose.yml -f docker-compose.aapanel.yml "$@"; }

compose up -d --build --remove-orphans

deadline=$((SECONDS + 180))
while true; do
  # Services with a healthcheck that are not healthy yet; the Health column is empty without one.
  waiting=$(compose ps --format '{{.Service}} {{.Health}}' | awk '$2 != "" && $2 != "healthy" {print $1}')
  [ -z "$waiting" ] && break
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "Not healthy after 3 minutes: $waiting" >&2
    for service in $waiting; do compose logs --tail 40 "$service" >&2; done
    exit 1
  fi
  sleep 5
done

compose ps --format 'table {{.Service}}\t{{.Status}}'
docker image prune -f > /dev/null
echo "Backend deployed: $(git log --oneline -1)"
