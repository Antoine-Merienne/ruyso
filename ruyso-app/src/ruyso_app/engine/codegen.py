"""
Standalone script export: turn a validated PipelineGraph into a plain
Python script that reproduces the exact same computation, with no
dependency on the rest of the engine.

The generated script:
    - imports only the concrete Node subclasses actually used by this
      pipeline (e.g. ``from ruyso_app.nodes.loaders import CSVLoader``),
    - instantiates each one with its exact parameters and calls
      ``.run(**inputs)`` in topological order, wiring each node's
      declared inputs to the right upstream output,
    - has NO import of ``PipelineGraph``, ``PipelineScheduler``,
      ``networkx``, or ``joblib`` — none of the graph bookkeeping or
      caching machinery is needed to simply replay a fixed pipeline.

This is useful for reproducibility outside the app (the script only
needs whatever libraries the nodes themselves use — pandas,
scikit-learn, matplotlib, pydantic — not the pipeline-builder app
itself), for auditing exactly what a pipeline does step by step, and
for handing off a pipeline to someone who wants to keep iterating on
it as ordinary Python code.

Node identifiers from the graph (``NodeSpec.id``) are user-supplied
strings and are not guaranteed to be valid Python identifiers, so they
are sanitized into safe local variable names for the generated code;
the original id is kept in a comment above each node's block for
traceability.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.graph import PipelineGraph

_INVALID_IDENTIFIER_CHARS = re.compile(r"[^0-9a-zA-Z_]")


def _sanitize_identifier(node_id: str) -> str:
    """
    Turn an arbitrary node id into a safe Python identifier.

    Args:
        node_id: The user-supplied NodeSpec.id (e.g. "load-csv #1").

    Returns:
        A string usable as a Python variable name, e.g. "load_csv__1".
        Prefixed with "n_" if it would otherwise start with a digit
        or be empty.
    """
    ident = _INVALID_IDENTIFIER_CHARS.sub("_", node_id)
    if not ident or ident[0].isdigit():
        ident = f"n_{ident}"
    return ident


def generate_script(graph: PipelineGraph, *, source_description: str | None = None) -> str:
    """
    Generate a standalone Python script that replays ``graph``.

    Args:
        graph: The pipeline to export. Validated internally before
            generation — an invalid graph raises before any code is
            produced.
        source_description: Optional human-readable note (e.g. the
            source JSON file path) recorded in the generated script's
            header comment, purely for traceability.

    Returns:
        The full contents of the generated ``.py`` script, as a string.
    """
    graph.validate()
    order = graph.topological_order()

    import_lines = _build_import_lines(graph)
    body_lines = _build_body_lines(graph, order)
    print_lines = _build_result_printing_lines(graph, order)

    header = _build_header(source_description)

    parts = [header, "", *import_lines, "", *body_lines]
    if print_lines:
        parts += ["", "# --- Results from terminal nodes (no downstream consumer) ---", ""]
        parts += print_lines

    return "\n".join(parts).rstrip() + "\n"


def save_script(
    graph: PipelineGraph, path: str | Path, *, source_description: str | None = None
) -> None:
    """
    Generate a standalone script for ``graph`` and write it to disk.

    Args:
        graph: The pipeline to export.
        path: Destination ``.py`` file path.
        source_description: See ``generate_script``.
    """
    Path(path).write_text(
        generate_script(graph, source_description=source_description), encoding="utf-8"
    )


def _build_header(source_description: str | None) -> str:
    source_line = f"Source: {source_description}\n" if source_description else ""
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        '"""\n'
        "Auto-generated, standalone pipeline script.\n"
        f"{source_line}"
        f"Generated: {generated_at}\n"
        "\n"
        "This file has no dependency on ruyso_app.engine (no PipelineGraph,\n"
        "PipelineScheduler, joblib caching, or networkx) and no dependency on\n"
        "ruyso_app.ui: it only imports the concrete node classes used by this\n"
        "specific pipeline, and can be read, run, or modified with nothing\n"
        "installed beyond the libraries those nodes themselves need.\n"
        '"""'
    )


def _build_import_lines(graph: PipelineGraph) -> list[str]:
    """One `from <module> import <ClassName>` line per node class used."""
    imports: dict[str, str] = {}
    for spec in graph.nodes.values():
        node_cls = NodeRegistry.get(spec.node_type)
        imports[node_cls.__name__] = node_cls.__module__

    return [
        f"from {module} import {class_name}"
        for class_name, module in sorted(imports.items(), key=lambda item: item[1])
    ]


def _build_body_lines(graph: PipelineGraph, order: list[str]) -> list[str]:
    """One block per node: build its inputs dict, then call .run()."""
    lines: list[str] = []
    for node_id in order:
        spec = graph.get_node(node_id)
        node_cls = NodeRegistry.get(spec.node_type)
        var = _sanitize_identifier(node_id)

        kv_pairs = [
            f'"{c.target_port}": out_{_sanitize_identifier(c.source_node)}["{c.source_port}"]'
            for c in graph.incoming_connections(node_id)
        ]
        inputs_literal = "{" + ", ".join(kv_pairs) + "}"

        lines.append(f"# Node '{node_id}' ({spec.node_type})")
        lines.append(
            f"out_{var} = {node_cls.__name__}(params={spec.params!r}).run(**{inputs_literal})"
        )
        lines.append("")
    return lines


def _build_result_printing_lines(graph: PipelineGraph, order: list[str]) -> list[str]:
    """Print the outputs of every terminal node (one with no downstream consumer)."""
    nodes_with_consumers = {c.source_node for c in graph.connections}
    terminal_node_ids = [node_id for node_id in order if node_id not in nodes_with_consumers]

    lines: list[str] = []
    for node_id in terminal_node_ids:
        var = _sanitize_identifier(node_id)
        lines.append(f"for _port, _value in out_{var}.items():")
        lines.append(f'    print(f"[{node_id}] {{_port}} = {{_value!r}}")')
    return lines
