from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
CSV_PATH = RESULTS_DIR / "benchmark_results.csv"


def save_bar_plot(df: pd.DataFrame, dataset: str) -> None:
    sub = df[df["dataset"] == dataset].copy()
    if sub.empty:
        return

    pivot = sub.pivot(index="query_name", columns="index_mode", values="execution_time_ms")
    ax = pivot.plot(kind="bar", figsize=(12, 6))
    ax.set_title(f"Execution Time by Query and Index Mode ({dataset})")
    ax.set_ylabel("Execution Time (ms)")
    ax.set_xlabel("Query")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / f"execution_time_{dataset}.png", dpi=200)
    plt.close()


def save_cost_plot(df: pd.DataFrame, dataset: str) -> None:
    sub = df[df["dataset"] == dataset].copy()
    if sub.empty:
        return

    pivot = sub.pivot(index="query_name", columns="index_mode", values="estimated_total_cost")
    ax = pivot.plot(kind="bar", figsize=(12, 6))
    ax.set_title(f"Estimated Plan Cost by Query and Index Mode ({dataset})")
    ax.set_ylabel("Estimated Total Cost")
    ax.set_xlabel("Query")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    plt.savefig(PLOTS_DIR / f"estimated_cost_{dataset}.png", dpi=200)
    plt.close()


def main() -> None:
    if not CSV_PATH.exists():
        raise FileNotFoundError("results/benchmark_results.csv not found. Run benchmarks first.")

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(CSV_PATH)

    for dataset in sorted(df["dataset"].unique()):
        save_bar_plot(df, dataset)
        save_cost_plot(df, dataset)

    print(f"Saved plots to {PLOTS_DIR}")


if __name__ == "__main__":
    main()
