#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
source scripts/common.sh

log_info "MemeGraph setup started. Full log: $LOG_FILE"

if [[ ! -f .env ]]; then
  cp .env.example .env
  log_info "Created .env from .env.example"
fi

if [[ ! -d .venv ]]; then
  run_logged "Creating Python virtual environment" python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
run_logged "Installing Python dependencies" pip install -r requirements.txt
run_logged "Starting PostgreSQL container" docker compose up -d postgres

log_info "Waiting for PostgreSQL container"
for i in {1..90}; do
  if docker compose exec -T postgres pg_isready -U memegraph -d memegraph >> "$LOG_FILE" 2>&1; then
    break
  fi
  sleep 1
  if [[ "$i" == "90" ]]; then
    echo "PostgreSQL did not become ready in time. Full log: $LOG_FILE" >&2
    exit 1
  fi
done

run_logged "Initializing database schema/functions" ./scripts/init_db.sh

if command -v npm >/dev/null 2>&1; then
  run_logged "Installing backend dependencies" bash -lc 'cd backend && npm install'
  run_logged "Installing frontend dependencies" bash -lc 'cd frontend && npm install'
else
  log_info "npm not found; skipped backend/frontend dependency install."
fi

log_info "Setup complete. Try: ./run.sh small"
log_info "Full setup log: $LOG_FILE"
