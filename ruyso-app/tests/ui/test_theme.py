"""
Tests for the dark/light theme model in ``ui.theme``.

Covers the non-visual logic: toggling swaps the active palette, the
generated stylesheet differs between palettes, the Options panel
background is a lightened translucent tint of a macro type color (and
falls back to an opaque panel color when no category applies), and
every one of the six spec macro types has a color in both palettes.
"""

import pytest

from ruyso_app.ui import theme


@pytest.fixture(autouse=True)
def _reset_theme():
    """Keep the module-level theme state from leaking between tests."""
    theme.set_current_theme("dark")
    yield
    theme.set_theme_mode("system")


def test_toggle_theme_swaps_between_dark_and_light():
    theme.set_current_theme("dark")
    assert theme.current_theme().name == "dark"
    assert theme.toggle_theme().name == "light"
    assert theme.current_theme().name == "light"
    assert theme.toggle_theme().name == "dark"


def test_theme_mode_pins_or_follows_the_system():
    theme.set_theme_mode("dark")
    assert theme.theme_mode() == "dark" and theme.current_theme().name == "dark"
    theme.set_theme_mode("light")
    assert theme.current_theme().name == "light"

    theme.set_theme_mode("system")
    assert theme.theme_mode() == "system"
    # resolves to one of the two known palettes
    assert theme.current_theme().name in ("dark", "light")

    with pytest.raises(ValueError):
        theme.set_theme_mode("purple")


def test_palette_for_uses_theme_colours(qapp):
    from PySide6.QtGui import QColor, QPalette

    p = theme.palette_for(theme.LIGHT_THEME)
    assert isinstance(p, QPalette)
    assert p.color(QPalette.Window) == QColor(theme.LIGHT_THEME.window_background)
    assert p.color(QPalette.Base) == QColor(theme.LIGHT_THEME.input_background)
    assert p.color(QPalette.Highlight) == QColor(theme.LIGHT_THEME.highlight_color)


def test_apply_to_app_applies_palette_and_stylesheet(qapp):
    from PySide6.QtGui import QColor, QPalette

    theme.set_current_theme("dark")
    theme.apply_to_app(qapp, force=True)
    assert qapp.styleSheet()  # non-empty QSS layered on top
    assert qapp.palette().color(QPalette.Base) == QColor(theme.DARK_THEME.input_background)

    theme.set_current_theme("light")
    theme.apply_to_app(qapp)  # not forced -> re-applies (theme changed)
    assert qapp.palette().color(QPalette.Base) == QColor(theme.LIGHT_THEME.input_background)


def test_every_macro_type_has_a_color_in_both_palettes():
    for macro_type in theme.MACRO_TYPE_LABELS:
        dark = theme.color_for_category(macro_type, theme.DARK_THEME)
        light = theme.color_for_category(macro_type, theme.LIGHT_THEME)
        assert dark == light  # node colors are palette-independent by design
        assert len(dark) == 3


def test_stylesheet_differs_between_dark_and_light():
    dark_css = theme.stylesheet_for(theme.DARK_THEME)
    light_css = theme.stylesheet_for(theme.LIGHT_THEME)
    assert dark_css != light_css
    assert theme.DARK_THEME.window_background in dark_css
    assert theme.LIGHT_THEME.window_background in light_css


def test_stylesheet_is_rounded_and_uses_the_accent_colour():
    css = theme.stylesheet_for(theme.DARK_THEME)
    assert "border-radius: 8px" in css  # the Material-ish rounded controls
    # the primary (Run) button is filled with the theme's accent highlight
    assert theme.DARK_THEME.highlight_color in css


def test_stylesheet_chevron_urls_point_at_bundled_assets():
    css = theme.stylesheet_for(theme.DARK_THEME)
    for name in ("chevron-down.svg", "chevron-up.svg"):
        asset = theme._ASSETS_DIR / name
        assert asset.is_file(), f"missing bundled QSS asset {asset}"
        assert asset.as_posix() in css


def test_lightened_transparent_color_moves_toward_white_and_adds_alpha():
    r, g, b, a = theme.lightened_transparent_color((0, 0, 0), amount=0.5, alpha=200)
    assert (r, g, b) == (128, 128, 128)
    assert a == 200


def test_options_panel_background_is_a_macro_tint_of_the_panel_colour():
    css = theme.options_panel_background("model", theme.DARK_THEME)
    assert css.startswith("rgb(")
    # a tint -- close to the panel colour but not exactly it
    assert css != theme.DARK_THEME.panel_background
    r, g, b = (int(v) for v in css.strip("rgb() ").split(","))
    pr, pg, pb = theme._hex_to_rgb(theme.DARK_THEME.panel_background)
    assert max(abs(r - pr), abs(g - pg), abs(b - pb)) < 60  # subtle


def test_options_panel_background_falls_back_to_opaque_panel_without_category():
    assert theme.options_panel_background(None, theme.DARK_THEME) == theme.DARK_THEME.panel_background


# -- combo popup container ----------------------------------------------


def test_combo_popup_container_is_flattened(qapp):
    """The dropdown must be one rounded list, not a rounded list inside
    a square frame -- so the container Qt wraps it in is made frameless
    and translucent, leaving only the QSS-rounded view visible."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    from ruyso_app.ui import theme

    theme.apply_to_app(qapp)
    combo = QComboBox()
    combo.addItems(["alpha", "beta"])
    combo.show()  # the container is polished with its combo, before any popup
    container = combo.view().window()

    assert container.inherits("QComboBoxPrivateContainer")
    assert container.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert bool(container.windowFlags() & Qt.WindowType.FramelessWindowHint)
    assert container.frameShape() == container.Shape.NoFrame


def test_a_menu_is_flattened_so_its_rounded_corners_show(qapp):
    """A QMenu paints its own opaque window over the QSS border-radius,
    so every right-click menu came up square."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMenu

    from ruyso_app.ui import theme

    theme.apply_to_app(qapp)
    menu = QMenu()
    menu.addAction("Something")
    menu.ensurePolished()

    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert bool(menu.windowFlags() & Qt.WindowType.FramelessWindowHint)


def test_a_nodegraphqt_menus_own_stylesheet_is_cleared(qapp):
    """NodeGraphQt's BaseMenu ships a dark stylesheet of its own, and a
    widget-local stylesheet beats the application one -- which is why the
    "New Node" menu looked nothing like the rest of the app."""
    from NodeGraphQt.widgets.actions import BaseMenu

    from ruyso_app.ui import theme

    theme.apply_to_app(qapp)
    menu = BaseMenu()
    assert menu.styleSheet()  # NodeGraphQt set it in its constructor

    menu.ensurePolished()
    assert menu.styleSheet() == ""


def test_popups_are_whiter_than_the_panel_in_the_light_theme(qapp):
    """A dropdown floats above the window; in the light theme it lifts
    to white. The dark theme has nowhere brighter to go."""
    from ruyso_app.ui import theme

    assert theme.LIGHT_THEME.popup_background == "#ffffff"
    assert theme.LIGHT_THEME.popup_background != theme.LIGHT_THEME.panel_background
    assert theme.DARK_THEME.popup_background == theme.DARK_THEME.panel_background


def test_menus_and_dropdown_lists_share_one_surface(qapp):
    """They are the same kind of floating card, and looked like two."""
    from ruyso_app.ui import theme

    css = theme.stylesheet_for(theme.LIGHT_THEME)
    menu = css.split("QMenu {", 1)[1].split("}", 1)[0]
    dropdown = css.split("QComboBox QAbstractItemView {", 1)[1].split("}", 1)[0]

    assert theme.LIGHT_THEME.popup_background in menu
    assert theme.LIGHT_THEME.popup_background in dropdown


def test_the_active_tab_has_no_accent_line_over_it(qapp):
    from ruyso_app.ui import theme

    css = theme.stylesheet_for()
    checked = css.split("QPushButton#ruysoTabButton:checked {", 1)[1].split("}", 1)[0]

    assert "border-top:" not in checked


def test_secondary_text_is_muted_but_not_invisible(qapp):
    """``palette(mid)`` is the *border* colour, which left the node
    description unreadable on the options panel's tint."""
    from PySide6.QtGui import QColor

    from ruyso_app.ui import theme

    for palette in (theme.DARK_THEME, theme.LIGHT_THEME):
        muted = QColor(theme.muted_text_color(palette))
        body = QColor(palette.text_color)
        panel = QColor(palette.panel_background)

        # Closer to the panel than body text is, but nowhere near it.
        assert abs(muted.lightness() - panel.lightness()) > 40
        assert abs(muted.lightness() - panel.lightness()) < abs(
            body.lightness() - panel.lightness()
        )


def test_splitter_handles_show_a_grip_from_a_bundled_asset(qapp):
    from pathlib import Path

    from ruyso_app.ui import theme

    css = theme.stylesheet_for()
    for name in ("grip-horizontal.svg", "grip-vertical.svg"):
        path = Path(theme._ASSETS_DIR) / name
        assert path.exists()
        assert path.as_posix() in css


def test_the_popup_styler_is_installed_once(qapp):
    from ruyso_app.ui import theme

    first = theme.install_combo_popup_styler(qapp)
    assert theme.install_combo_popup_styler(qapp) is first


# -- Appearance preferences ----------------------------------------------


def test_the_accent_preference_overrides_the_palette(qapp):
    from ruyso_app.engine import settings
    from ruyso_app.ui import theme

    try:
        assert theme.accent_color() == ""  # the theme's own, by default
        settings.set("appearance.accent_color", "#e91e63")
        assert theme.accent_color() == "#e91e63"
        assert "#e91e63" in theme.stylesheet_for()
    finally:
        settings.reset()


def test_an_unparseable_accent_is_ignored(qapp):
    """A typo should leave the app looking normal, not paint it black."""
    from ruyso_app.engine import settings
    from ruyso_app.ui import theme

    try:
        settings.set("appearance.accent_color", "not-a-colour")
        assert theme.accent_color() == ""
    finally:
        settings.reset()


def test_the_font_size_preference_reaches_the_stylesheet(qapp):
    from ruyso_app.engine import settings
    from ruyso_app.ui import theme

    try:
        assert "font-size: " not in theme.stylesheet_for().split("QWidget {")[1][:120]
        settings.set("appearance.font_size", 13)
        assert "font-size: 13pt" in theme.stylesheet_for()
    finally:
        settings.reset()


def test_an_out_of_range_font_size_falls_back_to_the_system(qapp):
    from ruyso_app.engine import settings
    from ruyso_app.ui import theme

    try:
        settings.set("appearance.font_size", 400)
        assert theme.ui_font_size() == 0
    finally:
        settings.reset()
