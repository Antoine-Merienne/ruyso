"""
Tests for the main window shell (Phase 1): the three-tab structure,
per-tab menu enable/disable, the live dark/light theme toggle, and the
Node menu's create/delete actions.

These exercise only assembly and state logic -- no pixels are checked;
the suite runs headless under QT_QPA_PLATFORM=offscreen.
"""

import pytest

from ruyso_app.ui import theme
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
    window._on_run_succeeded({plot.name(): {"figure": plt.figure()}})

    assert export.name() in window._dashboard_page._figure_items
    item = window._dashboard_page._figure_items[export.name()]
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
    window._on_run_succeeded({plot.name(): {"figure": plt.figure()}})

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
