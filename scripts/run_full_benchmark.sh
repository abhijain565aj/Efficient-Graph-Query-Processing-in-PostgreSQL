#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat

# Backward-compatible benchmark entrypoint.
# Usage: ./scripts/run_full_benchmark.sh [small|medium|large]
SIZE="${1:-small}"
./scripts/run_dataset_benchmark.sh "$SIZE"
