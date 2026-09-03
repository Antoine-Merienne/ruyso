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

from typing import Any, Callable

from NodeGraphQt import BaseNode, NodeGraph

import ruyso_app.nodes  # noqa: F401 - imported for its registration side effects
from ruyso_app.core.node import Node
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.node_preview import is_figure_core_class
from ruyso_app.ui.property_forms import add_properties_to_node

# Namespace under which every generated node class is registered in
# NodeGraphQt (it becomes part of the node's fully qualified type, e.g.
# "ruyso.CsvLoaderGraphNode"). Kept distinct from the ruyso_app Python
# package name to avoid any confusion between the two.
GRAPH_NODE_IDENTIFIER = "ruyso"

# One generated Qt class per node_type, reused across every graph.
# Rebuilding it on each ``register_all_nodes`` call (once per canvas)
# spawns hundreds of throwaway ``type`` objects over a test run, which
# inflates GC work and, colliding with NodeGraphQt's QUndoStack
# teardown, can crash PySide6. The wrapper only depends on the core
# node class, so caching it is safe.
_QT_CLASS_CACHE: dict[str, type[BaseNode]] = {}


def build_node_graph_class(node_type: str, node_cls: type[Node]) -> type[BaseNode]:
    """
    Build (or return a cached) NodeGraphQt.BaseNode subclass wrapping ``node_cls``.

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

        # Figure-bearing nodes (grapher, and figure
        # sinks like figure_export) get an on-canvas preview, but it is
        # a floating thumbnail managed by ui.node_preview.NodePreviewOverlay
        # -- not a widget embedded in the node here.
        self.is_figure_node = is_figure_core_class(node_cls)

    cached = _QT_CLASS_CACHE.get(node_type)
    if cached is not None and cached.CORE_NODE_CLASS is node_cls:
        return cached

    attrs: dict[str, Any] = {
        "__identifier__": GRAPH_NODE_IDENTIFIER,
        "NODE_NAME": _display_name_for(node_cls),
        "CORE_NODE_TYPE": node_type,
        "CORE_NODE_CLASS": node_cls,
        "__init__": __init__,
    }
    qt_class = type(_class_name_for(node_type), (BaseNode,), attrs)
    _QT_CLASS_CACHE[node_type] = qt_class
    return qt_class


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


def register_node_context_menu_actions(
    graph: NodeGraph,
    on_delete: Callable[[NodeGraph, BaseNode], None],
    on_add_to_dashboard: Callable[[NodeGraph, BaseNode], None],
) -> None:
    """
    Add "Delete Node" (every node type) and "Add to Dashboard" (only
    figure-bearing node types, see
    ``ui.node_preview.is_figure_core_class``) commands to the canvas's
    right-click node context menu.

    Must be called after ``register_all_nodes`` (it reads the node
    classes NodeGraphQt already registered on ``graph`` via
    ``graph.node_factory.nodes``, rather than rebuilding them, so both
    functions stay in agreement about which classes exist).

    Args:
        graph: The NodeGraphQt graph to attach the context menu to.
        on_delete: Called as ``on_delete(graph, node)`` when "Delete
            Node" is chosen for a right-clicked node.
        on_add_to_dashboard: Called as ``on_add_to_dashboard(graph, node)``
            when "Add to Dashboard" is chosen.

    Note:
        NodeGraphQt nests per-node-type commands under a submenu named
        after the node's class (this is how the library's
        ``NodesMenu.add_command(..., node_class=...)`` always works,
        not a choice made here) -- so right-clicking a node shows e.g.
        "CsvLoaderGraphNode > Delete Node", one submenu level deep,
        rather than a single flat "Delete Node" entry.
    """
    nodes_menu = graph.get_context_menu("nodes")
    for qt_cls in graph.node_factory.nodes.values():
        if not hasattr(qt_cls, "CORE_NODE_CLASS"):
            continue  # a NodeGraphQt built-in (e.g. BackdropNode), not one of ours

        nodes_menu.add_command("Delete Node", on_delete, node_class=qt_cls)
        if is_figure_core_class(qt_cls.CORE_NODE_CLASS):
            nodes_menu.add_command("Add to Dashboard", on_add_to_dashboard, node_class=qt_cls)


def core_node_types_by_category() -> dict[str, list[str]]:
    """
    Group every registered core node type by its macro type (category).

    Used by the "New Node" menu / Options panel micro-type dropdown to
    know which macro types actually have a node behind them: a macro
    type absent from this mapping (a macro type with no
    concrete node yet) is shown disabled rather than offered as an
    empty submenu.

    Returns:
        ``{category: [node_type, ...]}``, each list sorted, categories
        in the order they appear in ``theme.MACRO_TYPE_LABELS`` followed
        by any extras.
    """
    NodeRegistry.discover_package(ruyso_app.nodes)
    grouped: dict[str, list[str]] = {}
    for node_type, node_cls in NodeRegistry.all().items():
        grouped.setdefault(node_cls.category, []).append(node_type)

    ordered: dict[str, list[str]] = {}
    for category in theme.MACRO_TYPE_LABELS:
        if category in grouped:
            ordered[category] = sorted(grouped[category])
    for category, types in grouped.items():  # any category not in the spec list
        ordered.setdefault(category, sorted(types))
    return ordered


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