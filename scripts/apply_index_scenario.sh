#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat

# Load host-side DB settings when .env exists. Docker Compose also reads this file.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

SCENARIO="${1:-optimized}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-55432}"
DB_NAME="${POSTGRES_DB:-memegraph}"
DB_USER="${POSTGRES_USER:-memegraph}"
export PGPASSWORD="${POSTGRES_PASSWORD:-memegraph}"
export PGOPTIONS="${PGOPTIONS:--c client_min_messages=warning}"

psql -qAt -P pager=off -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
  -c "SELECT apply_index_scenario('$SCENARIO');" >/dev/null

echo "Index scenario applied: $SCENARIO"
