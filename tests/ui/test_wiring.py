"""
Tests for how ports and links are drawn (``ui.wiring``): the theme's
wire colour at rest, the accent while selected, the origin node's colour
desaturated while a link is dragged, and the smaller solid arrow.
"""

from NodeGraphQt.qgraphics.pipe import LivePipeItem, PipeItem
from NodeGraphQt.qgraphics.port import CustomPortItem
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme, wiring
from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.node_factory import qt_type_for

NodeRegistry.discover_package(ruyso_app.nodes)


def _wired(qapp):
    """A canvas with one link: csv_loader -> drop_na."""
    canvas = PipelineCanvas()
    canvas.graph.viewer().resize(900, 600)
    load = canvas.graph.create_node(qt_type_for("csv_loader"), name="load", pos=[0, 0])
    clean = canvas.graph.create_node(qt_type_for("drop_na"), name="clean", pos=[300, 0])
    load.outputs()["df"].connect_to(clean.inputs()["df"])
    canvas.graph.clear_selection()
    return canvas, load, clean


def _pipes(canvas):
    return [
        item
        for item in canvas.graph.viewer().scene().items()
        if isinstance(item, PipeItem) and not isinstance(item, LivePipeItem)
    ]


# -- ports ---------------------------------------------------------------


def test_every_port_is_drawn_by_our_painter(qapp):
    """NodeGraphQt's own PortItem.paint ignores a port's colour the
    moment it is hovered or connected, so a painter is the only hook
    that can hold one colour through every state."""
    canvas, load, _clean = _wired(qapp)

    ports = [port.view for port in load.output_ports() + load.input_ports()]
    assert ports and all(isinstance(port, CustomPortItem) for port in ports)


def test_a_free_port_is_card_filled_and_a_wired_one_is_wire_filled(qapp):
    from PySide6.QtCore import QRectF

    filled: list[str] = []

    class Recorder:
        """Stands in for a QPainter, recording what the brush would be."""

        def save(self):
            pass

        def restore(self):
            pass

        def setRenderHint(self, *_args):  # noqa: N802 - Qt spelling
            pass

        def setPen(self, _pen):  # noqa: N802 - Qt spelling
            pass

        def setBrush(self, brush):  # noqa: N802 - Qt spelling
            filled.append(brush.color().name())

        def drawEllipse(self, _rect):  # noqa: N802 - Qt spelling
            pass

    rect = QRectF(0, 0, 10, 10)
    wiring.paint_port(Recorder(), rect, {"connected": False, "hovered": False})
    wiring.paint_port(Recorder(), rect, {"connected": True, "hovered": False})

    current = theme.current_theme()
    assert filled == [
        QColor(current.panel_background).name(),  # opaque, the card colour
        QColor(current.wire_color).name(),
    ]


def test_a_hovered_port_takes_the_accent(qapp):
    from PySide6.QtCore import QRectF

    pens: list[QColor] = []

    class Recorder:
        def save(self):
            pass

        def restore(self):
            pass

        def setRenderHint(self, *_args):  # noqa: N802
            pass

        def setPen(self, pen):  # noqa: N802
            pens.append(pen.color())

        def setBrush(self, _brush):  # noqa: N802
            pass

        def drawEllipse(self, _rect):  # noqa: N802
            pass

    rect = QRectF(0, 0, 10, 10)
    wiring.paint_port(Recorder(), rect, {"connected": True, "hovered": False})
    wiring.paint_port(Recorder(), rect, {"connected": True, "hovered": True})

    assert pens == [wiring.wire_color(), wiring.accent_color()]


# -- links ---------------------------------------------------------------


def test_a_link_at_rest_is_the_themes_wire_colour(qapp):
    canvas, _load, _clean = _wired(qapp)

    assert _pipes(canvas)[0].pen().color() == wiring.wire_color()


def test_selecting_a_node_paints_its_links_with_the_accent(qapp):
    canvas, _load, clean = _wired(qapp)
    pipe = _pipes(canvas)[0]

    clean.set_selected(True)
    assert pipe.pen().color() == wiring.accent_color()

    clean.set_selected(False)
    assert pipe.pen().color() == wiring.wire_color()


def test_the_arrow_is_small_and_solid_in_the_links_colour(qapp):
    """Upstream fills it with color.darker(200) inside a color outline,
    which is what made it read as two-tone."""
    canvas, _load, _clean = _wired(qapp)
    pipe = _pipes(canvas)[0]
    arrow = pipe._dir_pointer

    assert arrow.brush().color() == pipe.pen().color()
    assert arrow.pen().color() == pipe.pen().color()
    half_width = max(abs(point.x()) for point in arrow.polygon())
    assert half_width == wiring.ARROW_SIZE
    assert wiring.ARROW_SIZE < 6.0  # NodeGraphQt's own


def test_a_theme_toggle_repaints_ports_and_links(qapp):
    canvas, _load, _clean = _wired(qapp)
    pipe = _pipes(canvas)[0]
    started_as = theme.theme_mode()
    try:
        theme.set_theme_mode("light")
        canvas.apply_theme()
        assert pipe.pen().color() == QColor(theme.LIGHT_THEME.wire_color)

        theme.set_theme_mode("dark")
        canvas.apply_theme()
        assert pipe.pen().color() == QColor(theme.DARK_THEME.wire_color)
    finally:
        theme.set_theme_mode(started_as)


def test_a_selected_link_keeps_its_accent_through_a_theme_toggle(qapp):
    canvas, _load, clean = _wired(qapp)
    pipe = _pipes(canvas)[0]
    clean.set_selected(True)
    started_as = theme.theme_mode()
    try:
        theme.set_theme_mode("light")
        canvas.apply_theme()
        assert pipe.pen().color() == wiring.accent_color()
    finally:
        theme.set_theme_mode(started_as)


# -- the link being dragged ----------------------------------------------


def test_a_dragged_link_is_its_origin_node_desaturated(qapp):
    canvas, load, _clean = _wired(qapp)
    live = canvas.graph.viewer()._LIVE_PIPE
    start = load.output_ports()[0].view
    node_colour = QColor(*tuple(load.view.color)[:3])

    live.draw_path(start, cursor_pos=QPointF(120, 40))

    assert live.pen().color() == wiring.desaturated(node_colour)
    assert live.pen().color().saturationF() < node_colour.saturationF()
    assert live.pen().color().hueF() == node_colour.hueF()  # still that node's colour


def test_a_dragged_link_turns_red_over_an_impossible_target(qapp):
    """The viewer passes a colour only when the drop would be refused."""
    canvas, load, _clean = _wired(qapp)
    live = canvas.graph.viewer()._LIVE_PIPE
    start = load.output_ports()[0].view

    live.draw_path(start, cursor_pos=QPointF(120, 40), color=[150, 60, 255])

    assert live.pen().color() == QColor(wiring.INVALID_COLOR)


def test_desaturating_leaves_a_grey_alone(qapp):
    """The statistics macro type is grey; pulling it toward grey is a no-op."""
    grey = QColor(127, 127, 127)

    assert wiring.desaturated(grey) == grey


def test_installing_the_wiring_twice_is_a_no_op(qapp):
    wiring.install_wiring()
    patched = PipeItem.reset
    wiring.install_wiring()

    assert PipeItem.reset is patched
