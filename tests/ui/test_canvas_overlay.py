"""
Tests for the empty-canvas hint (``ui.canvas_overlay.EmptyCanvasHint``).
"""

from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.canvas_overlay import EmptyCanvasHint
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes

NodeRegistry.discover_package(ruyso_app.nodes)


def test_hint_is_visible_only_while_the_graph_is_empty(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    viewer = graph.viewer()
    viewer.show()
    hint = EmptyCanvasHint(viewer, graph)

    assert hint.isVisible()

    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    assert not hint.isVisible()

    graph.delete_node(node)
    assert hint.isVisible()


def test_hint_ignores_mouse_so_the_context_menu_still_opens(qapp):
    from PySide6.QtCore import Qt

    graph = NodeGraph()
    register_all_nodes(graph)
    hint = EmptyCanvasHint(graph.viewer(), graph)
    assert hint.testAttribute(Qt.WA_TransparentForMouseEvents)
