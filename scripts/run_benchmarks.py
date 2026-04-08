from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg


ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = ROOT / "sql"
DATA_DIR = ROOT / "data"
RESULTS_DIR = ROOT / "results"
PLANS_DIR = RESULTS_DIR / "plans"

# Default is 5433 because your docker-compose is now exposing host port 5433.
# If you switch back to 5432 later, either change this line or set GRAPH_PG_CONNINFO.
CONNINFO = os.environ.get(
    "GRAPH_PG_CONNINFO",
    "dbname=graphdb user=postgres password=postgres host=127.0.0.1 port=5433",
)


QUERY_LIBRARY: dict[str, tuple[str, dict[str, Any]]] = {
    "reachability": (
        """
        WITH RECURSIVE reach(node) AS (
            SELECT %(src)s::int
            UNION
            SELECT e.dst::int
            FROM reach r
            JOIN edges e ON e.src = r.node
        )
        SELECT COUNT(*) AS reachable_nodes
        FROM reach;
        """,
        {"src": 1},
    ),
    "k_hop_neighborhood": (
        """
        WITH RECURSIVE khop(node, depth) AS (
            SELECT %(src)s::int, 0::int
            UNION ALL
            SELECT e.dst::int, (k.depth + 1)::int
            FROM khop k
            JOIN edges e ON e.src = k.node
            WHERE k.depth < %(max_depth)s::int
        )
        SELECT COUNT(DISTINCT node) AS nodes_within_k_hops
        FROM khop;
        """,
        {"src": 1, "max_depth": 3},
    ),
    "shortest_path_bfs_style": (
        """
        WITH RECURSIVE bfs(node, depth, path) AS (
            SELECT %(src)s::int, 0::int, ARRAY[%(src)s::int]
            UNION ALL
            SELECT e.dst::int, (b.depth + 1)::int, path || e.dst::int
            FROM bfs b
            JOIN edges e ON e.src = b.node
            WHERE b.depth < %(max_depth)s::int
              AND NOT (e.dst = ANY(path))
        )
        SELECT depth
        FROM bfs
        WHERE node = %(dst)s::int
        ORDER BY depth
        LIMIT 1;
        """,
        {"src": 1, "dst": 25, "max_depth": 6},
    ),
    "mutual_friends": (
        """
        SELECT COUNT(*) AS mutual_count
        FROM (
            SELECT e1.dst AS mutual_friend
            FROM edges e1
            JOIN edges e2 ON e1.dst = e2.dst
            WHERE e1.src = %(u1)s::int AND e2.src = %(u2)s::int
            GROUP BY e1.dst
        ) t;
        """,
        {"u1": 1, "u2": 2},
    ),
    "friend_recommendation": (
        """
        SELECT COUNT(*) AS recommendation_count
        FROM (
            SELECT e2.dst AS recommended_user, COUNT(*) AS support
            FROM edges e1
            JOIN edges e2 ON e1.dst = e2.src
            LEFT JOIN edges direct ON direct.src = e1.src AND direct.dst = e2.dst
            WHERE e1.src = %(src)s::int
              AND e2.dst <> %(src)s::int
              AND direct.dst IS NULL
            GROUP BY e2.dst
            ORDER BY support DESC, recommended_user
            LIMIT 10
        ) t;
        """,
        {"src": 1},
    ),
    "contact_tracing": (
        """
        WITH RECURSIVE trace(person_id, depth) AS (
            SELECT %(src)s::int, 0::int
            UNION ALL
            SELECT e.dst::int, (t.depth + 1)::int
            FROM trace t
            JOIN edges e ON e.src = t.person_id
            WHERE t.depth < %(max_depth)s::int
        )
        SELECT COUNT(DISTINCT person_id) AS traced_people
        FROM trace;
        """,
        {"src": 1, "max_depth": 4},
    ),
}


INDEX_MODES = {
    "no_index": ["02_drop_indexes.sql"],
    "basic_index": ["02_drop_indexes.sql", "03_create_basic_indexes.sql"],
    "composite_index": [
        "02_drop_indexes.sql",
        "03_create_basic_indexes.sql",
        "04_create_composite_indexes.sql",
    ],
}


def read_sql(filename: str) -> str:
    return (SQL_DIR / filename).read_text(encoding="utf-8")


def execute_sql_file(cur: psycopg.Cursor[Any], filename: str) -> None:
    cur.execute(read_sql(filename))


def load_csv(cur: psycopg.Cursor[Any], table: str, columns: list[str], csv_path: Path) -> None:
    with csv_path.open("r", encoding="utf-8") as f:
        copy_sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH CSV HEADER"
        with cur.copy(copy_sql) as copy:
            for line in f:
                copy.write(line)


def load_dataset(cur: psycopg.Cursor[Any], dataset_dir: Path) -> None:
    execute_sql_file(cur, "06_reset_tables.sql")
    load_csv(cur, "nodes", ["id", "label", "node_type"],
             dataset_dir / "nodes.csv")
    load_csv(cur, "edges", ["src", "dst", "weight",
             "interaction_type"], dataset_dir / "edges.csv")
    cur.execute("ANALYZE nodes;")
    cur.execute("ANALYZE edges;")


def apply_index_mode(cur: psycopg.Cursor[Any], mode: str) -> None:
    for filename in INDEX_MODES[mode]:
        execute_sql_file(cur, filename)
    cur.execute("ANALYZE edges;")


def collect_plan_metrics(plan_json: list[dict[str, Any]]) -> dict[str, Any]:
    payload = plan_json[0]
    root_plan = payload["Plan"]
    return {
        "planning_time_ms": payload.get("Planning Time", 0.0),
        "execution_time_ms": payload.get("Execution Time", 0.0),
        "estimated_total_cost": root_plan.get("Total Cost", 0.0),
        "actual_rows": root_plan.get("Actual Rows", 0),
        "plan_rows": root_plan.get("Plan Rows", 0),
        "node_type": root_plan.get("Node Type", ""),
    }


def connect_with_retry(conninfo: str, retries: int = 20, delay: float = 2.0) -> psycopg.Connection[Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return psycopg.connect(conninfo, autocommit=True)
        except psycopg.OperationalError as e:
            last_error = e
            print(
                f"Database not ready yet (attempt {attempt}/{retries}). Retrying in {delay} sec...")
            time.sleep(delay)
    assert last_error is not None
    raise last_error


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)

    datasets = sorted([d for d in DATA_DIR.iterdir()
                      if d.is_dir()], key=lambda p: p.name)
    if not datasets:
        raise FileNotFoundError(
            "No datasets found in data/. Run scripts/generate_data.py first.")

    rows: list[dict[str, Any]] = []

    with connect_with_retry(CONNINFO) as conn:
        with conn.cursor() as cur:
            execute_sql_file(cur, "01_schema.sql")

            for dataset_dir in datasets:
                dataset_name = dataset_dir.name
                print(f"\n=== Dataset: {dataset_name} ===")
                load_dataset(cur, dataset_dir)

                for mode in INDEX_MODES:
                    print(f"  -> Index mode: {mode}")
                    apply_index_mode(cur, mode)

                    for query_name, (sql, params) in QUERY_LIBRARY.items():
                        explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"
                        cur.execute(explain_sql, params)
                        plan_json = cur.fetchone()[0]
                        metrics = collect_plan_metrics(plan_json)

                        plan_path = PLANS_DIR / \
                            f"{dataset_name}__{mode}__{query_name}.json"
                        plan_path.write_text(json.dumps(
                            plan_json, indent=2), encoding="utf-8")

                        row = {
                            "dataset": dataset_name,
                            "index_mode": mode,
                            "query_name": query_name,
                            **metrics,
                            "plan_file": str(plan_path.relative_to(ROOT)),
                        }
                        rows.append(row)
                        print(
                            f"     {query_name:<24} exec={metrics['execution_time_ms']:.3f} ms  "
                            f"plan={metrics['planning_time_ms']:.3f} ms"
                        )

    df = pd.DataFrame(rows)
    out_csv = RESULTS_DIR / "benchmark_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nSaved results to {out_csv}")


if __name__ == "__main__":
    main()
