# Benchmarking Guide

## One-command runs

```bash
./setup.sh
./run.sh medium_dense
```

`run.sh` reuses generated CSVs when possible. Use `--reset` only when you want to regenerate data.

```bash
./run.sh medium_dense          # reuse data if present
./run.sh medium_dense --reset  # regenerate data
```


## Logging behavior

Top-level runs are quiet by default. Detailed command output, COPY progress, npm/pip output, and benchmark progress bars are written to `logs/*.log`. If a command fails, the last 80 log lines are printed automatically. Use `VERBOSE=1 ./run.sh medium_dense` when you want live detailed output.

## Full run

```bash
./run.sh all
```

This runs `small`, `small_dense`, `medium`, `medium_dense`, `large`, and `large_dense`.

## What is measured?

`src/run_benchmarks.py` measures normal `SELECT` latency for the feed functions. It separately samples a small number of `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` plans. This avoids polluting every latency number with explain overhead.

Modes:

- `exact`: recursive CTE traversal and ranking inside the request.
- `approx`: bounded traversal and bounded recent-like candidate generation inside the request.
- `cached`: feed cache is primed before timing; request is an indexed lookup over `account_feed_cache`.

## Index scenarios

- `no_extra_index`: primary keys only.
- `single_column`: individual indexes on key columns.
- `composite`: composite indexes matching join/filter paths.
- `optimized`: composite covering indexes, feed-cache index, neighbor-cache index, trending-rank index, and BRIN indexes on timestamps.

## Best plots for final submission

Use `medium_dense` for the clearest visual improvement. Use `large` to show scale. `large_dense` is a heavy stress case.

Generated plots are stored in:

```text
analysis_outputs/plots/<preset>/
```

The most useful plots are:

- `latency_by_mode.png`
- `latency_vs_k.png`
- `latency_distribution.png`
- `buffers_vs_k.png` when sampled plan data is available
