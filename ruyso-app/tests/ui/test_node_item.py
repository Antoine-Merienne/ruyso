"""
Tests for how a node is painted (``ui.node_item``): a panel-coloured
card with the macro-type colour as a thick contour, the name bar filling
with that colour only while the node is selected.
"""

from NodeGraphQt import NodeGraph
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes
from ruyso_app.ui.node_item import RuysoNodeItem, readable_on

NodeRegistry.discover_package(ruyso_app.nodes)


def _node(graph, node_type="csv_loader", name="n"):
    return graph.create_node(qt_type_for(node_type), name=name, pos=[0, 0])


def _render(item) -> QImage:
    """Paint one node item, at 1:1, into an image of its own size."""
    rect = item.boundingRect()
    image = QImage(int(rect.width()), int(rect.height()), QImage.Format_RGB32)
    image.fill(QColor(*theme.current_theme().canvas_background))
    painter = QPainter(image)
    item.scene().render(
        painter,
        QRectF(image.rect()),
        QRectF(item.pos().x(), item.pos().y(), rect.width(), rect.height()),
    )
    painter.end()
    return image


def _pixel(image: QImage, x: int, y: int) -> QColor:
    return QColor(image.pixel(x, y))


def _close(a: QColor, b: QColor, tolerance: int = 30) -> bool:
    """Same colour give or take antialiasing against the background."""
    return (
        abs(a.red() - b.red()) < tolerance
        and abs(a.green() - b.green()) < tolerance
        and abs(a.blue() - b.blue()) < tolerance
    )


# -- the contrast rule ---------------------------------------------------


def test_the_name_colour_follows_the_bar_it_sits_on():
    """The macro palette runs from a dark blue to a bright orange, so a
    single fixed name colour is unreadable at one end."""
    assert readable_on(QColor(31, 119, 180)).lightness() > 200  # loader blue
    assert readable_on(QColor(255, 127, 14)).lightness() < 60  # transform orange


# -- what the generated classes use --------------------------------------


def test_generated_nodes_are_painted_by_our_item(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    node = _node(graph)

    assert isinstance(node.view, RuysoNodeItem)


# -- the painted result --------------------------------------------------


def test_an_unselected_node_is_a_panel_coloured_card(qapp):
    canvas = PipelineCanvas()
    node = _node(canvas.graph, name="load")
    canvas.graph.clear_selection()
    item = node.view

    image = _render(item)
    panel = QColor(theme.current_theme().panel_background)
    bar_y = int(item.name_bar_height() / 2)
    body_y = int(item.boundingRect().height() - 8)
    middle = int(item.boundingRect().width() / 2)
    # Right of the centred name, and clear of the status dot on the left.
    bar_x = int(item.boundingRect().width() - 22)

    # Name bar and body are the same surface: no divider, no tint.
    assert _pixel(image, bar_x, bar_y) == panel
    assert _pixel(image, middle, body_y) == panel


def test_the_macro_colour_is_the_contour(qapp):
    canvas = PipelineCanvas()
    node = _node(canvas.graph, "csv_loader", name="load")
    canvas.graph.clear_selection()
    item = node.view

    image = _render(item)
    macro = QColor(*theme.color_for_category("loading"))
    x = int(item.boundingRect().width() / 2)

    # Scan the top edge rather than naming one: the stroke is a couple
    # of units thick and antialiased, so which row is fully covered
    # depends on its width.
    assert any(_close(_pixel(image, x, y), macro) for y in range(6))


def test_selecting_fills_the_name_bar_with_that_colour(qapp):
    canvas = PipelineCanvas()
    node = _node(canvas.graph, "csv_loader", name="load")
    canvas.graph.clear_selection()
    item = node.view
    panel = QColor(theme.current_theme().panel_background)
    macro = QColor(*theme.color_for_category("loading"))
    # Left of the centred name, inside the bar, clear of the status dot.
    x, y = 40, int(item.name_bar_height() / 2)

    assert _pixel(_render(item), x, y) == panel

    node.set_selected(True)
    filled = _pixel(_render(item), x, y)
    assert filled == macro

    # ... and the body underneath stays the theme's panel colour.
    body_y = int(item.boundingRect().height() - 8)
    assert _pixel(_render(item), int(item.boundingRect().width() / 2), body_y) == panel


def test_the_fill_stops_right_below_the_name(qapp):
    """Not at the port row: NodeGraphQt's text-height-plus-4 leaves a
    band of colour hanging under the name."""
    canvas = PipelineCanvas()
    node = _node(canvas.graph, "csv_loader", name="load")  # no input ports
    item = node.view
    node.set_selected(True)

    image = _render(item)
    macro = QColor(*theme.color_for_category("loading"))
    panel = QColor(theme.current_theme().panel_background)
    bar = item.name_bar_height()

    assert _pixel(image, 40, int(bar) - 2) == macro
    assert _pixel(image, 40, int(bar) + 3) == panel
    assert bar < item._text_item.boundingRect().height() + 4.0


def test_selection_thickens_the_contour(qapp):
    from ruyso_app.ui.node_item import BORDER, BORDER_SELECTED

    assert BORDER_SELECTED > BORDER

    canvas = PipelineCanvas()
    node = _node(canvas.graph, name="load")
    canvas.graph.clear_selection()
    item = node.view
    macro = QColor(*theme.color_for_category("loading"))

    def contour_depth(image: QImage) -> int:
        """How many rows of the top edge are the macro colour."""
        x = int(item.boundingRect().width() / 2)
        return sum(
            1
            for y in range(int(item.boundingRect().height() / 2))
            if _close(_pixel(image, x, y), macro)
        )

    before = contour_depth(_render(item))
    node.set_selected(True)
    assert contour_depth(_render(item)) > before


# -- text colours --------------------------------------------------------


def test_the_labels_take_the_themes_text_colour(qapp):
    """NodeGraphQt's own default is white-on-dark, which is invisible on
    the light theme's panel."""
    canvas = PipelineCanvas()
    node = _node(canvas.graph, name="load")
    item = node.view
    canvas.graph.clear_selection()

    expected = QColor(theme.current_theme().text_color)
    for text in list(item._input_items.values()) + list(item._output_items.values()):
        assert text.defaultTextColor().rgb() == expected.rgb()
    assert item._text_item.defaultTextColor().rgb() == expected.rgb()


def test_the_name_flips_to_read_on_the_bar_when_selected(qapp):
    canvas = PipelineCanvas()
    node = _node(canvas.graph, "sort", name="sort")
    item = node.view
    canvas.graph.clear_selection()

    node.set_selected(True)
    on_bar = readable_on(QColor(*theme.color_for_category("transform")))
    assert item._text_item.defaultTextColor().rgb() == on_bar.rgb()

    node.set_selected(False)
    theme_text = QColor(theme.current_theme().text_color)
    assert item._text_item.defaultTextColor().rgb() == theme_text.rgb()


def test_a_theme_toggle_recolours_the_body_and_the_labels(qapp):
    canvas = PipelineCanvas()
    node = _node(canvas.graph, name="load")
    item = node.view
    canvas.graph.clear_selection()
    started_as = theme.theme_mode()
    try:
        theme.set_theme_mode("dark")
        canvas.apply_theme()
        dark_label = item._text_item.defaultTextColor().rgb()

        theme.set_theme_mode("light")
        canvas.apply_theme()
        assert item._text_item.defaultTextColor().rgb() != dark_label
        assert _pixel(_render(item), int(item.boundingRect().width() / 2),
                      int(item.boundingRect().height() - 8)) == QColor(
            theme.LIGHT_THEME.panel_background
        )
    finally:
        theme.set_theme_mode(started_as)
