"""
The Dashboard's shared menus.

"Add Shape" and "Arrange" are offered in three places -- the global
``Dashboard`` menu (:mod:`ui.main_window`), the canvas right-click menu
(:mod:`ui.dashboard_page`) and the left tool bar
(:mod:`ui.dashboard_tools`) -- and they must list the same commands in
the same order wherever they are opened. They are built here once, from
a page, so the three cannot drift apart.

``page`` is duck-typed (a :class:`ui.dashboard_page.DashboardPage`)
rather than imported: the page builds its own context menu from this
module, so importing it back would be a cycle.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMenu

from ruyso_app.ui.dashboard_shapes import SHAPE_KINDS, SHAPE_LABELS

#: Z-order commands: label -> the page method to call.
_ORDER_COMMANDS = (
    ("Bring to Front", "bring_to_front"),
    ("Bring Forward", "bring_forward"),
    ("Send Backward", "send_backward"),
    ("Send to Back", "send_to_back"),
)

#: Alignment commands: label -> the edge ``page.align`` takes.
_ALIGN_COMMANDS = (
    ("Align Left", "left"),
    ("Align Centre", "hcenter"),
    ("Align Right", "right"),
    ("Align Top", "top"),
    ("Align Middle", "vcenter"),
    ("Align Bottom", "bottom"),
)


def fill_shape_menu(menu: QMenu, page: Any) -> QMenu:
    """Add one entry per shape kind, each dropping that shape on the canvas."""
    for kind in SHAPE_KINDS:
        menu.addAction(
            SHAPE_LABELS[kind], lambda _checked=False, k=kind: page.add_shape(k)
        )
    return menu


def fill_arrange_menu(menu: QMenu, page: Any) -> QMenu:
    """Add the z-order, alignment and distribution commands, in that order."""
    for label, method in _ORDER_COMMANDS:
        menu.addAction(label, getattr(page, method))
    menu.addSeparator()
    for label, edge in _ALIGN_COMMANDS:
        menu.addAction(label, lambda _checked=False, e=edge: page.align(e))
    menu.addSeparator()
    menu.addAction("Distribute Horizontally", lambda: page.distribute("h"))
    menu.addAction("Distribute Vertically", lambda: page.distribute("v"))
    return menu
