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


def test_grapher_column_field_lists_columns_and_warns_only_on_unknown(qapp):
    graph = _graph(qapp)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    panel = OptionsPanel()
    panel.show_node(plot, BY_CAT, input_columns={"age": "numeric", "name": "categorical"})

    combos = [c for c in panel._params_host.findChildren(QComboBox) if c.isEditable()]
    y_combo = combos[1]  # x then y, both column fields
    assert [y_combo.itemText(i) for i in range(y_combo.count())] == ["age", "name"]

    warning = panel._column_fields["y"][0]
    y_combo.setCurrentText("name")  # categorical y is fine for a grapher now
    assert warning.isHidden()

    y_combo.setCurrentText("nope")  # not a column at all -> still warns
    assert not warning.isHidden() and "not a column" in warning.text()


def test_numeric_only_column_field_warns_on_wrong_type(qapp):
    graph = _graph(qapp)
    scaler = graph.create_node(qt_type_for("standard_scaler"), name="scale")
    panel = OptionsPanel()
    panel.show_node(scaler, BY_CAT, input_columns={"age": "numeric", "city": "categorical"})

    combo = [c for c in panel._params_host.findChildren(QComboBox) if c.isEditable()][0]
    warning = panel._column_fields["columns"][0]
    # items: ["None", "age", "city"]
    combo.activated.emit(2)  # pick "city" -- categorical, scaler wants numeric
    assert not warning.isHidden() and "numeric" in warning.text()

    combo.activated.emit(2)  # toggle "city" back off
    combo.activated.emit(1)  # pick "age" -- numeric
    assert warning.isHidden()


def test_list_column_field_uses_one_editable_combo_like_single_fields(qapp):
    # The transformer's column selector must look the same as the
    # grapher/model ones: a single editable QComboBox, no extra button.
    from PySide6.QtWidgets import QToolButton

    graph = _graph(qapp)
    scaler = graph.create_node(qt_type_for("standard_scaler"), name="scale")
    panel = OptionsPanel()
    panel.show_node(scaler, BY_CAT, input_columns={"age": "numeric", "weight": "numeric"})

    assert panel._params_host.findChildren(QToolButton) == []
    combos = [c for c in panel._params_host.findChildren(QComboBox) if c.isEditable()]
    assert len(combos) == 1
    combo = combos[0]
    # index 0 is the italic-grey "None" clear entry, then the columns.
    assert [combo.itemText(i) for i in range(combo.count())] == ["None", "age", "weight"]


def test_list_column_field_toggles_picked_columns_into_the_value(qapp):
    graph = _graph(qapp)
    scaler = graph.create_node(qt_type_for("standard_scaler"), name="scale")
    panel = OptionsPanel()
    panel.show_node(scaler, BY_CAT, input_columns={"age": "numeric", "weight": "numeric"})

    combo = [c for c in panel._params_host.findChildren(QComboBox) if c.isEditable()][0]

    # A real dropdown pick sets the combo's text to the item first,
    # THEN emits activated -- reading currentText in the handler used
    # to toggle the just-picked item straight back off.
    def real_pick(index: int) -> None:
        combo.setCurrentIndex(index)
        combo.activated.emit(index)

    real_pick(1)  # pick "age"
    assert scaler.get_property("columns") == "age"

    real_pick(2)  # add "weight"
    assert scaler.get_property("columns") == "age, weight"

    real_pick(1)  # toggle "age" off
    assert scaler.get_property("columns") == "weight"

    real_pick(0)  # the "None" entry clears the field
    assert scaler.get_property("columns") == ""


def test_list_column_field_value_survives_a_form_rebuild(qapp):
    graph = _graph(qapp)
    scaler = graph.create_node(qt_type_for("standard_scaler"), name="scale")
    cols = {"a": "numeric", "b": "numeric", "c": "numeric"}
    panel = OptionsPanel()
    panel.show_node(scaler, BY_CAT, input_columns=cols)

    scaler.set_property("columns", "a, c")
    panel.show_node(scaler, BY_CAT, input_columns=cols)  # deselect + reselect

    combo = [c for c in panel._params_host.findChildren(QComboBox) if c.isEditable()][0]
    assert combo.currentText() == "a, c"
    combo.setCurrentIndex(2)
    combo.activated.emit(2)  # pick "b" -> appended to the kept value, not lost
    assert scaler.get_property("columns") == "a, c, b"


def test_set_input_columns_updates_pickers_in_place(qapp):
    graph = _graph(qapp)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    panel = OptionsPanel()
    panel.show_node(plot, BY_CAT, input_columns=None)

    combos = [c for c in panel._params_host.findChildren(QComboBox) if c.isEditable()]
    assert combos[0].count() == 0

    panel.set_input_columns({"a": "numeric", "b": "numeric"})
    assert [combos[0].itemText(i) for i in range(combos[0].count())] == ["a", "b"]


def test_background_tint_follows_selected_macro_type(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("linear_regression_fit"), name="model")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    assert "background-color: rgb(" in panel.styleSheet()


def test_loader_datetime_columns_is_a_column_dropdown_with_a_none_entry(qapp):
    from PySide6.QtCore import Qt

    graph = _graph(qapp)
    loader = graph.create_node(qt_type_for("csv_loader"), name="load")
    panel = OptionsPanel()
    # the loader's own last-run columns feed its datetime picker
    panel.show_node(loader, BY_CAT, input_columns={"date": "categorical", "n": "numeric"})

    combo = [
        c
        for c in panel._params_host.findChildren(QComboBox)
        if c.isEditable() and c.itemText(0) == "None"
    ][0]
    assert [combo.itemText(i) for i in range(combo.count())] == ["None", "date", "n"]
    # the "None" row is styled italic + grey
    assert combo.itemData(0, Qt.FontRole).italic()
    assert combo.itemData(0, Qt.ForegroundRole).getRgb()[:3] == (150, 150, 150)

    combo.activated.emit(1)  # pick "date"
    assert loader.get_property("datetime_columns") == "date"
    combo.activated.emit(0)  # "None" clears
    assert loader.get_property("datetime_columns") == ""


def test_loader_datetime_format_is_an_editable_suggestions_combo(qapp):
    from ruyso_app.nodes.loaders import COMMON_DATETIME_FORMATS

    graph = _graph(qapp)
    loader = graph.create_node(qt_type_for("csv_loader"), name="load")
    panel = OptionsPanel()
    panel.show_node(loader, BY_CAT)

    combo = [
        c
        for c in panel._params_host.findChildren(QComboBox)
        if c.isEditable() and c.itemText(0) == "infer"
    ][0]
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == ["infer", *COMMON_DATETIME_FORMATS]

    combo.setCurrentText("%d-%m-%Y")  # free text is accepted
    assert loader.get_property("datetime_format") == "%d-%m-%Y"
    combo.activated.emit(0)  # "infer" clears
    assert loader.get_property("datetime_format") == ""


def _rows(panel):
    f = panel._params_form
    out = {}
    for r in range(f.rowCount()):
        li = f.itemAt(r, f.ItemRole.LabelRole)
        lbl = li.widget().text() if li and li.widget() else f"row{r}"
        out[lbl] = f.isRowVisible(r)
    return out


def test_row_filter_shows_only_the_active_mode_fields(qapp):
    graph = _graph(qapp)
    rf = graph.create_node(qt_type_for("row_filter"), name="rf")
    panel = OptionsPanel()
    panel.show_node(rf, BY_CAT, input_columns={"price": "numeric"})

    rows = _rows(panel)
    assert rows["position op"] is True and rows["column"] is False

    panel._field_widgets["mode"].setCurrentText("value")
    rows = _rows(panel)
    assert rows["position op"] is False
    assert rows["column"] is True and rows["value op"] is True


def test_row_filter_operator_list_reacts_to_the_chosen_column(qapp):
    graph = _graph(qapp)
    rf = graph.create_node(qt_type_for("row_filter"), name="rf")
    panel = OptionsPanel()
    panel.show_node(rf, BY_CAT, input_columns={"price": "numeric", "city": "categorical"})

    op_combo = panel._reactive_choices["value_op"][0]
    panel._field_widgets["column"]._combo.setCurrentText("city")
    assert [op_combo.itemText(i) for i in range(op_combo.count())] == ["==", "!=", "contains"]

    panel._field_widgets["column"]._combo.setCurrentText("price")
    assert "contains" not in [op_combo.itemText(i) for i in range(op_combo.count())]


def test_change_type_target_list_reacts_to_the_chosen_column(qapp):
    graph = _graph(qapp)
    ct = graph.create_node(qt_type_for("change_type"), name="ct")
    panel = OptionsPanel()
    panel.show_node(ct, BY_CAT, input_columns={"amount": "numeric"})

    types = panel._reactive_choices["target_type"][0]
    panel._field_widgets["column"]._combo.setCurrentText("amount")
    got = [types.itemText(i) for i in range(types.count())]
    assert "int" not in got and "float" not in got
    assert "datetime" in got


def test_column_filter_tickboxes_track_the_stored_value(qapp):
    from PySide6.QtWidgets import QCheckBox, QScrollArea

    graph = _graph(qapp)
    cf = graph.create_node(qt_type_for("column_filter"), name="cf")
    panel = OptionsPanel()
    panel.show_node(cf, BY_CAT, input_columns={"a": "numeric", "b": "numeric", "c": "categorical"})

    boxes = panel._params_host.findChild(QScrollArea).findChildren(QCheckBox)
    assert [b.text() for b in boxes] == ["a", "b", "c"]

    boxes[0].setChecked(True)
    boxes[2].setChecked(True)
    assert cf.get_property("columns") == "a, c"

    panel.set_input_columns({"a": "numeric", "c": "categorical"})
    boxes = panel._params_host.findChild(QScrollArea).findChildren(QCheckBox)
    assert [(b.text(), b.isChecked()) for b in boxes] == [("a", True), ("c", True)]


def test_tickbox_edit_is_batched_until_flush(qapp):
    graph = _graph(qapp)
    cf = graph.create_node(qt_type_for("column_filter"), name="cf")
    panel = OptionsPanel()
    panel.show_node(cf, BY_CAT, input_columns={"a": "numeric", "b": "numeric"})

    seen = []
    panel.recompute_requested.connect(lambda: seen.append(1))

    from PySide6.QtWidgets import QCheckBox, QScrollArea

    box = panel._params_host.findChild(QScrollArea).findChildren(QCheckBox)[0]
    box.setChecked(True)
    assert cf.get_property("columns") == "a"  # value written immediately
    assert panel.autorun_suppressed() is False  # flag only held during the write
    assert seen == []  # ...but no recompute yet

    panel.flush_recompute()
    assert seen == [1]
    panel.flush_recompute()  # nothing pending now
    assert seen == [1]


def test_checkbox_list_repopulate_is_a_noop_when_columns_unchanged(qapp):
    from PySide6.QtWidgets import QCheckBox, QScrollArea

    graph = _graph(qapp)
    cf = graph.create_node(qt_type_for("column_filter"), name="cf")
    panel = OptionsPanel()
    panel.show_node(cf, BY_CAT, input_columns={"a": "numeric", "b": "numeric"})

    boxes_before = panel._params_host.findChild(QScrollArea).findChildren(QCheckBox)
    panel.set_input_columns({"a": "numeric", "b": "numeric"})  # same set
    boxes_after = panel._params_host.findChild(QScrollArea).findChildren(QCheckBox)
    # identical widget objects -> the list was not rebuilt
    assert boxes_before == boxes_after


def test_dtype_filter_has_four_fixed_tickboxes(qapp):
    from PySide6.QtWidgets import QCheckBox, QScrollArea

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("dtype_filter"), name="dt")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns=None)

    boxes = panel._params_host.findChild(QScrollArea).findChildren(QCheckBox)
    assert [b.text() for b in boxes] == ["str", "category", "numeric", "other"]
    boxes[2].setChecked(True)
    assert node.get_property("kinds") == "numeric"


# -- grapher "colour by" section -------------------------------------


def _grapher(qapp, cols):
    graph = _graph(qapp)
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    panel = OptionsPanel()
    panel.show_node(plot, BY_CAT, input_columns=cols)
    return panel, plot


def test_grapher_color_by_is_a_single_picker_with_a_none_clear_row(qapp):
    panel, plot = _grapher(qapp, {"team": "categorical", "score": "numeric"})

    combo = panel._field_widgets["color_by"]._combo
    assert [combo.itemText(i) for i in range(combo.count())] == ["None", "score", "team"]

    combo.setCurrentText("team")
    assert plot.get_property("color_by") == "team"
    combo.activated.emit(0)  # the "None" row clears the field
    assert plot.get_property("color_by") == ""


def test_grapher_mark_colour_field_has_a_choose_button(qapp):
    from PySide6.QtWidgets import QPushButton

    panel, _plot = _grapher(qapp, None)

    combo = panel._field_widgets["mark_color"]._combo
    assert combo.currentText() == "darkblue"
    assert "darkblue" in [combo.itemText(i) for i in range(combo.count())]
    row = panel._field_widgets["mark_color"]
    assert any(b.text() == "Choose..." for b in row.findChildren(QPushButton))


def test_grapher_colour_section_visibility_follows_color_by(qapp):
    panel, _plot = _grapher(qapp, {"team": "categorical"})
    rows = _rows(panel)
    # nothing chosen -> fixed mark colour visible, colormap hidden
    assert rows["mark color"] is True
    assert rows["colormap"] is False

    panel._field_widgets["color_by"]._combo.setCurrentText("team")
    rows = _rows(panel)
    assert rows["mark color"] is False
    assert rows["colormap"] is True


def test_grapher_colormap_options_follow_the_color_by_column_type(qapp):
    panel, _plot = _grapher(qapp, {"team": "categorical", "score": "numeric"})
    cmap = panel._reactive_choices["colormap"][0]

    panel._field_widgets["color_by"]._combo.setCurrentText("team")
    assert "tab10" in [cmap.itemText(i) for i in range(cmap.count())]

    panel._field_widgets["color_by"]._combo.setCurrentText("score")
    got = [cmap.itemText(i) for i in range(cmap.count())]
    assert "viridis" in got and "tab10" not in got


def test_grapher_mark_size_row_follows_the_kind(qapp):
    panel, _plot = _grapher(qapp, None)
    rows = _rows(panel)
    assert rows["point size"] is True and rows["line width"] is False

    panel._field_widgets["kind"].setCurrentText("line")
    rows = _rows(panel)
    assert rows["point size"] is False and rows["line width"] is True


def test_grapher_shape_channel_adapts_to_the_shape_by_column(qapp):
    panel, _plot = _grapher(qapp, {"team": "categorical", "score": "numeric"})
    rows = _rows(panel)
    # scatter + no shape-by -> fixed marker shape shown, shape map hidden
    assert rows["marker shape"] is True and rows["shape map"] is False

    # discrete shape-by -> the shape-series ("shape map") picker
    panel._field_widgets["shape_by"]._combo.setCurrentText("team")
    rows = _rows(panel)
    assert rows["marker shape"] is False and rows["shape map"] is True

    # continuous shape-by -> neither (shape keeps its fixed value); a note
    panel._field_widgets["shape_by"]._combo.setCurrentText("score")
    rows = _rows(panel)
    assert rows["marker shape"] is False and rows["shape map"] is False


def test_grapher_size_channel_adapts_to_the_size_by_column_and_kind(qapp):
    panel, _plot = _grapher(qapp, {"team": "categorical", "score": "numeric"})
    rows = _rows(panel)
    assert rows["point size"] is True and rows["size min"] is False

    panel._field_widgets["size_by"]._combo.setCurrentText("score")
    rows = _rows(panel)
    assert rows["point size"] is False  # fixed size gives way to the range
    assert rows["size min"] is True and rows["size max"] is True

    panel._field_widgets["kind"].setCurrentText("line")
    rows = _rows(panel)
    assert rows["size min"] is False and rows["width min"] is True


def test_grapher_alpha_channel_uses_sliders(qapp):
    from PySide6.QtWidgets import QSlider

    panel, plot = _grapher(qapp, {"team": "categorical"})
    rows = _rows(panel)
    assert rows["alpha"] is True and rows["alpha min"] is False

    slider = panel._field_widgets["alpha"].findChild(QSlider)
    assert slider is not None
    slider.setValue(slider.value() - 10)  # nudge the fixed alpha down
    assert plot.get_property("alpha") < 0.9

    panel._field_widgets["alpha_by"]._combo.setCurrentText("team")
    rows = _rows(panel)
    assert rows["alpha"] is False and rows["alpha min"] is True and rows["alpha max"] is True


def test_grapher_colormap_survives_a_form_rebuild(qapp):
    # Regression: reselecting the node used to reset the colormap combo
    # to the first option ("tab10") and overwrite the saved value.
    panel, plot = _grapher(qapp, {"team": "categorical"})
    panel._field_widgets["color_by"]._combo.setCurrentText("team")

    cmap = panel._reactive_choices["colormap"][0]
    cmap.setCurrentText("Set2")
    assert plot.get_property("colormap") == "Set2"

    panel.show_node(plot, BY_CAT, input_columns={"team": "categorical"})  # deselect+reselect
    assert plot.get_property("colormap") == "Set2"
    assert panel._reactive_choices["colormap"][0].currentText() == "Set2"


def test_grapher_bar_mode_needs_bar_kind_and_a_colour_by_column(qapp):
    panel, _plot = _grapher(qapp, {"team": "categorical"})
    assert _rows(panel)["bar mode"] is False  # scatter, no colour-by

    panel._field_widgets["kind"].setCurrentText("bar")
    assert _rows(panel)["bar mode"] is False  # bar, but still no colour-by

    panel._field_widgets["color_by"]._combo.setCurrentText("team")
    assert _rows(panel)["bar mode"] is True  # bar + colour-by -> shown

    panel._field_widgets["kind"].setCurrentText("line")
    assert _rows(panel)["bar mode"] is False  # colour-by set but not a bar


# -- visible_unless (Bin transformer) --------------------------------


def test_bin_count_row_hides_for_the_explicit_method(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("bin"), name="bin")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"score": "numeric"})

    rows = _rows(panel)
    assert rows["bin count"] is True and rows["cut points"] is False

    panel._field_widgets["method"].setCurrentText("explicit")
    rows = _rows(panel)
    assert rows["bin count"] is False and rows["cut points"] is True

    panel._field_widgets["method"].setCurrentText("quantile")
    assert _rows(panel)["bin count"] is True


def test_bin_labels_row_only_shows_for_string_output(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("bin"), name="bin")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"score": "numeric"})

    assert _rows(panel)["labels"] is False
    panel._field_widgets["output_type"].setCurrentText("string")
    assert _rows(panel)["labels"] is True


# -- new stat grapher nodes build a working form --------------------


def test_box_plot_options_form_has_the_colour_by_section(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("box_plot"), name="box")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"team": "categorical", "score": "numeric"})

    rows = _rows(panel)
    assert rows["single color"] is True and rows["colormap"] is False

    panel._field_widgets["color_by"]._combo.setCurrentText("team")
    rows = _rows(panel)
    assert rows["single color"] is False
    assert rows["colormap"] is True and rows["show legend"] is True


def test_histogram_bins_row_hides_for_pure_kde(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("histogram_plot"), name="hist")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"n": "numeric"})

    assert _rows(panel)["bins"] is True and _rows(panel)["stat"] is True
    panel._field_widgets["mode"].setCurrentText("kde")
    assert _rows(panel)["bins"] is False and _rows(panel)["stat"] is False


def test_heatmap_value_column_row_only_shows_for_aggregate(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("heatmap_plot"), name="hm")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"a": "categorical", "b": "categorical"})

    assert _rows(panel)["value column"] is False
    panel._field_widgets["statistic"].setCurrentText("aggregate")
    rows = _rows(panel)
    assert rows["value column"] is True and rows["aggregate"] is True


# -- rename_categories: the category-map table --------------------------


def test_rename_categories_shows_a_hint_until_data_is_available(qapp):
    from PySide6.QtWidgets import QLabel, QScrollArea

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("rename_categories"), name="rn")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"grp": "categorical"}, column_values={})

    scroll = panel._field_widgets["renames"]
    assert isinstance(scroll, QScrollArea)
    hints = [w for w in scroll.findChildren(QLabel) if "run the pipeline" in w.text()]
    assert hints


def test_rename_categories_builds_one_row_per_category_and_writes_json(qapp):
    import json

    from PySide6.QtWidgets import QLineEdit, QScrollArea

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("rename_categories"), name="rn")
    panel = OptionsPanel()
    panel.show_node(
        node,
        BY_CAT,
        input_columns={"grp": "categorical"},
        column_values={"grp": ["a", "b", "c"]},
    )
    node.set_property("column", "grp")
    panel._on_controller_changed("column")

    scroll = panel._field_widgets["renames"]
    edits = scroll.findChildren(QLineEdit)
    assert [e.placeholderText() for e in edits] == ["a", "b", "c"]  # old names as hints

    edits[0].setText("Alpha")
    edits[2].setText("Gamma")
    assert json.loads(node.get_property("renames")) == {"a": "Alpha", "c": "Gamma"}

    edits[0].clear()  # blank again -> dropped from the map
    assert json.loads(node.get_property("renames")) == {"c": "Gamma"}


def test_rename_categories_table_reacts_to_the_chosen_column(qapp):
    from PySide6.QtWidgets import QLineEdit, QScrollArea

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("rename_categories"), name="rn")
    panel = OptionsPanel()
    panel.show_node(
        node,
        BY_CAT,
        input_columns={"grp": "categorical", "team": "categorical"},
        column_values={"grp": ["a", "b"], "team": ["x", "y", "z"]},
    )
    node.set_property("column", "grp")
    panel._on_controller_changed("column")
    scroll = panel._field_widgets["renames"]
    assert len(scroll.findChildren(QLineEdit)) == 2

    node.set_property("column", "team")
    panel._on_controller_changed("column")
    assert len(scroll.findChildren(QLineEdit)) == 3


# -- model nodes: the classifier/regressor task toggle ----------------


def test_model_task_toggle_switches_the_criterion_and_class_weight_rows(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("random_forest_fit"), name="rf")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    rows = _rows(panel)
    assert rows["classifier criterion"] is True and rows["regressor criterion"] is False
    assert rows["class weight"] is True  # classifier-only

    panel._field_widgets["task"].setCurrentText("regressor")
    rows = _rows(panel)
    assert rows["classifier criterion"] is False and rows["regressor criterion"] is True
    assert rows["class weight"] is False


def test_box_plot_swarm_only_rows_follow_the_kind(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("box_plot"), name="bp")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"team": "categorical", "v": "numeric"})

    rows = _rows(panel)
    assert rows["point size"] is False and rows["swarm max points"] is False

    panel._field_widgets["kind"].setCurrentText("swarm")
    rows = _rows(panel)
    assert rows["point size"] is True and rows["swarm max points"] is True


# -- unit-interval slider widget -------------------------------------


def test_ratio_field_renders_a_slider_that_writes_a_float(qapp):
    from PySide6.QtWidgets import QSlider

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("train_test_split"), name="split")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    row = panel._field_widgets["test_size"]
    slider = row.findChild(QSlider)
    assert slider is not None
    # default 0.2 on a 0.05..0.95 / 0.01 range
    assert node.get_property("test_size") == 0.2
    slider.setValue(slider.value() + 5)
    assert abs(node.get_property("test_size") - 0.25) < 1e-6
    assert isinstance(node.get_property("test_size"), float)


def test_gradient_boosting_has_sliders_for_subsample_and_validation_fraction(qapp):
    from PySide6.QtWidgets import QSlider

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("gradient_boosting_fit"), name="gb")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT)

    for field in ("subsample", "validation_fraction"):
        assert panel._field_widgets[field].findChild(QSlider) is not None


# -- column-map table widget (combine_datetime's `mapping`) -------------


def test_combine_datetime_mapping_is_a_component_to_column_table(qapp):
    from PySide6.QtWidgets import QComboBox, QScrollArea
    import json

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("combine_datetime"), name="cd")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"yr": "numeric", "mo": "numeric"})

    scroll = panel._field_widgets["mapping"]
    assert isinstance(scroll, QScrollArea)
    combos = scroll.findChildren(QComboBox)
    assert len(combos) == 10  # one row per time component
    # first column of a row is the blank "no column" entry
    assert combos[0].itemText(0) == "—"
    assert [combos[0].itemText(i) for i in range(1, combos[0].count())] == ["mo", "yr"]

    combos[0].setCurrentText("yr")  # the "year" row
    assert json.loads(node.get_property("mapping")) == {"year": "yr"}


def test_column_map_widget_repopulates_and_keeps_selection(qapp):
    from PySide6.QtWidgets import QComboBox
    import json

    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("combine_datetime"), name="cd")
    panel = OptionsPanel()
    panel.show_node(node, BY_CAT, input_columns={"yr": "numeric"})
    combos = panel._field_widgets["mapping"].findChildren(QComboBox)
    combos[0].setCurrentText("yr")

    panel.set_input_columns({"yr": "numeric", "when": "numeric"})
    combos = panel._field_widgets["mapping"].findChildren(QComboBox)
    assert [combos[0].itemText(i) for i in range(1, combos[0].count())] == ["when", "yr"]
    assert combos[0].currentText() == "yr"  # prior pick survived the refresh
    assert json.loads(node.get_property("mapping")) == {"year": "yr"}
