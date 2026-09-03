"""
Centralized visual theme for the UI layer.

Everything that affects how the app *looks* -- the canvas background,
the colour of each node macro type, the fonts, the Qt palette and the
stylesheet -- lives here, for a dark and a light palette.

Consistency across *every* widget is enforced by forcing Qt's
``Fusion`` style and driving it from a :class:`QPalette` built from the
active :class:`Theme` (native styles ignore custom palettes for many
widgets, which is why some controls used to follow the OS theme while
others followed the app's). See :func:`apply_to_app`.

Which palette is active is decided by :data:`_mode`:

* ``"system"`` (default) -- follow the OS light/dark setting, live;
* ``"dark"`` / ``"light"`` -- pinned by the user via the View menu.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Fonts -------------------------------------------------------------
UI_FONT_FAMILY = "Helvetica, Arial, sans-serif"
MONOSPACE_FONT_FAMILY = "Consolas, Menlo, 'Courier New', monospace"

# --- Macro types ---------------------------------------------------------
MACRO_TYPE_LABELS: dict[str, str] = {
    "loading": "Data Loader",
    "transform": "Transformer",
    "model": "Model",
    "statistics": "Statistics",
    "grapher": "Grapher",
    "export": "Exporter",
}

PREVIEW_MACRO_TYPES = frozenset({"grapher"})


@dataclass(frozen=True)
class Theme:
    """A complete colour set: canvas + nodes + window chrome + inputs."""

    name: str
    canvas_background: tuple[int, int, int]
    category_colors: dict[str, tuple[int, int, int]]
    default_category_color: tuple[int, int, int]
    window_background: str  # hex, e.g. "#22252b"
    panel_background: str
    input_background: str  # text fields / lists / tables
    text_color: str
    border_color: str
    accent_color: str
    highlight_color: str  # selection / active accent


_MACRO_TYPE_COLORS: dict[str, tuple[int, int, int]] = {
    "loading": (31, 119, 180),
    "transform": (255, 127, 14),
    "model": (44, 160, 44),
    "statistics": (127, 127, 127),
    "grapher": (148, 103, 189),
    "export": (140, 86, 75),
}

DARK_THEME = Theme(
    name="dark",
    canvas_background=(38, 41, 48),
    category_colors=dict(_MACRO_TYPE_COLORS),
    default_category_color=(90, 90, 90),
    window_background="#22252b",
    panel_background="#2c2f36",
    input_background="#1c1e23",
    text_color="#e6e6e6",
    border_color="#4a4f5b",
    accent_color="#3a3f4b",
    highlight_color="#3d6fb0",
)

LIGHT_THEME = Theme(
    name="light",
    canvas_background=(224, 226, 230),
    category_colors=dict(_MACRO_TYPE_COLORS),
    default_category_color=(180, 180, 180),
    window_background="#f4f5f7",
    panel_background="#e6e8eb",
    input_background="#ffffff",
    text_color="#202226",
    border_color="#c6c9ce",
    accent_color="#f0f1f3",
    highlight_color="#3d7fd0",
)

THEMES: dict[str, Theme] = {"dark": DARK_THEME, "light": LIGHT_THEME}

#: User preference: "system" | "dark" | "light".
_mode: str = "system"
#: Resolved palette name currently in effect.
_current_theme_name: str = "dark"


# --- mode / resolution ------------------------------------------------


def system_scheme_is_dark() -> bool:
    """Whether the OS is set to a dark appearance (defaults to dark)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return True
    try:
        from PySide6.QtCore import Qt

        return app.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except (AttributeError, TypeError):  # Qt < 6.5
        return True


def _resolve_name() -> str:
    if _mode in ("dark", "light"):
        return _mode
    return "dark" if system_scheme_is_dark() else "light"


def theme_mode() -> str:
    """The current preference: "system" / "dark" / "light"."""
    return _mode


def set_theme_mode(mode: str) -> Theme:
    """Set the preference and re-resolve which palette is active."""
    global _mode, _current_theme_name
    if mode not in ("system", "dark", "light"):
        raise ValueError(f"Unknown theme mode {mode!r}")
    _mode = mode
    _current_theme_name = _resolve_name()
    return THEMES[_current_theme_name]


def refresh_from_system() -> Theme:
    """Re-resolve the active palette (call on an OS colour-scheme change)."""
    global _current_theme_name
    _current_theme_name = _resolve_name()
    return THEMES[_current_theme_name]


def current_theme() -> Theme:
    """The Theme currently in effect."""
    return THEMES[_current_theme_name]


def set_current_theme(name: str) -> Theme:
    """Pin the active palette by name ("dark" / "light"). Sets the mode."""
    if name not in THEMES:
        raise ValueError(f"Unknown theme {name!r}; expected one of {sorted(THEMES)}")
    return set_theme_mode(name)


def toggle_theme() -> Theme:
    """Flip between the dark and light palettes (pins the mode)."""
    return set_current_theme("light" if _current_theme_name == "dark" else "dark")


# --- lookups --------------------------------------------------------


def color_for_category(category: str, theme: Theme | None = None) -> tuple[int, int, int]:
    theme = theme if theme is not None else current_theme()
    return theme.category_colors.get(category, theme.default_category_color)


def label_for_category(category: str) -> str:
    return MACRO_TYPE_LABELS.get(category, category.replace("_", " ").title())


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    """Blend colour ``a`` towards ``b`` by ``amount`` (0..1)."""
    return tuple(round(x + (y - x) * amount) for x, y in zip(a, b))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def lightened_transparent_color(
    rgb: tuple[int, int, int], amount: float = 0.55, alpha: int = 235
) -> tuple[int, int, int, int]:
    """Blend an RGB colour toward white and attach an alpha channel."""
    return (*_blend(rgb, (255, 255, 255), amount), alpha)


def rgba_css(rgba: tuple[int, int, int, int]) -> str:
    r, g, b, a = rgba
    return f"rgba({r}, {g}, {b}, {a / 255:.3f})"


def options_panel_background(category: str | None, theme: Theme | None = None) -> str:
    """
    CSS colour for the Options panel background: a subtle tint of the
    selected node's macro-type colour, blended toward the theme's panel
    colour so text stays readable in both dark and light modes.
    """
    theme = theme if theme is not None else current_theme()
    if category is None:
        return theme.panel_background
    tinted = _blend(
        _hex_to_rgb(theme.panel_background),
        color_for_category(category, theme),
        0.16,
    )
    return f"rgb({tinted[0]}, {tinted[1]}, {tinted[2]})"


# --- palette + stylesheet + application -----------------------------


def palette_for(theme: Theme | None = None):
    """A :class:`QPalette` built from ``theme`` for the Fusion style."""
    from PySide6.QtGui import QColor, QPalette

    theme = theme if theme is not None else current_theme()
    window = QColor(theme.window_background)
    panel = QColor(theme.panel_background)
    base = QColor(theme.input_background)
    text = QColor(theme.text_color)
    border = QColor(theme.border_color)
    accent = QColor(theme.accent_color)
    highlight = QColor(theme.highlight_color)
    disabled = QColor(theme.text_color)
    disabled.setAlpha(115)

    p = QPalette()
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, panel)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, accent)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.ToolTipBase, panel)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.PlaceholderText, disabled)
    p.setColor(QPalette.Highlight, highlight)
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Link, highlight)
    p.setColor(QPalette.Light, panel)
    p.setColor(QPalette.Midlight, border)
    p.setColor(QPalette.Mid, border)
    p.setColor(QPalette.Dark, border)
    p.setColor(QPalette.Shadow, QColor("#000000"))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, disabled)
    return p


_applied_theme_name: str | None = None


def apply_to_app(app, force: bool = False) -> None:
    """
    Force a consistent look on ``app``: the Fusion style, the current
    theme's palette, and the small amount of extra QSS for the custom
    widgets. Safe to call repeatedly -- it is a no-op when the active
    theme has not changed since the last application.
    """
    global _applied_theme_name
    if not force and _applied_theme_name == _current_theme_name and app.styleSheet():
        return

    from PySide6.QtWidgets import QStyleFactory

    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    app.setPalette(palette_for())
    app.setStyleSheet(stylesheet_for())
    _applied_theme_name = _current_theme_name


def stylesheet_for(theme: Theme | None = None) -> str:
    """
    The QSS layered on top of the Fusion style + palette.

    The palette already colours every standard widget; this only sets
    fonts and the handful of custom, object-name-targeted widgets that
    the palette cannot express (the tab band, run controls, the
    empty-canvas hint).
    """
    theme = theme if theme is not None else current_theme()
    return f"""
QWidget {{
    font-family: {UI_FONT_FAMILY};
}}
QPlainTextEdit, QTextEdit {{
    font-family: {MONOSPACE_FONT_FAMILY};
}}
QTableView, QHeaderView::section, QTableWidget {{
    font-family: {MONOSPACE_FONT_FAMILY};
}}
QToolTip {{
    background-color: {theme.panel_background};
    color: {theme.text_color};
    border: 1px solid {theme.border_color};
}}

/* Empty-canvas hint drawn over the NodeGraphQt viewer. */
QLabel#ruysoEmptyHint {{
    color: #8a8a8a;
    font-size: 22px;
}}

/* Custom tab band at the top of the window (see ui/tab_bar.py). */
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

/* Pipeline-run controls, right-aligned in the tab band. */
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
