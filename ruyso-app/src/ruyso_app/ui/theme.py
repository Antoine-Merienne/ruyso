"""
Centralized visual theme for the UI layer.

Everything that affects how the app *looks* -- rather than how it
behaves -- is meant to live in this one file: the canvas background,
the color assigned to each node macro type, the fonts, and the Qt
stylesheet applied to the rest of the window, for both a dark and a
light theme. To re-skin the app, or to adjust the dark/light palettes,
this should be the only file that needs touching.

Design decision (see spec section 8 -- exact palette values were not
given in the mockups): macro type colors follow the Matplotlib
"tab10" qualitative palette (blue, orange, green, gray, purple, brown,
...), one color per macro type, identical across the dark and light
themes (only the surrounding chrome -- backgrounds, text -- changes
between themes, so a node's color stays recognizable when the user
toggles theme).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --- Fonts -------------------------------------------------------------
#
# UI_FONT_FAMILY is applied everywhere by default. MONOSPACE_FONT_FAMILY
# is used only for the run console/log and any text that names a
# specific library/class (e.g. "StandardScaler"), per the spec. Both
# are CSS-style font stacks with cross-platform fallbacks -- Consolas
# is Windows-only, so Menlo (macOS) and a generic "monospace" are
# listed after it.
UI_FONT_FAMILY = "Helvetica, Arial, sans-serif"
MONOSPACE_FONT_FAMILY = "Consolas, Menlo, 'Courier New', monospace"

# --- Macro types ---------------------------------------------------------
#
# The six node macro types from the UI spec, in menu/display order. The
# key is the exact string used as Node.category on concrete node
# classes (see src/ruyso_app/nodes/*.py); the value is the human
# readable label shown in menus and the Options panel. "statistical_test"
# has no concrete node yet -- see node_menu.py, which omits a macro
# type from the "New Node" menu if the NodeRegistry has no node
# registered under it, rather than showing an empty submenu.
MACRO_TYPE_LABELS: dict[str, str] = {
    "loading": "Data Loader",
    "transform": "Transformer",
    "model": "Model",
    "statistical_test": "Statistical Test",
    "grapher": "Grapher",
    "export": "Exporter",
}

# Macro types whose nodes get an on-canvas preview widget (a plot or a
# test result rendered behind/attached to the node -- see
# ui/node_preview.py) instead of just an editable properties form.
PREVIEW_MACRO_TYPES = frozenset({"grapher", "statistical_test"})


@dataclass(frozen=True)
class Theme:
    """
    A complete color palette for the app: canvas + nodes + window chrome.

    Two instances of this exist (DARK_THEME, LIGHT_THEME); toggling the
    theme (see set_current_theme/toggle_theme below) swaps which one is
    "current" and every themed widget re-reads its colors from it.
    """

    name: str
    canvas_background: tuple[int, int, int]
    category_colors: dict[str, tuple[int, int, int]]
    default_category_color: tuple[int, int, int]
    window_background: str  # hex, e.g. "#22252b"
    panel_background: str
    text_color: str
    border_color: str
    accent_color: str


# Tab10-style qualitative palette, shared by both themes so a node's
# color stays recognizable regardless of dark/light mode.
_MACRO_TYPE_COLORS: dict[str, tuple[int, int, int]] = {
    "loading": (31, 119, 180),  # blue
    "transform": (255, 127, 14),  # orange
    "model": (44, 160, 44),  # green
    "statistical_test": (127, 127, 127),  # gray
    "grapher": (148, 103, 189),  # purple
    "export": (140, 86, 75),  # brown
}

DARK_THEME = Theme(
    name="dark",
    canvas_background=(38, 41, 48),
    category_colors=dict(_MACRO_TYPE_COLORS),
    default_category_color=(90, 90, 90),
    window_background="#22252b",
    panel_background="#2c2f36",
    text_color="#e6e6e6",
    border_color="#4a4f5b",
    accent_color="#3a3f4b",
)

LIGHT_THEME = Theme(
    name="light",
    canvas_background=(224, 226, 230),
    category_colors=dict(_MACRO_TYPE_COLORS),
    default_category_color=(180, 180, 180),
    window_background="#f4f5f7",
    panel_background="#e6e8eb",
    text_color="#202226",
    border_color="#c6c9ce",
    accent_color="#ffffff",
)

THEMES: dict[str, Theme] = {"dark": DARK_THEME, "light": LIGHT_THEME}

_current_theme_name: str = "dark"


def current_theme() -> Theme:
    """The Theme currently in effect."""
    return THEMES[_current_theme_name]


def set_current_theme(name: str) -> Theme:
    """
    Switch the current theme by name ("dark" or "light").

    This only updates which Theme is considered "current" -- it does
    not, by itself, repaint anything. Callers that hold live widgets
    (PipelineCanvas.apply_theme, MainWindow's theme-toggle action) are
    responsible for re-applying the new theme's colors/stylesheet.
    """
    global _current_theme_name
    if name not in THEMES:
        raise ValueError(f"Unknown theme {name!r}; expected one of {sorted(THEMES)}")
    _current_theme_name = name
    return THEMES[name]


def toggle_theme() -> Theme:
    """Switch from dark to light or vice versa; returns the new Theme."""
    return set_current_theme("light" if _current_theme_name == "dark" else "dark")


def color_for_category(category: str, theme: Theme | None = None) -> tuple[int, int, int]:
    """Return the RGB color associated with a node macro type (category)."""
    theme = theme if theme is not None else current_theme()
    return theme.category_colors.get(category, theme.default_category_color)


def label_for_category(category: str) -> str:
    """Human-readable macro type label for a node category, for menus/UI text."""
    return MACRO_TYPE_LABELS.get(category, category.replace("_", " ").title())


def lightened_transparent_color(
    rgb: tuple[int, int, int], amount: float = 0.55, alpha: int = 235
) -> tuple[int, int, int, int]:
    """
    Blend an RGB color toward white and attach an alpha channel.

    Used for the Options panel background: a lighter, slightly
    translucent tint of the selected node's macro type color (per the
    spec). ``amount`` is how far toward white to blend (0 = unchanged,
    1 = pure white); ``alpha`` (0-255) controls translucency.
    """
    r, g, b = rgb
    blended = tuple(round(channel + (255 - channel) * amount) for channel in (r, g, b))
    return (*blended, alpha)


def rgba_css(rgba: tuple[int, int, int, int]) -> str:
    """Format an ``(r, g, b, a)`` tuple as a CSS ``rgba(...)`` string.

    ``a`` is given on the 0-255 scale (as returned by
    ``lightened_transparent_color``) and converted to the 0-1 scale CSS
    expects.
    """
    r, g, b, a = rgba
    return f"rgba({r}, {g}, {b}, {a / 255:.3f})"


def options_panel_background(
    category: str | None, theme: Theme | None = None
) -> str:
    """CSS color for the Options panel background.

    Per the spec, this is a lightened, slightly translucent tint of the
    macro type color of the last selected (or last existing) node. When
    no node is relevant yet (``category is None``), fall back to an
    opaque panel color so the panel still reads as a distinct surface.
    """
    theme = theme if theme is not None else current_theme()
    if category is None:
        return theme.panel_background
    return rgba_css(lightened_transparent_color(color_for_category(category, theme)))


def stylesheet_for(theme: Theme | None = None) -> str:
    """
    Build the Qt stylesheet (QSS) for the whole window from a Theme.

    Only affects surrounding window chrome (menus, docks, toolbar,
    tables, buttons) -- the canvas itself is styled separately via
    PipelineCanvas.apply_theme (NodeGraphQt does not use QSS).
    """
    theme = theme if theme is not None else current_theme()
    return f"""
QWidget {{
    font-family: {UI_FONT_FAMILY};
}}
QMainWindow {{
    background-color: {theme.window_background};
}}
QMenuBar {{
    background-color: {theme.panel_background};
    color: {theme.text_color};
}}
QMenuBar::item:selected {{
    background-color: {theme.accent_color};
}}
QMenu {{
    background-color: {theme.panel_background};
    color: {theme.text_color};
}}
QMenu::item:selected {{
    background-color: {theme.accent_color};
}}
QDockWidget {{
    color: {theme.text_color};
    font-size: 12px;
}}
QDockWidget::title {{
    background-color: {theme.panel_background};
    padding: 4px;
}}
QToolBar {{
    background-color: {theme.panel_background};
    border: none;
    spacing: 6px;
    padding: 4px;
}}
QStatusBar {{
    background-color: {theme.panel_background};
    color: {theme.text_color};
}}
QPlainTextEdit, QTextEdit {{
    font-family: {MONOSPACE_FONT_FAMILY};
    background-color: {theme.panel_background};
    color: {theme.text_color};
    border: 1px solid {theme.border_color};
}}
QTableView {{
    background-color: {theme.window_background};
    color: {theme.text_color};
    gridline-color: {theme.border_color};
    font-family: {MONOSPACE_FONT_FAMILY};
}}
QHeaderView::section {{
    background-color: {theme.panel_background};
    color: {theme.text_color};
    font-family: {MONOSPACE_FONT_FAMILY};
    padding: 4px;
    border: none;
}}
QPushButton {{
    background-color: {theme.accent_color};
    color: {theme.text_color};
    border: 1px solid {theme.border_color};
    border-radius: 4px;
    padding: 5px 12px;
}}
QPushButton:hover {{
    background-color: {theme.border_color};
}}

/* Custom tab band at the top of the window (see ui/tab_bar.py). The
   active tab is a lighter surface, inactive tabs sit on the darker
   window background -- reproducing the mockups' tab strip rather than
   relying on QTabWidget's platform-native look. */
QWidget#ruysoTabBar {{
    background-color: {theme.window_background};
}}
QPushButton#ruysoTabButton {{
    background-color: {theme.window_background};
    color: {theme.text_color};
    border: none;
    border-right: 1px solid {theme.border_color};
    border-radius: 0px;
    padding: 8px 22px;
}}
QPushButton#ruysoTabButton:hover {{
    background-color: {theme.accent_color};
}}
QPushButton#ruysoTabButton:checked {{
    background-color: {theme.panel_background};
    font-weight: bold;
}}

/* Pipeline-run controls, right-aligned in the tab band
   (see ui/run_progress.py): a Run button, a slim progress bar, and a
   percentage label. The bar's fill colour switches on a dynamic
   "state" property: neutral blue while running, green on success,
   red on failure. */
QPushButton#ruysoRunButton {{
    background-color: {theme.accent_color};
    color: {theme.text_color};
    border: 1px solid {theme.border_color};
    border-radius: 4px;
    padding: 4px 12px;
    font-weight: bold;
}}
QPushButton#ruysoRunButton:hover {{
    background-color: {theme.border_color};
}}
QPushButton#ruysoRunButton:disabled {{
    color: {theme.border_color};
}}
QProgressBar#ruysoRunProgress {{
    background-color: {theme.border_color};
    border: none;
    border-radius: 2px;
}}
QProgressBar#ruysoRunProgress::chunk {{
    border-radius: 2px;
    background-color: #4a90d9;
}}
QProgressBar#ruysoRunProgress[state="success"]::chunk {{
    background-color: #3fae5a;
}}
QProgressBar#ruysoRunProgress[state="error"]::chunk {{
    background-color: #d9534f;
}}
QLabel#ruysoRunPercent {{
    color: {theme.text_color};
    font-size: 10px;
}}
"""