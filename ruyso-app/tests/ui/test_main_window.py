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
    theme.set_current_theme("dark")


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


def test_toggle_theme_repaints_canvas_background(window):
    before = window._canvas.graph.background_color()
    window._toggle_theme()
    after = window._canvas.graph.background_color()
    assert theme.current_theme().name == "light"
    assert tuple(before) != tuple(after)
    assert tuple(after) == theme.LIGHT_THEME.canvas_background


def test_toggle_theme_recolors_existing_nodes(window):
    window._on_pick_macro_type("loading")  # creates a "loading" category node
    node = window._canvas.graph.all_nodes()[0]
    # Node color is palette-independent by design, so it should stay the
    # category color across a toggle (and definitely not crash).
    window._toggle_theme()
    assert node.color() == theme.color_for_category("loading")


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
    other_type = "standard_scaler" if original_type == "drop_na" else "drop_na"

    window._pipeline_page.options_panel.node_type_change_requested.emit(other_type)

    remaining = window._canvas.graph.all_nodes()
    assert len(remaining) == 1
    assert type(remaining[0]).CORE_NODE_TYPE == other_type


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


def test_statistical_test_macro_type_has_no_enabled_new_node_action(window):
    # "statistical_test" has no concrete node yet -> its New Node entry
    # must be present but disabled, never missing or crashing.
    new_node_menu = None
    for action in window._node_menu.actions():
        if action.text() == "New Node":
            new_node_menu = action.menu()
    labels = {a.text(): a.isEnabled() for a in new_node_menu.actions()}
    assert labels[theme.MACRO_TYPE_LABELS["statistical_test"]] is False
    assert labels[theme.MACRO_TYPE_LABELS["grapher"]] is True
