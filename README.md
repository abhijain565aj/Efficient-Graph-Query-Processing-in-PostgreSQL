# MemeGraph: Scalable Meme Recommendation over PostgreSQL Graph Data

This is a complete CS349-style database systems project built around **optimized and approximate graph queries** in PostgreSQL.

The application models a social-media meme feed. Given a user, the system uses the social graph, neighbor likes, recent-view filtering, and trending fallback candidates to recommend memes. The project compares three serving strategies:

1. **Exact recursive SQL** — correctness baseline using recursive CTE k-hop traversal.
2. **Online bounded approximation** — limits fanout and recent-like lookups during the request.
3. **Precomputed feed cache** — industry-style serving path using an offline/nearline feed cache and indexed lookup.

The backend/frontend are intentionally lightweight: their job is to make the database query behavior easy to visualize. The main credit-worthy part is the data generation, indexing, approximate query design, benchmarking, plotting, and stress testing.

---

## Quick start

```bash
./setup.sh
./run.sh medium_dense
./app.sh
```

Open:

```text
http://localhost:5173
```

The UI compares **exact**, **approx**, and **cached** recommendations for the same user and k-hop value in one view.

---

## Important script behavior

### Pager is disabled

All scripts disable the PostgreSQL pager, so you should never have to press `q` during a script run:

```bash
export PSQL_PAGER=cat
export PAGER=cat
psql -P pager=off ...
```


### Quiet terminal + full log files

Top-level scripts keep the terminal short and write detailed command output to `logs/*.log`.
On failure, the script prints the last log lines automatically.

```bash
./setup.sh
./run.sh medium_dense
VERBOSE=1 ./run.sh medium_dense   # optional: show full live output
```

### Data is reused by default

`run.sh` generates data only when the required CSVs do not already exist.

```bash
./run.sh medium_dense        # reuse existing data if present
./run.sh medium_dense --reset  # delete and regenerate this preset
```

### Full benchmark run

```bash
./run.sh all
```

This runs all six presets:

1. `small`
2. `small_dense`
3. `medium`
4. `medium_dense`
5. `large`
6. `large_dense`

`large_dense` is intentionally heavy. It keeps the same 1M users / 100k memes scale but increases degree and interaction counts. Use it only when you have enough disk space and time.

---

## Dataset presets

Generated data is written under `data/generated/<preset>/` and is git-ignored.

| Preset | Users | Memes | Avg neighbors | Avg likes/user | Avg views/user | Use |
|---|---:|---:|---:|---:|---:|---|
| `small` | 1,000 | 100 | 24 | 40 | 70 | smoke test |
| `small_dense` | 1,000 | 100 | 48 | 75 | 120 | dense correctness demo |
| `medium` | 10,000 | 1,000 | 48 | 70 | 130 | normal benchmark |
| `medium_dense` | 10,000 | 1,000 | 96 | 120 | 220 | best report-quality benchmark |
| `large` | 1,000,000 | 100,000 | 12 | 20 | 36 | large-scale benchmark |
| `large_dense` | 1,000,000 | 100,000 | 18 | 32 | 60 | heavy stress benchmark |

The generator creates:

```text
accounts.csv
memes.csv
account_account.csv
account_liked_meme.csv
account_viewed_meme.csv
```

No generated data is included in the submission ZIP.

---

## Recommended evaluation workflow

For a strong final report, run:

```bash
./run.sh small --reset
./run.sh small_dense --reset
./run.sh medium --reset
./run.sh medium_dense --reset
```

Then, for scale:

```bash
./run.sh large --reset
```

Run `large_dense` only if the machine has enough resources:

```bash
./run.sh large_dense --reset
```

Outputs are written to:

```text
analysis_outputs/benchmarks_<preset>_<index_scenario>.csv
analysis_outputs/benchmarks_<preset>_all.csv
analysis_outputs/plots/<preset>/
analysis_outputs/plans/
```

---

## Why small datasets may not show large improvements

For 1k or 10k users, much of the data can fit in memory. PostgreSQL may also choose similar plans because table scans are cheap at that scale. The project therefore includes dense variants and large variants. Meaningful improvements appear when:

- graph fanout is high,
- k-hop traversal expands quickly,
- recent-view anti-joins touch many rows,
- and the cached serving path avoids repeated online candidate generation.

The intended performance story is:

```text
Exact recursive SQL: correct but worsens with k and density.
Online approximation: bounded and more stable.
Cached serving: fastest online path after precomputation.
```

---

## Frontend behavior

The frontend avoids confusing parameter controls. It exposes only:

- User ID
- k-hop distance
- Results per mode

The UI shows the algorithm-specific parameters next to each strategy:

- Exact: `k`, `limit`, recent-view window
- Approx: `k`, `degreeCap=16`, `likesPerNeighbor=24`, `limit`
- Cached: `k`, `cacheItems=250`, `limit`

Click **Compare all 3 modes** to run exact, approx, and cached in one view. Click an individual mode button to inspect one strategy separately.

---

## Backend endpoints

```text
GET  /health
GET  /api/stats
GET  /api/users/:id/feed/compare?k=2&limit=20
GET  /api/users/:id/feed?mode=exact|approx|cached&k=2&limit=20
GET  /api/users/:id/neighbors?mode=exact|approx|cached&k=2
POST /api/users/:id/refresh-feed-cache?k=2&cacheItems=250
```

---

## Implementation structure

```text
db/
  00_schema.sql            Base tables, cache tables, indexes
  01_functions.sql         Exact, approx, cached recommendation functions
  02_index_scenarios.sql   no-index, single-column, composite, optimized setups
src/
  data_generation.py       Synthetic data generator
  run_benchmarks.py        DB latency + sampled EXPLAIN plans
  plotter.py               Benchmark plots
  stress_test_api.py       Async API stress testing
backend/
  src/server.js            Express API
frontend/
  src/App.jsx              React comparison UI
scripts/
  init_db.sh
  load_data.sh
  run_dataset_benchmark.sh
  apply_index_scenario.sh
setup.sh
run.sh
app.sh
```

---

## Notes on large runs

The Docker PostgreSQL service uses:

- host port `55432` to avoid local PostgreSQL conflicts,
- `shm_size: 2gb` to avoid Docker shared-memory failures during large aggregation/index jobs,
- index-drop-before-COPY loading,
- and `max_parallel_workers_per_gather=0` for stable laptop-scale runs.

If large still fails on your machine, reduce only the large density from the command line:

```bash
python src/data_generation.py --users 1000000 --memes 100000 \
  --avg-out-degree 10 --avg-likes-per-user 16 --avg-views-per-user 28 \
  --out data/generated/large_custom
```

Then load it manually:

```bash
./scripts/load_data.sh data/generated/large_custom
./scripts/run_dataset_benchmark.sh large
```
