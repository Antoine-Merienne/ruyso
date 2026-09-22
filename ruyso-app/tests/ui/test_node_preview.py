"""
Tests for on-canvas figure previews (``ui.node_preview`` and
``ui.preview_card``): which nodes get one, resolving the right figure
from a run's outputs, the card's lifecycle and placement, clicks on a
card or its node's chevron, and the pop-out window sizing.
"""

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from NodeGraphQt import NodeGraph
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes
from ruyso_app.ui.node_preview import (
    FigureWindow,
    NodePreviewOverlay,
    is_figure_core_class,
    resolve_figure,
)
from ruyso_app.ui.preview_card import GAP, PreviewCard, raster_bucket

NodeRegistry.discover_package(ruyso_app.nodes)


def _graph(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    graph.viewer().resize(900, 600)
    return graph


def _figure():
    import pandas as pd

    return NodeRegistry.get("matplotlib_plot")(params={"x": "a", "y": "b"}).run(
        df=pd.DataFrame({"a": [1.0, 2, 3], "b": [10.0, 50, 30]})
    )["figure"]


def _renders_done():
    """
    Wait for the render thread to deliver every bitmap asked for.

    Cards are drawn on a worker (``ui/render_queue.py``) so a slow
    figure cannot freeze the window, which means a pixmap is not there
    the instant a run's results are merged.
    """
    from ruyso_app.ui import render_queue

    assert render_queue.queue().wait_idle(15_000), "a render never finished"


def _wired_plot(qapp):
    """A graph with a rendered matplotlib_plot, plus its overlay."""
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    overlay = NodePreviewOverlay(graph)
    overlay.set_run_outputs({"plot": {"figure": _figure()}})
    _renders_done()
    return graph, node, overlay


def _click(overlay, graph, scene_point, release_at=None):
    """Press (and release) at a scene point; returns what the filter consumed."""
    viewer = graph.viewer()
    viewport = viewer.viewport()
    consumed = []
    for kind, point in (
        (QEvent.Type.MouseButtonPress, scene_point),
        (QEvent.Type.MouseButtonRelease, release_at or scene_point),
    ):
        pos = viewer.mapFromScene(point)
        buttons = Qt.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.NoButton
        event = QMouseEvent(
            kind, QPointF(pos), QPointF(viewport.mapToGlobal(pos)),
            Qt.LeftButton, buttons, Qt.NoModifier,
        )
        consumed.append(overlay.eventFilter(viewport, event))
    return consumed


def _card_centre(card):
    return card.mapToScene(card.boundingRect().center())


# -- which nodes, which figure -------------------------------------------


def test_is_figure_core_class():
    assert is_figure_core_class(NodeRegistry.get("matplotlib_plot"))  # grapher
    # Export / sink nodes carry a figure input but get no on-canvas preview.
    assert not is_figure_core_class(NodeRegistry.get("export_figure"))
    assert not is_figure_core_class(NodeRegistry.get("export_to_dashboard"))
    assert not is_figure_core_class(NodeRegistry.get("csv_loader"))
    assert not is_figure_core_class(None)


def test_resolve_figure_for_grapher_and_for_figure_sink(qapp):
    graph = _graph(qapp)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    export = graph.create_node(qt_type_for("export_figure"), name="save")
    plot.set_output(0, export.input(0))

    figure = plt.figure()
    outputs = {"plot": {"figure": figure}, "save": {}}

    assert resolve_figure(plot, outputs) is figure
    assert resolve_figure(export, outputs) is figure  # follows the wire upstream


# -- the card's lifecycle ------------------------------------------------


def test_a_figure_node_gets_a_card_in_the_scene(qapp):
    graph = _graph(qapp)
    overlay = NodePreviewOverlay(graph)

    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    graph.create_node(qt_type_for("csv_loader"), name="load")

    cards = overlay.cards()
    assert list(cards) == [plot.id]  # the loader gets none
    assert isinstance(cards[plot.id], PreviewCard)
    assert cards[plot.id].scene() is graph.viewer().scene()
    assert plot.view.has_preview


def test_deleting_a_node_removes_its_card_and_undo_brings_it_back(qapp):
    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]

    graph.delete_node(node)
    assert node.id not in overlay.cards()
    assert card.scene() is None

    graph.undo_stack().undo()
    restored = overlay.cards()[node.id]
    assert restored.scene() is graph.viewer().scene()
    assert restored.has_figure()  # not a blank card waiting for the next run


def test_a_card_shows_a_placeholder_until_a_run(qapp):
    graph = _graph(qapp)
    overlay = NodePreviewOverlay(graph)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    card = overlay.cards()[plot.id]

    assert not card.has_figure()
    assert "run pipeline" in card.placeholder()

    figure = _figure()
    overlay.set_run_outputs({"plot": {"figure": figure}})
    assert card.figure() is figure


# -- placement: in the same frame as the node ----------------------------


def _is_beneath(card, node) -> bool:
    rect = node.view.sceneBoundingRect()
    return (
        abs(card.pos().x() - rect.left()) < 0.01
        and abs(card.pos().y() - (rect.bottom() + GAP)) < 0.01
    )


def test_the_card_follows_its_node_without_waiting_for_the_event_loop(qapp):
    """The old preview was a widget re-placed by a 60 ms timer, and trailed
    a dragged node by up to four frames. A card is re-placed from the
    node's own itemChange -- synchronously, in the same call."""
    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    assert _is_beneath(card, node)

    node.set_pos(310, 145)  # no processEvents in between
    assert _is_beneath(card, node)


def test_the_card_follows_an_undone_move(qapp):
    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]

    node.set_pos(400, 90)
    graph.undo_stack().undo()

    assert node.pos() == [0.0, 0.0]
    assert _is_beneath(card, node)


def test_the_card_is_stacked_above_wires_and_below_nodes(qapp):
    """A widget over the viewport always painted over every node."""
    from NodeGraphQt.constants import Z_VAL_NODE, Z_VAL_PIPE

    _graph_, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]

    assert Z_VAL_PIPE < card.zValue() < Z_VAL_NODE


# -- rendering -----------------------------------------------------------


def test_raster_bucket_rounds_up_to_a_power_of_two_within_bounds():
    from ruyso_app.ui.preview_card import MAX_RASTER_PX, MIN_RASTER_PX

    assert raster_bucket(300) == 512
    assert raster_bucket(512) == 512
    assert raster_bucket(1) == MIN_RASTER_PX
    assert raster_bucket(10_000) == MAX_RASTER_PX


def test_the_bitmap_is_rendered_for_the_screens_pixel_ratio(qapp, monkeypatch):
    """The old thumbnail was scaled at *logical* size and shown on a 2x
    screen, which is why its tick labels were unreadable."""
    from ruyso_app.ui import node_preview

    monkeypatch.setattr(node_preview, "_screen_ratio", lambda: 2.0)
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    overlay = NodePreviewOverlay(graph)
    overlay.set_run_outputs({"plot": {"figure": _figure()}})
    _renders_done()
    card = overlay.cards()[node.id]

    assert card.pixmap_pixels() == raster_bucket(card.plate_width() * 2.0)
    assert card.pixmap().width() == card.pixmap_pixels()


def test_an_unchanged_figure_is_not_rasterised_again(qapp, monkeypatch):
    """
    The skip cache hands back the *same* Figure object for a grapher
    nothing changed for, so identity says the pixels are already right.
    Re-rasterising on every keystroke-triggered background run is waste.
    """
    from ruyso_app.ui import node_preview

    calls: list[int] = []
    original = node_preview.figure_to_png_bytes

    def counted(figure, width_px=None):
        calls.append(1)
        return original(figure, width_px=width_px)

    monkeypatch.setattr(node_preview, "figure_to_png_bytes", counted)
    graph = _graph(qapp)
    graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    overlay = NodePreviewOverlay(graph)

    figure = _figure()
    overlay.set_run_outputs({"plot": {"figure": figure}})
    overlay.set_run_outputs({"plot": {"figure": figure}})  # same object
    _renders_done()
    assert len(calls) == 1

    overlay.set_run_outputs({"plot": {"figure": _figure()}})  # a genuinely new one
    _renders_done()
    assert len(calls) == 2


def _paint_at(card, scale):
    """Paint ``card`` as a view zoomed to ``scale`` would (device ratio 1)."""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionGraphicsItem

    rect = card.boundingRect()
    image = QImage(
        int(rect.width() * scale) + 2, int(rect.height() * scale) + 2,
        QImage.Format_ARGB32,
    )
    image.fill(0)
    painter = QPainter(image)
    painter.scale(scale, scale)
    card.paint(painter, QStyleOptionGraphicsItem(), None)
    painter.end()


def test_a_new_figure_is_rendered_for_the_zoom_the_card_was_last_shown_at(qapp):
    """Auto-run hands back a new figure after every edit. Rendering each
    one for 1:1 left a zoomed-in card blurry after every change, and cost
    a second render once the next paint noticed."""
    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    _paint_at(card, 2.0)

    overlay.set_run_outputs({"plot": {"figure": _figure()}})  # a new figure
    _renders_done()

    assert card.pixmap_pixels() == raster_bucket(card.plate_width() * 2.0)


def test_repainting_at_the_same_zoom_asks_for_an_upgrade_once(qapp):
    """Asking on every paint let any unrelated repaint -- a status-dot
    animation, a hover -- keep restarting the debounce, so the upgrade
    only ran once the canvas went quiet: always a zoom step behind."""
    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    asked: list[str] = []
    card.request_upgrade = asked.append

    for _ in range(3):
        _paint_at(card, 3.0)
    assert asked == [node.id]

    card.rasterise_at(card.wanted_px)
    _renders_done()
    _paint_at(card, 3.0)
    assert asked == [node.id]  # the bitmap now matches: nothing more to ask


def test_the_manager_renders_a_requested_upgrade(qapp):
    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    before = card.pixmap_pixels()

    _paint_at(card, 4.0)  # asks through the manager's real callback
    overlay._run_upgrades()  # what the debounce timer calls
    _renders_done()

    assert card.pixmap_pixels() == raster_bucket(card.plate_width() * 4.0)
    assert card.pixmap_pixels() > before


def test_a_card_keeps_its_picture_while_the_next_one_is_drawn(qapp):
    """Drawing moved to a worker thread, so a card that dropped its
    bitmap the moment a new figure arrived went *blank* for as long as
    the render took -- and one that adopted the new proportions early
    drew the old plot letterboxed inside them."""
    from matplotlib.figure import Figure

    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    before = card.pixmap()
    before_aspect = card.plate_rect().height() / card.plate_rect().width()
    assert before is not None

    tall = Figure(figsize=(4.0, 4.0))  # a different shape from the first
    tall.add_subplot().plot([1, 2], [1, 2])
    card.set_figure(tall)

    assert card.pixmap() is before  # still showing the old plot...
    assert card.plate_rect().height() / card.plate_rect().width() == before_aspect

    _renders_done()
    assert card.pixmap() is not before  # ...until the new one is ready
    assert card.plate_rect().height() / card.plate_rect().width() != before_aspect


def test_a_dense_plot_is_flattened_to_a_bitmap_inside_the_svg(qapp):
    """One vector shape per point made a 400k-point block a 79 MB file:
    9.9 s to write, 2.7 s for Qt to parse, slow at every repaint after."""
    import numpy as np
    from matplotlib.figure import Figure

    from ruyso_app.ui.node_preview import _SVG_RASTER_MIN, figure_to_svg_bytes

    figure = Figure()
    axes = figure.add_subplot()
    n = _SVG_RASTER_MIN + 1
    dots = axes.scatter(np.arange(n), np.arange(n))

    data = figure_to_svg_bytes(figure)

    assert b"image/png" in data  # the dots are one embedded bitmap
    assert b"<text" in data  # while the labels stay real text
    assert not dots.get_rasterized()  # the figure is left as it was found


def test_an_ordinary_plot_stays_fully_vector(qapp):
    from matplotlib.figure import Figure

    from ruyso_app.ui.node_preview import figure_to_svg_bytes

    figure = Figure()
    figure.add_subplot().scatter(range(50), range(50))

    assert b"image/png" not in figure_to_svg_bytes(figure)


def test_figure_to_pixmap_renders_the_requested_width(qapp):
    from ruyso_app.ui.node_preview import figure_to_pixmap

    pixmap = figure_to_pixmap(plt.figure(figsize=(6.0, 3.0)), width_px=512)

    assert pixmap.width() == 512
    assert pixmap.height() == pytest.approx(256, abs=2)


def test_a_card_is_painted_in_the_themes_panel_colour(qapp):
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtWidgets import QStyleOptionGraphicsItem

    from ruyso_app.ui import theme

    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    started_as = theme.theme_mode()

    def margin_colour():
        rect = card.boundingRect()
        image = QImage(int(rect.width()), int(rect.height()), QImage.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        card.paint(painter, QStyleOptionGraphicsItem(), None)
        painter.end()
        return QColor(image.pixel(3, int(rect.height() / 2)))  # between edge and plate

    try:
        for mode, palette in (("dark", theme.DARK_THEME), ("light", theme.LIGHT_THEME)):
            theme.set_theme_mode(mode)
            assert margin_colour() == QColor(palette.panel_background)
    finally:
        theme.set_theme_mode(started_as)


# -- clicks --------------------------------------------------------------


def test_a_click_on_a_card_selects_its_node_and_opens_the_window(qapp):
    graph, node, overlay = _wired_plot(qapp)
    seen: list[str] = []
    overlay.node_activated.connect(seen.append)

    consumed = _click(overlay, graph, _card_centre(overlay.cards()[node.id]))

    assert consumed == [True, True]  # NodeGraphQt never sees it -- no rubber band
    assert seen == [node.id]
    assert list(overlay._windows) == [node.id]


def test_a_press_dragged_off_the_card_does_nothing(qapp):
    """Like a button: only a release over the same target acts."""
    graph, node, overlay = _wired_plot(qapp)
    seen: list[str] = []
    overlay.node_activated.connect(seen.append)
    card = overlay.cards()[node.id]

    _click(overlay, graph, _card_centre(card), release_at=QPointF(-5000, -5000))

    assert seen == []
    assert overlay._windows == {}


def test_a_click_on_the_nodes_body_is_left_to_the_canvas(qapp):
    graph, node, overlay = _wired_plot(qapp)
    body = node.view.mapToScene(node.view.boundingRect().center())

    assert overlay.target_at(graph.viewer().mapFromScene(body)) is None


def test_the_chevron_collapses_the_card_and_reports_a_layout_change(qapp):
    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    changes: list[int] = []
    overlay.layout_changed.connect(lambda: changes.append(1))
    chevron = node.view.mapToScene(node.view.chevron_rect().center())

    _click(overlay, graph, chevron)
    assert node.view.preview_collapsed
    assert not card.isVisible()
    assert overlay._windows == {}  # the chevron does not open the figure

    _click(overlay, graph, chevron)
    assert not node.view.preview_collapsed
    assert card.isVisible()
    assert changes == [1, 1]


def test_a_collapsed_node_keeps_its_card_hidden_through_a_move(qapp):
    graph, node, overlay = _wired_plot(qapp)
    node.view.set_preview_collapsed(True)

    node.set_pos(120, 60)
    assert not overlay.cards()[node.id].isVisible()


def test_turning_previews_off_hides_every_card(qapp):
    from ruyso_app.engine import settings

    graph, node, overlay = _wired_plot(qapp)
    try:
        settings.set("appearance.node_thumbnails", False)
        overlay.apply_preferences()
        assert not overlay.cards()[node.id].isVisible()
    finally:
        settings.set("appearance.node_thumbnails", True)
        overlay.apply_preferences()
    assert overlay.cards()[node.id].isVisible()


def test_the_size_preference_scales_the_card_against_its_node(qapp):
    from ruyso_app.engine import settings
    from ruyso_app.ui.preview_card import BASE_WIDTH

    graph, node, overlay = _wired_plot(qapp)
    card = overlay.cards()[node.id]
    node_width = node.view.sceneBoundingRect().width()
    assert card.boundingRect().width() == pytest.approx(node_width)

    try:
        settings.set("appearance.thumbnail_width", int(BASE_WIDTH * 2))
        overlay.apply_preferences()
        assert card.boundingRect().width() == pytest.approx(node_width * 2)
    finally:
        settings.set("appearance.thumbnail_width", int(BASE_WIDTH))


# -- the figure window opens at one stable size --------------------------


def test_figure_window_sizes_to_the_figure(qapp):
    figure = plt.figure(figsize=(5, 2), dpi=100)
    window = FigureWindow(figure, "t")
    assert window.size().width() == 500
    assert window.size().height() == 200


def test_window_size_ignores_a_dpi_a_canvas_has_doubled(qapp):
    """
    The bug this guards: attaching a ``FigureCanvasQTAgg`` rewrites
    ``figure.dpi`` to ``devicePixelRatio * dpi``, and the ratio is only
    2.0 once the widget is on a Retina screen. Reading the live dpi gave
    100 on the first open and 200 on every later one -- the same plot
    opening at 650x450, then 1300x900. Cannot be reproduced on an
    offscreen display (ratio is always 1.0), so the mutation is applied
    by hand here.
    """
    from ruyso_app.ui.node_preview import window_size_for

    figure = plt.figure(figsize=(6.5, 4.5), dpi=100)
    first = window_size_for(figure)

    figure.set_dpi(200)  # what a Retina canvas does to the figure
    fresh = plt.figure(figsize=(6.5, 4.5), dpi=200)

    assert (first.width(), first.height()) == (650, 450)
    assert window_size_for(fresh) == first


def test_window_size_survives_the_user_resizing_a_window(qapp):
    """A canvas writes its widget size back onto the figure; the
    remembered size must not drift with it."""
    from ruyso_app.ui.node_preview import window_size_for

    figure = plt.figure(figsize=(6.0, 4.0), dpi=100)
    first = window_size_for(figure)

    figure.set_size_inches(11.0, 8.0)  # as a dragged-bigger canvas would
    assert window_size_for(figure) == first


def test_reopening_a_window_returns_to_the_configured_size(qapp):
    figure = plt.figure(figsize=(6.0, 4.0), dpi=100)
    window = FigureWindow(figure, "t")
    window.show_at_configured_size()
    original = window.size()

    window.resize(1100, 800)
    window.close()
    window.show_at_configured_size()

    assert window.size() == original


def test_a_window_is_clamped_to_the_screen(qapp):
    from ruyso_app.ui.node_preview import window_size_for

    huge = plt.figure(figsize=(400, 300), dpi=100)
    size = window_size_for(huge)
    available = qapp.primaryScreen().availableGeometry()

    assert size.width() <= available.width()
    assert size.height() <= available.height()
    assert size.width() / size.height() == pytest.approx(400 / 300, rel=0.05)


# -- one window per node, reused ----------------------------------------


def test_clicking_a_figure_twice_reuses_one_window(qapp):
    _graph_, node, overlay = _wired_plot(qapp)

    overlay._open_window(node.id)
    first = overlay._windows[node.id]
    overlay._open_window(node.id)

    assert len(overlay._windows) == 1
    assert overlay._windows[node.id] is first


def test_an_open_window_follows_a_re_render(qapp):
    import pandas as pd

    _graph_, node, overlay = _wired_plot(qapp)
    overlay._open_window(node.id)
    window = overlay._windows[node.id]

    rerendered = NodeRegistry.get("matplotlib_plot")(
        params={"x": "a", "y": "b", "kind": "line"}
    ).run(df=pd.DataFrame({"a": [1.0, 2, 3], "b": [10.0, 50, 30]}))["figure"]
    overlay.set_run_outputs({"plot": {"figure": rerendered}})

    assert window.figure() is rerendered


def test_deleting_a_node_drops_its_window(qapp):
    graph, node, overlay = _wired_plot(qapp)
    overlay._open_window(node.id)
    assert overlay._windows

    graph.delete_nodes([node])
    assert overlay._windows == {}


def test_the_window_is_titled_with_the_node_name(qapp):
    _graph_, node, overlay = _wired_plot(qapp)
    overlay._open_window(node.id)
    assert overlay._windows[node.id].windowTitle() == "Figure - plot"


# -- axis limits read back off a rendered figure -------------------------


def test_figure_axis_limits_reports_a_numeric_axis_as_trimmed_numbers(qapp):
    import pandas as pd

    from ruyso_app.nodes.viz import MatplotlibPlot, MatplotlibPlotParams
    from ruyso_app.ui.node_preview import figure_axis_limits

    figure = MatplotlibPlot(params=MatplotlibPlotParams(x="a", y="b")).run(
        df=pd.DataFrame({"a": [1.0, 2, 3], "b": [10.0, 50, 30]})
    )["figure"]
    limits = figure_axis_limits(figure)

    assert set(limits) == {"x_min", "x_max", "y_min", "y_max"}
    assert limits["y_min"] == "8" and limits["y_max"] == "52"  # whole numbers stay whole
    assert limits["x_min"] == "0.9"


def test_figure_axis_limits_reports_a_date_axis_as_iso_text(qapp):
    import numpy as np
    import pandas as pd

    from ruyso_app.nodes.viz import TimeSeriesPlot, TimeSeriesPlotParams
    from ruyso_app.ui.node_preview import figure_axis_limits

    df = pd.DataFrame({"d": pd.date_range("2021-03-05", periods=120), "v": np.arange(120.0)})
    figure = TimeSeriesPlot(params=TimeSeriesPlotParams(x_column="d", y_column="v")).run(
        df=df
    )["figure"]
    limits = figure_axis_limits(figure)

    # Round-trips: what is shown is what _limit_value parses back.
    assert limits["x_min"].startswith("2021-02-2")
    assert pd.to_datetime(limits["x_min"]) < pd.Timestamp("2021-03-05")
    assert pd.to_datetime(limits["x_max"]) > pd.Timestamp("2021-07-01")


def test_figure_axis_limits_of_nothing_is_empty(qapp):
    from ruyso_app.ui.node_preview import figure_axis_limits

    assert figure_axis_limits(None) == {}
