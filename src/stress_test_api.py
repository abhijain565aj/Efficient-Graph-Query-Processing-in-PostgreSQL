#!/usr/bin/env python3
"""Async API stress tester for MemeGraph backend."""
from __future__ import annotations

import argparse
import asyncio
import csv
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import aiohttp


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Stress test the MemeGraph API")
    p.add_argument("--base-url", default="http://localhost:4000")
    p.add_argument("--users", type=int, default=1000, help="Random user ids sampled from [1, users]")
    p.add_argument("--requests", type=int, default=2000)
    p.add_argument("--concurrency", type=int, default=64)
    p.add_argument("--mode", choices=["exact", "approx", "cached"], default="cached")
    p.add_argument("--k", type=int, default=2)
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--out", type=Path, default=Path("analysis_outputs/api_stress.csv"))
    p.add_argument("--seed", type=int, default=349)
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--prewarm-cache", action="store_true", help="Precompute cached feeds for sampled users before stress phase")
    p.add_argument("--prewarm-limit", type=int, default=1000, help="Max unique users to prewarm")
    return p.parse_args()


async def fetch_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore, args: argparse.Namespace, user_id: int, idx: int) -> Dict[str, object]:
    url = f"{args.base_url.rstrip('/')}/api/users/{user_id}/feed"
    params = {"mode": args.mode, "k": str(args.k), "limit": str(args.limit), "degreeCap": "10", "likesPerNeighbor": "14", "cacheNeighbors": "250"}
    async with sem:
        started = datetime.now(timezone.utc).isoformat()
        t0 = time.perf_counter()
        status = 0
        ok = False
        error = ""
        rows = None
        try:
            async with session.get(url, params=params) as resp:
                status = resp.status
                data = await resp.json(content_type=None)
                ok = 200 <= resp.status < 300
                rows = len(data.get("items", [])) if isinstance(data, dict) else None
                if not ok:
                    error = str(data)[:200]
        except Exception as e:  # noqa: BLE001 - benchmark should record errors, not crash
            error = repr(e)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "request_id": idx,
            "started_at": started,
            "user_id": user_id,
            "mode": args.mode,
            "k": args.k,
            "limit": args.limit,
            "status": status,
            "ok": ok,
            "latency_ms": latency_ms,
            "rows": rows,
            "error": error,
        }


async def prewarm_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore, args: argparse.Namespace, user_id: int) -> None:
    url = f"{args.base_url.rstrip('/')}/api/users/{user_id}/refresh-feed-cache"
    params = {"k": str(args.k), "degreeCap": "10", "cacheNeighbors": "250"}
    async with sem:
        try:
            async with session.post(url, params=params) as resp:
                await resp.read()
        except Exception:
            # Prewarming is best-effort; benchmark phase records real errors.
            pass


async def run(args: argparse.Namespace) -> List[Dict[str, object]]:
    rng = random.Random(args.seed)
    user_ids = [rng.randint(1, args.users) for _ in range(args.requests)]
    sem = asyncio.Semaphore(args.concurrency)
    timeout = aiohttp.ClientTimeout(total=args.timeout)
    connector = aiohttp.TCPConnector(limit=args.concurrency)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        if args.mode == "cached" and args.prewarm_cache:
            unique_users = list(dict.fromkeys(user_ids))[: args.prewarm_limit]
            print(f"Prewarming cached feeds for {len(unique_users)} users")
            warm_tasks = [prewarm_one(session, sem, args, u) for u in unique_users]
            for fut in asyncio.as_completed(warm_tasks):
                await fut

        tasks = [fetch_one(session, sem, args, user_id, i) for i, user_id in enumerate(user_ids)]
        results = []
        for fut in asyncio.as_completed(tasks):
            results.append(await fut)
        return results


def percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int((len(values) - 1) * p)
    return values[idx]


def main() -> None:
    args = parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    rows = asyncio.run(run(args))
    elapsed = time.perf_counter() - t0

    fieldnames = ["request_id", "started_at", "user_id", "mode", "k", "limit", "status", "ok", "latency_ms", "rows", "error"]
    with args.out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    latencies = [float(r["latency_ms"]) for r in rows if r["ok"]]
    ok_count = sum(1 for r in rows if r["ok"])
    print(f"Wrote {len(rows)} rows to {args.out}")
    print(f"ok={ok_count}/{len(rows)} throughput={len(rows)/elapsed:.2f} req/s elapsed={elapsed:.2f}s")
    if latencies:
        print(
            f"latency_ms mean={statistics.mean(latencies):.2f} "
            f"p50={percentile(latencies, 0.50):.2f} "
            f"p95={percentile(latencies, 0.95):.2f} "
            f"p99={percentile(latencies, 0.99):.2f} "
            f"max={max(latencies):.2f}"
        )


if __name__ == "__main__":
    main()
