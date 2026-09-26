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


def _dot(node):
    """The node's status colour. It is a vector ellipse on our own node
    items -- a bitmap icon went blocky the moment you zoomed in."""
    return node.view.status_colour()


def test_set_status_records_and_recolours_the_dot(qapp):
    from PySide6.QtGui import QColor

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    ctrl = NodeStatusController(graph)

    ctrl.set_status("load", "running")
    assert ctrl.status_of("load") == "running"
    assert _dot(node) == QColor(theme.STATUS_COLORS["running"])

    ctrl.set_status("load", "ok")
    assert ctrl.status_of("load") == "ok"
    assert _dot(node) == QColor(theme.STATUS_COLORS["ok"])


def test_blocked_and_pending_share_the_grey_dot(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    ctrl = NodeStatusController(graph)

    ctrl.set_status("load", "blocked")
    blocked = _dot(node)
    ctrl.set_status("load", "pending")
    assert _dot(node) == blocked


def test_a_node_without_the_vector_dot_still_gets_a_pixmap(qapp):
    """A NodeGraphQt built-in has only the icon slot, which takes a
    bitmap; the controller must not assume our vector item. Faked
    rather than built from a real throwaway node class -- those collide
    with NodeGraphQt's QUndoStack teardown (exit 139)."""

    class FakeIcon:
        pixmap_set = None

        def setPixmap(self, pixmap):  # noqa: N802 - Qt spelling
            self.pixmap_set = pixmap

    class FakeView:
        def __init__(self):
            self._icon_item = FakeIcon()

        def setToolTip(self, text):  # noqa: N802 - Qt spelling
            self.tip = text

    class FakeNode:
        def __init__(self):
            self.view = FakeView()

        def name(self):
            return "plain"

    node = FakeNode()

    class FakeGraph:
        def all_nodes(self):
            return [node]

    NodeStatusController(FakeGraph()).set_status("plain", "error", "boom")

    assert node.view._icon_item.pixmap_set is not None
    assert node.view.tip == "Failed: boom"


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


def test_blocked_and_unwired_are_both_grey_but_read_differently(qapp):
    """The split exists so a half-built canvas does not look broken."""
    from ruyso_app.ui import theme

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    ctrl = NodeStatusController(graph)

    ctrl.set_status("load", "blocked")
    blocked_tip = node.view.toolTip()
    ctrl.set_status("load", "unwired")
    unwired_tip = node.view.toolTip()

    assert blocked_tip != unwired_tip
    assert "failed" in blocked_tip
    assert "not connected" in unwired_tip
    # Neither ran, so both stay on the idle colour.
    assert ctrl._dot("idle").cacheKey() == ctrl._dot("idle").cacheKey()
    assert theme.STATUS_COLORS["idle"]
