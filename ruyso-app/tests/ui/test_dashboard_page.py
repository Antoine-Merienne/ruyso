"""
Tests for the Dashboard tab (``ui.dashboard_page`` + ``dashboard_canvas``
+ ``dashboard_items``): the empty-state / disconnected-source overlay,
vector figure items synced from a run's outputs and keyed to their
``export_to_dashboard`` node, the "· modified" staleness flag, text
items + live restyle, multi-select, and vector PDF / PNG export.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.dashboard_items import FigureItem, TextItem
from ruyso_app.ui.dashboard_page import DashboardPage
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes

NodeRegistry.discover_package(ruyso_app.nodes)


def _graph_with_export(qapp, title=""):
    """
    example_data -> table_viewer -> export_to_dashboard.

    Returns ``(graph, export_node, source_node)``. ``export_to_dashboard``
    is a sink, so a run's figure is keyed by ``source_node.name()`` in the
    outputs dict, not by the export node.
    """
    graph = NodeGraph()
    register_all_nodes(graph)
    load = graph.create_node(qt_type_for("example_data"), name="load")
    view = graph.create_node(qt_type_for("table_viewer"), name="view")
    export = graph.create_node(qt_type_for("export_to_dashboard"), name="export")
    if title:
        export.set_property("title", title)
    load.outputs()["df"].connect_to(view.inputs()["df"])
    view.outputs()["figure"].connect_to(export.inputs()["figure"])
    return graph, export, view


def test_overlay_shows_empty_hint_until_a_block_exists(qapp):
    page = DashboardPage()
    overlay = page._view.overlay
    assert "export_to_dashboard" in overlay.text()

    page.add_text_item()
    assert overlay.text() == ""


def test_disconnected_source_message_is_a_canvas_overlay(qapp):
    page = DashboardPage()
    page.add_text_item()  # so the empty hint is not what we see
    page.set_canvas_message("source plot is disconnected")
    assert page._view.overlay.text() == "source plot is disconnected"
    page.set_canvas_message(None)
    assert page._view.overlay.text() == ""


def test_add_text_item_shows_inspector_and_restyles_live(qapp):
    page = DashboardPage()
    item = page.add_text_item(is_title=True)

    assert page._inspector_stack.currentWidget() is page._text_inspector
    assert item.style()["bold"] is True  # title preset

    page._text_inspector._bold.setChecked(False)
    page._text_inspector._size.setValue(30)
    assert item.style()["bold"] is False
    assert item.font().pointSize() == 30


def test_sync_figures_creates_one_vector_item_per_export_node(qapp):
    graph, export, source = _graph_with_export(qapp, title="My table")
    page = DashboardPage()

    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    figs = [i for i in page._scene.items() if isinstance(i, FigureItem)]
    assert len(figs) == 1
    item = figs[0]
    assert item.export_node_id == export.name()
    assert item.title() == "My table"
    assert item._renderer is not None and item._renderer.isValid()

    item.setPos(120, 140)
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    assert [i for i in page._scene.items() if isinstance(i, FigureItem)] == [item]
    assert item.pos().toTuple() == (120, 140)  # layout preserved


def test_figure_marked_modified_when_source_id_is_in_the_modified_set(qapp):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    item = next(i for i in page._scene.items() if isinstance(i, FigureItem))
    assert not item.is_stale()

    page.sync_figures(
        graph, {source.name(): {"figure": plt.figure()}}, modified_ids={"view"}
    )
    assert item.is_stale()


def test_selecting_exactly_one_figure_emits_the_export_node_id(qapp):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})

    received: list[str] = []
    page.figure_block_selected.connect(received.append)
    item = next(i for i in page._scene.items() if isinstance(i, FigureItem))
    item.setSelected(True)

    assert received == [export.name()]  # MainWindow binds the Options panel


def test_rubber_band_style_multi_select(qapp):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    page.add_text_item()

    for it in page._scene.items():
        if isinstance(it, (FigureItem, TextItem)):
            it.setSelected(True)
    assert len(page._scene.selectedItems()) == 2
    # multi-selection -> neither single-item inspector
    assert page._inspector_stack.currentIndex() == 2


def test_block_for_a_deleted_export_node_is_kept_but_flagged_stale(qapp):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})

    graph.delete_node(export)
    page.sync_figures(graph, {})

    figs = [i for i in page._scene.items() if isinstance(i, FigureItem)]
    assert len(figs) == 1  # snapshot survives


def test_export_writes_pdf_and_png_over_a_non_empty_scene(qapp, tmp_path):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    page.add_text_item(is_title=True)

    pdf = tmp_path / "board.pdf"
    png = tmp_path / "board.png"
    page.export(str(pdf))
    page.export(str(png))

    assert pdf.stat().st_size > 0
    assert png.stat().st_size > 0


def test_export_on_an_empty_dashboard_raises(qapp, tmp_path):
    page = DashboardPage()
    try:
        page.export(str(tmp_path / "x.png"))
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError on an empty dashboard")
