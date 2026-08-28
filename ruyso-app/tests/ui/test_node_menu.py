"""
Tests for the canvas right-click "New Node" menu (``ui.node_menu``).
"""

from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import register_all_nodes
from ruyso_app.ui.node_menu import install_new_node_menu

NodeRegistry.discover_package(ruyso_app.nodes)


def test_new_node_submenu_has_one_entry_per_macro_type(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    install_new_node_menu(graph, lambda _c: None)

    graph_qmenu = graph.get_context_menu("graph").qmenu
    submenu = next(
        a.menu() for a in graph_qmenu.actions() if a.text() == "New Node"
    )
    labels = {a.text(): a.isEnabled() for a in submenu.actions()}

    for label in theme.MACRO_TYPE_LABELS.values():
        assert label in labels
    assert labels[theme.MACRO_TYPE_LABELS["statistical_test"]] is False
    assert labels[theme.MACRO_TYPE_LABELS["grapher"]] is True


def test_choosing_a_macro_type_calls_back(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    picked = []
    install_new_node_menu(graph, picked.append)

    graph_qmenu = graph.get_context_menu("graph").qmenu
    submenu = next(a.menu() for a in graph_qmenu.actions() if a.text() == "New Node")
    grapher_action = next(
        a for a in submenu.actions()
        if a.text() == theme.MACRO_TYPE_LABELS["grapher"]
    )
    grapher_action.trigger()

    assert picked == ["grapher"]


def test_install_is_idempotent(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    install_new_node_menu(graph, lambda _c: None)
    install_new_node_menu(graph, lambda _c: None)

    graph_qmenu = graph.get_context_menu("graph").qmenu
    new_node_actions = [a for a in graph_qmenu.actions() if a.text() == "New Node"]
    assert len(new_node_actions) == 1
