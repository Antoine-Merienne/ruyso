"""
The canvas's right-click "New Node" menu.

Per the mockups a node is created from a menu, not a left-click popup:
this installs a "New Node" submenu on NodeGraphQt's graph (background)
context menu with one entry per macro type, mirroring the top
``Node > New Node`` menu. Choosing a macro type calls back into
``MainWindow`` to run the two-step macro -> micro creation flow.

A macro type with no registered concrete node yet is shown but
disabled, never omitted and never a crash.
"""

from __future__ import annotations

from typing import Callable

from NodeGraphQt import NodeGraph

from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import core_node_types_by_category

#: Signature of the pick-macro callback: ``on_pick_macro(category, pos)``
#: where ``pos`` is ``[x, y]`` scene coordinates under the cursor, or
#: ``None`` when there is no meaningful cursor position.
OnPickMacro = Callable[[str, "list[float] | None"], None]

#: Guard attribute so a second ``install_new_node_menu`` call on the
#: same graph is a no-op (NodeGraphMenu.get_menu is unreliable upstream).
_INSTALLED_FLAG = "_ruyso_new_node_menu_installed"

#: Where the per-category commands are stashed on the graph, so their
#: enabled state can be refreshed after a toolbox change.
_COMMANDS_ATTR = "_ruyso_new_node_commands"


def install_new_node_menu(graph: NodeGraph, on_pick_macro: OnPickMacro) -> None:
    """
    Add a "New Node" submenu to ``graph``'s background context menu.

    Args:
        graph: The NodeGraphQt graph whose canvas should get the menu.
        on_pick_macro: Called as ``on_pick_macro(category, pos)`` when
            an entry is chosen. ``pos`` is the ``[x, y]`` scene
            position under the cursor when the menu was opened, so the
            new node can appear right there.
    """
    if getattr(graph, _INSTALLED_FLAG, False):
        return
    setattr(graph, _INSTALLED_FLAG, True)

    viewer = graph.viewer()

    def _cursor_scene_pos() -> list[float] | None:
        # NodeGraphQt stores the last mouse-press position on the
        # viewer; the context menu is opened right after a right-click,
        # so this is where the cursor is.
        previous = getattr(viewer, "_previous_pos", None)
        if previous is None:
            return None
        scene_pos = viewer.mapToScene(previous)
        return [scene_pos.x(), scene_pos.y()]

    graph_menu = graph.get_context_menu("graph")
    new_node_menu = graph_menu.add_menu("New Node")

    commands: dict[str, object] = {}
    for category, label in theme.MACRO_TYPE_LABELS.items():
        command = new_node_menu.add_command(
            label,
            lambda _graph, c=category: on_pick_macro(c, _cursor_scene_pos()),
        )
        commands[category] = command
    # Kept on the graph so a toolbox switched on or off can re-enable
    # them; NodeGraphQt offers no way to look a command back up.
    setattr(graph, _COMMANDS_ATTR, commands)
    refresh_new_node_menu(graph)


def refresh_new_node_menu(graph: NodeGraph) -> None:
    """Re-enable / disable each macro entry for what is registered now."""
    commands = getattr(graph, _COMMANDS_ATTR, None)
    if not commands:
        return
    available = core_node_types_by_category()
    for category, command in commands.items():
        command.set_enabled(category in available)
