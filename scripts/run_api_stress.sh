#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat
mkdir -p analysis_outputs
python src/stress_test_api.py \
  --base-url "${BASE_URL:-http://localhost:4000}" \
  --users "${USERS:-1000}" \
  --requests "${REQUESTS:-2000}" \
  --concurrency "${CONCURRENCY:-64}" \
  --mode "${MODE:-cached}" \
  --prewarm-cache \
  --out analysis_outputs/api_stress.csv
