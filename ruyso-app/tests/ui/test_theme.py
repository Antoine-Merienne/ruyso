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
    """Keep the module-level 'current theme' from leaking between tests."""
    theme.set_current_theme("dark")
    yield
    theme.set_current_theme("dark")


def test_toggle_theme_swaps_between_dark_and_light():
    assert theme.current_theme().name == "dark"
    assert theme.toggle_theme().name == "light"
    assert theme.current_theme().name == "light"
    assert theme.toggle_theme().name == "dark"


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


def test_lightened_transparent_color_moves_toward_white_and_adds_alpha():
    r, g, b, a = theme.lightened_transparent_color((0, 0, 0), amount=0.5, alpha=200)
    assert (r, g, b) == (128, 128, 128)
    assert a == 200


def test_options_panel_background_is_a_translucent_tint_for_a_category():
    css = theme.options_panel_background("model", theme.DARK_THEME)
    assert css.startswith("rgba(")
    # alpha component < 1.0 -> translucent
    alpha = float(css.rstrip(")").split(",")[-1])
    assert 0.0 < alpha < 1.0


def test_options_panel_background_falls_back_to_opaque_panel_without_category():
    assert theme.options_panel_background(None, theme.DARK_THEME) == theme.DARK_THEME.panel_background
