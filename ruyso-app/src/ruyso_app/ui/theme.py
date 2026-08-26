"""
Centralized visual theme for the UI layer.

Everything that affects how the app *looks* -- rather than how it
behaves -- is meant to live in this one file: the canvas background,
the color assigned to each node category, and the Qt stylesheet
applied to the rest of the main window. To re-skin the app, this
should be the only file that needs touching.
"""

from __future__ import annotations

# --- Canvas colors --------------------------------------------------------

# Background of the node-graph canvas itself (R, G, B), 0-255.
CANVAS_BACKGROUND_COLOR: tuple[int, int, int] = (38, 41, 48)

# --- Node colors, by category ----------------------------------------------
#
# Every value of ruyso_app.core.node.Node.category used by a concrete
# node (see the `category` class attribute in src/ruyso_app/nodes/*.py)
# should have an entry here, so every node type gets a distinct,
# meaningful color on the canvas. Adding a new node category later only
# requires adding one line here -- node_factory.py picks it up
# automatically.
CATEGORY_COLORS: dict[str, tuple[int, int, int]] = {
    "loading": (58, 122, 118),  # teal
    "transform": (86, 130, 63),  # green
    "model": (122, 79, 130),  # purple
    "viz": (168, 122, 42),  # amber
    "export": (140, 68, 68),  # brick red
}

# Fallback color for a category not listed above.
DEFAULT_CATEGORY_COLOR: tuple[int, int, int] = (90, 90, 90)  # neutral gray


def color_for_category(category: str) -> tuple[int, int, int]:
    """Return the RGB color associated with a node category."""
    return CATEGORY_COLORS.get(category, DEFAULT_CATEGORY_COLOR)


# --- Main window stylesheet -------------------------------------------------
#
# Plain Qt stylesheet (QSS) applied to the whole main window in app.py.
# Edit freely -- this only affects the surrounding window chrome
# (toolbar, docks, buttons, status bar), not the canvas itself, which
# is styled separately via CANVAS_BACKGROUND_COLOR and CATEGORY_COLORS
# above (NodeGraphQt does not use Qt stylesheets for the canvas).
MAIN_WINDOW_STYLESHEET = """
QMainWindow {
    background-color: #22252b;
}
QDockWidget {
    color: #e6e6e6;
    font-size: 12px;
}
QDockWidget::title {
    background-color: #2c2f36;
    padding: 4px;
}
QToolBar {
    background-color: #2c2f36;
    border: none;
    spacing: 6px;
    padding: 4px;
}
QStatusBar {
    background-color: #2c2f36;
    color: #cfcfcf;
}
QPushButton {
    background-color: #3a3f4b;
    color: #f0f0f0;
    border: 1px solid #4a4f5b;
    border-radius: 4px;
    padding: 5px 12px;
}
QPushButton:hover {
    background-color: #454b59;
}
QPushButton:pressed {
    background-color: #2f333d;
}
"""
