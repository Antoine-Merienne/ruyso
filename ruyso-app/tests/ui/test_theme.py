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
