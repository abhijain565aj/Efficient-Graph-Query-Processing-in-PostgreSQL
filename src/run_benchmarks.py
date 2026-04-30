#!/usr/bin/env python3
"""Benchmark exact, online-approx and cached-approx MemeGraph PostgreSQL queries.

Important methodology change from the earlier version:
- Latency rows are measured with normal SELECT calls, not EXPLAIN ANALYZE.
- EXPLAIN ANALYZE samples are collected separately because PostgreSQL's own
  docs warn that EXPLAIN ANALYZE can add significant measurement overhead.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import psycopg
from dotenv import load_dotenv
from tqdm import tqdm

from explain_plan_utils import summarize_explain_json


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run PostgreSQL feed-query benchmarks")
    p.add_argument("--users", type=int, default=50, help="Number of random users to sample")
    p.add_argument("--user-min", type=int, default=1)
    p.add_argument("--user-max", type=int, default=None, help="Default is max account id from DB")
    p.add_argument("--k-values", type=int, nargs="+", default=[1, 2, 3])
    p.add_argument("--modes", choices=["exact", "approx", "cached"], nargs="+", default=["exact", "approx", "cached"])
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--view-window-days", type=int, default=30)
    p.add_argument("--degree-cap", type=int, default=8)
    p.add_argument("--likes-per-neighbor", type=int, default=12)
    p.add_argument("--cache-neighbors", type=int, default=200, help="Number of feed items to precompute/keep per user+parameter key for cached mode")
    p.add_argument("--warmup", type=int, default=5)
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--index-scenario", default="optimized")
    p.add_argument("--dataset-label", default="current")
    p.add_argument("--label", default="manual")
    p.add_argument("--out", type=Path, default=Path("analysis_outputs/benchmarks.csv"))
    p.add_argument("--plans-out", type=Path, default=Path("analysis_outputs/plans.jsonl"))
    p.add_argument("--plan-samples-per-combo", type=int, default=1)
    p.add_argument("--prime-cache", action="store_true", help="Precompute neighbor and feed caches for sampled users before timing")
    p.add_argument("--seed", type=int, default=349)
    return p.parse_args()


def conninfo() -> str:
    load_dotenv()
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "55432")
    db = os.getenv("POSTGRES_DB", "memegraph")
    user = os.getenv("POSTGRES_USER", "memegraph")
    password = os.getenv("POSTGRES_PASSWORD", "memegraph")
    return f"host={host} port={port} dbname={db} user={user} password={password}"


def get_max_user(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(MAX(id), 1) FROM accounts")
        return int(cur.fetchone()[0])


def sql_for(mode: str, explain: bool = False) -> str:
    prefix = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " if explain else ""
    if mode == "exact":
        return prefix + "SELECT * FROM fn_feed_exact(%s, %s, %s, %s)"
    if mode == "approx":
        return prefix + "SELECT * FROM fn_feed_approx(%s, %s, %s, %s, %s, %s, 0.10)"
    if mode == "cached":
        return prefix + "SELECT * FROM fn_feed_cached(%s, %s, %s, %s, %s, %s, 0.10, %s)"
    raise ValueError(f"unknown mode: {mode}")


def params_for(args: argparse.Namespace, mode: str, user_id: int, k: int) -> tuple:
    if mode == "exact":
        return (user_id, k, args.limit, args.view_window_days)
    if mode == "approx":
        return (user_id, k, args.limit, args.view_window_days, args.degree_cap, args.likes_per_neighbor)
    if mode == "cached":
        return (
            user_id,
            k,
            args.limit,
            args.view_window_days,
            args.degree_cap,
            args.likes_per_neighbor,
            args.cache_neighbors,
        )
    raise ValueError(f"unknown mode: {mode}")


def prime_neighbor_cache(conn: psycopg.Connection, args: argparse.Namespace, users: List[int]) -> None:
    """Prime production-style serving caches for sampled users.

    Earlier versions only cached the k-hop neighbor set, which still left the
    online request doing many lateral recent-like lookups. Real feed systems
    usually precompute a candidate/ranking cache for active users and serve the
    request with an indexed lookup. We still refresh the neighbor cache because
    it is useful for the UI's /neighbors endpoint, but the latency benchmark for
    cached mode is now dominated by account_feed_cache lookup, as intended.
    """
    if "cached" not in args.modes:
        return

    max_k = max(args.k_values)
    print(
        f"Priming caches for {len(users)} sampled users "
        f"(k-values={args.k_values}, degree_cap={args.degree_cap}, cache_items={args.cache_neighbors})"
    )
    with conn.cursor() as cur:
        for user_id in tqdm(users, desc="prime-cache"):
            # Useful for the UI's cached-neighbor endpoint.
            cur.execute(
                "SELECT refresh_neighbor_cache_for_user(%s, %s, %s, %s)",
                (user_id, max_k, args.degree_cap, max(args.cache_neighbors, 200)),
            )
            # Actual fast serving path used by fn_feed_cached.
            for k in args.k_values:
                cur.execute(
                    "SELECT refresh_feed_cache_for_user(%s, %s, %s, %s, %s, %s, 0.10)",
                    (
                        user_id,
                        k,
                        max(args.cache_neighbors, args.limit),
                        args.view_window_days,
                        args.degree_cap,
                        args.likes_per_neighbor,
                    ),
                )
        cur.execute("ANALYZE account_neighbor_cache")
        cur.execute("ANALYZE account_feed_cache")


def run_one_normal(conn: psycopg.Connection, args: argparse.Namespace, mode: str, user_id: int, k: int) -> Dict[str, object]:
    start = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql_for(mode, explain=False), params_for(args, mode, user_id, k))
        rows = cur.fetchall()
    wall_ms = (time.perf_counter() - start) * 1000.0
    return {
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "query_name": "feed",
        "mode": mode,
        "user_id": user_id,
        "k": k,
        "result_limit": args.limit,
        "latency_ms": wall_ms,
        "planning_ms": None,
        "execution_ms": None,
        "returned_rows": len(rows),
        "buffers_hit": None,
        "buffers_read": None,
        "plan_node": None,
        "total_cost": None,
        "index_scenario": args.index_scenario,
        "dataset_label": args.dataset_label,
    }


def sample_explain(conn: psycopg.Connection, args: argparse.Namespace, mode: str, user_id: int, k: int) -> Dict[str, object]:
    with conn.cursor() as cur:
        cur.execute(sql_for(mode, explain=True), params_for(args, mode, user_id, k))
        explain_doc = cur.fetchone()[0]
    summary = summarize_explain_json(explain_doc)
    return {
        "mode": mode,
        "user_id": user_id,
        "k": k,
        "index_scenario": args.index_scenario,
        "dataset_label": args.dataset_label,
        "summary": summary,
        "plan": explain_doc,
    }


def warmup(conn: psycopg.Connection, args: argparse.Namespace, users: List[int]) -> None:
    if args.warmup <= 0:
        return
    jobs = []
    for mode in args.modes:
        for k in args.k_values:
            for user_id in users[: args.warmup]:
                jobs.append((mode, user_id, k))
    random.shuffle(jobs)
    for mode, user_id, k in tqdm(jobs, desc="warmup"):
        with conn.cursor() as cur:
            cur.execute(sql_for(mode, explain=False), params_for(args, mode, user_id, k))
            cur.fetchall()


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.plans_out.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    with psycopg.connect(conninfo(), autocommit=True) as conn:
        max_user = args.user_max or get_max_user(conn)
        users = [rng.randint(args.user_min, max_user) for _ in range(args.users)]

        if args.prime_cache:
            prime_neighbor_cache(conn, args, users)

        warmup(conn, args, users)

        fieldnames = [
            "measured_at", "query_name", "mode", "user_id", "k", "result_limit",
            "latency_ms", "planning_ms", "execution_ms", "returned_rows",
            "buffers_hit", "buffers_read", "plan_node", "total_cost",
            "index_scenario", "dataset_label",
        ]
        rows: List[Dict[str, object]] = []
        jobs = []
        for _repeat in range(args.repeats):
            for mode in args.modes:
                for k in args.k_values:
                    for user_id in users:
                        jobs.append((mode, user_id, k))
        rng.shuffle(jobs)

        plan_budget: Dict[Tuple[str, int], int] = defaultdict(lambda: args.plan_samples_per_combo)

        with args.plans_out.open("w") as pf:
            for mode, user_id, k in tqdm(jobs, desc="benchmark"):
                row = run_one_normal(conn, args, mode, user_id, k)
                rows.append(row)

                key = (mode, k)
                if plan_budget[key] > 0:
                    try:
                        plan = sample_explain(conn, args, mode, user_id, k)
                        pf.write(json.dumps(plan, default=str) + "\n")
                    except Exception as exc:  # plan capture should never fail the latency run
                        pf.write(json.dumps({"mode": mode, "k": k, "error": str(exc)}) + "\n")
                    plan_budget[key] -= 1

        with args.out.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    latencies = [float(r["latency_ms"]) for r in rows]
    if latencies:
        print(f"Wrote {len(rows)} benchmark rows to {args.out}")
        print(
            "latency_ms:",
            f"mean={statistics.mean(latencies):.2f}",
            f"median={statistics.median(latencies):.2f}",
            f"max={max(latencies):.2f}",
        )


if __name__ == "__main__":
    main()
