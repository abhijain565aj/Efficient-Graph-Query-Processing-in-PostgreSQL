#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
source scripts/common.sh

log_info "Starting MemeGraph app. Full log: $LOG_FILE"
run_logged "Starting PostgreSQL + backend + frontend containers" docker compose up -d postgres backend frontend
log_info "Backend API:  http://localhost:4000"
log_info "Frontend UI: http://localhost:5173"
log_info "Health:      http://localhost:4000/health"
