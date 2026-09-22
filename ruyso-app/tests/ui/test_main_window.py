"""
Tests for the main window shell (Phase 1): the three-tab structure,
per-tab menu enable/disable, the live dark/light theme toggle, and the
Node menu's create/delete actions.

These exercise only assembly and state logic -- no pixels are checked;
the suite runs headless under QT_QPA_PLATFORM=offscreen.
"""

import pytest

from ruyso_app.engine.errors import NodeError
from ruyso_app.engine.scheduler import RunReport
from ruyso_app.ui import theme


def _boom(node_id: str, field: str = "") -> NodeError:
    """A stand-in failure, as the scheduler would report one."""
    return NodeError(
        node_id=node_id, node_type="sort", kind="runtime",
        title="boom", field=field or None, raw="Traceback ... boom",
    )
from ruyso_app.ui.dashboard_page import DashboardPage
from ruyso_app.ui.main_window import MainWindow
from ruyso_app.ui.options_panel import OptionsPanel
from ruyso_app.ui.pipeline_page import PipelinePage
from ruyso_app.ui.table_page import TablePage


@pytest.fixture(autouse=True)
def _reset_theme():
    theme.set_current_theme("dark")
    yield
    theme.set_theme_mode("system")


@pytest.fixture
def window(qapp):
    return MainWindow()


def test_window_has_three_pages_in_spec_order(window):
    pages = [window._stack.widget(i) for i in range(window._stack.count())]
    assert [type(p) for p in pages] == [PipelinePage, TablePage, DashboardPage]
    assert window.current_tab() == "pipeline"


def test_switching_tab_updates_the_stacked_page(window):
    window._tab_bar.set_current_key("table")
    assert window._stack.currentIndex() == 1
    window._tab_bar.set_current_key("dashboard")
    assert window._stack.currentIndex() == 2


def test_node_menu_only_enabled_on_pipeline_tab(window):
    assert window._node_menu.isEnabled()
    window._tab_bar.set_current_key("table")
    assert not window._node_menu.isEnabled()
    window._tab_bar.set_current_key("pipeline")
    assert window._node_menu.isEnabled()


def test_dashboard_menu_only_enabled_on_dashboard_tab(window):
    assert not window._dashboard_menu.isEnabled()
    window._tab_bar.set_current_key("dashboard")
    assert window._dashboard_menu.isEnabled()


def test_options_panel_present_on_pipeline_and_dashboard_not_table(window):
    assert isinstance(window._pipeline_page.options_panel, OptionsPanel)
    assert isinstance(window._dashboard_page.options_panel, OptionsPanel)
    assert not hasattr(window._table_page, "options_panel")


def test_setting_theme_mode_repaints_canvas_background(window):
    window._set_theme_mode("dark")
    before = window._canvas.graph.background_color()
    window._set_theme_mode("light")
    after = window._canvas.graph.background_color()
    assert theme.current_theme().name == "light"
    assert tuple(before) != tuple(after)
    assert tuple(after) == theme.LIGHT_THEME.canvas_background


def test_setting_theme_mode_recolors_existing_nodes(window):
    window._on_pick_macro_type("loading")  # creates a "loading" category node
    node = window._canvas.graph.all_nodes()[0]
    # Node color is palette-independent by design, so it should stay the
    # category color across a theme change (and definitely not crash).
    window._set_theme_mode("light")
    assert node.color() == theme.color_for_category("loading")


def test_view_menu_has_a_three_way_theme_submenu(window):
    view_menu = next(
        a.menu() for a in window.menuBar().actions() if a.text() == "View"
    )
    theme_menu = next(a.menu() for a in view_menu.actions() if a.text() == "Theme")
    labels = [a.text() for a in theme_menu.actions()]
    assert labels == ["System", "Dark", "Light"]
    assert all(a.isCheckable() for a in theme_menu.actions())


def test_new_node_action_creates_a_node(window):
    assert window._canvas.graph.all_nodes() == []
    window._on_pick_macro_type("loading")
    assert len(window._canvas.graph.all_nodes()) == 1


def test_delete_selected_nodes_removes_them(window):
    window._on_pick_macro_type("loading")
    window._canvas.graph.select_all()
    window._on_delete_selected_nodes()
    assert window._canvas.graph.all_nodes() == []


def test_copy_paste_selected_node_preserves_params(window):
    graph = window._canvas.graph
    window._on_pick_macro_type("loading")
    original = graph.all_nodes()[0]
    original.set_property("filepath", "/tmp/data.csv")
    window._select_only(original)

    window._on_copy_nodes()
    window._on_paste_nodes()

    nodes = graph.all_nodes()
    assert len(nodes) == 2
    pasted = next(n for n in nodes if n is not original)
    assert pasted.get_property("filepath") == "/tmp/data.csv"
    # the fresh copy is the one now shown in the Options panel
    assert window._options.current_node() is pasted


def test_duplicate_selected_node_adds_a_copy(window):
    graph = window._canvas.graph
    window._on_pick_macro_type("loading")
    window._select_only(graph.all_nodes()[0])

    window._on_duplicate_nodes()

    assert len(graph.all_nodes()) == 2


def test_pipeline_menu_is_always_enabled_and_run_has_f5(window):
    pipeline_menu = next(
        a.menu() for a in window.menuBar().actions() if a.text() == "Pipeline"
    )
    assert pipeline_menu.isEnabled()
    window._tab_bar.set_current_key("dashboard")
    assert pipeline_menu.isEnabled()
    assert window._run_action.shortcut().toString() == "F5"


def test_picking_a_macro_type_creates_and_selects_a_node_and_opens_options(window):
    window._on_pick_macro_type("transform")
    nodes = window._canvas.graph.all_nodes()
    assert len(nodes) == 1
    assert nodes[0].selected()
    assert window._pipeline_page.options_panel.current_node() is nodes[0]


def test_micro_type_change_recreates_the_underlying_node(window):
    window._on_pick_macro_type("transform")
    node = window._canvas.graph.all_nodes()[0]
    original_type = type(node).CORE_NODE_TYPE
    other_type = "scaler" if original_type == "drop_na" else "drop_na"

    window._pipeline_page.options_panel.node_type_change_requested.emit(other_type)

    remaining = window._canvas.graph.all_nodes()
    assert len(remaining) == 1
    assert type(remaining[0]).CORE_NODE_TYPE == other_type


def test_pick_macro_type_places_node_at_given_position(window):
    window._on_pick_macro_type("loading", [140.0, -25.0])
    node = window._canvas.graph.all_nodes()[0]
    assert node.pos() == [140.0, -25.0]


def test_retype_via_options_updates_the_node_name(window):
    window._on_pick_macro_type("transform")
    node = window._canvas.graph.all_nodes()[0]
    start_type = type(node).CORE_NODE_TYPE
    other = "scaler" if start_type == "drop_na" else "drop_na"

    window._on_node_type_change(other)

    new_node = window._canvas.graph.all_nodes()[0]
    assert type(new_node).CORE_NODE_TYPE == other
    expected = other.replace("_", " ").title()
    assert expected in new_node.name()


def test_tab_band_run_button_runs_the_pipeline_and_drives_progress(window, tmp_path):
    import pandas as pd

    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_csv(csv, index=False)
    window._on_pick_macro_type("loading")
    loader = window._canvas.graph.all_nodes()[0]
    loader.set_property("filepath", str(csv))

    window._tab_bar.run_button.click()  # the button, not the menu action
    assert not window._tab_bar.run_button.isEnabled()  # disabled while running
    window._worker.wait(5000)
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()

    assert window._tab_bar.progress.property("state") == "success"
    assert window._tab_bar.progress.percent_text() == "100%"
    assert window._tab_bar.run_button.isEnabled()  # re-enabled after


def test_run_progress_bar_is_visible_before_any_run(window):
    assert not window._tab_bar.progress.isHidden()
    assert window._tab_bar.progress.property("state") == "idle"


def test_auto_pill_tracks_auto_run_state(window):
    pill = window._tab_bar.auto_pill
    assert pill.state() == "idle"  # nothing has auto-run yet

    window._auto_run.started.emit()
    assert pill.state() == "running"

    window._on_auto_run_finished(RunReport())
    assert pill.state() == "ok"

    window._on_auto_run_finished(RunReport(errors={"some_node": _boom("some_node")}))
    assert pill.state() == "error"

    # a manual run greys it out, then it returns to the last auto state
    window._tab_bar.run_button.setEnabled(False)
    window._refresh_auto_pill()
    assert pill.state() == "idle"
    window._tab_bar.run_button.setEnabled(True)
    window._on_run_finished()
    assert pill.state() == "error"


def test_view_menu_auto_run_toggle_gates_scheduling(window):
    action = window._auto_run_action
    assert action.isCheckable() and action.isChecked()

    action.setChecked(False)  # emits toggled(False)
    assert not window._auto_run.is_user_enabled()
    assert window._tab_bar.auto_pill.state() == "idle"

    action.setChecked(True)
    assert window._auto_run.is_user_enabled()


def test_colormaps_menu_has_designer_and_manager(window):
    menu = next(m.menu() for m in window.menuBar().actions() if m.text() == "Colormaps")
    labels = {a.text() for a in menu.actions()}
    assert labels == {"Colormap Designer...", "Colormap Manager..."}


def test_colormaps_changed_refreshes_open_colormap_dropdowns(window):
    from ruyso_app.engine import colormaps as cm

    window._on_pick_macro_type("grapher")
    node = window._graph.all_nodes()[0]
    from ruyso_app.ui.node_editing import change_node_micro_type

    change_node_micro_type(window._graph, node, "confusion_matrix_plot")
    window._select_only(window._graph.all_nodes()[0])
    combo = window._options._field_widgets["colormap"]
    assert "Ocean" not in [combo.itemText(i) for i in range(combo.count())]

    cm.upsert("Ocean", {"kind": "continuous", "stops": [[0.0, "#012"], [1.0, "#9ef"]]})
    try:
        window._on_colormaps_changed()
        assert "Ocean" in [combo.itemText(i) for i in range(combo.count())]
    finally:
        cm.save_store({"custom": {}, "lists": {}})
        cm._last_signature = None


def test_new_node_starts_with_a_pending_status_dot(window):
    window._on_pick_macro_type("loading")
    node = window._graph.all_nodes()[0]
    assert window._node_status.status_of(node.name()) == "pending"


def test_streamed_node_status_updates_the_controller(window):
    window._on_pick_macro_type("loading")
    name = window._graph.all_nodes()[0].name()

    window._auto_run.node_status.emit(name, "running")
    assert window._node_status.status_of(name) == "running"
    window._auto_run.node_status.emit(name, "error")
    assert window._node_status.status_of(name) == "error"


def test_clicking_auto_pill_toggles_auto_run_and_stays_in_sync_with_the_menu(window):
    pill = window._tab_bar.auto_pill
    action = window._auto_run_action
    assert window._auto_run.is_user_enabled() and action.isChecked()

    pill.clicked.emit()  # pause
    assert not window._auto_run.is_user_enabled()
    assert not action.isChecked()

    pill.clicked.emit()  # resume
    assert window._auto_run.is_user_enabled()
    assert action.isChecked()


def test_new_node_actions_have_cmd_p_chord_shortcuts(window):
    new_node_menu = next(
        a.menu() for a in window._node_menu.actions() if a.text() == "New Node"
    )
    shortcuts = {a.text(): a.shortcut().toString() for a in new_node_menu.actions()}
    assert shortcuts[theme.MACRO_TYPE_LABELS["loading"]] == "Ctrl+P, L"
    assert shortcuts[theme.MACRO_TYPE_LABELS["grapher"]] == "Ctrl+P, G"


def test_changing_macro_type_recreates_node_in_new_category(window):
    window._on_pick_macro_type("loading")
    node = window._canvas.graph.all_nodes()[0]
    assert type(node).CORE_NODE_CLASS.category == "loading"

    # Emulate the Options panel asking for a transformer.
    window._on_node_type_change("drop_na")

    remaining = window._canvas.graph.all_nodes()
    assert len(remaining) == 1
    assert type(remaining[0]).CORE_NODE_CLASS.category == "transform"


def test_switching_to_table_tab_populates_the_navigator_from_the_canvas(window):
    window._on_pick_macro_type("loading")
    window._on_pick_macro_type("transform")

    window._tab_bar.set_current_key("table")

    labels = [
        window._table_page._nav.item(i).text()
        for i in range(window._table_page._nav.count())
    ]
    assert len(labels) == 2  # one table each for the loader and the transformer


def test_dashboard_menu_has_add_title_and_text_box_actions(window):
    labels = [a.text() for a in window._dashboard_menu.actions()]
    assert "Add Title" in labels
    assert "Add Text Box" in labels
    assert "Exporter..." in labels


def test_add_to_dashboard_context_action_wires_an_export_node(window):
    window._on_pick_macro_type("grapher")
    plot = window._canvas.graph.all_nodes()[0]

    window._on_ctx_add_to_dashboard(window._graph, plot)

    types = {type(n).CORE_NODE_TYPE for n in window._canvas.graph.all_nodes()}
    assert "export_to_dashboard" in types
    export = next(
        n for n in window._canvas.graph.all_nodes()
        if type(n).CORE_NODE_TYPE == "export_to_dashboard"
    )
    assert export.inputs()["figure"].connected_ports()  # wired to the plot


def test_run_populates_a_dashboard_block_editable_via_the_source_plot(window):
    import matplotlib.pyplot as plt

    window._on_pick_macro_type("grapher")
    plot = window._canvas.graph.all_nodes()[0]
    window._on_ctx_add_to_dashboard(window._graph, plot)
    export = next(
        n for n in window._canvas.graph.all_nodes()
        if type(n).CORE_NODE_TYPE == "export_to_dashboard"
    )

    # the export node is a sink: its figure comes from the grapher's output
    window._on_run_succeeded(RunReport(outputs={plot.name(): {"figure": plt.figure()}}))

    assert export.name() in window._dashboard_page._figure_items
    item = window._dashboard_page._figure_items[export.name()]
    # The vector art is drawn on the render thread (ui/render_queue.py).
    from ruyso_app.ui import render_queue

    assert render_queue.queue().wait_idle(15_000)
    assert item._renderer is not None  # rendered from SVG
    item.setSelected(True)

    # the dashboard Options panel is now bound to the upstream plot node
    assert window._dashboard_page.options_panel.current_node() is plot
    assert window._dashboard_page.is_editing_figure()


def test_disconnected_figure_shows_a_canvas_message_not_an_options_page(window):
    import matplotlib.pyplot as plt

    window._on_pick_macro_type("grapher")
    plot = window._canvas.graph.all_nodes()[0]
    window._on_ctx_add_to_dashboard(window._graph, plot)
    export = next(
        n for n in window._canvas.graph.all_nodes()
        if type(n).CORE_NODE_TYPE == "export_to_dashboard"
    )
    window._on_run_succeeded(RunReport(outputs={plot.name(): {"figure": plt.figure()}}))

    plot.outputs()["figure"].disconnect_from(export.inputs()["figure"])
    item = window._dashboard_page._figure_items[export.name()]
    item.setSelected(True)

    assert window._dashboard_page._view.overlay.text() != ""  # canvas overlay
    assert not window._dashboard_page.is_editing_figure()


def test_editing_a_source_param_flags_its_dashboard_figure_modified(window):
    import matplotlib.pyplot as plt

    window._on_pick_macro_type("grapher")
    plot = window._canvas.graph.all_nodes()[0]
    window._on_ctx_add_to_dashboard(window._graph, plot)
    export = next(
        n for n in window._canvas.graph.all_nodes()
        if type(n).CORE_NODE_TYPE == "export_to_dashboard"
    )
    # first sync: fresh, not stale
    window._dashboard_page.sync_figures(
        window._graph, {plot.name(): {"figure": plt.figure()}}, set(), set()
    )
    item = window._dashboard_page._figure_items[export.name()]
    assert not item.is_stale()

    # a later (auto-)run reports the source plot as modified since the run
    window._dashboard_page.sync_figures(
        window._graph, {plot.name(): {"figure": plt.figure()}},
        {plot.name()}, set(),
    )
    assert item.is_stale()


def test_every_macro_type_has_an_enabled_new_node_action(window):
    # Every macro type now has at least one concrete node, so every
    # New Node entry is present and enabled.
    new_node_menu = None
    for action in window._node_menu.actions():
        if action.text() == "New Node":
            new_node_menu = action.menu()
    labels = {a.text(): a.isEnabled() for a in new_node_menu.actions()}
    for label in theme.MACRO_TYPE_LABELS.values():
        assert labels.get(label) is True


# -- undo / redo ---------------------------------------------------------

from ruyso_app.ui.node_factory import qt_type_for  # noqa: E402


def test_undo_and_redo_step_through_real_edits(qapp):
    window = MainWindow()
    graph = window._canvas.graph

    load = graph.create_node(qt_type_for("example_data"), name="load")
    window._select_only(load)
    load.set_property("dataset", "seaborn/tips")
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")

    window._undo_action.trigger()
    assert len(graph.all_nodes()) == 1  # the plot node is gone
    window._undo_action.trigger()
    assert load.get_property("dataset") != "seaborn/tips"

    window._redo_action.trigger()
    assert load.get_property("dataset") == "seaborn/tips"
    window._redo_action.trigger()
    assert len(graph.all_nodes()) == 2
    window.close()


def test_selecting_a_node_does_not_land_on_the_undo_stack(qapp):
    """Otherwise the first Ctrl+Z presses would only undo selections."""
    window = MainWindow()
    graph = window._canvas.graph
    stack = graph.undo_stack()

    node = graph.create_node(qt_type_for("sort"), name="s")
    before = stack.count()
    window._select_only(node)

    assert stack.count() == before
    window.close()


def test_undo_resyncs_the_options_panel(qapp):
    window = MainWindow()
    graph = window._canvas.graph

    node = graph.create_node(qt_type_for("sort"), name="s")
    window._select_only(node)

    # Edit through the widget, the way a person would.
    window._options._field_widgets["na_position"].setCurrentText("first")
    assert node.get_property("na_position") == "first"

    window._undo_action.trigger()
    assert node.get_property("na_position") == "last"
    # The form is rebuilt, so the box shows the reverted value rather
    # than the one that was just undone.
    assert window._options._field_widgets["na_position"].currentText() == "last"
    window.close()


def test_undo_actions_disable_at_the_ends_of_history(qapp):
    window = MainWindow()
    graph = window._canvas.graph

    assert window._undo_action.isEnabled() is False
    graph.create_node(qt_type_for("sort"), name="s")
    assert window._undo_action.isEnabled() is True
    assert window._redo_action.isEnabled() is False

    window._undo_action.trigger()
    assert window._undo_action.isEnabled() is False
    assert window._redo_action.isEnabled() is True
    window.close()


def test_editing_a_field_does_not_rebuild_the_form_underneath_it(qapp):
    """The resync must hang off undo/redo, not off every stack push."""
    window = MainWindow()
    graph = window._canvas.graph

    node = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    window._select_only(node)
    combo = window._options._field_widgets["mark_color"]._combo
    combo.setCurrentText("#ff8800")

    # The very same widget object must still be alive and hold the value.
    assert combo.currentText() == "#ff8800"
    assert node.get_property("mark_color") == "#ff8800"
    assert window._options._field_widgets["mark_color"]._combo is combo
    window.close()


def test_clicking_a_figure_selects_its_node_and_keeps_the_panel(qapp):
    """Opening a figure used to clear the selection and blank the panel."""
    window = MainWindow()
    graph = window._canvas.graph
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    other = graph.create_node(qt_type_for("sort"), name="s")
    window._select_only(other)

    window._preview_overlay.node_activated.emit(plot.id)

    assert [n.name() for n in graph.selected_nodes()] == ["plot"]
    assert window._options.current_node() is plot
    window.close()


# -- document lifecycle --------------------------------------------------

from ruyso_app.engine import settings as app_settings  # noqa: E402


@pytest.fixture
def _restore_settings():
    yield
    app_settings.reset()
    app_settings.set("general.confirm_on_close", False)


def test_a_fresh_window_is_untitled_and_unmodified(qapp):
    window = MainWindow()
    assert window.windowTitle() == "ruyso-app - Untitled"
    assert not window.is_modified()
    window.close()


def test_editing_marks_the_window_modified(qapp):
    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("sort"), name="s")

    assert window.is_modified()
    assert window.windowTitle().endswith("•")
    window.close()


def test_saving_clears_the_modified_marker(qapp, tmp_path, _restore_settings):
    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("sort"), name="s")
    assert window.is_modified()

    window._mark_saved(str(tmp_path / "p.json"))

    assert not window.is_modified()
    assert window.windowTitle() == "ruyso-app - p.json"
    assert app_settings.get("general.last_pipeline") == str(tmp_path / "p.json")
    window.close()


def test_opening_a_file_names_the_window_and_starts_it_clean(qapp, tmp_path, _restore_settings):
    path = tmp_path / "saved.json"
    path.write_text('{"nodes": [{"id": "s", "node_type": "sort", "params": {}}],'
                    ' "connections": []}')
    window = MainWindow()
    window._open_pipeline_file(str(path))

    assert window.windowTitle() == "ruyso-app - saved.json"
    assert not window.is_modified()
    window.close()


def test_the_prompt_is_skipped_when_there_is_nothing_to_lose(qapp, _restore_settings):
    app_settings.set("general.confirm_on_close", True)
    window = MainWindow()
    assert window.confirm_discard_changes() is True  # no modal appears
    window.close()


def test_discarding_unsaved_changes_is_confirmed(qapp, monkeypatch, _restore_settings):
    from PySide6.QtWidgets import QMessageBox

    app_settings.set("general.confirm_on_close", True)
    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("sort"), name="s")

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    assert window.confirm_discard_changes() is False  # the close is called off

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    assert window.confirm_discard_changes() is True

    app_settings.set("general.confirm_on_close", False)
    window.close()


def test_the_prompt_can_be_turned_off(qapp, monkeypatch, _restore_settings):
    from PySide6.QtWidgets import QMessageBox

    app_settings.set("general.confirm_on_close", False)
    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("sort"), name="s")

    def _fail(*_a, **_k):
        raise AssertionError("no dialog should be raised")

    monkeypatch.setattr(QMessageBox, "question", _fail)
    assert window.confirm_discard_changes() is True
    window.close()


def test_the_theme_choice_is_remembered(qapp, _restore_settings):
    window = MainWindow()
    window._set_theme_mode("light")
    assert app_settings.get("appearance.theme") == "light"
    window.close()


def test_the_auto_run_switch_is_remembered(qapp, _restore_settings):
    window = MainWindow()
    window._on_toggle_auto_run(False)
    assert app_settings.get("execution.auto_run") is False
    window.close()


def test_a_large_result_is_summarised_in_the_log(qapp, _restore_settings):
    import pandas as pd

    window = MainWindow()
    frame = pd.DataFrame({"a": range(500), "b": range(500)})
    window._on_run_succeeded(RunReport(outputs={"load": {"df": frame}}))

    text = window._pipeline_page.log.toPlainText()
    assert "DataFrame(500 rows x 2 cols)" in text
    window.close()


def test_the_verbose_preference_prints_the_whole_thing(qapp, _restore_settings):
    import pandas as pd

    app_settings.set("advanced.verbose_log", True)
    window = MainWindow()
    window._on_run_succeeded(RunReport(outputs={"load": {"df": pd.DataFrame({"a": [1, 2]})}}))

    text = window._pipeline_page.log.toPlainText()
    assert "DataFrame(" not in text  # the real repr, not the summary
    window.close()


# -- the Problems panel replaces the modal -------------------------------


def test_a_failing_run_fills_the_panel_instead_of_raising_a_dialog(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    def _fail(*_a, **_k):
        raise AssertionError("a run failure must not open a modal")

    monkeypatch.setattr(QMessageBox, "critical", _fail)

    window = MainWindow()
    window._on_run_succeeded(RunReport(errors={"Sort 1": _boom("Sort 1", "columns")}))

    assert window._pipeline_page.problems.count() == 1
    assert window._tab_bar.problems_chip.count() == 1
    window.close()


def test_a_run_that_cannot_start_becomes_one_pipeline_wide_row(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from ruyso_app.ui.error_panel import GRAPH_PROBLEM

    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: pytest.fail("no modal expected")
    )
    window = MainWindow()
    window._on_run_failed("Pipeline graph contains a cycle.")

    rows = window._pipeline_page.problems.rows()
    assert len(rows) == 1
    assert rows[0].error.node_id == GRAPH_PROBLEM
    assert "cycle" in rows[0].error.title
    window.close()


def test_blocked_nodes_do_not_get_rows_of_their_own(qapp):
    """One bad parameter can block eight steps; eight rows would bury it."""
    window = MainWindow()
    window._on_run_succeeded(
        RunReport(
            errors={"Sort 1": _boom("Sort 1")},
            blocked={"Plot 1": "Sort 1", "Export 1": "Sort 1"},
        )
    )

    assert [r.error.node_id for r in window._pipeline_page.problems.rows()] == ["Sort 1"]
    window.close()


def test_a_clean_run_empties_the_panel_and_hides_the_chip(qapp):
    window = MainWindow()
    window._on_run_succeeded(RunReport(errors={"Sort 1": _boom("Sort 1")}))
    assert window._tab_bar.problems_chip.count() == 1

    window._on_run_succeeded(RunReport(outputs={"Sort 1": {"df": None}}))

    assert window._pipeline_page.problems.count() == 0
    assert window._tab_bar.problems_chip.isHidden()
    window.close()


def test_auto_run_failures_reach_the_panel_too(qapp):
    """The panel is the pipeline's current state, not the last Run's."""
    window = MainWindow()
    window._on_auto_run_finished(RunReport(errors={"Sort 1": _boom("Sort 1")}))

    assert window._pipeline_page.problems.count() == 1
    window.close()


def test_activating_a_problem_selects_its_node_and_marks_the_field(qapp):
    window = MainWindow()
    node = window._canvas.graph.create_node(qt_type_for("sort"), name="Sort 1")
    window._on_run_succeeded(RunReport(errors={"Sort 1": _boom("Sort 1", "columns")}))

    window._on_problem_activated("Sort 1", "columns")

    assert window._canvas.graph.selected_nodes() == [node]
    assert window._options.current_node() is node
    assert window._options.field_errors() == {"columns"}
    window.close()


def test_editing_the_marked_field_clears_its_outline(qapp):
    window = MainWindow()
    node = window._canvas.graph.create_node(qt_type_for("sort"), name="Sort 1")
    window._on_run_succeeded(RunReport(errors={"Sort 1": _boom("Sort 1", "na_position")}))
    window._on_problem_activated("Sort 1", "na_position")
    assert window._options.field_errors() == {"na_position"}

    node.set_property("na_position", "first")

    assert window._options.field_errors() == set()
    window.close()


def test_activating_a_problem_for_a_deleted_node_is_harmless(qapp):
    window = MainWindow()
    window._on_problem_activated("gone", "columns")  # must not raise
    window.close()


def test_saving_still_uses_a_modal(qapp, monkeypatch, tmp_path):
    """A failed Save reported only in a panel on another tab loses work."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    shown: list[str] = []
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "x.json"), "")
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda _p, title, _m: shown.append(title)
    )
    window = MainWindow()
    monkeypatch.setattr(
        window, "_build_pipeline_or_raise",
        lambda: (_ for _ in ()).throw(RuntimeError("disk on fire")),
    )
    window._on_save_pipeline()

    assert shown == ["Could not save pipeline"]
    window.close()


# -- toolboxes -----------------------------------------------------------

from ruyso_app.core import toolboxes as _toolboxes  # noqa: E402


def _geo_pipeline_file(tmp_path):
    import json

    path = tmp_path / "geo.json"
    path.write_text(
        json.dumps(
            {
                "nodes": [{"id": "buf", "node_type": "geo_buffer", "params": {}}],
                "connections": [],
            }
        )
    )
    return str(path)


def test_the_window_reports_which_nodes_are_in_use(qapp, _restore_settings):
    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("sort"), name="Sort 1")
    window._canvas.graph.create_node(qt_type_for("sort"), name="Sort 2")

    assert window._nodes_in_use()["sort"] == ["Sort 1", "Sort 2"]
    window.close()


def test_switching_a_family_off_disables_its_menu_entry(qapp, _restore_settings):
    window = MainWindow()
    assert window._macro_actions["statistics"].isEnabled()

    app_settings.set(_toolboxes.SETTING, ["export", "ml", "geo"])
    window._on_preferences_applied()

    assert not window._macro_actions["statistics"].isEnabled()
    assert window._macro_actions["transform"].isEnabled()  # essential
    window.close()


def test_a_pipeline_needing_a_switched_off_family_is_spotted(qapp, tmp_path, _restore_settings):
    from ruyso_app.engine.serialization import load_graph

    app_settings.set(_toolboxes.SETTING, ["export"])  # geo off
    window = MainWindow()
    pipeline = load_graph(_geo_pipeline_file(tmp_path))

    assert [t.key for t in window._missing_toolboxes(pipeline)] == ["geo"]
    window.close()


def test_spotting_it_gives_the_same_answer_twice(qapp, tmp_path, _restore_settings):
    """
    Working out which family owns a node type imports every module, so
    an answer based on "is it in the registry" would be true the first
    time and false the second -- and false again after anything else
    (opening Preferences) had imported them.
    """
    from ruyso_app.engine.serialization import load_graph

    app_settings.set(_toolboxes.SETTING, ["export"])
    window = MainWindow()
    pipeline = load_graph(_geo_pipeline_file(tmp_path))

    first = [t.key for t in window._missing_toolboxes(pipeline)]
    second = [t.key for t in window._missing_toolboxes(pipeline)]

    assert first == second == ["geo"]
    window.close()


def test_opening_such_a_pipeline_offers_to_switch_it_back_on(
    qapp, tmp_path, monkeypatch, _restore_settings
):
    from PySide6.QtWidgets import QMessageBox

    asked: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: (asked.append(a[2]), QMessageBox.Yes)[1],
    )
    app_settings.set(_toolboxes.SETTING, ["export"])
    window = MainWindow()
    window._open_pipeline_file(_geo_pipeline_file(tmp_path))

    assert "Geo / maps" in asked[0]
    assert "geo" in app_settings.get(_toolboxes.SETTING)
    assert [n.name() for n in window._canvas.graph.all_nodes()] == ["buf"]
    window.close()


def test_declining_leaves_the_preference_and_the_canvas_alone(
    qapp, tmp_path, monkeypatch, _restore_settings
):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    app_settings.set(_toolboxes.SETTING, ["export"])
    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("sort"), name="Keep Me")

    window._open_pipeline_file(_geo_pipeline_file(tmp_path))

    assert "geo" not in app_settings.get(_toolboxes.SETTING)
    assert [n.name() for n in window._canvas.graph.all_nodes()] == ["Keep Me"]
    window.close()


def test_an_ordinary_pipeline_asks_nothing(qapp, tmp_path, monkeypatch, _restore_settings):
    import json

    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **k: pytest.fail("no prompt expected")
    )
    path = tmp_path / "plain.json"
    path.write_text(
        json.dumps({"nodes": [{"id": "s", "node_type": "sort", "params": {}}],
                    "connections": []})
    )
    window = MainWindow()
    window._open_pipeline_file(str(path))

    assert [n.name() for n in window._canvas.graph.all_nodes()] == ["s"]
    window.close()


# -- the Dashboard's own history ----------------------------------------


def test_every_dashboard_menu_entry_works(qapp):
    """The menu called add_text_block; the method is add_text_item, so
    both entries raised AttributeError the moment they were used."""
    window = MainWindow()
    for action in window._dashboard_menu.actions():
        if action.menu() or action.isSeparator() or action.text() == "Exporter...":
            continue
        action.trigger()  # must not raise
    assert window._dashboard_page.blocks()
    window.close()


def test_the_add_shape_menu_offers_every_kind(qapp):
    from ruyso_app.ui.dashboard_shapes import SHAPE_KINDS, SHAPE_LABELS

    window = MainWindow()
    shape_menu = next(
        a.menu() for a in window._dashboard_menu.actions() if a.text() == "Add Shape"
    )
    labels = [a.text() for a in shape_menu.actions()]

    assert labels == [SHAPE_LABELS[k] for k in SHAPE_KINDS]
    shape_menu.actions()[0].trigger()
    assert window._dashboard_page.blocks()
    window.close()


def test_undo_follows_the_tab_in_front(qapp):
    """Otherwise Cmd+Z on the Dashboard quietly undoes a pipeline edit."""
    window = MainWindow()
    page = window._dashboard_page

    window._tab_bar.set_current_key("pipeline")
    assert window.active_undo_stack() is window._canvas.graph.undo_stack()

    window._tab_bar.set_current_key("dashboard")
    assert window.active_undo_stack() is page.undo_stack()
    window.close()


def test_undoing_on_the_dashboard_leaves_the_pipeline_alone(qapp):
    window = MainWindow()
    node = window._canvas.graph.create_node(qt_type_for("sort"), name="Sort 1")
    page = window._dashboard_page
    page.add_shape("rectangle")

    window._tab_bar.set_current_key("dashboard")
    window._undo_action.trigger()

    assert page.blocks() == []  # the shape went
    assert node in window._canvas.graph.all_nodes()  # the node stayed
    window.close()


def test_the_undo_action_reflects_the_active_tabs_history(qapp):
    window = MainWindow()
    window._tab_bar.set_current_key("dashboard")
    assert not window._undo_action.isEnabled()  # nothing done here yet

    window._dashboard_page.add_shape("ellipse")
    assert window._undo_action.isEnabled()

    window._tab_bar.set_current_key("pipeline")
    assert not window._undo_action.isEnabled()  # the pipeline is untouched
    window.close()


# -- the dashboard travels with the pipeline ----------------------------


def _saved_document(window, tmp_path, name="doc.json"):
    from ruyso_app.engine.serialization import save_document
    from ruyso_app.ui.graph_bridge import canvas_to_pipeline

    path = tmp_path / name
    save_document(
        canvas_to_pipeline(window._canvas.graph),
        path,
        {"dashboard": window._dashboard_page.to_dict()},
    )
    return str(path)


def test_saving_writes_the_dashboard_into_the_pipeline_file(
    qapp, tmp_path, monkeypatch, _restore_settings
):
    import json

    from PySide6.QtWidgets import QFileDialog

    path = tmp_path / "report.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))

    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("example_data"), name="Load")
    window._dashboard_page.add_shape("arrow")
    window._on_save_pipeline()

    data = json.loads(path.read_text())
    # The canvas layout (node positions, collapsed previews) is saved
    # beside the dashboard's.
    assert sorted(data) == ["canvas", "connections", "dashboard", "nodes"]
    assert [i["type"] for i in data["dashboard"]["items"]] == ["shape"]
    window.close()


def test_dashboard_edits_mark_the_document_unsaved(qapp, _restore_settings):
    """The layout is saved to the file, so losing it is losing work."""
    window = MainWindow()
    assert not window.is_modified()

    window._dashboard_page.add_shape("rectangle")

    assert window.is_modified()
    assert window.windowTitle().endswith("•")
    window.close()


def test_saving_clears_both_histories(qapp, tmp_path, monkeypatch, _restore_settings):
    from PySide6.QtWidgets import QFileDialog

    path = tmp_path / "report.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))

    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("example_data"), name="Load")
    window._dashboard_page.add_shape("rectangle")
    window._on_save_pipeline()

    assert not window.is_modified()
    window.close()


def test_opening_restores_the_saved_layout(qapp, tmp_path, _restore_settings):
    window = MainWindow()
    window._canvas.graph.create_node(qt_type_for("example_data"), name="Load")
    shape = window._dashboard_page.add_shape("ellipse")
    shape.setPos(120, 34)
    path = _saved_document(window, tmp_path)
    window.close()

    reopened = MainWindow()
    reopened._open_pipeline_file(path)

    blocks = reopened._dashboard_page.blocks()
    assert len(blocks) == 1
    assert blocks[0].kind == "ellipse"
    assert (blocks[0].pos().x(), blocks[0].pos().y()) == (120.0, 34.0)
    assert not reopened.is_modified()  # a freshly opened document is clean
    reopened.close()


def test_opening_a_file_with_no_dashboard_clears_the_canvas(
    qapp, tmp_path, _restore_settings
):
    """Otherwise the old blocks would be written into the new file."""
    import json

    plain = tmp_path / "plain.json"
    plain.write_text(
        json.dumps({"nodes": [{"id": "s", "node_type": "sort", "params": {}}],
                    "connections": []})
    )
    window = MainWindow()
    window._dashboard_page.add_shape("rectangle")

    window._open_pipeline_file(str(plain))

    assert window._dashboard_page.blocks() == []
    window.close()


# -- the canvas layout travels with the document -------------------------


def _saveable_window():
    """A window whose pipeline passes validate(): an unsatisfied required
    port would raise the save error dialog, and a modal hangs the suite."""
    window = MainWindow()
    graph = window._canvas.graph
    load = graph.create_node(qt_type_for("example_data"), name="load", pos=[-320, 10])
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot", pos=[140, 75])
    load.outputs()["df"].connect_to(plot.inputs()["df"])
    return window, load, plot


def test_node_positions_and_collapsed_previews_survive_save_and_open(
    qapp, monkeypatch, tmp_path
):
    """Reopening used to lay every node out in a single row."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    path = tmp_path / "doc.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: pytest.fail("no modal expected")
    )
    window, load, plot = _saveable_window()
    plot.view.set_preview_collapsed(True)
    window._on_save_pipeline()
    window.close()

    reopened = MainWindow()
    reopened._open_pipeline_file(str(path))
    nodes = {n.name(): n for n in reopened._canvas.graph.all_nodes()}

    assert nodes["load"].pos() == [-320.0, 10.0]
    assert nodes["plot"].pos() == [140.0, 75.0]
    assert nodes["plot"].view.preview_collapsed
    card = reopened._preview_overlay.cards()[nodes["plot"].id]
    assert not card.isVisible()
    assert not reopened.is_modified()  # opening a file is not an edit
    reopened.close()


def test_collapsing_a_preview_marks_the_document_until_it_is_saved(
    qapp, monkeypatch, tmp_path
):
    """The flag is saved with the pipeline but pushes no undo command, so
    without its own marker the close prompt would not know about it."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    path = tmp_path / "doc.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **k: pytest.fail("no modal expected")
    )
    window, _load, plot = _saveable_window()
    window._on_save_pipeline()
    assert not window.is_modified()

    window._preview_overlay.toggle_collapsed(plot.id)
    assert window.is_modified()
    assert window.windowTitle().endswith("•")

    window._on_save_pipeline()
    assert not window.is_modified()
    window.close()
