from __future__ import annotations

from typing import Any, Dict, Tuple


def _sum_buffers(node: Dict[str, Any]) -> Tuple[int, int]:
    hit = int(node.get("Shared Hit Blocks", 0) or 0)
    read = int(node.get("Shared Read Blocks", 0) or 0)
    for child in node.get("Plans", []) or []:
        c_hit, c_read = _sum_buffers(child)
        hit += c_hit
        read += c_read
    return hit, read


def summarize_explain_json(explain_result: Any) -> Dict[str, Any]:
    """Return compact metrics from EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON).

    psycopg returns a nested Python object for JSON output. psql-style drivers may
    wrap it in one extra list. This helper handles both shapes.
    """
    root = explain_result
    if isinstance(root, list) and root and isinstance(root[0], list):
        root = root[0]
    if isinstance(root, list) and root and isinstance(root[0], dict):
        doc = root[0]
    elif isinstance(root, dict):
        doc = root
    else:
        return {}

    plan = doc.get("Plan", {})
    hit, read = _sum_buffers(plan)
    return {
        "planning_ms": float(doc.get("Planning Time", 0.0) or 0.0),
        "execution_ms": float(doc.get("Execution Time", 0.0) or 0.0),
        "returned_rows": int(plan.get("Actual Rows", 0) or 0),
        "buffers_hit": hit,
        "buffers_read": read,
        "plan_node": plan.get("Node Type", "unknown"),
        "total_cost": float(plan.get("Total Cost", 0.0) or 0.0),
    }
