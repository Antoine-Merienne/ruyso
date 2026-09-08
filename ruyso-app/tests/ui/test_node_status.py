"""
Tests for ``ui.node_status.NodeStatusController`` -- the per-node
status dots on the pipeline canvas.
"""

from NodeGraphQt import NodeGraph

import ruyso_app.nodes  # noqa: F401 - registration side effects
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes
from ruyso_app.ui.node_status import NodeStatusController

NodeRegistry.discover_package(ruyso_app.nodes)


def _graph(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    return graph


def _icon(node):
    view = node.view
    return getattr(view, "icon_item", None) or getattr(view, "_icon_item", None)


def test_set_status_records_and_swaps_the_node_icon(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    ctrl = NodeStatusController(graph)

    ctrl.set_status("load", "running")
    assert ctrl.status_of("load") == "running"
    running_px = _icon(node).pixmap().cacheKey()

    ctrl.set_status("load", "ok")
    assert ctrl.status_of("load") == "ok"
    assert _icon(node).pixmap().cacheKey() != running_px  # a different dot


def test_blocked_and_pending_share_the_grey_dot(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    ctrl = NodeStatusController(graph)

    ctrl.set_status("load", "blocked")
    blocked_px = _icon(node).pixmap().cacheKey()
    ctrl.set_status("load", "pending")
    assert _icon(node).pixmap().cacheKey() == blocked_px


def test_reset_marks_every_node_pending(qapp):
    graph = _graph(qapp)
    graph.create_node(qt_type_for("csv_loader"), name="a")
    graph.create_node(qt_type_for("drop_na"), name="b")
    ctrl = NodeStatusController(graph)
    ctrl.set_status("a", "ok")

    ctrl.reset()
    assert ctrl.status_of("a") == "pending"
    assert ctrl.status_of("b") == "pending"


def test_error_status_puts_the_message_on_the_node_tooltip(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    ctrl = NodeStatusController(graph)

    ctrl.set_status("load", "error", "boom: file not found")
    assert "boom: file not found" in node.view.toolTip()


def test_unknown_node_id_is_a_safe_no_op(qapp):
    graph = _graph(qapp)
    ctrl = NodeStatusController(graph)
    ctrl.set_status("ghost", "ok")  # must not raise


def test_refresh_theme_repaints_without_error(qapp):
    graph = _graph(qapp)
    graph.create_node(qt_type_for("csv_loader"), name="load")
    ctrl = NodeStatusController(graph)
    ctrl.set_status("load", "ok")

    theme.set_current_theme("light")
    try:
        ctrl.refresh_theme()
        assert ctrl.status_of("load") == "ok"
    finally:
        theme.set_theme_mode("system")
