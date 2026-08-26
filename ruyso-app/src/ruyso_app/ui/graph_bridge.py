"""
Bidirectional conversion between a live NodeGraphQt ``NodeGraph`` (the
canvas) and an ``engine.PipelineGraph`` (the execution engine's own
graph representation).

This module is the seam between the UI and the engine: the canvas
never talks to ``PipelineScheduler`` directly, and the engine never
imports anything from NodeGraphQt. Both directions produce/consume a
plain ``PipelineGraph``, which is exactly what ``engine.serialization``
already knows how to read from and write to JSON -- so a pipeline
built visually can be run from the command line
(``examples/run_example.py``), and a pipeline written by hand in JSON
can be opened and edited on the canvas, with no format conversion
beyond what already exists in the engine layer.
"""

from __future__ import annotations

from typing import Any

from NodeGraphQt import BaseNode, NodeGraph

from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph
from ruyso_app.ui.node_factory import qt_type_for
from ruyso_app.ui.property_forms import extract_params_from_node


class UnsupportedCanvasNodeError(TypeError):
    """
    Raised when the canvas contains a node with no associated core
    Node type (e.g. a plain NodeGraphQt BackdropNode used purely for
    visual grouping), which cannot be translated into a NodeSpec.
    """


def canvas_to_pipeline(graph: NodeGraph) -> PipelineGraph:
    """
    Build a ``PipelineGraph`` describing the current state of the canvas.

    Args:
        graph: The live NodeGraphQt graph.

    Returns:
        A ``PipelineGraph`` (not yet validated -- call ``.validate()``
        before executing it, which ``execution_worker.py`` does) with
        one ``NodeSpec`` per canvas node and one ``Connection`` per
        wire between two ports.

    Raises:
        UnsupportedCanvasNodeError: If the canvas contains a node not
            built by ``node_factory`` (see class docstring).
    """
    pipeline = PipelineGraph()

    for node in graph.all_nodes():
        pipeline.add_node(_node_spec_for(node))

    for node in graph.all_nodes():
        for port in node.output_ports():
            for connected_port in port.connected_ports():
                pipeline.add_connection(
                    Connection(
                        source_node=node.name(),
                        source_port=port.name(),
                        target_node=connected_port.node().name(),
                        target_port=connected_port.name(),
                    )
                )

    return pipeline


def pipeline_to_canvas(pipeline: PipelineGraph, graph: NodeGraph) -> dict[str, BaseNode]:
    """
    Populate an empty NodeGraphQt graph from a ``PipelineGraph``.

    Args:
        pipeline: The pipeline to render. Nodes are placed at simple,
            evenly spaced positions along the x axis; the person can
            rearrange them freely afterwards.
        graph: An empty NodeGraphQt graph, already populated with node
            classes via ``node_factory.register_all_nodes``.

    Returns:
        Mapping of pipeline node id -> the created canvas node.
    """
    canvas_nodes: dict[str, BaseNode] = {}

    for index, spec in enumerate(pipeline.nodes.values()):
        canvas_node = graph.create_node(
            qt_type_for(spec.node_type),
            name=spec.id,
            pos=(index * 220, 0),
            push_undo=False,
        )
        for field_name, value in spec.params.items():
            canvas_node.set_property(field_name, _property_display_value(value))
        canvas_nodes[spec.id] = canvas_node

    for connection in pipeline.connections:
        source_port = canvas_nodes[connection.source_node].outputs()[connection.source_port]
        target_port = canvas_nodes[connection.target_node].inputs()[connection.target_port]
        source_port.connect_to(target_port)

    return canvas_nodes


# --- internals ---------------------------------------------------------------


def _node_spec_for(node: BaseNode) -> NodeSpec:
    """
    Build a NodeSpec for a canvas node.

    ``NodeSpec.id`` is taken from the node's *display name*
    (``node.name()``) rather than NodeGraphQt's internal ``node.id``
    (an opaque memory-address-derived string): the display name is
    what the person sees and edits on the canvas, and what already
    appears as the "id" in hand-written pipeline JSON (e.g. "load",
    "clean") -- using it keeps UI-built and CLI-built pipelines
    consistent and human-readable. NodeGraphQt automatically
    disambiguates duplicate names (e.g. "Csv Loader", "Csv Loader 1"),
    so this is guaranteed unique within one graph.
    """
    node_cls = type(node)
    if not hasattr(node_cls, "CORE_NODE_TYPE"):
        raise UnsupportedCanvasNodeError(
            f"Canvas node {node.name()!r} ({node_cls.__name__}) was not built by "
            "node_factory and has no corresponding core Node type."
        )
    params = extract_params_from_node(node, node_cls.CORE_NODE_CLASS.params_schema)
    return NodeSpec(id=node.name(), node_type=node_cls.CORE_NODE_TYPE, params=params)


def _property_display_value(value: Any) -> Any:
    """
    Convert a NodeSpec param value into what ``set_property`` expects.

    Only ``list[str]`` needs special handling here: property_forms
    displays such fields as a single comma-separated string (see its
    module docstring), so a Python list must be joined back into text
    before being written into the property.
    """
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return value
