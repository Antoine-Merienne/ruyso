"""
Tests for the Options panel as the selected-node editor
(``ui.options_panel.OptionsPanel``).
"""

from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes
from ruyso_app.ui.options_panel import OptionsPanel

NodeRegistry.discover_package(ruyso_app.nodes)


def _graph(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    return graph


def test_show_node_populates_macro_and_micro(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()

    panel.show_node(node, ["drop_na", "standard_scaler"])

    assert panel.current_category() == "transform"
    assert panel._macro_label.text() == theme.label_for_category("transform")
    items = [panel._micro_combo.itemText(i) for i in range(panel._micro_combo.count())]
    assert items == ["drop_na", "standard_scaler"]
    assert panel._micro_combo.currentText() == "drop_na"


def test_editing_a_field_writes_back_to_the_node_property(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    panel = OptionsPanel()
    panel.show_node(node, ["csv_loader"])

    # csv_loader has a "filepath" string field -> a QLineEdit in the form.
    from PySide6.QtWidgets import QLineEdit

    edits = panel._params_host.findChildren(QLineEdit)
    target = next(e for e in edits)
    target.setText("/tmp/data.csv")

    assert node.get_property("filepath") == "/tmp/data.csv"


def test_user_micro_change_emits_signal_but_programmatic_populate_does_not(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()

    seen = []
    panel.micro_type_change_requested.connect(seen.append)

    panel.show_node(node, ["drop_na", "standard_scaler"])
    assert seen == []  # repopulating the combo must not fire

    panel._micro_combo.setCurrentText("standard_scaler")
    assert seen == ["standard_scaler"]


def test_clear_shows_empty_state(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    panel = OptionsPanel()
    panel.show_node(node, ["drop_na"])
    panel.clear()

    assert panel.current_node() is None
    assert not panel._params_host.isVisible()


def test_background_tint_follows_selected_macro_type(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("linear_regression_fit"), name="model")
    panel = OptionsPanel()
    panel.show_node(node, ["linear_regression_fit"])

    assert "rgba(" in panel.styleSheet()
