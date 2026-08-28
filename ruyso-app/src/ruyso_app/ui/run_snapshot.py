"""
Detecting which pipeline steps have been changed since the last
successful run, so the Table tab can flag a shown table as stale
("· modified") rather than pretending it still reflects the pipeline.

A *signature* captures everything about a node that could change its
output: its type, its parameter values, and its incoming wiring. A
node counts as modified when its own signature changed, when it did
not exist at run time, or -- transitively -- when any upstream node is
modified.

Pure functions over ``engine.PipelineGraph``; no UI, fully testable.
"""

from __future__ import annotations

from ruyso_app.engine.graph import PipelineGraph


def pipeline_signatures(pipeline: PipelineGraph) -> dict[str, str]:
    """``node_id -> signature`` for every node in ``pipeline``."""
    incoming: dict[str, list[str]] = {}
    for conn in pipeline.connections:
        incoming.setdefault(conn.target_node, []).append(
            f"{conn.source_node}.{conn.source_port}->{conn.target_port}"
        )
    signatures: dict[str, str] = {}
    for node_id, spec in pipeline.nodes.items():
        params = repr(sorted(spec.params.items(), key=lambda kv: kv[0]))
        wires = repr(sorted(incoming.get(node_id, [])))
        signatures[node_id] = f"{spec.node_type}|{params}|{wires}"
    return signatures


def modified_since_run(
    pipeline: PipelineGraph, run_signatures: dict[str, str]
) -> set[str]:
    """
    Node ids whose output may differ from ``run_signatures`` (the
    signatures captured when the pipeline was last run).

    Empty if ``run_signatures`` is empty (nothing has been run).
    """
    if not run_signatures:
        return set()

    current = pipeline_signatures(pipeline)

    try:
        order = pipeline.topological_order()
    except Exception:  # noqa: BLE001 - fall back to arbitrary order
        order = list(pipeline.nodes)

    upstream: dict[str, set[str]] = {}
    for conn in pipeline.connections:
        upstream.setdefault(conn.target_node, set()).add(conn.source_node)

    modified: set[str] = set()
    for node_id in order:
        if run_signatures.get(node_id) != current.get(node_id):
            modified.add(node_id)
        elif any(up in modified for up in upstream.get(node_id, ())):
            modified.add(node_id)
    return modified
