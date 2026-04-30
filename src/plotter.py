#!/usr/bin/env python3
"""Plot benchmark outputs for the final report."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Create plots from benchmark CSV")
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--outdir", type=Path, default=Path("analysis_outputs/plots"))
    return p.parse_args()


def q95(x):
    return x.quantile(0.95)


def q99(x):
    return x.quantile(0.99)


def save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    print(f"saved {path}")


def plot_latency_by_mode(df: pd.DataFrame, outdir: Path) -> None:
    summary = (
        df.groupby(["index_scenario", "mode"], dropna=False)["latency_ms"]
        .agg(mean="mean", median="median", p95=q95, p99=q99)
        .reset_index()
    )
    summary.to_csv(outdir / "latency_summary_by_mode.csv", index=False)

    labels = [f"{r.index_scenario}\n{r.mode}" for r in summary.itertuples()]
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(max(8, len(labels) * 0.8), 5))
    ax.bar(x, summary["p95"])
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=30, ha="right")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title("Feed-query p95 latency by mode and index scenario")
    save(fig, outdir / "latency_by_mode.png")


def plot_latency_vs_k(df: pd.DataFrame, outdir: Path) -> None:
    summary = df.groupby(["mode", "k"], dropna=False)["latency_ms"].agg(median="median", p95=q95).reset_index()
    fig, ax = plt.subplots(figsize=(8, 5))
    for mode, group in summary.groupby("mode"):
        group = group.sort_values("k")
        ax.plot(group["k"], group["p95"], marker="o", label=f"{mode} p95")
    ax.set_xlabel("k-hop depth")
    ax.set_ylabel("p95 latency (ms)")
    ax.set_title("Latency growth as k increases")
    ax.legend()
    save(fig, outdir / "latency_vs_k.png")


def plot_buffers(df: pd.DataFrame, outdir: Path) -> None:
    if "buffers_read" not in df.columns:
        return
    summary = df.groupby(["mode", "k"], dropna=False)[["buffers_hit", "buffers_read"]].median().reset_index()
    fig, ax = plt.subplots(figsize=(8, 5))
    for mode, group in summary.groupby("mode"):
        group = group.sort_values("k")
        ax.plot(group["k"], group["buffers_hit"] + group["buffers_read"], marker="o", label=mode)
    ax.set_xlabel("k-hop depth")
    ax.set_ylabel("median shared buffers touched")
    ax.set_title("Buffer footprint of exact vs approximate query")
    ax.legend()
    save(fig, outdir / "buffers_vs_k.png")


def plot_latency_distribution(df: pd.DataFrame, outdir: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = []
    data = []
    for mode, group in df.groupby("mode"):
        labels.append(mode)
        data.append(group["latency_ms"].values)
    ax.boxplot(data, tick_labels=labels, showfliers=False)
    ax.set_ylabel("latency (ms)")
    ax.set_title("Latency distribution without outlier clutter")
    save(fig, outdir / "latency_distribution.png")


def plot_throughput_from_stress(stress_path: Path, outdir: Path) -> None:
    if not stress_path.exists():
        return
    df = pd.read_csv(stress_path)
    if df.empty or "latency_ms" not in df.columns:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    df = df.sort_values("started_at") if "started_at" in df.columns else df
    ax.plot(range(len(df)), df["latency_ms"].rolling(50, min_periods=1).median())
    ax.set_xlabel("request index")
    ax.set_ylabel("rolling median latency (ms)")
    ax.set_title("API stress-test rolling median latency")
    save(fig, outdir / "api_stress_rolling_latency.png")


def main() -> None:
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.input)
    if df.empty:
        raise SystemExit("Benchmark CSV is empty")
    df["latency_ms"] = pd.to_numeric(df["latency_ms"], errors="coerce")
    df = df.dropna(subset=["latency_ms"])

    plot_latency_by_mode(df, args.outdir)
    plot_latency_vs_k(df, args.outdir)
    plot_buffers(df, args.outdir)
    plot_latency_distribution(df, args.outdir)
    plot_throughput_from_stress(args.input.parent / "api_stress.csv", args.outdir)

    print(f"All plots written to {args.outdir}")


if __name__ == "__main__":
    main()
