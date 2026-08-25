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
