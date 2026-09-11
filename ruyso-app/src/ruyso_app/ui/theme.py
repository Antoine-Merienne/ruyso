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
from pathlib import Path

#: Small themed QSS assets (dropdown / spin-box chevrons). Referenced by
#: absolute POSIX path from ``stylesheet_for`` -- Qt resolves ``url()``
#: in an application stylesheet relative to the working directory, which
#: is not reliable, so an absolute path is used.
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# --- Fonts -------------------------------------------------------------
# Prefer each OS's native UI font (crisper than Helvetica on macOS,
# matches the platform on Windows/Linux). Qt silently skips families it
# cannot resolve, so the unknown-to-Qt CSS keywords are harmless padding
# and the concrete names after them are the real fallback chain.
UI_FONT_FAMILY = (
    "-apple-system, '.AppleSystemUIFont', 'SF Pro Text', 'Segoe UI', "
    "'system-ui', 'Helvetica Neue', Arial, sans-serif"
)
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
    #: Dropdown lists and menus. A popup floats above the window, so in
    #: the light theme it is white -- brighter than the panel it opens
    #: from -- while the dark theme has nowhere brighter to go and keeps
    #: the panel colour.
    popup_background: str
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
    # Deep, near-neutral charcoal (no blue cast) -- Material-dark's
    # #121212 surface family, with the panel a step lighter so inputs
    # recess against it.
    canvas_background=(22, 22, 22),
    category_colors=dict(_MACRO_TYPE_COLORS),
    default_category_color=(96, 96, 96),
    window_background="#1a1a1a",
    panel_background="#242424",
    popup_background="#242424",
    input_background="#121212",
    text_color="#ededed",
    border_color="#3d3d3d",
    accent_color="#2a2a2a",
    highlight_color="#1e88e5",  # Material Blue 600 -- reads on deep dark
)

LIGHT_THEME = Theme(
    name="light",
    # Warm near-white (a hint of cream, R>=G>=B) instead of the old
    # blue-grey, so the light theme reads clean rather than dull.
    canvas_background=(237, 235, 231),
    category_colors=dict(_MACRO_TYPE_COLORS),
    default_category_color=(178, 176, 172),
    window_background="#faf9f7",
    panel_background="#f1efeb",
    popup_background="#ffffff",
    input_background="#ffffff",
    text_color="#1c1c1e",
    border_color="#dcd8d1",
    accent_color="#efece7",
    highlight_color="#1976d2",  # Material Blue 700
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


def muted_text_color(theme: Theme | None = None, amount: float = 0.38) -> str:
    """
    Secondary text: the theme's text colour blended toward the panel.

    For captions and help text that should read as quieter than the
    body without disappearing. ``amount`` is how far toward the panel
    colour to go -- 0 is body text, 1 is invisible.
    """
    theme = theme if theme is not None else current_theme()
    blended = _blend(
        _hex_to_rgb(theme.text_color), _hex_to_rgb(theme.panel_background), amount
    )
    return "#{:02x}{:02x}{:02x}".format(*blended)


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


def accent_color() -> str:
    """
    The ``appearance.accent_color`` preference, or ``""`` to use the
    active palette's own highlight.

    An unparseable value is treated as unset: a typo in a colour should
    leave the app looking normal, not paint every focus ring black.
    """
    from PySide6.QtGui import QColor

    from ruyso_app.engine import settings

    value = str(settings.get("appearance.accent_color") or "").strip()
    if not value:
        return ""
    return value if QColor(value).isValid() else ""


def ui_font_size() -> int:
    """The ``appearance.font_size`` preference in points (0 = platform default)."""
    from ruyso_app.engine import settings

    try:
        size = int(settings.get("appearance.font_size"))
    except (TypeError, ValueError):
        return 0
    return size if 7 <= size <= 24 else 0


#: Installed once on the QApplication; see :func:`install_combo_popup_styler`.
_popup_styler: object | None = None


def install_combo_popup_styler(app) -> object:
    """
    Strip the square frame Qt draws behind every popup -- combo-box
    dropdowns *and* menus -- so both show the rounded card the QSS asks
    for.

    A ``QComboBox`` popup is two nested widgets: a
    ``QComboBoxPrivateContainer`` (a plain ``QFrame`` top-level window)
    holding the list view. The QSS above rounds the *view*, but the
    container still painted its own square-cornered -- and usually
    wider -- background behind it, so every dropdown read as a rounded
    list sitting inside a square box. Making the container frameless and
    translucent leaves only the rounded list visible.

    A ``QMenu`` has the same problem in one widget: its own window is
    opaque, so the ``border-radius`` was painted over at the corners and
    every right-click menu came up square. The same two flags fix it,
    which is what makes the canvas menus match the dropdowns.
    NodeGraphQt's ``BaseMenu`` additionally ships a hard-coded dark
    stylesheet of its own (``widgets/actions.py``); a widget-local
    stylesheet beats the application one, so it is cleared here -- that
    is the only reason the "New Node" menu looked nothing like the rest
    of the app.

    One application-wide event filter rather than a call per widget: the
    combo container is private API with no public accessor, and menus
    are built on the fly all over the app and inside NodeGraphQt.
    ``Polish`` is the hook rather than ``Show`` because
    ``setWindowFlags`` *hides* an already-visible widget -- restyling on
    show would close the popup the person just opened.

    Idempotent: returns the existing filter if one is already installed.
    """
    global _popup_styler
    if _popup_styler is not None:
        return _popup_styler

    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtWidgets import QMenu

    def _flatten(widget) -> None:
        """Make one popup window frameless and translucent."""
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        widget.setWindowFlags(
            widget.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        if hasattr(widget, "setFrameShape"):  # it is a QFrame
            widget.setFrameShape(widget.Shape.NoFrame)

    class ComboPopupStyler(QObject):
        """Flattens each popup window the first time it is polished."""

        def __init__(self) -> None:
            super().__init__()
            self.styled = 0
            self.menus_styled = 0

        def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
            if event.type() != QEvent.Type.Polish:
                return False
            try:
                if isinstance(watched, QMenu):
                    self._style_menu(watched)
                    return False
                if not watched.inherits("QComboBoxPrivateContainer"):
                    return False
            except (AttributeError, RuntimeError):
                return False
            _flatten(watched)
            self._plain_rows(watched)
            self.styled += 1
            return False  # never swallow it -- the popup must still appear

        @staticmethod
        def _plain_rows(container) -> None:
            """
            Draw the rows as view items rather than as combo boxes.

            Qt's private combo delegate paints each row with the *combo*
            as the styled widget, so every row wore the closed combo's
            own bordered box. See ui/popup_delegate.py.
            """
            from PySide6.QtWidgets import QAbstractItemView

            from ruyso_app.ui import popup_delegate

            view = container.findChild(QAbstractItemView)
            if view is not None:
                popup_delegate.install_on(view)

        def _style_menu(self, menu) -> None:
            if menu.property("ruysoStyled"):
                return
            # Set the guard first: clearing a stylesheet re-polishes the
            # widget, which would re-enter this handler.
            menu.setProperty("ruysoStyled", True)
            if menu.styleSheet():
                menu.setStyleSheet("")  # NodeGraphQt's own dark menu QSS
            _flatten(menu)
            self.menus_styled += 1

    _popup_styler = ComboPopupStyler()
    app.installEventFilter(_popup_styler)
    return _popup_styler


def apply_to_app(app, force: bool = False) -> None:
    """
    Force a consistent look on ``app``: the Fusion style, the current
    theme's palette, and the small amount of extra QSS for the custom
    widgets. Safe to call repeatedly -- it is a no-op when the active
    theme has not changed since the last application.
    """
    global _applied_theme_name

    install_combo_popup_styler(app)

    if not force and _applied_theme_name == _current_theme_name and app.styleSheet():
        return

    from PySide6.QtWidgets import QStyleFactory

    fusion = QStyleFactory.create("Fusion")
    if fusion is not None:
        app.setStyle(fusion)
    app.setPalette(palette_for())
    app.setStyleSheet(stylesheet_for())
    _applied_theme_name = _current_theme_name


#: Run-status colours, shared by the run-progress bar chunk, the "auto"
#: pill dot and the per-node status dots (see ui/node_status.py).
STATUS_COLORS: dict[str, str] = {
    "running": "#4a90d9",  # blue
    "ok": "#3fae5a",       # green
    "error": "#d9534f",    # red
    "idle": "#8a8a8a",     # grey -- also "blocked" / "pending" on nodes
}


def _rgb_css(rgb: tuple[int, int, int]) -> str:
    return f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"


def stylesheet_for(theme: Theme | None = None) -> str:
    """
    The QSS layered on top of the Fusion style + palette.

    The palette colours every standard widget's *fill*; this adds the
    shape language the palette cannot express -- rounded (8px) inputs,
    buttons and menus, pill tabs, a Material-indigo primary button and
    focus ring, slim scrollbars -- plus the fonts and the handful of
    object-name-targeted custom widgets (tab band, run controls,
    empty-canvas hint).

    Nothing here touches the NodeGraphQt canvas or the node bodies:
    those are painted by the library from ``node.set_color`` and stay
    on their own colour scheme.
    """
    theme = theme if theme is not None else current_theme()

    _white = (255, 255, 255)
    _black = (0, 0, 0)

    # A point size of 0 means "whatever the platform picked", so the
    # rule is omitted entirely rather than being written out as 0pt.
    size = ui_font_size()
    base_font_size = f"\n    font-size: {size}pt;" if size else ""

    # The accent preference overrides the palette's own highlight; an
    # unparseable value is ignored rather than painting the app black.
    primary = accent_color() or theme.highlight_color
    primary_rgb = _hex_to_rgb(primary)
    on_primary = "#ffffff"
    # Hover/pressed shades of the indigo primary, and a faint indigo
    # tint of the panel colour for secondary ("tonal") buttons.
    primary_hover = _rgb_css(_blend(primary_rgb, _white, 0.16))
    primary_pressed = _rgb_css(_blend(primary_rgb, _black, 0.18))
    panel_rgb = _hex_to_rgb(theme.panel_background)
    tonal = _rgb_css(_blend(panel_rgb, primary_rgb, 0.14))
    tonal_hover = _rgb_css(_blend(panel_rgb, primary_rgb, 0.26))
    disabled_text = _rgb_css(_blend(_hex_to_rgb(theme.text_color), panel_rgb, 0.6))
    scroll_track = "transparent"
    field_bg = theme.input_background
    border = theme.border_color
    surface = theme.panel_background
    text = theme.text_color
    text_rgb = _hex_to_rgb(theme.text_color)
    # Popups (dropdown lists, menus) and the hover overlay on their
    # rows: a tint of the text colour, so one rule serves both themes.
    popup = theme.popup_background
    popup_rgb = _hex_to_rgb(popup)
    popup_hover = _rgb_css(_blend(popup_rgb, text_rgb, 0.10))
    # Splitter grips: three dots painted on the handle. A true mid-grey
    # reads on both themes, so they are static assets like the chevrons
    # -- a border-coloured line was what made the light theme's handles
    # impossible to find.
    grip_h = (_ASSETS_DIR / "grip-horizontal.svg").as_posix()
    grip_v = (_ASSETS_DIR / "grip-vertical.svg").as_posix()
    chevron_down = (_ASSETS_DIR / "chevron-down.svg").as_posix()
    chevron_up = (_ASSETS_DIR / "chevron-up.svg").as_posix()

    return f"""
QWidget {{
    font-family: {UI_FONT_FAMILY};{base_font_size}
}}
QPlainTextEdit, QTextEdit {{
    font-family: {MONOSPACE_FONT_FAMILY};
}}
QTableView, QHeaderView::section, QTableWidget {{
    font-family: {MONOSPACE_FONT_FAMILY};
}}
QToolTip {{
    background-color: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 6px;
}}

/* --- Text inputs & spin boxes ------------------------------------- */
QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox {{
    background-color: {field_bg};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 3px 8px;
    selection-background-color: {primary};
    selection-color: {on_primary};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QAbstractSpinBox:focus {{
    border: 1px solid {primary};
}}
QLineEdit:disabled, QAbstractSpinBox:disabled, QPlainTextEdit:disabled {{
    color: {disabled_text};
}}
QAbstractSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 18px;
    border: none;
}}
QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 18px;
    border: none;
}}
QAbstractSpinBox::up-arrow {{
    image: url("{chevron_up}");
    width: 10px;
    height: 10px;
}}
QAbstractSpinBox::down-arrow {{
    image: url("{chevron_down}");
    width: 10px;
    height: 10px;
}}

/* --- Combo boxes ------------------------------------------------- */
QComboBox {{
    background-color: {field_bg};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 3px 8px;
    min-height: 20px;
}}
QComboBox:focus, QComboBox:on {{
    border: 1px solid {primary};
}}
QComboBox:disabled {{
    color: {disabled_text};
}}
QComboBox QLineEdit {{
    border: none;
    border-radius: 0px;
    background: transparent;
    padding: 0px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox::down-arrow {{
    image: url("{chevron_down}");
    width: 12px;
    height: 12px;
}}
/* The dropdown list. ``show-decoration-selected: 0`` keeps Qt from
   painting the selection band edge-to-edge behind the rounded row --
   that square bar spanning the whole popup was the artefact the rows'
   own border-radius could not hide. The view and its viewport are both
   painted: the viewport is a child widget with its own background, and
   leaving it on the palette's Base colour showed a white slab under
   the rounded list. */
QComboBox QAbstractItemView {{
    background-color: {popup};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    show-decoration-selected: 0;
}}
QComboBox QAbstractItemView::viewport {{
    background-color: {popup};
    border-radius: 8px;
}}
QComboBox QAbstractItemView::item {{
    background-color: transparent;
    color: {text};
    padding: 4px 8px;
    border-radius: 6px;
    min-height: 20px;
}}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {{
    background-color: {popup_hover};
    color: {text};
}}

/* --- Buttons: tonal by default, indigo when pressed ------------- */
QPushButton {{
    background-color: {tonal};
    color: {text};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 5px 14px;
}}
QPushButton:hover {{
    background-color: {tonal_hover};
}}
QPushButton:pressed {{
    background-color: {primary};
    color: {on_primary};
}}
QPushButton:default {{
    border: 1px solid {primary};
}}
QPushButton:disabled {{
    color: {disabled_text};
    background-color: {surface};
}}

/* --- Menu bar & menus ------------------------------------------- */
QMenuBar {{
    background-color: {theme.window_background};
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 10px;
    border-radius: 6px;
}}
QMenuBar::item:selected {{
    background-color: {tonal_hover};
}}
/* A menu is the same kind of floating card as a dropdown list, so it
   takes the same surface and the same rounded hover overlay. */
QMenu {{
    background-color: {popup};
    border: 1px solid {border};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    background-color: transparent;
    padding: 5px 24px 5px 12px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {popup_hover};
    color: {text};
}}
QMenu::item:disabled {{
    color: {disabled_text};
}}
QMenu::separator {{
    height: 1px;
    background: {border};
    margin: 4px 8px;
}}

/* --- Splitters ------------------------------------------------ */
/* No band between the panes: the handle paints only a short grip of
   three dots, centred, so the Log/Problems strip butts straight
   against the canvas and the drag target is on the panel's own edge. */
QSplitter::handle {{
    background: transparent;
    image: none;
}}
QSplitter::handle:horizontal {{
    width: 7px;
    image: url("{grip_v}");
}}
QSplitter::handle:vertical {{
    height: 7px;
    image: url("{grip_h}");
}}
QSplitter::handle:hover {{
    background-color: {tonal_hover};
}}
/* Same affordance, for a panel that scrolls and so cannot be split
   (see ui/height_grip.py). */
QWidget#ruysoHeightGrip {{
    background-color: transparent;
    background-image: url("{grip_h}");
    background-repeat: no-repeat;
    background-position: center;
    border-radius: 4px;
}}
QWidget#ruysoHeightGrip:hover {{
    background-color: {tonal_hover};
}}

/* --- Tab widgets (the Log / Problems strip) -------------------- */
/* Rounded folder tabs on a frameless pane, so the strip reads as part
   of the page rather than as a boxed-in sub-window. */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabWidget::tab-bar {{
    left: 6px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {disabled_text};
    border: 1px solid transparent;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    padding: 5px 16px;
    margin-right: 2px;
}}
QTabBar::tab:hover {{
    color: {text};
    background-color: {tonal_hover};
}}
QTabBar::tab:selected {{
    background-color: {surface};
    color: {text};
    font-weight: bold;
}}
/* The run log is the page under those tabs, not a field on it: a
   bordered box there reads as a sub-window boxed off from the canvas,
   which is the seam this strip is meant not to have. */
QPlainTextEdit#ruysoRunLog {{
    background-color: {surface};
    border: none;
    border-radius: 0px;
}}

/* --- Scroll areas & slim scrollbars --------------------------- */
/* No frame: the Options-panel param scroller and the tickbox lists
   must read as part of the panel, not as boxed-off sub-widgets. */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {scroll_track};
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {border};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {primary};
}}
QScrollBar:horizontal {{
    background: {scroll_track};
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {border};
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {primary};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px; width: 0px;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: {scroll_track};
}}

/* --- Sliders (unit-interval param fields) --------------------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {border};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {primary};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {primary};
    width: 14px;
    height: 14px;
    margin: -6px 0px;
    border-radius: 7px;
}}

/* --- Tables --------------------------------------------------- */
QTableView {{
    gridline-color: {border};
    selection-background-color: {primary};
    selection-color: {on_primary};
}}
QHeaderView::section {{
    background-color: {surface};
    border: none;
    border-right: 1px solid {border};
    border-bottom: 1px solid {border};
    padding: 4px 8px;
}}

/* --- Group boxes -------------------------------------------- */
QGroupBox {{
    border: 1px solid {border};
    border-radius: 8px;
    margin-top: 8px;
    padding-top: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0px 4px;
}}

/* Empty-canvas hint drawn over the NodeGraphQt viewer. */
QLabel#ruysoEmptyHint {{
    color: #8a8a8a;
    font-size: 22px;
}}

/* Empty-state hint drawn over the Dashboard page frame. */
QLabel#ruysoDashboardHint {{
    color: #8a8a8a;
    font-size: 16px;
}}

/* Dashboard tool strip down the left edge (see ui/dashboard_tools.py).
   Reads as part of the window chrome, separated from the canvas by a
   single hairline rather than a panel of its own. */
QWidget#ruysoDashboardTools {{
    background-color: {theme.window_background};
    border-right: 1px solid {border};
}}
QToolButton#ruysoDashTool {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
}}
QToolButton#ruysoDashTool:hover {{
    background-color: {tonal_hover};
}}
QToolButton#ruysoDashTool:pressed {{
    background-color: {tonal};
    border: 1px solid {primary};
}}
QToolButton#ruysoDashTool::menu-indicator {{
    image: url("{chevron_down}");
    width: 7px;
    height: 7px;
    subcontrol-origin: padding;
    subcontrol-position: bottom right;
}}

/* Custom tab band at the top of the window (see ui/tab_bar.py).
   The tabs are shaped like binder dividers: rounded-top folder tabs
   sitting on the band's baseline, the active one raised, capped with a
   blue edge and open at the bottom so it reads as attached to the
   page below. */
QWidget#ruysoTabBar {{
    background-color: {theme.window_background};
    border-bottom: 1px solid {border};
}}
QPushButton#ruysoTabButton {{
    background-color: transparent;
    color: {disabled_text};
    border: 1px solid transparent;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    border-bottom-left-radius: 0px;
    border-bottom-right-radius: 0px;
    margin: 7px 2px 0px 2px;
    padding: 7px 20px;
}}
QPushButton#ruysoTabButton:hover {{
    background-color: {tonal_hover};
    color: {text};
}}
QPushButton#ruysoTabButton:checked {{
    background-color: {surface};
    color: {text};
    font-weight: bold;
    border: 1px solid {border};
    border-bottom-color: {surface};
    margin-top: 3px;
}}

/* Pipeline-run controls, right-aligned in the tab band. */
QPushButton#ruysoRunButton {{
    background-color: {primary};
    color: {on_primary};
    border: none;
    border-radius: 8px;
    padding: 6px 16px;
    font-weight: 600;
}}
QPushButton#ruysoRunButton:hover {{
    background-color: {primary_hover};
}}
QPushButton#ruysoRunButton:pressed {{
    background-color: {primary_pressed};
}}
QPushButton#ruysoRunButton:disabled {{
    background-color: {surface};
    color: {disabled_text};
}}
QProgressBar#ruysoRunProgress {{
    background-color: {border};
    border: none;
    border-radius: 2px;
}}
QProgressBar#ruysoRunProgress::chunk {{
    border-radius: 2px;
    background-color: {STATUS_COLORS["running"]};
}}
QProgressBar#ruysoRunProgress[state="success"]::chunk {{
    background-color: {STATUS_COLORS["ok"]};
}}
QProgressBar#ruysoRunProgress[state="error"]::chunk {{
    background-color: {STATUS_COLORS["error"]};
}}
QLabel#ruysoRunPercent {{
    color: {text};
    font-size: 10px;
}}

/* "auto" status chip: a status dot + the word "auto"; click to toggle
   auto-run. The dot colours match the run-progress chunk (blue running
   / green ok / red error) plus a grey idle. */
QWidget#ruysoAutoPill {{
    border: 1px solid {border};
    border-radius: 8px;
    background: transparent;
}}
QWidget#ruysoAutoPill:hover {{
    background-color: {tonal_hover};
}}
QLabel#ruysoAutoLabel {{
    color: {disabled_text};
    font-size: 10px;
    background: transparent;
}}
QLabel#ruysoAutoDot {{
    border-radius: 4px;
    background-color: {border};
}}
QWidget#ruysoProblemsChip {{
    border: 1px solid {STATUS_COLORS["error"]};
    border-radius: 8px;
    background: transparent;
}}
QWidget#ruysoProblemsChip:hover {{
    background-color: {tonal_hover};
}}
QLabel#ruysoProblemsLabel {{
    color: {STATUS_COLORS["error"]};
    font-size: 10px;
    background: transparent;
}}
QLabel#ruysoProblemsDot {{
    border-radius: 4px;
    background-color: {STATUS_COLORS["error"]};
}}
QFrame#ruysoProblemRow {{
    border: none;
    border-bottom: 1px solid {border};
    background: transparent;
}}
QLabel#ruysoAutoDot[state="running"] {{ background-color: {STATUS_COLORS["running"]}; }}
QLabel#ruysoAutoDot[state="ok"] {{ background-color: {STATUS_COLORS["ok"]}; }}
QLabel#ruysoAutoDot[state="error"] {{ background-color: {STATUS_COLORS["error"]}; }}
"""
