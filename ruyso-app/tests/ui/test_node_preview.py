"""
Tests for on-canvas figure previews (``ui.node_preview``): which nodes
get one, resolving the right figure from a run's outputs, thumbnail
lifecycle, and the pop-out window sizing.
"""

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes
from ruyso_app.ui.node_preview import (
    FigureWindow,
    NodePreviewOverlay,
    is_figure_core_class,
    resolve_figure,
)

NodeRegistry.discover_package(ruyso_app.nodes)


def _graph(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    return graph


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


def test_overlay_tracks_thumbnails_by_node_lifecycle(qapp):
    graph = _graph(qapp)
    overlay = NodePreviewOverlay(graph)

    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    graph.create_node(qt_type_for("csv_loader"), name="load")

    assert plot.id in overlay._thumbs
    assert len(overlay._thumbs) == 1  # the loader gets none

    graph.delete_node(plot)
    assert plot.id not in overlay._thumbs


def test_overlay_fills_thumbnail_from_run_outputs(qapp):
    graph = _graph(qapp)
    overlay = NodePreviewOverlay(graph)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")

    assert not overlay._thumbs[plot.id].has_figure()

    figure, ax = plt.subplots()
    ax.plot([0, 1], [1, 0])
    overlay.set_run_outputs({"plot": {"figure": figure}})

    assert overlay._thumbs[plot.id].has_figure()
    assert overlay._thumbs[plot.id].figure() is figure


def test_figure_window_sizes_to_the_figure(qapp):
    figure = plt.figure(figsize=(5, 2), dpi=100)
    window = FigureWindow(figure, "t")
    assert window.size().width() == 500
    assert window.size().height() == 200


# -- the figure window opens at one stable size --------------------------


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


def _wired_plot(qapp):
    """A graph with a rendered matplotlib_plot, plus its overlay."""
    import pandas as pd

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    overlay = NodePreviewOverlay(graph)
    figure = NodeRegistry.get("matplotlib_plot")(params={"x": "a", "y": "b"}).run(
        df=pd.DataFrame({"a": [1.0, 2, 3], "b": [10.0, 50, 30]})
    )["figure"]
    overlay.set_run_outputs({"plot": {"figure": figure}})
    return graph, node, overlay


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


# -- clicking a thumbnail must not fall through to the canvas ------------


def test_a_thumbnail_click_is_accepted_and_announces_its_node(qapp):
    """
    An ignored press propagates to the NodeGraphQt viewport, which reads
    it as a click on empty canvas and clears the selection -- which is
    what used to blank the Options panel as the figure window opened.
    """
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    _graph_, node, overlay = _wired_plot(qapp)
    seen: list[str] = []
    overlay.node_activated.connect(seen.append)

    event = QMouseEvent(
        QEvent.MouseButtonPress, QPointF(5, 5),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
    )
    QApplication.sendEvent(overlay._thumbs[node.id], event)

    assert event.isAccepted()
    assert seen == [node.id]


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


# -- C3: no work for a figure that has not changed -----------------------


def test_an_unchanged_figure_is_not_rasterised_again(qapp):
    """
    The skip cache hands back the *same* Figure object for a grapher
    nothing changed for, so identity says the pixels are already right.
    Re-rasterising through an Agg canvas on every keystroke-triggered
    background run is pure waste.
    """
    from ruyso_app.ui import node_preview

    calls: list[int] = []
    original = node_preview.figure_to_pixmap

    def counted(figure):
        calls.append(1)
        return original(figure)

    node_preview.figure_to_pixmap = counted
    try:
        figure = plt.figure()
        thumb = node_preview.FigureThumbnail("n", "placeholder")
        thumb.show_figure(figure)
        thumb.show_figure(figure)  # same object
        assert len(calls) == 1

        thumb.show_figure(plt.figure())  # a genuinely new one
        assert len(calls) == 2
    finally:
        node_preview.figure_to_pixmap = original


def test_the_position_timer_is_idle_until_the_canvas_moves(qapp):
    """It used to tick 16 times a second for the life of the app."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QResizeEvent
    from PySide6.QtCore import QSize

    graph = _graph(qapp)
    overlay = NodePreviewOverlay(graph)
    graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    overlay._timer.stop()
    overlay._idle.stop()
    assert not overlay._timer.isActive()

    overlay.eventFilter(None, QResizeEvent(QSize(10, 10), QSize(9, 9)))

    assert overlay._timer.isActive()  # woken by the interaction
    assert overlay._idle.isActive()  # ...and armed to stop again


def test_an_event_that_is_not_canvas_movement_does_not_wake_it(qapp):
    from PySide6.QtCore import QEvent

    graph = _graph(qapp)
    overlay = NodePreviewOverlay(graph)
    graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    overlay._timer.stop()
    overlay._idle.stop()

    overlay.eventFilter(None, QEvent(QEvent.Type.ToolTip))

    assert not overlay._timer.isActive()


def test_the_timer_never_wakes_with_no_thumbnails(qapp):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent

    graph = _graph(qapp)
    overlay = NodePreviewOverlay(graph)  # no figure nodes at all
    overlay.eventFilter(None, QResizeEvent(QSize(10, 10), QSize(9, 9)))
    assert not overlay._timer.isActive()
