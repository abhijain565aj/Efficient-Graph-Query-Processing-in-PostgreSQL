#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat

# Start the full app after a dataset has been loaded.
# Usage:
#   ./setup.sh
#   ./run.sh medium --skip-benchmark
#   ./app.sh

cd "$(dirname "$0")"

docker compose up -d postgres backend frontend

echo "Backend API:  http://localhost:4000"
echo "Frontend UI: http://localhost:5173"
echo "Health:      http://localhost:4000/health"
