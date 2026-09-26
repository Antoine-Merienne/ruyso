"""
Tests for the Table tab (``ui.table_page.TablePage``): navigator
population, availability gating, selection wiring and the spec's
placeholder messages.
"""

import pandas as pd
from NodeGraphQt import NodeGraph
from PySide6.QtCore import Qt

import ruyso_app.nodes  # noqa: F401
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes
from ruyso_app.ui.table_page import MESSAGE_BEFORE_RUN, MESSAGE_NO_SELECTION, TablePage

NodeRegistry.discover_package(ruyso_app.nodes)


def _graph_with_split(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    loader = graph.create_node(qt_type_for("csv_loader"), name="load")
    split = graph.create_node(qt_type_for("train_test_split"), name="split")
    loader.set_output(0, split.input(0))
    return graph


def test_navigator_lists_every_table_before_a_run_all_disabled(qapp):
    graph = _graph_with_split(qapp)
    page = TablePage()
    page.refresh(graph, None)

    labels = [page._nav.item(i).text() for i in range(page._nav.count())]
    assert labels == ["load", "split / X_train", "split / X_test"]
    for i in range(page._nav.count()):
        assert not (page._nav.item(i).flags() & Qt.ItemIsEnabled)
    assert page.current_message() == MESSAGE_BEFORE_RUN


def test_after_run_available_tables_are_enabled_and_selectable(qapp):
    graph = _graph_with_split(qapp)
    page = TablePage()
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    page.refresh(graph, {"load": {"df": df}})

    load_item = page._nav.item(0)
    assert load_item.flags() & Qt.ItemIsEnabled
    # the split outputs were not produced -> disabled
    assert not (page._nav.item(1).flags() & Qt.ItemIsEnabled)

    page._nav.setCurrentRow(0)
    assert page._stack.currentWidget() is page._table_view
    assert page._table_view.model().columnCount() == 2


def test_modified_nodes_get_the_tag_role(qapp):
    graph = _graph_with_split(qapp)
    page = TablePage()
    df = pd.DataFrame({"a": [1, 2]})
    page.refresh(graph, {"load": {"df": df}}, modified={"load"})

    from ruyso_app.ui.table_page import _MODIFIED_ROLE

    load_item = page._nav.item(0)
    assert load_item.data(_MODIFIED_ROLE) is True
    # a disabled (never-run) entry is never tagged
    assert page._nav.item(1).data(_MODIFIED_ROLE) is False


def test_message_is_no_selection_after_run_with_nothing_selected(qapp):
    graph = _graph_with_split(qapp)
    page = TablePage()
    page.refresh(graph, {"load": {"df": pd.DataFrame({"a": [1]})}})
    assert page.current_message() == MESSAGE_NO_SELECTION


def test_columns_are_interactively_resizable(qapp):
    from PySide6.QtWidgets import QHeaderView

    page = TablePage()
    page._table_model.set_dataframe(pd.DataFrame({"a": [1], "b": [2]}))

    header = page._table_view.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.Interactive
