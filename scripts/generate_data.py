from __future__ import annotations

import argparse
import csv
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class DatasetSpec:
    name: str
    num_nodes: int
    avg_degree: int
    seed: int
    community_count: int
    hub_fraction: float
    local_bias: float


DEFAULT_SPECS = [
    DatasetSpec("small", 1500, 8, 11, 6, 0.02, 0.72),
    DatasetSpec("medium", 6000, 10, 17, 12, 0.015, 0.74),
    DatasetSpec("large", 12000, 12, 23, 20, 0.01, 0.76),
]

INTERACTION_TYPES = ["friendship", "follow", "contact", "message"]
NODE_TYPES = ["person", "person", "person", "person", "group", "organisation"]


def write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def generate_nodes(spec: DatasetSpec) -> list[tuple[int, str, str]]:
    nodes = []
    for i in range(1, spec.num_nodes + 1):
        node_type = NODE_TYPES[(i + spec.seed) % len(NODE_TYPES)]
        nodes.append((i, f"Node_{i}", node_type))
    return nodes


def community_bounds(num_nodes: int, community_count: int) -> list[tuple[int, int]]:
    bounds: list[tuple[int, int]] = []
    base = num_nodes // community_count
    extra = num_nodes % community_count
    start = 1
    for c in range(community_count):
        size = base + (1 if c < extra else 0)
        end = start + size - 1
        bounds.append((start, end))
        start = end + 1
    return bounds


def node_to_community(node_id: int, bounds: list[tuple[int, int]]) -> int:
    for idx, (lo, hi) in enumerate(bounds):
        if lo <= node_id <= hi:
            return idx
    return len(bounds) - 1


def sample_node_from_community(rng: random.Random, bounds: tuple[int, int], exclude: int | None = None) -> int:
    lo, hi = bounds
    while True:
        x = rng.randint(lo, hi)
        if exclude is None or x != exclude:
            return x


def generate_graph(spec: DatasetSpec) -> tuple[list[tuple[int, str, str]], list[tuple[int, int, int, str]], dict]:
    rng = random.Random(spec.seed)
    nodes = generate_nodes(spec)
    target_edges = spec.num_nodes * spec.avg_degree
    bounds = community_bounds(spec.num_nodes, spec.community_count)
    hubs = list(range(1, max(2, int(spec.num_nodes * spec.hub_fraction)) + 1))

    edge_set: set[tuple[int, int]] = set()

    # Ring backbone for weak global connectivity.
    for i in range(1, spec.num_nodes):
        edge_set.add((i, i + 1))
    edge_set.add((spec.num_nodes, 1))

    # Local neighbourhood edges inside communities.
    for node_id in range(1, spec.num_nodes + 1):
        comm_id = node_to_community(node_id, bounds)
        lo, hi = bounds[comm_id]
        for delta in (1, 2):
            dst = node_id + delta
            if dst <= hi:
                edge_set.add((node_id, dst))
            dst_back = node_id - delta
            if dst_back >= lo:
                edge_set.add((node_id, dst_back))

    while len(edge_set) < target_edges:
        src = rng.randint(1, spec.num_nodes)
        src_comm = node_to_community(src, bounds)

        roll = rng.random()
        if roll < spec.local_bias:
            dst = sample_node_from_community(rng, bounds[src_comm], exclude=src)
        elif roll < spec.local_bias + 0.15:
            dst = rng.choice(hubs)
            if dst == src:
                continue
        else:
            other_comm = rng.randrange(spec.community_count)
            if other_comm == src_comm:
                other_comm = (other_comm + 1) % spec.community_count
            dst = sample_node_from_community(rng, bounds[other_comm], exclude=src)

        if src != dst:
            edge_set.add((src, dst))
            if rng.random() < 0.18:
                edge_set.add((dst, src))

    edges = []
    for src, dst in sorted(edge_set):
        weight = 1 + ((src + 3 * dst + spec.seed) % 5)
        interaction = INTERACTION_TYPES[(src + dst + spec.seed) % len(INTERACTION_TYPES)]
        edges.append((src, dst, weight, interaction))

    metadata = {
        **asdict(spec),
        "actual_num_edges": len(edges),
        "average_out_degree": len(edges) / spec.num_nodes,
        "density": len(edges) / (spec.num_nodes * (spec.num_nodes - 1)),
    }
    return nodes, edges, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate more informative synthetic graph datasets.")
    parser.add_argument("--output-dir", default="data", help="Directory where dataset folders will be created.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for spec in DEFAULT_SPECS:
        nodes, edges, metadata = generate_graph(spec)
        ds_dir = output_dir / spec.name
        write_csv(ds_dir / "nodes.csv", ["id", "label", "node_type"], nodes)
        write_csv(ds_dir / "edges.csv", ["src", "dst", "weight", "interaction_type"], edges)
        (ds_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(
            f"Generated dataset '{spec.name}': nodes={len(nodes)}, edges={len(edges)}, "
            f"avg_degree={metadata['average_out_degree']:.2f} -> {ds_dir}"
        )


if __name__ == "__main__":
    main()
