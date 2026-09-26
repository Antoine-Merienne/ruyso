"""
Tests for ``ui.swatches`` -- the rendered previews used by the
Options-panel dropdowns (and, later, the colormap designer).

Non-visual: every renderer returns a usable, correctly sized pixmap,
an unknown value degrades gracefully, and two different colormaps
produce visibly different strips.
"""

import pytest

from ruyso_app.ui import swatches, theme


@pytest.fixture(autouse=True)
def _reset_theme():
    theme.set_current_theme("dark")
    yield
    theme.set_theme_mode("system")


def test_colormap_pixmap_is_sized_and_non_null(qapp):
    pm = swatches.colormap_pixmap("viridis")
    assert not pm.isNull()
    assert pm.size() == swatches.icon_size("colormap")


def test_colormap_pixmap_unknown_name_is_a_placeholder_not_an_error(qapp):
    pm = swatches.colormap_pixmap("definitely-not-a-colormap")
    assert not pm.isNull()  # a hatched grey placeholder, still a pixmap


def test_two_colormaps_render_differently(qapp):
    a = swatches.colormap_pixmap("viridis").toImage()
    b = swatches.colormap_pixmap("Blues").toImage()
    mid = a.width() // 2
    assert a.pixel(mid, a.height() // 2) != b.pixel(mid, b.height() // 2)


def test_marker_line_hatch_shapemap_pixmaps_render(qapp):
    for name in ("circle", "square", "triangle", "diamond", "plus", "cross", "star", "point"):
        assert not swatches.marker_pixmap(name).isNull()
    for name in ("solid", "dashed", "dash-dot", "dotted"):
        assert not swatches.linestyle_pixmap(name).isNull()
    for name in ("none", "diagonal", "back-diagonal", "cross", "dots", "stars"):
        assert not swatches.hatch_pixmap(name).isNull()
    for name in ("assorted", "geometric", "bold", "minimal"):
        assert not swatches.shapemap_pixmap(name).isNull()


def test_color_pixmap_valid_and_invalid(qapp):
    assert not swatches.color_pixmap("darkblue").isNull()
    assert not swatches.color_pixmap("#ff0000").isNull()
    assert swatches.color_pixmap("not a colour").isNull()  # caller shows nothing


def test_icon_for_dispatches_by_kind(qapp):
    assert not swatches.icon_for("colormap", "plasma").isNull()
    assert not swatches.icon_for("marker", "star").isNull()
    assert swatches.icon_for("color", "bogus!!").isNull()


def test_marker_glyph_follows_the_active_theme_colour(qapp):
    theme.set_current_theme("dark")
    dark = swatches.marker_pixmap("square").toImage()
    theme.set_current_theme("light")
    light = swatches.marker_pixmap("square").toImage()
    theme.set_current_theme("dark")
    # centre pixel is the fill -- different text colour per theme
    assert dark.pixel(dark.width() // 2, dark.height() // 2) != light.pixel(
        light.width() // 2, light.height() // 2
    )
