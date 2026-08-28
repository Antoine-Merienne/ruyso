"""
The canvas's right-click "New Node" menu.

Per the mockups a node is created from a menu, not a left-click popup:
this installs a "New Node" submenu on NodeGraphQt's graph (background)
context menu with one entry per macro type, mirroring the top
``Node > New Node`` menu. Choosing a macro type calls back into
``MainWindow`` to run the two-step macro -> micro creation flow.

A macro type with no registered concrete node yet (e.g.
``statistical_test``) is shown but disabled, never omitted and never a
crash.
"""

from __future__ import annotations

from typing import Callable

from NodeGraphQt import NodeGraph

from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import core_node_types_by_category

#: Guard attribute so a second ``install_new_node_menu`` call on the
#: same graph is a no-op (NodeGraphMenu.get_menu is unreliable upstream).
_INSTALLED_FLAG = "_ruyso_new_node_menu_installed"


def install_new_node_menu(graph: NodeGraph, on_pick_macro: Callable[[str], None]) -> None:
    """
    Add a "New Node" submenu to ``graph``'s background context menu.

    Args:
        graph: The NodeGraphQt graph whose canvas should get the menu.
        on_pick_macro: Called as ``on_pick_macro(category)`` with the
            macro type string when one of the submenu entries is
            chosen.
    """
    if getattr(graph, _INSTALLED_FLAG, False):
        return
    setattr(graph, _INSTALLED_FLAG, True)

    graph_menu = graph.get_context_menu("graph")
    new_node_menu = graph_menu.add_menu("New Node")

    available = core_node_types_by_category()
    for category, label in theme.MACRO_TYPE_LABELS.items():
        command = new_node_menu.add_command(
            label,
            lambda _graph, c=category: on_pick_macro(c),
        )
        if category not in available:
            command.set_enabled(False)
