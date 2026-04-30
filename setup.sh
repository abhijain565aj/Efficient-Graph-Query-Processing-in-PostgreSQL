#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat

# One-time setup for MemeGraph.
# Creates .env, Python venv, installs dependencies, starts PostgreSQL on host port 55432,
# and initializes the database schema/functions/index helpers.

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  echo "Created Python virtual environment: .venv"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt

docker compose up -d postgres

echo "Waiting for PostgreSQL container..."
for i in {1..60}; do
  if docker compose exec -T postgres pg_isready -U memegraph -d memegraph >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [[ "$i" == "60" ]]; then
    echo "PostgreSQL did not become ready in time." >&2
    exit 1
  fi
done

./scripts/init_db.sh

if command -v npm >/dev/null 2>&1; then
  (cd backend && npm install)
  (cd frontend && npm install)
else
  echo "npm not found; skipped backend/frontend dependency install."
fi

echo "Setup complete. Try: ./run.sh small"
