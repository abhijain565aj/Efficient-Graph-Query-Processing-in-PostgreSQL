# Efficient Graph Query Processing in PostgreSQL using Recursive SQL and Indexing

This repository is a submission-ready implementation of the project proposed in **Project-Idea.pdf**. The project models graph data in PostgreSQL, implements graph queries using recursive SQL (`WITH RECURSIVE`), studies the effect of indexing on execution time and query plans, and demonstrates two practical use cases: social network analysis and contact tracing. The implementation directly follows the stated project goals: relational graph modeling, recursive traversal, optimizer/plan analysis, indexing evaluation, and real-world graph workloads. fileciteturn2file0

## 1. Folder structure

```text
project_submission/
├── README.md
├── requirements.txt
├── docker-compose.yml
├── run_all.sh
├── sql/
│   ├── 01_schema.sql
│   ├── 02_drop_indexes.sql
│   ├── 03_create_basic_indexes.sql
│   ├── 04_create_composite_indexes.sql
│   ├── 05_queries.sql
│   └── 06_reset_tables.sql
├── scripts/
│   ├── generate_data.py
│   ├── run_benchmarks.py
│   └── plot_results.py
├── data/
│   └── (generated CSV files)
└── report/
    └── report_template.tex
```

## 2. What this project does

### Graph representation
We store the graph in two relational tables:
- `nodes(id, label, node_type)`
- `edges(src, dst, weight, interaction_type)`

### Core graph queries
Implemented queries include:
- reachability
- k-hop neighborhood
- shortest-path style path search using BFS-like recursion
- mutual friend detection
- friend recommendation via 2-hop traversal
- contact tracing / infection chain exploration

### Performance study
The project compares three settings:
1. **No secondary indexes**
2. **Basic indexes** on `edges(src)` and `edges(dst)`
3. **Composite indexes** on `(src, dst)` and `(dst, src)`

For each setting, the code records:
- execution time
- planning time
- estimated total cost
- actual rows processed
- query plan JSON

## 3. How to run

### Option A: Recommended (Docker)

#### Step 1: Start PostgreSQL
```bash
docker compose up -d
```

#### Step 2: Install Python dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### Step 3: Generate synthetic graph datasets
```bash
python scripts/generate_data.py
```

This generates:
- `data/small/nodes.csv`, `data/small/edges.csv`
- `data/medium/nodes.csv`, `data/medium/edges.csv`
- `data/large/nodes.csv`, `data/large/edges.csv`

#### Step 4: Run all benchmarks
```bash
python scripts/run_benchmarks.py
```

This produces:
- `results/benchmark_results.csv`
- `results/plans/*.json`

#### Step 5: Plot results
```bash
python scripts/plot_results.py
```

This produces figures in:
- `results/plots/`

### Option B: One-command run
```bash
bash run_all.sh
```

## 4. Submission workflow

Use this exact order for your submission/demo:

1. Start PostgreSQL using Docker.
2. Generate synthetic datasets of varying sizes/densities.
3. Load the schema.
4. Run graph queries without indexes.
5. Create indexes and rerun the same queries.
6. Compare `EXPLAIN ANALYZE` plans and timings.
7. Show plots and discuss which queries benefit the most from indexing.
8. Demonstrate the two use cases:
   - social network analysis
   - disease spread / contact tracing

## 5. Suggested discussion points for report/viva

- Why recursive CTEs are a natural fit for graph traversal in SQL.
- Why adjacency-list storage maps well to `JOIN`-based expansion.
- Why `edges(src)` is especially important for forward traversal.
- Why composite indexes can improve some join/filter patterns.
- Why recursive queries may still become expensive on dense graphs.
- How query plans change between nested-loop/hash-join style execution.
- Why PostgreSQL can support moderate graph workloads even without a specialized graph DB.

## 6. Notes

- The project is designed to be **easy to run and easy to explain**.
- The code is submission-ready, but you should update names/roll numbers and include the generated graphs in your final PDF/report.
- If your course requires local PostgreSQL instead of Docker, simply update the connection string in `scripts/run_benchmarks.py`.
