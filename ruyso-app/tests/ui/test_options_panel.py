"""
Tests for the Options panel as the selected-node editor
(``ui.options_panel.OptionsPanel``).
"""

from NodeGraphQt import NodeGraph
from PySide6.QtWidgets import QComboBox, QLineEdit, QPushButton, QSizePolicy

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import (
    core_node_types_by_category,
    qt_type_for,
    register_all_nodes,
)
from ruyso_app.ui.options_panel import OptionsPanel

NodeRegistry.discover_package(ruyso_app.nodes)

BY_CAT = core_node_types_by_category()


def _graph(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    return graph


def test_show_node_populates_macro_and_micro(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()

    panel.show_node(node, BY_CAT)

    assert panel.current_category() == "transform"
    assert panel._macro_combo.currentText() == theme.label_for_category("transform")
    items = [panel._micro_combo.itemText(i) for i in range(panel._micro_combo.count())]
    assert items == BY_CAT["transform"]
    assert panel._micro_combo.currentText() == "drop_na"


def test_editing_a_field_writes_back_to_the_node_property(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    edits = panel._params_host.findChildren(QLineEdit)
    edits[0].setText("/tmp/data.csv")  # the "filepath" field

    assert node.get_property("filepath") == "/tmp/data.csv"


def test_user_type_change_emits_signal_but_programmatic_populate_does_not(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()

    seen = []
    panel.node_type_change_requested.connect(seen.append)

    panel.show_node(node, BY_CAT)
    assert seen == []  # repopulating the combos must not fire

    panel._micro_combo.setCurrentText("standard_scaler")
    assert seen == ["standard_scaler"]


def test_changing_macro_type_requests_first_node_of_new_macro(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    seen = []
    panel.node_type_change_requested.connect(seen.append)

    panel._macro_combo.setCurrentText(theme.label_for_category("loading"))

    assert seen == [BY_CAT["loading"][0]]


def test_macro_combo_disables_macro_types_without_nodes(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    model = panel._macro_combo.model()
    for i in range(panel._macro_combo.count()):
        category = panel._macro_combo.itemData(i)
        assert model.item(i).isEnabled() == bool(BY_CAT.get(category))


def test_clear_shows_empty_state(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)
    panel.clear()

    assert panel.current_node() is None
    assert not panel._params_host.isVisible()


def test_path_field_has_a_browse_button_and_an_expanding_edit(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    assert panel._params_host.findChildren(QPushButton)  # the Browse... button
    edit = panel._params_host.findChildren(QLineEdit)[0]
    assert edit.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding


def test_non_path_field_has_no_browse_button(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("standard_scaler"), name="scale")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    assert panel._params_host.findChildren(QPushButton) == []


def test_column_field_lists_input_columns_and_warns(qapp):
    graph = _graph(qapp)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    panel = OptionsPanel()

    # "y" accepts only numeric columns; feed it a mix.
    panel.show_node(plot, BY_CAT, input_columns={"age": "numeric", "name": "categorical"})

    combos = [c for c in panel._params_host.findChildren(QComboBox) if c.isEditable()]
    y_combo = combos[1]  # x then y, both column fields
    assert [y_combo.itemText(i) for i in range(y_combo.count())] == ["age", "name"]

    warning, *_ = panel._column_fields["y"]
    y_combo.setCurrentText("name")  # exists but wrong type
    assert not warning.isHidden() and "numeric" in warning.text()

    y_combo.setCurrentText("nope")  # not a column at all
    assert not warning.isHidden() and "not a column" in warning.text()

    y_combo.setCurrentText("age")  # numeric -> fine
    assert warning.isHidden()


def test_background_tint_follows_selected_macro_type(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("linear_regression_fit"), name="model")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    assert "rgba(" in panel.styleSheet()
