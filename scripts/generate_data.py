from __future__ import annotations

import argparse
import csv
import os
import random
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DatasetSpec:
    name: str
    num_nodes: int
    avg_degree: int
    seed: int


DEFAULT_SPECS = [
    DatasetSpec("small", 1000, 6, 11),
    DatasetSpec("medium", 5000, 8, 17),
    DatasetSpec("large", 10000, 10, 23),
]


def generate_graph(num_nodes: int, avg_degree: int, seed: int) -> tuple[list[tuple[int, str, str]], list[tuple[int, int, int, str]]]:
    rng = random.Random(seed)
    nodes = [(i, f"User_{i}", "person") for i in range(1, num_nodes + 1)]

    target_edges = num_nodes * avg_degree
    edge_set: set[tuple[int, int]] = set()

    # Ring backbone to keep the graph reasonably connected.
    for i in range(1, num_nodes):
        edge_set.add((i, i + 1))
    edge_set.add((num_nodes, 1))

    # Random edges.
    while len(edge_set) < target_edges:
        src = rng.randint(1, num_nodes)
        dst = rng.randint(1, num_nodes)
        if src != dst:
            edge_set.add((src, dst))

    interaction_types = ["friendship", "follow", "contact", "message"]
    edges = [
        (src, dst, 1, interaction_types[(src + dst + seed) % len(interaction_types)])
        for src, dst in sorted(edge_set)
    ]
    return nodes, edges


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic graph datasets as CSV files.")
    parser.add_argument("--output-dir", default="data", help="Directory where CSV folders will be created.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for spec in DEFAULT_SPECS:
        nodes, edges = generate_graph(spec.num_nodes, spec.avg_degree, spec.seed)
        ds_dir = output_dir / spec.name
        write_csv(ds_dir / "nodes.csv", ["id", "label", "node_type"], nodes)
        write_csv(ds_dir / "edges.csv", ["src", "dst", "weight", "interaction_type"], edges)
        print(f"Generated dataset '{spec.name}': nodes={len(nodes)}, edges={len(edges)} -> {ds_dir}")


if __name__ == "__main__":
    main()
