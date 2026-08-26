"""
Dynamic construction of NodeGraphQt node classes from the core
NodeRegistry.

Rather than hand-writing one NodeGraphQt.BaseNode subclass per
concrete pipeline node (CSVLoader, DropNA, ...), this module builds
them programmatically: for every ``Node`` subclass registered in
``ruyso_app.core.registry.NodeRegistry``, it creates a matching
``BaseNode`` subclass whose ports mirror the core node's ``Port``
declarations and whose editable properties mirror its
``params_schema`` (via ``property_forms.py``). Adding a new node in
``nodes/`` therefore makes it appear on the canvas automatically, with
no UI code to write for it.
"""

from __future__ import annotations

from typing import Any

from NodeGraphQt import BaseNode, NodeGraph

import ruyso_app.nodes  # noqa: F401 - imported for its registration side effects
from ruyso_app.core.node import Node
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.property_forms import add_properties_to_node

# Namespace under which every generated node class is registered in
# NodeGraphQt (it becomes part of the node's fully qualified type, e.g.
# "ruyso.CsvLoaderGraphNode"). Kept distinct from the ruyso_app Python
# package name to avoid any confusion between the two.
GRAPH_NODE_IDENTIFIER = "ruyso"


def build_node_graph_class(node_type: str, node_cls: type[Node]) -> type[BaseNode]:
    """
    Build a NodeGraphQt.BaseNode subclass wrapping ``node_cls``.

    Args:
        node_type: The registered node_type identifier (e.g. "csv_loader").
        node_cls: The core Node subclass to wrap.

    Returns:
        A new BaseNode subclass. Instantiating it (via
        ``graph.create_node(...)``) draws a box with the node's input
        and output ports, colored by its category (see
        ``ui.theme.color_for_category``), and one editable property
        per field of ``node_cls.params_schema``.

    Note:
        The returned class carries two extra class attributes that are
        not part of NodeGraphQt itself, but that ``graph_bridge.py``
        relies on to translate a canvas node back into a core
        ``NodeSpec``: ``CORE_NODE_TYPE`` (the registry key) and
        ``CORE_NODE_CLASS`` (the Node subclass itself).
    """

    def __init__(self) -> None:
        BaseNode.__init__(self)
        self.set_color(*theme.color_for_category(node_cls.category))

        for port in node_cls.inputs:
            self.add_input(port.name, multi_input=False)
        for port in node_cls.outputs:
            self.add_output(port.name)

        add_properties_to_node(self, node_cls.params_schema)

    attrs: dict[str, Any] = {
        "__identifier__": GRAPH_NODE_IDENTIFIER,
        "NODE_NAME": _display_name_for(node_cls),
        "CORE_NODE_TYPE": node_type,
        "CORE_NODE_CLASS": node_cls,
        "__init__": __init__,
    }
    return type(_class_name_for(node_type), (BaseNode,), attrs)


def register_all_nodes(graph: NodeGraph) -> None:
    """
    Discover every node in ``ruyso_app.nodes`` and register a matching
    NodeGraphQt class on ``graph``, so they all appear in the canvas's
    "add node" search (press Tab on the canvas) and in a
    ``NodesPaletteWidget``.

    Safe to call more than once: ``NodeRegistry.discover_package`` is
    idempotent, and re-registering a node type under the same
    identifier simply replaces the previous class.
    """
    NodeRegistry.discover_package(ruyso_app.nodes)
    for node_type, node_cls in sorted(NodeRegistry.all().items()):
        graph.register_node(build_node_graph_class(node_type, node_cls))


def qt_type_for(node_type: str) -> str:
    """Return the fully qualified NodeGraphQt type string for a node_type.

    e.g. "csv_loader" -> "ruyso.CsvLoaderGraphNode". Exposed for
    ``graph_bridge.py``, which needs to call ``graph.create_node(...)``
    with this exact string when rebuilding a canvas from a
    ``PipelineGraph``.
    """
    return f"{GRAPH_NODE_IDENTIFIER}.{_class_name_for(node_type)}"


def _class_name_for(node_type: str) -> str:
    """e.g. "csv_loader" -> "CsvLoaderGraphNode"."""
    return "".join(part.capitalize() for part in node_type.split("_")) + "GraphNode"


def _display_name_for(node_cls: type[Node]) -> str:
    """e.g. "csv_loader" -> "CSV Loader" (the node's on-canvas label)."""
    return node_cls.node_type.replace("_", " ").title()
