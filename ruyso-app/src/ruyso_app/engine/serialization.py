"""
Conversion between a PipelineGraph and its on-disk JSON representation.

The JSON schema is intentionally minimal — a list of nodes and a list
of connections — so that a pipeline can be written by hand (as in
``examples/simple_regression_pipeline.json``) without any tooling:

    {
      "nodes": [
        {"id": "load", "node_type": "csv_loader", "params": {"filepath": "data.csv"}},
        {"id": "clean", "node_type": "drop_na", "params": {}}
      ],
      "connections": [
        {"source_node": "load", "source_port": "df",
         "target_node": "clean", "target_port": "df"}
      ]
    }

This module only converts between this schema and a PipelineGraph —
it never validates node types or ports itself (that is
``PipelineGraph.validate()``'s job), so a syntactically valid but
semantically broken JSON file will load fine and fail only when
``validate()`` or the scheduler is run on it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph


def graph_to_dict(graph: PipelineGraph) -> dict[str, Any]:
    """
    Convert a PipelineGraph to a plain, JSON-serializable dict.

    Args:
        graph: The graph to serialize.

    Returns:
        A dict with "nodes" and "connections" lists, matching the
        module-level schema documented above.
    """
    return {
        "nodes": [spec.model_dump() for spec in graph.nodes.values()],
        "connections": [conn.model_dump() for conn in graph.connections],
    }


def graph_from_dict(data: dict[str, Any]) -> PipelineGraph:
    """
    Build a PipelineGraph from a plain dict matching the module schema.

    Args:
        data: A dict with "nodes" and (optionally) "connections" lists.

    Returns:
        A populated (but not yet validated) PipelineGraph. Call
        ``graph.validate()`` before executing it.
    """
    graph = PipelineGraph()
    for node_data in data.get("nodes", []):
        graph.add_node(NodeSpec(**node_data))
    for conn_data in data.get("connections", []):
        graph.add_connection(Connection(**conn_data))
    return graph


def graph_to_json(graph: PipelineGraph, *, indent: int = 2) -> str:
    """Serialize a PipelineGraph directly to a JSON string."""
    return json.dumps(graph_to_dict(graph), indent=indent)


def graph_from_json(text: str) -> PipelineGraph:
    """Build a PipelineGraph directly from a JSON string."""
    return graph_from_dict(json.loads(text))


def save_graph(graph: PipelineGraph, path: str | Path, *, indent: int = 2) -> None:
    """Serialize a PipelineGraph and write it to a JSON file."""
    Path(path).write_text(graph_to_json(graph, indent=indent), encoding="utf-8")


def load_graph(path: str | Path) -> PipelineGraph:
    """Read a JSON file and build a PipelineGraph from it."""
    return graph_from_json(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Documents: the pipeline, plus whatever else the file carries
# --------------------------------------------------------------------------
#
# A saved file is more than its graph -- the Dashboard's layout lives in
# it too, so sending someone a pipeline sends the report with it. That
# extra material is kept in *separate top-level keys*, never mixed into
# the node and connection lists, so:
#
#   * ``graph_to_dict`` / ``graph_from_dict`` stay exactly what they
#     were. A hand-written file, the bundled examples and the headless
#     CLI neither produce nor need any of it.
#   * A key this version does not understand is carried in and out
#     untouched rather than dropped, so a file written by a newer build
#     survives a round trip through an older one.

#: Top-level keys that belong to the graph itself.
GRAPH_KEYS = frozenset({"nodes", "connections"})

#: Key under which the Dashboard stores its layout.
DASHBOARD_KEY = "dashboard"

#: Key under which the pipeline canvas stores its layout: where each node
#: sits, and which figure previews are collapsed. Pure presentation --
#: the engine never reads it, so a headless run is unaffected.
CANVAS_KEY = "canvas"


def document_to_dict(
    graph: PipelineGraph, extras: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    The graph, plus any extra top-level sections.

    Extra keys that collide with the graph's own are ignored rather than
    allowed to overwrite the pipeline -- losing a report is a nuisance,
    losing the pipeline is losing the work.
    """
    data = graph_to_dict(graph)
    for key, value in (extras or {}).items():
        if key not in GRAPH_KEYS and value:
            data[key] = value
    return data


def document_from_dict(data: dict[str, Any]) -> tuple[PipelineGraph, dict[str, Any]]:
    """``(graph, extras)`` -- extras being every non-graph top-level key."""
    graph = graph_from_dict(data)
    extras = {k: v for k, v in data.items() if k not in GRAPH_KEYS}
    return graph, extras


def save_document(
    graph: PipelineGraph,
    path: str | Path,
    extras: dict[str, Any] | None = None,
    *,
    indent: int = 2,
) -> None:
    """Write a graph and its extra sections to a JSON file."""
    payload = document_to_dict(graph, extras)
    Path(path).write_text(json.dumps(payload, indent=indent), encoding="utf-8")


def load_document(path: str | Path) -> tuple[PipelineGraph, dict[str, Any]]:
    """Read a JSON file as ``(graph, extras)``."""
    return document_from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
