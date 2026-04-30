from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"
PLOTS_DIR = RESULTS_DIR / "plots"
SUMMARY_CSV = RESULTS_DIR / "benchmark_results.csv"
CASE_CSV = RESULTS_DIR / "benchmark_case_summary.csv"
RUNS_CSV = RESULTS_DIR / "benchmark_runs.csv"

DATASET_ORDER = ["small", "medium", "large"]
INDEX_ORDER = ["no_index", "basic_index", "composite_index"]
QUERY_ORDER = [
    "reachability",
    "k_hop_neighborhood",
    "shortest_path_bfs_style",
    "mutual_friends",
    "friend_recommendation",
    "contact_tracing",
]


def ordered_unique(values: list[str], preferred_order: list[str]) -> list[str]:
    seen = set(values)
    ordered = [v for v in preferred_order if v in seen]
    ordered += [v for v in values if v not in ordered]
    return ordered


def nice_name(name: str) -> str:
    return name.replace("_", " ").title()


def prepare_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["dataset"] = pd.Categorical(out["dataset"], categories=DATASET_ORDER, ordered=True)
    out["index_mode"] = pd.Categorical(out["index_mode"], categories=INDEX_ORDER, ordered=True)
    out["query_name"] = pd.Categorical(out["query_name"], categories=QUERY_ORDER, ordered=True)
    out = out.sort_values(["dataset", "query_name", "index_mode"])
    return out


def save_grouped_bar_with_error(
    sub: pd.DataFrame,
    value_col: str,
    err_col: str,
    ylabel: str,
    title: str,
    out_path: Path,
    log_scale: bool = False,
) -> None:
    queries = [q for q in QUERY_ORDER if q in set(sub["query_name"].astype(str))]
    index_modes = [m for m in INDEX_ORDER if m in set(sub["index_mode"].astype(str))]
    if not queries or not index_modes:
        return

    x = np.arange(len(queries))
    width = 0.24 if len(index_modes) >= 3 else 0.35

    fig, ax = plt.subplots(figsize=(13, 6.5))
    for i, mode in enumerate(index_modes):
        vals = []
        errs = []
        for q in queries:
            row = sub[(sub["query_name"].astype(str) == q) & (sub["index_mode"].astype(str) == mode)]
            if row.empty:
                vals.append(np.nan)
                errs.append(0.0)
            else:
                vals.append(float(row.iloc[0][value_col]))
                errs.append(float(row.iloc[0][err_col]))
        ax.bar(x + (i - (len(index_modes) - 1) / 2) * width, vals, width=width, yerr=errs, capsize=4, label=mode)

    ax.set_xticks(x)
    ax.set_xticklabels([q.replace("_", "\n") for q in queries], rotation=0)
    ax.set_ylabel(ylabel)
    ax.set_xlabel("Query")
    ax.set_title(title)
    if log_scale:
        ax.set_yscale("log")
    ax.legend(title="index_mode")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=220)
    plt.close(fig)


def save_speedup_heatmap(sub: pd.DataFrame, dataset: str) -> None:
    queries = [q for q in QUERY_ORDER if q in set(sub["query_name"].astype(str))]
    base = sub[sub["index_mode"].astype(str) == "no_index"].set_index("query_name")
    comparison_modes = [m for m in ["basic_index", "composite_index"] if m in set(sub["index_mode"].astype(str))]
    if base.empty or not comparison_modes:
        return

    values = []
    for mode in comparison_modes:
        comp = sub[sub["index_mode"].astype(str) == mode].set_index("query_name")
        row_vals = []
        for q in queries:
            if q in base.index and q in comp.index:
                denom = float(comp.loc[q, "mean_execution_time_ms"])
                numer = float(base.loc[q, "mean_execution_time_ms"])
                row_vals.append(numer / denom if denom > 0 else np.nan)
            else:
                row_vals.append(np.nan)
        values.append(row_vals)

    arr = np.array(values)
    fig, ax = plt.subplots(figsize=(12, 3.8))
    im = ax.imshow(arr, aspect="auto")
    ax.set_xticks(np.arange(len(queries)))
    ax.set_xticklabels([q.replace("_", "\n") for q in queries])
    ax.set_yticks(np.arange(len(comparison_modes)))
    ax.set_yticklabels(comparison_modes)
    ax.set_title(f"Speedup over No Index ({dataset})")
    ax.set_xlabel("Query")
    ax.set_ylabel("Indexed Mode")

    for i in range(arr.shape[0]):
        for j in range(arr.shape[1]):
            if not np.isnan(arr[i, j]):
                ax.text(j, i, f"{arr[i, j]:.2f}x", ha="center", va="center", fontsize=9)

    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("Speedup = no_index / indexed_runtime")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"speedup_heatmap_{dataset}.png", dpi=220)
    plt.close(fig)


def save_scaling_plot(summary: pd.DataFrame, query_name: str) -> None:
    sub = summary[summary["query_name"].astype(str) == query_name].copy()
    if sub.empty:
        return

    datasets = [d for d in DATASET_ORDER if d in set(sub["dataset"].astype(str))]
    x = np.arange(len(datasets))

    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    for mode in INDEX_ORDER:
        part = sub[sub["index_mode"].astype(str) == mode].copy()
        if part.empty:
            continue
        part = part.set_index(part["dataset"].astype(str))
        y = [float(part.loc[d, "mean_execution_time_ms"]) if d in part.index else np.nan for d in datasets]
        ax.plot(x, y, marker="o", linewidth=2, label=mode)

    ax.set_xticks(x)
    ax.set_xticklabels(datasets)
    ax.set_xlabel("Dataset")
    ax.set_ylabel("Mean Execution Time (ms)")
    ax.set_yscale("log")
    ax.set_title(f"Scaling of {nice_name(query_name)}")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(title="index_mode")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"scaling_{query_name}.png", dpi=220)
    plt.close(fig)


def save_cost_runtime_scatter(summary: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(10.5, 6))
    for mode in INDEX_ORDER:
        part = summary[summary["index_mode"].astype(str) == mode]
        if part.empty:
            continue
        ax.scatter(part["mean_estimated_total_cost"], part["mean_execution_time_ms"], s=65, alpha=0.8, label=mode)

    ax.set_xlabel("Mean Estimated Total Cost")
    ax.set_ylabel("Mean Execution Time (ms)")
    ax.set_yscale("log")
    ax.set_title("Planner Cost vs Measured Runtime")
    ax.grid(alpha=0.25)
    ax.legend(title="index_mode")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "cost_vs_runtime_all.png", dpi=220)
    plt.close(fig)


def save_planning_ratio_plot(summary: pd.DataFrame) -> None:
    grouped = (
        summary.groupby(["query_name", "index_mode"], as_index=False, observed=False)["planning_to_execution_ratio"]
        .mean()
        .sort_values(["query_name", "index_mode"])
    )
    queries = [q for q in QUERY_ORDER if q in set(grouped["query_name"].astype(str))]
    x = np.arange(len(queries))
    width = 0.24

    fig, ax = plt.subplots(figsize=(13, 6))
    for i, mode in enumerate(INDEX_ORDER):
        vals = []
        for q in queries:
            row = grouped[(grouped["query_name"].astype(str) == q) & (grouped["index_mode"].astype(str) == mode)]
            vals.append(float(row.iloc[0]["planning_to_execution_ratio"]) if not row.empty else np.nan)
        ax.bar(x + (i - 1) * width, vals, width=width, label=mode)

    ax.set_xticks(x)
    ax.set_xticklabels([q.replace("_", "\n") for q in queries])
    ax.set_xlabel("Query")
    ax.set_ylabel("Planning Time / Execution Time")
    ax.set_title("Relative Planning Overhead by Query")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(title="index_mode")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "planning_ratio_by_query.png", dpi=220)
    plt.close(fig)


def save_buffer_plot(sub: pd.DataFrame, dataset: str, value_col: str, ylabel: str, stem: str) -> None:
    save_grouped_bar_with_error(
        sub=sub.assign(dummy_err=0.0),
        value_col=value_col,
        err_col="dummy_err",
        ylabel=ylabel,
        title=f"{ylabel} by Query and Index Mode ({dataset})",
        out_path=PLOTS_DIR / f"{stem}_{dataset}.png",
        log_scale=True,
    )


def save_case_variation_plot(case_df: pd.DataFrame, dataset: str, query_name: str) -> None:
    sub = case_df[(case_df["dataset"].astype(str) == dataset) & (case_df["query_name"].astype(str) == query_name)].copy()
    if sub.empty:
        return

    sub = sub.sort_values(["case_id", "index_mode"])
    cases = list(dict.fromkeys(sub["case_id"].astype(str).tolist()))
    x = np.arange(len(cases))
    width = 0.24

    fig, ax = plt.subplots(figsize=(12.5, 5.5))
    for i, mode in enumerate(INDEX_ORDER):
        part = sub[sub["index_mode"].astype(str) == mode].copy()
        part["case_id"] = part["case_id"].astype(str)
        part = part.set_index("case_id")
        y = [float(part.loc[c, "mean_execution_time_ms"]) if c in part.index else np.nan for c in cases]
        ax.bar(x + (i - 1) * width, y, width=width, label=mode)

    ax.set_xticks(x)
    ax.set_xticklabels(cases, rotation=30, ha="right")
    ax.set_xlabel("Parameter Case")
    ax.set_ylabel("Mean Execution Time (ms)")
    ax.set_yscale("log")
    ax.set_title(f"Case-wise Runtime Variation: {nice_name(query_name)} ({dataset})")
    ax.grid(axis="y", alpha=0.25)
    ax.legend(title="index_mode")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / f"case_variation_{query_name}_{dataset}.png", dpi=220)
    plt.close(fig)


def save_dataset_summary_table(summary: pd.DataFrame) -> None:
    best = summary.sort_values("mean_execution_time_ms").groupby(["dataset", "query_name"], as_index=False, observed=False).first()
    best = best[["dataset", "query_name", "index_mode", "mean_execution_time_ms", "mean_estimated_total_cost"]].copy()
    best.rename(
        columns={
            "index_mode": "best_index_mode",
            "mean_execution_time_ms": "best_mean_execution_time_ms",
            "mean_estimated_total_cost": "best_mean_estimated_total_cost",
        },
        inplace=True,
    )
    best.to_csv(RESULTS_DIR / "best_index_mode_by_query.csv", index=False)


def main() -> None:
    if not SUMMARY_CSV.exists():
        raise FileNotFoundError("results/benchmark_results.csv not found. Run benchmarks first.")

    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    summary = prepare_summary(pd.read_csv(SUMMARY_CSV))
    case_df = pd.read_csv(CASE_CSV) if CASE_CSV.exists() else pd.DataFrame()

    datasets = ordered_unique(summary["dataset"].astype(str).tolist(), DATASET_ORDER)
    for dataset in datasets:
        sub = summary[summary["dataset"].astype(str) == dataset].copy()
        if sub.empty:
            continue
        save_grouped_bar_with_error(
            sub=sub,
            value_col="mean_execution_time_ms",
            err_col="std_execution_time_ms",
            ylabel="Mean Execution Time (ms)",
            title=f"Execution Time by Query and Index Mode ({dataset})",
            out_path=PLOTS_DIR / f"execution_time_{dataset}.png",
            log_scale=True,
        )
        save_grouped_bar_with_error(
            sub=sub.assign(dummy_err=0.0),
            value_col="mean_estimated_total_cost",
            err_col="dummy_err",
            ylabel="Mean Estimated Total Cost",
            title=f"Planner Cost by Query and Index Mode ({dataset})",
            out_path=PLOTS_DIR / f"estimated_cost_{dataset}.png",
            log_scale=True,
        )
        save_speedup_heatmap(sub, dataset)
        save_buffer_plot(sub, dataset, "mean_shared_read_blocks", "Mean Shared Read Blocks", "shared_reads")
        save_buffer_plot(sub, dataset, "mean_shared_hit_blocks", "Mean Shared Hit Blocks", "shared_hits")

    for query_name in QUERY_ORDER:
        save_scaling_plot(summary, query_name)

    save_cost_runtime_scatter(summary)
    save_planning_ratio_plot(summary)
    save_dataset_summary_table(summary)

    if not case_df.empty:
        for dataset in datasets:
            for query_name in ["k_hop_neighborhood", "shortest_path_bfs_style", "contact_tracing"]:
                save_case_variation_plot(case_df, dataset, query_name)

    print(f"Saved plots to {PLOTS_DIR}")


if __name__ == "__main__":
    main()
