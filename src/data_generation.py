#!/usr/bin/env python3
"""Synthetic data generator for MemeGraph.

The generator is intentionally streaming/chunked so that large datasets can be
created without keeping the whole graph in memory. It creates five CSV files:

- accounts.csv
- memes.csv
- account_account.csv
- account_liked_meme.csv
- account_viewed_meme.csv

The default presets match the final benchmark requirement:
small = 1k users / 100 memes, medium = 10k users / 1k memes,
large = 1M users / 100k memes. Dense variants keep the same node/meme
counts but increase degree and interactions to make benchmark differences visible.
Generated CSVs are not committed.
"""
from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
from tqdm import tqdm


@dataclass(frozen=True)
class Preset:
    users: int
    memes: int
    avg_out_degree: float
    avg_likes_per_user: float
    avg_views_per_user: float


PRESETS: Dict[str, Preset] = {
    # Required benchmark scales for the final submission.
    # Important: default presets are intentionally denser than the first draft.
    # Low-degree toy graphs stay in memory and make all query plans look similar;
    # denser data exposes exact-recursive vs bounded-approx vs cached-serving behavior.
    "small": Preset(users=1_000, memes=100, avg_out_degree=24, avg_likes_per_user=40, avg_views_per_user=70),
    "medium": Preset(users=10_000, memes=1_000, avg_out_degree=48, avg_likes_per_user=70, avg_views_per_user=130),
    # Large remains 1M users / 100k memes, but is denser than the original draft.
    # It is still meant to be laptop-feasible after index/drop-before-COPY and shm tuning.
    "large": Preset(users=1_000_000, memes=100_000, avg_out_degree=12, avg_likes_per_user=20, avg_views_per_user=36),

    # Same node/meme counts, higher density. Use medium_dense for the clearest report plots.
    "small_dense": Preset(users=1_000, memes=100, avg_out_degree=48, avg_likes_per_user=75, avg_views_per_user=120),
    "medium_dense": Preset(users=10_000, memes=1_000, avg_out_degree=96, avg_likes_per_user=120, avg_views_per_user=220),
    # Heavy stress case: generates tens of millions of rows; use when you have enough disk/time.
    "large_dense": Preset(users=1_000_000, memes=100_000, avg_out_degree=18, avg_likes_per_user=32, avg_views_per_user=60),
}

CATEGORIES = [
    "cricket", "college", "programming", "bollywood", "anime", "sports",
    "startup", "exam", "hostel", "gaming", "politics", "random",
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate synthetic MemeGraph CSV data")
    p.add_argument("--preset", choices=PRESETS.keys(), default=None, help="Preset scale")
    p.add_argument("--users", type=int, default=None)
    p.add_argument("--memes", type=int, default=None)
    p.add_argument("--avg-out-degree", type=float, default=None)
    p.add_argument("--avg-likes-per-user", type=float, default=None)
    p.add_argument("--avg-views-per-user", type=float, default=None)
    p.add_argument("--seed", type=int, default=349)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--days", type=int, default=180, help="Synthetic event history window")
    p.add_argument("--chunk-users", type=int, default=25_000, help="Progress chunk for large runs")
    return p.parse_args()


def resolve_config(args: argparse.Namespace) -> Preset:
    base = PRESETS[args.preset] if args.preset else PRESETS["small"]
    return Preset(
        users=args.users or base.users,
        memes=args.memes or base.memes,
        avg_out_degree=args.avg_out_degree or base.avg_out_degree,
        avg_likes_per_user=args.avg_likes_per_user or base.avg_likes_per_user,
        avg_views_per_user=args.avg_views_per_user or base.avg_views_per_user,
    )


def random_timestamp(rng: np.random.Generator, now: datetime, days: int) -> str:
    # Exponential recency: more interactions happen recently.
    age_days = min(days, rng.exponential(scale=days / 3.0))
    seconds = int(age_days * 86400 + rng.integers(0, 86400))
    microseconds = int(rng.integers(0, 1_000_000))
    return (now - timedelta(seconds=seconds, microseconds=microseconds)).isoformat()


def batched_range(start: int, stop: int, batch: int) -> Iterable[Tuple[int, int]]:
    cur = start
    while cur <= stop:
        end = min(stop, cur + batch - 1)
        yield cur, end
        cur = end + 1


def open_writer(path: Path, header: List[str]):
    f = path.open("w", newline="")
    w = csv.writer(f)
    w.writerow(header)
    return f, w


def generate_accounts(out: Path, cfg: Preset, rng: np.random.Generator, now: datetime, days: int) -> None:
    f, w = open_writer(out / "accounts.csv", ["id", "username", "region_id", "created_at"])
    try:
        for user_id in tqdm(range(1, cfg.users + 1), desc="accounts"):
            region_id = int(rng.integers(1, 101))
            w.writerow([user_id, f"user_{user_id}", region_id, random_timestamp(rng, now, days * 3)])
    finally:
        f.close()


def generate_memes(out: Path, cfg: Preset, rng: np.random.Generator, now: datetime, days: int) -> None:
    f, w = open_writer(out / "memes.csv", ["id", "title", "category", "creator_id", "quality_score", "created_at"])
    try:
        for meme_id in tqdm(range(1, cfg.memes + 1), desc="memes"):
            category = CATEGORIES[int(rng.integers(0, len(CATEGORIES)))]
            creator_id = int(rng.integers(1, cfg.users + 1))
            quality = float(np.clip(rng.beta(2.0, 2.0), 0.01, 0.99))
            title = f"{category.title()} Meme #{meme_id}"
            w.writerow([meme_id, title, category, creator_id, f"{quality:.4f}", random_timestamp(rng, now, days)])
    finally:
        f.close()


def choose_heavy_tail_ids(rng: np.random.Generator, upper: int, n: int, alpha: float = 0.35) -> np.ndarray:
    """Sample ids from a fast heavy-tailed distribution.

    numpy.random.zipf becomes very slow when its exponent is close to 1, which
    is the regime that creates social-media-like skew. For a data generator we
    only need skew, not an exact Zipf law, so we use the power distribution with
    alpha < 1. This over-samples low-ranked ids and is fast at large scale.
    """
    if n <= 0:
        return np.empty(0, dtype=np.int64)
    ranks = np.floor(rng.power(alpha, size=n) * upper).astype(np.int64) + 1
    return np.clip(ranks, 1, upper)


def generate_edges(out: Path, cfg: Preset, rng: np.random.Generator, now: datetime, days: int) -> None:
    f, w = open_writer(out / "account_account.csv", ["src", "dst", "strength", "created_at"])
    try:
        for user_id in tqdm(range(1, cfg.users + 1), desc="edges"):
            degree = max(1, int(rng.poisson(cfg.avg_out_degree)))
            # Mix local-ish follows and celebrity/popular follows.
            local_n = degree // 2
            popular_n = degree - local_n
            local_offsets = rng.integers(-5000, 5001, size=local_n)
            local = ((user_id + local_offsets - 1) % cfg.users) + 1
            popular = choose_heavy_tail_ids(rng, cfg.users, popular_n, alpha=0.40)
            dsts = np.concatenate([local, popular])
            seen = set()
            for dst in dsts:
                dst_i = int(dst)
                if dst_i == user_id or dst_i in seen:
                    continue
                seen.add(dst_i)
                strength = float(np.clip(rng.beta(2.0, 5.0) + 0.1, 0.01, 1.0))
                w.writerow([user_id, dst_i, f"{strength:.4f}", random_timestamp(rng, now, days * 2)])
    finally:
        f.close()


def generate_likes(out: Path, cfg: Preset, rng: np.random.Generator, now: datetime, days: int) -> None:
    f, w = open_writer(out / "account_liked_meme.csv", ["account_id", "meme_id", "liked_at", "weight"])
    try:
        for user_id in tqdm(range(1, cfg.users + 1), desc="likes"):
            count = int(rng.poisson(cfg.avg_likes_per_user))
            memes = choose_heavy_tail_ids(rng, cfg.memes, count, alpha=0.35)
            seen = set()
            for meme_id in memes:
                meme_i = int(meme_id)
                if meme_i in seen:
                    continue
                seen.add(meme_i)
                weight = float(np.clip(rng.normal(1.0, 0.15), 0.2, 2.0))
                w.writerow([user_id, meme_i, random_timestamp(rng, now, days), f"{weight:.4f}"])
    finally:
        f.close()


def generate_views(out: Path, cfg: Preset, rng: np.random.Generator, now: datetime, days: int) -> None:
    f, w = open_writer(out / "account_viewed_meme.csv", ["account_id", "meme_id", "viewed_at"])
    try:
        for user_id in tqdm(range(1, cfg.users + 1), desc="views"):
            count = int(rng.poisson(cfg.avg_views_per_user))
            memes = choose_heavy_tail_ids(rng, cfg.memes, count, alpha=0.30)
            # Views may repeat across time, but avoid too many duplicates in one user row group.
            for meme_id in memes:
                w.writerow([user_id, int(meme_id), random_timestamp(rng, now, days)])
    finally:
        f.close()


def write_metadata(out: Path, cfg: Preset, args: argparse.Namespace) -> None:
    meta = out / "dataset_meta.txt"
    expected_edges = int(cfg.users * cfg.avg_out_degree)
    expected_likes = int(cfg.users * cfg.avg_likes_per_user)
    expected_views = int(cfg.users * cfg.avg_views_per_user)
    meta.write_text(
        "MemeGraph synthetic dataset\n"
        f"users={cfg.users}\n"
        f"memes={cfg.memes}\n"
        f"avg_out_degree={cfg.avg_out_degree}\n"
        f"avg_likes_per_user={cfg.avg_likes_per_user}\n"
        f"avg_views_per_user={cfg.avg_views_per_user}\n"
        f"seed={args.seed}\n"
        f"expected_edges_approx={expected_edges}\n"
        f"expected_likes_approx={expected_likes}\n"
        f"expected_views_approx={expected_views}\n"
    )


def main() -> None:
    args = parse_args()
    cfg = resolve_config(args)
    args.out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    now = datetime.now(timezone.utc)

    print("Generating MemeGraph dataset")
    print(cfg)
    print(f"Output: {args.out}")

    generate_accounts(args.out, cfg, rng, now, args.days)
    generate_memes(args.out, cfg, rng, now, args.days)
    generate_edges(args.out, cfg, rng, now, args.days)
    generate_likes(args.out, cfg, rng, now, args.days)
    generate_views(args.out, cfg, rng, now, args.days)
    write_metadata(args.out, cfg, args)

    print("Done. Load with: ./scripts/load_data.sh", args.out)


if __name__ == "__main__":
    main()
