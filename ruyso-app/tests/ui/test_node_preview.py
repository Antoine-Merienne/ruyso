"""
Tests for on-canvas figure previews (``ui.node_preview``): which nodes
get one, resolving the right figure from a run's outputs, thumbnail
lifecycle, and the pop-out window sizing.
"""

import matplotlib

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
    assert is_figure_core_class(NodeRegistry.get("figure_export"))  # figure input
    assert not is_figure_core_class(NodeRegistry.get("csv_loader"))
    assert not is_figure_core_class(None)


def test_resolve_figure_for_grapher_and_for_figure_sink(qapp):
    graph = _graph(qapp)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    export = graph.create_node(qt_type_for("figure_export"), name="save")
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
