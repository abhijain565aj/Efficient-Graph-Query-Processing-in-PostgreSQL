#!/usr/bin/env bash
set -euo pipefail

# Disable psql pager so scripts never pause at an (END) screen requiring q.
export PSQL_PAGER=cat
export PAGER=cat

# Run DB benchmark suite for the currently loaded dataset, with size-aware defaults.
# Usage: ./scripts/run_dataset_benchmark.sh small|medium|large|small_dense|medium_dense|large_dense

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

SIZE="${1:-small}"
mkdir -p analysis_outputs/plans analysis_outputs/plots

case "$SIZE" in
  small)
    BENCH_USERS="${BENCH_USERS:-80}"
    K_VALUES=(1 2 3)
    MODES=(exact approx cached)
    SCENARIOS=(no_extra_index single_column composite optimized)
    DEGREE_CAP="${DEGREE_CAP:-16}"
    LIKES_PER_NEIGHBOR="${LIKES_PER_NEIGHBOR:-24}"
    CACHE_NEIGHBORS="${CACHE_NEIGHBORS:-200}"
    ;;
  small_dense)
    BENCH_USERS="${BENCH_USERS:-50}"
    K_VALUES=(1 2 3)
    MODES=(exact approx cached)
    SCENARIOS=(composite optimized)
    DEGREE_CAP="${DEGREE_CAP:-20}"
    LIKES_PER_NEIGHBOR="${LIKES_PER_NEIGHBOR:-32}"
    CACHE_NEIGHBORS="${CACHE_NEIGHBORS:-200}"
    ;;
  medium)
    BENCH_USERS="${BENCH_USERS:-40}"
    K_VALUES=(1 2 3)
    MODES=(exact approx cached)
    SCENARIOS=(no_extra_index single_column composite optimized)
    DEGREE_CAP="${DEGREE_CAP:-20}"
    LIKES_PER_NEIGHBOR="${LIKES_PER_NEIGHBOR:-32}"
    CACHE_NEIGHBORS="${CACHE_NEIGHBORS:-250}"
    ;;
  medium_dense)
    BENCH_USERS="${BENCH_USERS:-24}"
    K_VALUES=(1 2 3)
    MODES=(exact approx cached)
    SCENARIOS=(composite optimized)
    DEGREE_CAP="${DEGREE_CAP:-24}"
    LIKES_PER_NEIGHBOR="${LIKES_PER_NEIGHBOR:-40}"
    CACHE_NEIGHBORS="${CACHE_NEIGHBORS:-250}"
    ;;
  large)
    BENCH_USERS="${BENCH_USERS:-60}"
    K_VALUES=(1 2 3)
    MODES=(approx cached)
    SCENARIOS=(optimized)
    DEGREE_CAP="${DEGREE_CAP:-20}"
    LIKES_PER_NEIGHBOR="${LIKES_PER_NEIGHBOR:-32}"
    CACHE_NEIGHBORS="${CACHE_NEIGHBORS:-250}"
    echo "Large dataset selected: optimized scenario only; exact traversal is intentionally skipped."
    ;;
  large_dense)
    BENCH_USERS="${BENCH_USERS:-40}"
    K_VALUES=(1 2 3)
    MODES=(approx cached)
    SCENARIOS=(optimized)
    DEGREE_CAP="${DEGREE_CAP:-24}"
    LIKES_PER_NEIGHBOR="${LIKES_PER_NEIGHBOR:-40}"
    CACHE_NEIGHBORS="${CACHE_NEIGHBORS:-250}"
    echo "Large dense selected: optimized scenario only; exact traversal is intentionally skipped."
    ;;
  *)
    echo "Unknown dataset size: $SIZE. Use small, medium, large, small_dense, medium_dense, or large_dense." >&2
    exit 1
    ;;
esac

# Optional overrides:
#   MODES_OVERRIDE="exact approx cached" K_VALUES_OVERRIDE="1 2" SCENARIOS_OVERRIDE="optimized" ./scripts/run_dataset_benchmark.sh medium
if [[ -n "${MODES_OVERRIDE:-}" ]]; then
  read -r -a MODES <<< "$MODES_OVERRIDE"
fi
if [[ -n "${K_VALUES_OVERRIDE:-}" ]]; then
  read -r -a K_VALUES <<< "$K_VALUES_OVERRIDE"
fi
if [[ -n "${SCENARIOS_OVERRIDE:-}" ]]; then
  read -r -a SCENARIOS <<< "$SCENARIOS_OVERRIDE"
fi

for scenario in "${SCENARIOS[@]}"; do
  echo "== [$SIZE] Applying index scenario: $scenario =="
  ./scripts/apply_index_scenario.sh "$scenario"

  python src/run_benchmarks.py \
    --users "$BENCH_USERS" \
    --k-values "${K_VALUES[@]}" \
    --modes "${MODES[@]}" \
    --degree-cap "$DEGREE_CAP" \
    --likes-per-neighbor "$LIKES_PER_NEIGHBOR" \
    --cache-neighbors "$CACHE_NEIGHBORS" \
    --prime-cache \
    --index-scenario "$scenario" \
    --dataset-label "$SIZE" \
    --out "analysis_outputs/benchmarks_${SIZE}_${scenario}.csv" \
    --plans-out "analysis_outputs/plans/plans_${SIZE}_${scenario}.jsonl"
done

# Merge all CSVs for this size.
SIZE_FOR_MERGE="$SIZE" python - <<'PY'
from pathlib import Path
import os
import pandas as pd
size = os.environ['SIZE_FOR_MERGE']
paths = sorted(Path('analysis_outputs').glob(f'benchmarks_{size}_*.csv'))
frames = [pd.read_csv(p) for p in paths if p.stat().st_size > 0 and not p.name.endswith('_all.csv')]
if frames:
    out = Path('analysis_outputs') / f'benchmarks_{size}_all.csv'
    pd.concat(frames, ignore_index=True).to_csv(out, index=False)
    print(f'Wrote {out}')
PY

python src/plotter.py \
  --input "analysis_outputs/benchmarks_${SIZE}_all.csv" \
  --outdir "analysis_outputs/plots/${SIZE}"
