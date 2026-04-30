#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat

# Main runner.
# Usage:
#   ./run.sh small                 # generate only if missing, then load + benchmark
#   ./run.sh medium_dense          # denser report-quality benchmark
#   ./run.sh all                   # runs all 6 presets: small, small_dense, medium, medium_dense, large, large_dense
#   ./run.sh small --reset         # delete and regenerate generated data for this size
#   ./run.sh small --skip-generate # never generate; fail if data is missing
#   ./run.sh medium --skip-benchmark
#   ./run.sh medium --with-app     # also starts backend + frontend

cd "$(dirname "$0")"

SIZE="${1:-small}"
shift || true
SKIP_GENERATE=0
SKIP_BENCHMARK=0
WITH_BACKEND=0
WITH_FRONTEND=0
RESET_DATA=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-generate) SKIP_GENERATE=1 ;;
    --reset|--force-generate) RESET_DATA=1 ;;
    --skip-benchmark) SKIP_BENCHMARK=1 ;;
    --with-backend) WITH_BACKEND=1 ;;
    --with-frontend|--with-app) WITH_BACKEND=1; WITH_FRONTEND=1 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

if [[ -d .venv ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
else
  echo ".venv not found. Run ./setup.sh first." >&2
  exit 1
fi

dataset_exists() {
  local dir="$1"
  local required=(
    "accounts.csv"
    "memes.csv"
    "account_account.csv"
    "account_liked_meme.csv"
    "account_viewed_meme.csv"
  )

  [[ -d "$dir" ]] || return 1
  for f in "${required[@]}"; do
    [[ -s "$dir/$f" ]] || return 1
  done
  return 0
}

normalize_size() {
  case "$1" in
    small|medium|large|small_dense|medium_dense|large_dense) echo "$1" ;;
    small-dense|small_dense_) echo "small_dense" ;;
    medium-dense|medium_dense_) echo "medium_dense" ;;
    large-dense|large_dense_) echo "large_dense" ;;
    *) echo "$1" ;;
  esac
}

wait_for_postgres() {
  for i in {1..90}; do
    if docker compose exec -T postgres pg_isready -U memegraph -d memegraph >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "PostgreSQL did not become ready in time." >&2
  exit 1
}

run_one_size() {
  local raw_size="$1"
  local size
  size="$(normalize_size "$raw_size")"

  case "$size" in
    small|medium|large|small_dense|medium_dense|large_dense) ;;
    *) echo "Unknown size: $raw_size. Use small, small_dense, medium, medium_dense, large, large_dense, all, or smoke." >&2; exit 1 ;;
  esac

  local make_size="${size//_/-}"
  local data_dir="data/generated/$size"

  echo ""
  echo "============================================================"
  echo " Running dataset: $size"
  echo "============================================================"

  echo "== Starting PostgreSQL =="
  docker compose up -d postgres
  wait_for_postgres

  echo "== Initializing DB schema/functions/index helpers =="
  ./scripts/init_db.sh

  if [[ "$RESET_DATA" == "1" ]]; then
    echo "== Reset requested: deleting generated $size dataset =="
    rm -rf "$data_dir"
  fi

  if [[ "$SKIP_GENERATE" == "1" ]]; then
    echo "== Skipping generation for $size because --skip-generate was passed =="
  elif dataset_exists "$data_dir"; then
    echo "== Reusing existing $size dataset at $data_dir =="
    echo "   Pass --reset to delete and regenerate it."
  else
    echo "== Generated data for $size not found/incomplete; generating now =="
    make "generate-$make_size"
  fi

  if ! dataset_exists "$data_dir"; then
    echo "Dataset for $size is missing or incomplete at $data_dir." >&2
    echo "Run ./run.sh $size --reset, or remove --skip-generate." >&2
    exit 1
  fi

  echo "== Loading $size dataset =="
  make "load-$make_size"

  if [[ "$SKIP_BENCHMARK" == "0" ]]; then
    echo "== Benchmarking $size dataset =="
    make "benchmark-$make_size"
  else
    echo "== Skipping benchmark for $size =="
  fi
}

case "$SIZE" in
  all)
    for s in small small_dense medium medium_dense large large_dense; do
      run_one_size "$s"
    done
    ;;
  smoke)
    run_one_size small
    ;;
  *)
    run_one_size "$SIZE"
    ;;
esac

if [[ "$WITH_BACKEND" == "1" ]]; then
  echo "== Starting backend container =="
  docker compose up -d backend
  echo "Backend API: http://localhost:4000"
  if [[ "$WITH_FRONTEND" == "1" ]]; then
    echo "== Starting frontend container =="
    docker compose up -d frontend
    echo "Frontend UI: http://localhost:5173"
  else
    echo "Frontend dev UI: cd frontend && npm run dev"
  fi
fi

echo "Done. Results are under analysis_outputs/. Generated CSV data is under data/generated/ and is git-ignored."
