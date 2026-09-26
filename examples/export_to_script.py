"""
Export a hand-written pipeline JSON file into a standalone Python
script, with no UI involved.

Usage (from the project root, after `pip install -e .`):

    python examples/export_to_script.py \\
        examples/simple_regression_pipeline.json \\
        examples/simple_regression_pipeline_exported.py

The resulting script can then be run on its own:

    python examples/simple_regression_pipeline_exported.py
"""

from __future__ import annotations

import sys

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.codegen import save_script
from ruyso_app.engine.serialization import load_graph


def main(graph_path: str, output_path: str) -> None:
    """Load, validate, and export the pipeline at ``graph_path``."""
    NodeRegistry.discover_package(ruyso_app.nodes)

    graph = load_graph(graph_path)
    graph.validate()

    save_script(graph, output_path, source_description=graph_path)
    print(f"Standalone script written to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "Usage: python examples/export_to_script.py "
            "<path_to_pipeline.json> <output_script.py>"
        )
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])
