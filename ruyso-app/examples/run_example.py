"""
Minimal command-line runner demonstrating the Phase-2 exit criterion:
a pipeline described by hand in JSON can be loaded and executed with
no UI involved at all.

Usage (from the project root, after `pip install -e .`):

    python examples/run_example.py examples/simple_regression_pipeline.json

This script deliberately contains no pipeline-specific logic: it only
discovers the registered nodes, loads the graph, and runs it. All the
actual behaviour comes from the node/graph/scheduler layers.
"""

from __future__ import annotations

import sys

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.scheduler import PipelineScheduler
from ruyso_app.engine.serialization import load_graph


def main(graph_path: str) -> None:
    """Load, validate, and execute the pipeline at ``graph_path``."""
    NodeRegistry.discover_package(src.ruyso_app.nodes)

    graph = load_graph(graph_path)
    graph.validate()

    scheduler = PipelineScheduler()
    outputs = scheduler.run(graph)

    for node_id, node_outputs in outputs.items():
        for port_name, value in node_outputs.items():
            print(f"[{node_id}] {port_name} = {_short_repr(value)}")


def _short_repr(value) -> str:
    """Render a value compactly enough for a one-line CLI log entry."""
    text = repr(value)
    return text if len(text) <= 120 else text[:117] + "..."


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python examples/run_example.py <path_to_pipeline.json>")
        raise SystemExit(1)
    main(sys.argv[1])
