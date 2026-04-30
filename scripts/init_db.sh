#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-55432}"
DB_NAME="${POSTGRES_DB:-memegraph}"
DB_USER="${POSTGRES_USER:-memegraph}"
export PGPASSWORD="${POSTGRES_PASSWORD:-memegraph}"
export PGOPTIONS="${PGOPTIONS:--c client_min_messages=warning}"

PSQL=(psql -q -P pager=off -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1)

"${PSQL[@]}" -f db/00_schema.sql
"${PSQL[@]}" -f db/01_functions.sql
"${PSQL[@]}" -f db/02_index_scenarios.sql
"${PSQL[@]}" -f db/03_sample_queries.sql
"${PSQL[@]}" -c "SELECT apply_index_scenario('optimized') AS index_scenario;"
