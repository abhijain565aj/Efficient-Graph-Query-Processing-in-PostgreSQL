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

DATA_DIR="${1:-data/generated/small}"
DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-55432}"
DB_NAME="${POSTGRES_DB:-memegraph}"
DB_USER="${POSTGRES_USER:-memegraph}"
export PGPASSWORD="${POSTGRES_PASSWORD:-memegraph}"
export PGOPTIONS="${PGOPTIONS:--c client_min_messages=warning}"

if [[ ! -d "$DATA_DIR" ]]; then
  echo "Data directory not found: $DATA_DIR" >&2
  exit 1
fi

PSQL=(psql -q -P pager=off -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1)

echo "Dropping secondary indexes before COPY load; they are recreated after load."
"${PSQL[@]}" <<SQL
SET max_parallel_workers_per_gather = 0;
SET synchronous_commit = off;
SELECT drop_experiment_indexes();
TRUNCATE account_feed_cache, account_neighbor_cache, account_viewed_meme, account_liked_meme, account_account, meme_daily_stats, memes, accounts RESTART IDENTITY;
SQL

copy_file() {
  local table="$1"
  local file="$2"
  local columns="$3"
  if [[ -f "$file" ]]; then
    echo "Loading $table from $file"
    "${PSQL[@]}" -c "\\copy $table ($columns) FROM '$file' WITH (FORMAT csv, HEADER true)"
  else
    echo "Missing file: $file" >&2
    exit 1
  fi
}

copy_file accounts "$DATA_DIR/accounts.csv" "id, username, region_id, created_at"
copy_file memes "$DATA_DIR/memes.csv" "id, title, category, creator_id, quality_score, created_at"
copy_file account_account "$DATA_DIR/account_account.csv" "src, dst, strength, created_at"
copy_file account_liked_meme "$DATA_DIR/account_liked_meme.csv" "account_id, meme_id, liked_at, weight"
copy_file account_viewed_meme "$DATA_DIR/account_viewed_meme.csv" "account_id, meme_id, viewed_at"

echo "Refreshing derived candidate stats with parallel workers disabled to avoid Docker shared-memory blowups."
"${PSQL[@]}" <<SQL
SET max_parallel_workers_per_gather = 0;
SELECT refresh_meme_daily_stats();
SELECT apply_index_scenario('optimized') AS index_scenario;
ANALYZE accounts;
ANALYZE memes;
ANALYZE account_account;
ANALYZE account_liked_meme;
ANALYZE account_viewed_meme;
ANALYZE meme_daily_stats;
ANALYZE account_neighbor_cache;
ANALYZE account_feed_cache;
SELECT * FROM v_dataset_stats ORDER BY table_name;
SQL
