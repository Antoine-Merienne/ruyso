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


def _renders_done():
    """Wait for the render thread: a block's vector art is drawn off the
    GUI thread (``ui/render_queue.py``), so it is not there the instant
    ``sync_figures`` returns."""
    from ruyso_app.ui import render_queue

    assert render_queue.queue().wait_idle(15_000), "a render never finished"


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


def test_the_empty_hint_survives_a_title_text_box_and_shape(qapp):
    """The hint is about *figures*, which only an export_to_dashboard
    node can deliver -- adding a text box is not the thing it asks for,
    so it must not read as done."""
    page = DashboardPage()
    overlay = page._view.overlay
    assert "export_to_dashboard" in overlay.text()

    page.add_text_item(is_title=True)
    page.add_text_item()
    page.add_shape("rectangle")
    assert "export_to_dashboard" in overlay.text()


def test_the_empty_hint_goes_once_a_figure_arrives(qapp):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()

    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    assert page._view.overlay.text() == ""


def test_disconnected_source_message_is_a_canvas_overlay(qapp):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})

    page.set_canvas_message("source plot is disconnected")
    assert page._view.overlay.text() == "source plot is disconnected"
    page.set_canvas_message(None)
    assert page._view.overlay.text() == ""


def test_a_canvas_message_outranks_the_empty_hint(qapp):
    """It is about the block just selected; the hint is always true."""
    page = DashboardPage()
    page.set_canvas_message("source plot is disconnected")
    assert page._view.overlay.text() == "source plot is disconnected"

    page.set_canvas_message(None)
    assert "export_to_dashboard" in page._view.overlay.text()


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
    _renders_done()
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
    # A figure and a text box have nothing in common to edit together,
    # so a mixed selection falls back to the placeholder. (Several
    # blocks of the *same* kind are bound as a group instead.)
    from ruyso_app.ui.dashboard_page import _PAGE_EMPTY

    assert page._inspector_stack.currentIndex() == _PAGE_EMPTY


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


def test_an_unchanged_figure_is_not_serialised_to_svg_again(qapp):
    """Serialising to SVG is the most expensive thing this tab does."""
    import matplotlib.pyplot as plt

    from ruyso_app.ui import dashboard_page as module

    calls: list[int] = []
    original = module.figure_to_svg_bytes

    def counted(figure, **kwargs):
        calls.append(1)
        return original(figure, **kwargs)

    module.figure_to_svg_bytes = counted
    try:
        graph, _export, source = _graph_with_export(qapp)
        page = DashboardPage()
        figure = plt.figure()
        outputs = {source.name(): {"figure": figure}}

        page.sync_figures(graph, outputs)
        page.sync_figures(graph, outputs)  # the same Figure object
        _renders_done()
        assert len(calls) == 1

        page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
        _renders_done()
        assert len(calls) == 2
    finally:
        module.figure_to_svg_bytes = original


# -- shapes, undo and locking -------------------------------------------

from ruyso_app.ui.dashboard_shapes import SHAPE_KINDS, ShapeItem  # noqa: E402


def test_every_shape_kind_can_be_added(qapp):
    page = DashboardPage()
    for kind in SHAPE_KINDS:
        page.add_shape(kind)

    kinds = sorted(b.kind for b in page.blocks() if isinstance(b, ShapeItem))
    assert kinds == sorted(SHAPE_KINDS)


def test_adding_a_shape_is_undoable(qapp):
    page = DashboardPage()
    page.add_shape("ellipse")
    assert len(page.blocks()) == 1

    page.undo_stack().undo()
    assert page.blocks() == []

    page.undo_stack().redo()
    assert len(page.blocks()) == 1


def test_deleting_keeps_the_block_alive_so_undo_restores_it(qapp):
    """Undo must bring back the same figure, not a blank one waiting
    for the next run."""
    page = DashboardPage()
    shape = page.add_shape("rectangle")
    page._scene.clearSelection()
    shape.setSelected(True)
    page.remove_selected()
    assert page.blocks() == []

    page.undo_stack().undo()

    assert page.blocks() == [shape]  # the very same object


def test_a_restyle_is_undoable(qapp):
    page = DashboardPage()
    shape = page.add_shape("rectangle")
    page._scene.clearSelection()
    shape.setSelected(True)
    page._shape_inspector._push(stroke_width=9.0)
    assert shape.style()["stroke_width"] == 9.0

    page.undo_stack().undo()
    assert shape.style()["stroke_width"] != 9.0


def test_several_shapes_are_restyled_together(qapp):
    page = DashboardPage()
    a, b = page.add_shape("ellipse"), page.add_shape("rectangle")
    page._scene.clearSelection()
    a.setSelected(True)
    b.setSelected(True)

    assert len(page._shape_inspector.items()) == 2
    page._shape_inspector._push(stroke_width=7.0)
    assert a.style()["stroke_width"] == b.style()["stroke_width"] == 7.0


def test_a_mixed_selection_has_nothing_in_common_to_edit(qapp):
    from ruyso_app.ui.dashboard_page import _PAGE_EMPTY

    page = DashboardPage()
    shape = page.add_shape("rectangle")
    text = page.add_text_item()
    page._scene.clearSelection()
    shape.setSelected(True)
    text.setSelected(True)

    assert page._inspector_stack.currentIndex() == _PAGE_EMPTY


def test_locking_makes_a_block_untouchable(qapp):
    from PySide6.QtWidgets import QGraphicsItem

    page = DashboardPage()
    shape = page.add_shape("rectangle")
    page._scene.clearSelection()
    shape.setSelected(True)
    page.lock_selected()

    assert shape.is_locked()
    assert not shape.flags() & QGraphicsItem.ItemIsSelectable
    assert not shape.flags() & QGraphicsItem.ItemIsMovable
    assert not shape.isSelected()

    page.remove_selected()  # nothing is selected, so nothing is deleted
    assert page.blocks() == [shape]


def test_unlock_all_is_the_way_back(qapp):
    """A locked block cannot be selected, so it cannot be unlocked from
    its own inspector."""
    page = DashboardPage()
    shape = page.add_shape("rectangle")
    page._scene.clearSelection()
    shape.setSelected(True)
    page.lock_selected()
    assert page.has_locked_blocks()

    page.unlock_all()

    assert not page.has_locked_blocks()
    assert not shape.is_locked()


def test_duplicating_offsets_a_copy_and_selects_it(qapp):
    page = DashboardPage()
    shape = page.add_shape("ellipse")
    shape.set_style(stroke_width=5.0)
    page._scene.clearSelection()
    shape.setSelected(True)

    made = page.duplicate_selected()

    assert len(made) == 1
    copy = made[0]
    assert copy is not shape
    assert copy.kind == "ellipse"
    assert copy.style()["stroke_width"] == 5.0
    assert copy.pos() != shape.pos()


def test_a_figure_block_is_not_duplicated(qapp):
    """It belongs to its export node; a second copy would have no source."""
    graph, _export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    for item in page.blocks():
        item.setSelected(True)

    assert page.duplicate_selected() == []


def test_arranging_is_one_undo_step(qapp):
    page = DashboardPage()
    a, b = page.add_shape("rectangle"), page.add_shape("rectangle")
    b.setPos(200, 0)
    page._scene.clearSelection()
    a.setSelected(True)
    b.setSelected(True)
    before = page.undo_stack().count()

    page.align("left")

    assert page.undo_stack().count() == before + 1
    page.undo_stack().undo()
    assert b.pos().x() == 200


# -- saving and reopening the layout ------------------------------------


def test_an_empty_dashboard_writes_nothing(qapp):
    """A file only grows the key once it has a report to carry."""
    assert DashboardPage().to_dict() == {}


def test_the_layout_round_trips_through_plain_data(qapp):
    import json

    page = DashboardPage()
    shape = page.add_shape("arrow")
    shape.setPos(40, 50)
    shape.set_style(stroke="#ff0000", stroke_width=6.0)
    title = page.add_text_item(is_title=True)
    title.setPos(10, 10)

    data = json.loads(json.dumps(page.to_dict()))  # must be JSON, not objects

    reopened = DashboardPage()
    reopened.restore(data)

    kinds = sorted(type(b).__name__ for b in reopened.blocks())
    assert kinds == ["ShapeItem", "TextItem"]
    back = next(b for b in reopened.blocks() if isinstance(b, ShapeItem))
    assert back.kind == "arrow"
    assert (back.pos().x(), back.pos().y()) == (40.0, 50.0)
    assert back.style()["stroke"] == "#ff0000"
    assert back.style()["stroke_width"] == 6.0


def test_z_order_survives_a_round_trip(qapp):
    page = DashboardPage()
    low, high = page.add_shape("rectangle"), page.add_shape("ellipse")
    low.setZValue(-2)
    high.setZValue(7)

    reopened = DashboardPage()
    reopened.restore(page.to_dict())

    by_kind = {b.kind: b.zValue() for b in reopened.blocks()}
    assert by_kind == {"rectangle": -2.0, "ellipse": 7.0}


def test_a_figure_block_is_saved_by_its_export_node_name(qapp):
    graph, export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    list(page._figure_items.values())[0].setPos(77, 88)

    data = page.to_dict()
    figure_specs = [i for i in data["items"] if i["type"] == "figure"]

    assert len(figure_specs) == 1
    assert figure_specs[0]["state"]["export_node_id"] == export.name()


def test_the_rendered_picture_is_not_saved(qapp):
    """It comes back from running the pipeline; a stale picture on disk
    would be worse than none."""
    import json

    graph, _export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})

    text = json.dumps(page.to_dict())
    assert "svg" not in text.lower()
    assert len(text) < 4000  # a description, not an image


def test_a_restored_figure_is_rebound_by_a_run_not_duplicated(qapp):
    graph, _export, source = _graph_with_export(qapp)
    page = DashboardPage()
    page.sync_figures(graph, {source.name(): {"figure": plt.figure()}})
    list(page._figure_items.values())[0].setPos(77, 88)

    reopened = DashboardPage()
    reopened.restore(page.to_dict())
    restored = list(reopened._figure_items.values())[0]
    assert restored.is_stale()  # nothing has run yet

    reopened.sync_figures(graph, {source.name(): {"figure": plt.figure()}})

    figures = [b for b in reopened.blocks() if isinstance(b, FigureItem)]
    assert figures == [restored]  # the same block, not a second one
    assert (restored.pos().x(), restored.pos().y()) == (77.0, 88.0)
    assert not restored.is_stale()


def test_a_block_whose_export_node_is_gone_is_kept_and_flagged(qapp):
    """Matches what happens when that node is deleted with the app open."""
    page = DashboardPage()
    page.restore(
        {
            "version": 1,
            "items": [
                {
                    "type": "figure",
                    "pos": [5, 6],
                    "z": 0,
                    "state": {"export_node_id": "Gone", "title": "Sales"},
                }
            ],
        }
    )

    blocks = page.blocks()
    assert len(blocks) == 1
    assert blocks[0].export_node_id == "Gone"
    assert blocks[0].is_stale()


def test_restoring_replaces_whatever_was_there(qapp):
    page = DashboardPage()
    page.add_shape("rectangle")
    page.restore({"version": 1, "items": []})
    assert page.blocks() == []


def test_restoring_nothing_clears_the_canvas(qapp):
    """A file with no dashboard section means an empty dashboard, so
    blocks cannot bleed from one document into the next."""
    page = DashboardPage()
    page.add_shape("rectangle")
    page.restore(None)
    assert page.blocks() == []


def test_a_restored_layout_starts_with_no_history(qapp):
    page = DashboardPage()
    page.add_shape("rectangle")
    page.restore({"version": 1, "items": []})

    assert page.undo_stack().count() == 0
    assert page.undo_stack().isClean()


def test_one_unreadable_block_does_not_lose_the_others(qapp):
    page = DashboardPage()
    page.restore(
        {
            "version": 1,
            "items": [
                {"type": "nonsense", "pos": [0, 0], "z": 0, "state": {}},
                {"type": "shape", "pos": [1, 2], "z": 0, "state": {"kind": "ellipse"}},
            ],
        }
    )
    assert [b.kind for b in page.blocks()] == ["ellipse"]
