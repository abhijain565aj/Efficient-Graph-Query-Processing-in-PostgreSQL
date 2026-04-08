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

CONNINFO = os.environ.get(
    "GRAPH_PG_CONNINFO",
    "dbname=graphdb user=postgres password=postgres host=127.0.0.1 port=5433",
)
WARMUP_RUNS = int(os.environ.get("GRAPH_WARMUP_RUNS", "1"))
MEASURE_RUNS = int(os.environ.get("GRAPH_MEASURE_RUNS", "3"))
CONNECT_RETRIES = int(os.environ.get("GRAPH_CONNECT_RETRIES", "30"))
CONNECT_RETRY_DELAY_SEC = float(os.environ.get("GRAPH_CONNECT_RETRY_DELAY_SEC", "2"))

INDEX_MODES = {
    "no_index": ["02_drop_indexes.sql"],
    "basic_index": ["02_drop_indexes.sql", "03_create_basic_indexes.sql"],
    "composite_index": [
        "02_drop_indexes.sql",
        "03_create_basic_indexes.sql",
        "04_create_composite_indexes.sql",
    ],
}

QUERY_LIBRARY: dict[str, str] = {
    "reachability": """
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
    "k_hop_neighborhood": """
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
    "shortest_path_bfs_style": """
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
    "mutual_friends": """
        SELECT COUNT(*) AS mutual_count
        FROM (
            SELECT e1.dst AS mutual_friend
            FROM edges e1
            JOIN edges e2 ON e1.dst = e2.dst
            WHERE e1.src = %(u1)s::int AND e2.src = %(u2)s::int
            GROUP BY e1.dst
        ) t;
    """,
    "friend_recommendation": """
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
    "contact_tracing": """
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
    load_csv(cur, "nodes", ["id", "label", "node_type"], dataset_dir / "nodes.csv")
    load_csv(cur, "edges", ["src", "dst", "weight", "interaction_type"], dataset_dir / "edges.csv")
    cur.execute("ANALYZE nodes;")
    cur.execute("ANALYZE edges;")


def apply_index_mode(cur: psycopg.Cursor[Any], mode: str) -> None:
    for filename in INDEX_MODES[mode]:
        execute_sql_file(cur, filename)
    cur.execute("ANALYZE edges;")


def fetch_dataset_stats(cur: psycopg.Cursor[Any]) -> dict[str, int | float]:
    cur.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM nodes;")
    num_nodes, max_node_id = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM edges;")
    num_edges = cur.fetchone()[0]
    avg_out_degree = (num_edges / num_nodes) if num_nodes else 0.0
    density = (num_edges / (num_nodes * (num_nodes - 1))) if num_nodes > 1 else 0.0
    return {
        "num_nodes": int(num_nodes),
        "num_edges": int(num_edges),
        "max_node_id": int(max_node_id),
        "avg_out_degree": float(avg_out_degree),
        "density": float(density),
    }


def representative_nodes(max_node_id: int) -> list[int]:
    if max_node_id <= 0:
        return [1]
    candidates = [1, max_node_id // 4, max_node_id // 2, (3 * max_node_id) // 4, max_node_id]
    cleaned = sorted({min(max(1, x), max_node_id) for x in candidates})
    return cleaned


def build_query_cases(stats: dict[str, int | float]) -> dict[str, list[dict[str, Any]]]:
    n = int(stats["max_node_id"])
    sources = representative_nodes(n)
    sparse_sources = sources[: min(3, len(sources))]
    offsets = [max(7, n // 50), max(25, n // 20)]

    shortest_cases: list[dict[str, Any]] = []
    for src in sparse_sources[:2]:
        for depth in (4, 6):
            dst = ((src - 1 + offsets[0] + depth * 3) % n) + 1
            shortest_cases.append(
                {
                    "case_id": f"src_{src}_dst_{dst}_d{depth}",
                    "params": {"src": src, "dst": dst, "max_depth": depth},
                }
            )

    mutual_cases: list[dict[str, Any]] = []
    for i in range(len(sources) - 1):
        u1 = sources[i]
        u2 = sources[i + 1]
        if u1 != u2:
            mutual_cases.append({"case_id": f"u1_{u1}_u2_{u2}", "params": {"u1": u1, "u2": u2}})

    return {
        "reachability": [
            {"case_id": f"src_{src}", "params": {"src": src}}
            for src in sources
        ],
        "k_hop_neighborhood": [
            {"case_id": f"src_{src}_d{depth}", "params": {"src": src, "max_depth": depth}}
            for src in sparse_sources[:2]
            for depth in (2, 4)
        ],
        "shortest_path_bfs_style": shortest_cases,
        "mutual_friends": mutual_cases[:3],
        "friend_recommendation": [
            {"case_id": f"src_{src}", "params": {"src": src}}
            for src in sparse_sources
        ],
        "contact_tracing": [
            {"case_id": f"src_{src}_d{depth}", "params": {"src": src, "max_depth": depth}}
            for src in sparse_sources[:2]
            for depth in (2, 4)
        ],
    }


def walk_plan(node: dict[str, Any], depth: int = 1) -> dict[str, int]:
    children = node.get("Plans", []) or []
    node_type = str(node.get("Node Type", ""))
    is_scan = int("Scan" in node_type)
    is_join = int(("Join" in node_type) or (node_type == "Nested Loop"))
    is_sort = int("Sort" in node_type)
    is_recursive_union = int(node_type == "Recursive Union")
    is_aggregate = int("Aggregate" in node_type)

    acc = {
        "plan_nodes": 1,
        "plan_depth": depth,
        "scan_nodes": is_scan,
        "join_nodes": is_join,
        "sort_nodes": is_sort,
        "recursive_union_nodes": is_recursive_union,
        "aggregate_nodes": is_aggregate,
    }
    for child in children:
        child_acc = walk_plan(child, depth + 1)
        acc["plan_nodes"] += child_acc["plan_nodes"]
        acc["plan_depth"] = max(acc["plan_depth"], child_acc["plan_depth"])
        acc["scan_nodes"] += child_acc["scan_nodes"]
        acc["join_nodes"] += child_acc["join_nodes"]
        acc["sort_nodes"] += child_acc["sort_nodes"]
        acc["recursive_union_nodes"] += child_acc["recursive_union_nodes"]
        acc["aggregate_nodes"] += child_acc["aggregate_nodes"]
    return acc


def collect_plan_metrics(plan_json: list[dict[str, Any]]) -> dict[str, Any]:
    payload = plan_json[0]
    root_plan = payload["Plan"]
    structure = walk_plan(root_plan)
    return {
        "planning_time_ms": float(payload.get("Planning Time", 0.0)),
        "execution_time_ms": float(payload.get("Execution Time", 0.0)),
        "estimated_total_cost": float(root_plan.get("Total Cost", 0.0)),
        "actual_rows": int(root_plan.get("Actual Rows", 0)),
        "plan_rows": int(root_plan.get("Plan Rows", 0)),
        "root_node_type": str(root_plan.get("Node Type", "")),
        "shared_hit_blocks": int(root_plan.get("Shared Hit Blocks", 0)),
        "shared_read_blocks": int(root_plan.get("Shared Read Blocks", 0)),
        "shared_dirtied_blocks": int(root_plan.get("Shared Dirtied Blocks", 0)),
        "shared_written_blocks": int(root_plan.get("Shared Written Blocks", 0)),
        "local_hit_blocks": int(root_plan.get("Local Hit Blocks", 0)),
        "local_read_blocks": int(root_plan.get("Local Read Blocks", 0)),
        "temp_read_blocks": int(root_plan.get("Temp Read Blocks", 0)),
        "temp_written_blocks": int(root_plan.get("Temp Written Blocks", 0)),
        **structure,
    }


def mode_or_first(series: pd.Series) -> Any:
    modes = series.mode(dropna=True)
    if not modes.empty:
        return modes.iloc[0]
    if not series.empty:
        return series.iloc[0]
    return None


def connect_with_retry(conninfo: str) -> psycopg.Connection[Any]:
    last_error: Exception | None = None
    for attempt in range(1, CONNECT_RETRIES + 1):
        try:
            return psycopg.connect(conninfo, autocommit=True)
        except psycopg.OperationalError as exc:
            last_error = exc
            print(
                f"Database not ready yet (attempt {attempt}/{CONNECT_RETRIES}). "
                f"Retrying in {CONNECT_RETRY_DELAY_SEC} sec..."
            )
            time.sleep(CONNECT_RETRY_DELAY_SEC)
    assert last_error is not None
    raise last_error


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)

    datasets = sorted([d for d in DATA_DIR.iterdir() if d.is_dir()], key=lambda p: p.name)
    if not datasets:
        raise FileNotFoundError("No datasets found in data/. Run scripts/generate_data.py first.")

    detailed_rows: list[dict[str, Any]] = []

    with connect_with_retry(CONNINFO) as conn:
        with conn.cursor() as cur:
            execute_sql_file(cur, "01_schema.sql")

            for dataset_dir in datasets:
                dataset_name = dataset_dir.name
                print(f"\n=== Dataset: {dataset_name} ===")
                load_dataset(cur, dataset_dir)
                stats = fetch_dataset_stats(cur)
                query_cases = build_query_cases(stats)

                for mode in INDEX_MODES:
                    print(f"  -> Index mode: {mode}")
                    apply_index_mode(cur, mode)

                    for query_name, sql in QUERY_LIBRARY.items():
                        cases = query_cases[query_name]
                        for case in cases:
                            case_id = str(case["case_id"])
                            params = dict(case["params"])

                            for phase, run_count in (("warmup", WARMUP_RUNS), ("measure", MEASURE_RUNS)):
                                for run_idx in range(1, run_count + 1):
                                    explain_sql = f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"
                                    cur.execute(explain_sql, params)
                                    plan_json = cur.fetchone()[0]
                                    metrics = collect_plan_metrics(plan_json)

                                    plan_rel_path = None
                                    if phase == "measure" and run_idx == 1:
                                        plan_path = PLANS_DIR / (
                                            f"{dataset_name}__{mode}__{query_name}__{case_id}.json"
                                        )
                                        plan_path.write_text(json.dumps(plan_json, indent=2), encoding="utf-8")
                                        plan_rel_path = str(plan_path.relative_to(ROOT))

                                    row = {
                                        "dataset": dataset_name,
                                        "index_mode": mode,
                                        "query_name": query_name,
                                        "case_id": case_id,
                                        "run_phase": phase,
                                        "run_index": run_idx,
                                        **stats,
                                        **params,
                                        **metrics,
                                        "plan_file": plan_rel_path,
                                    }
                                    detailed_rows.append(row)

                            measured = [
                                r for r in detailed_rows
                                if r["dataset"] == dataset_name
                                and r["index_mode"] == mode
                                and r["query_name"] == query_name
                                and r["case_id"] == case_id
                                and r["run_phase"] == "measure"
                            ]
                            mean_exec = sum(r["execution_time_ms"] for r in measured) / max(len(measured), 1)
                            print(f"     {query_name:<24} case={case_id:<18} avg_exec={mean_exec:>10.3f} ms")

    df_runs = pd.DataFrame(detailed_rows)
    detailed_csv = RESULTS_DIR / "benchmark_runs.csv"
    df_runs.to_csv(detailed_csv, index=False)

    measure_df = df_runs[df_runs["run_phase"] == "measure"].copy()

    case_summary = (
        measure_df.groupby(["dataset", "index_mode", "query_name", "case_id"], as_index=False)
        .agg(
            num_nodes=("num_nodes", "first"),
            num_edges=("num_edges", "first"),
            avg_out_degree=("avg_out_degree", "first"),
            density=("density", "first"),
            mean_execution_time_ms=("execution_time_ms", "mean"),
            std_execution_time_ms=("execution_time_ms", "std"),
            min_execution_time_ms=("execution_time_ms", "min"),
            max_execution_time_ms=("execution_time_ms", "max"),
            mean_planning_time_ms=("planning_time_ms", "mean"),
            mean_estimated_total_cost=("estimated_total_cost", "mean"),
            mean_shared_hit_blocks=("shared_hit_blocks", "mean"),
            mean_shared_read_blocks=("shared_read_blocks", "mean"),
            mean_temp_written_blocks=("temp_written_blocks", "mean"),
            mean_plan_depth=("plan_depth", "mean"),
            mean_plan_nodes=("plan_nodes", "mean"),
            mean_scan_nodes=("scan_nodes", "mean"),
            mean_join_nodes=("join_nodes", "mean"),
            mean_recursive_union_nodes=("recursive_union_nodes", "mean"),
            representative_plan_file=("plan_file", mode_or_first),
            root_node_type=("root_node_type", mode_or_first),
            measure_runs=("execution_time_ms", "size"),
        )
    )
    case_summary["std_execution_time_ms"] = case_summary["std_execution_time_ms"].fillna(0.0)
    case_csv = RESULTS_DIR / "benchmark_case_summary.csv"
    case_summary.to_csv(case_csv, index=False)

    summary = (
        measure_df.groupby(["dataset", "index_mode", "query_name"], as_index=False)
        .agg(
            num_nodes=("num_nodes", "first"),
            num_edges=("num_edges", "first"),
            avg_out_degree=("avg_out_degree", "first"),
            density=("density", "first"),
            mean_execution_time_ms=("execution_time_ms", "mean"),
            std_execution_time_ms=("execution_time_ms", "std"),
            min_execution_time_ms=("execution_time_ms", "min"),
            max_execution_time_ms=("execution_time_ms", "max"),
            mean_planning_time_ms=("planning_time_ms", "mean"),
            mean_estimated_total_cost=("estimated_total_cost", "mean"),
            mean_shared_hit_blocks=("shared_hit_blocks", "mean"),
            mean_shared_read_blocks=("shared_read_blocks", "mean"),
            mean_temp_written_blocks=("temp_written_blocks", "mean"),
            mean_plan_depth=("plan_depth", "mean"),
            mean_plan_nodes=("plan_nodes", "mean"),
            mean_scan_nodes=("scan_nodes", "mean"),
            mean_join_nodes=("join_nodes", "mean"),
            mean_recursive_union_nodes=("recursive_union_nodes", "mean"),
            representative_plan_file=("plan_file", mode_or_first),
            root_node_type=("root_node_type", mode_or_first),
            total_measured_runs=("execution_time_ms", "size"),
            total_parameter_cases=("case_id", "nunique"),
        )
    )
    summary["std_execution_time_ms"] = summary["std_execution_time_ms"].fillna(0.0)
    summary["planning_to_execution_ratio"] = summary["mean_planning_time_ms"] / summary[
        "mean_execution_time_ms"
    ].clip(lower=1e-9)

    summary_csv = RESULTS_DIR / "benchmark_results.csv"
    summary.to_csv(summary_csv, index=False)

    print(f"\nSaved detailed run-level results to {detailed_csv}")
    print(f"Saved case-level summary to {case_csv}")
    print(f"Saved aggregated summary to {summary_csv}")


if __name__ == "__main__":
    main()
