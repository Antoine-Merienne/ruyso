"""
Tests for the Dashboard tab's left tool strip (``ui.dashboard_tools``)
and the menus it shares with the canvas right-click and the global
Dashboard menu (``ui.dashboard_menus``).
"""

from PySide6.QtWidgets import QMenu

from ruyso_app.ui.dashboard_items import TextItem
from ruyso_app.ui.dashboard_page import DashboardPage
from ruyso_app.ui.dashboard_shapes import SHAPE_KINDS, SHAPE_LABELS, ShapeItem


def _labels(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def test_the_strip_offers_the_four_tools(qapp):
    page = DashboardPage()
    tools = page.tools

    assert [b.toolTip() for b in tools.buttons()][:3] == [
        "Add title",
        "Add text box",
        "Add shape",
    ]
    assert tools.arrange_button.toolTip().startswith("Arrange")
    assert all(not b.icon().isNull() for b in tools.buttons())


def test_the_title_and_text_buttons_add_their_block(qapp):
    page = DashboardPage()

    page.tools.title_button.click()
    page.tools.text_button.click()

    texts = [b for b in page.blocks() if isinstance(b, TextItem)]
    # blocks() is in scene order, not creation order -- one of each.
    assert sorted(t.is_title for t in texts) == [False, True]


def test_the_shape_button_drops_a_menu_of_every_kind(qapp):
    page = DashboardPage()
    menu = page.tools.shape_button.menu()

    assert _labels(menu) == [SHAPE_LABELS[k] for k in SHAPE_KINDS]

    menu.actions()[0].trigger()
    assert [type(b) for b in page.blocks()] == [ShapeItem]


def test_arrange_is_disabled_until_something_is_selected(qapp):
    """Every entry acts on a selection, so an always-enabled button
    would open a menu where nothing does anything."""
    page = DashboardPage()
    assert not page.tools.arrange_button.isEnabled()

    shape = page.add_shape("rectangle")  # selects it
    assert page.tools.arrange_button.isEnabled()

    shape.setSelected(False)
    assert not page.tools.arrange_button.isEnabled()


def test_arranging_from_the_strip_moves_the_block(qapp):
    page = DashboardPage()
    back = page.add_shape("rectangle")
    front = page.add_shape("ellipse")
    front.setZValue(5.0)

    page._scene.clearSelection()
    back.setSelected(True)
    action = next(
        a for a in page.tools.arrange_button.menu().actions()
        if a.text() == "Bring to Front"
    )
    action.trigger()

    assert back.zValue() > front.zValue()


def test_the_strip_and_the_canvas_menu_offer_the_same_commands(qapp):
    """Two routes to the same commands must not drift apart."""
    page = DashboardPage()
    page.add_shape("rectangle")  # so the menu shows its selection entries
    canvas_menu = page.build_context_menu()

    shapes = next(a.menu() for a in canvas_menu.actions() if a.text() == "Add Shape")
    arrange = next(a.menu() for a in canvas_menu.actions() if a.text() == "Arrange")

    assert _labels(shapes) == _labels(page.tools.shape_button.menu())
    assert _labels(arrange) == _labels(page.tools.arrange_button.menu())


def test_the_canvas_menu_builds_without_a_selection(qapp):
    """It used to raise NameError on every right-click (SHAPE_KINDS was
    never imported into dashboard_page)."""
    page = DashboardPage()
    labels = _labels(page.build_context_menu())

    assert labels == [
        "Add Title", "Add Text Box", "Add Shape", "Add Image...", "Exporter..."
    ]


def test_a_glyph_fills_its_icon_instead_of_being_cropped(qapp):
    """QPainter already applies the pixmap's device pixel ratio; scaling
    by it again drew the glyph at twice the size and the icon came out
    cropped to its top-left corner."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor

    from ruyso_app.ui.dashboard_tools import ICON_SIZE, _draw_text_box, make_icon

    image = make_icon(_draw_text_box, QColor("black")).pixmap(
        QSize(ICON_SIZE, ICON_SIZE)
    ).toImage()
    inked = [
        (x, y)
        for x in range(image.width())
        for y in range(image.height())
        if image.pixelColor(x, y).alpha() > 0
    ]
    assert inked
    right = max(x for x, _ in inked) / (image.width() - 1)
    bottom = max(y for _, y in inked) / (image.height() - 1)

    assert right > 0.75  # the box reaches x=20.5 of the 24-unit grid
    assert bottom > 0.70  # ... and y=18.5


def test_the_icons_are_repainted_for_the_active_theme(qapp):
    from ruyso_app.ui import theme

    page = DashboardPage()
    before = page.tools.title_button.icon().cacheKey()
    try:
        theme.set_theme_mode("light" if theme.theme_mode() != "light" else "dark")
        page.apply_theme()
        assert page.tools.title_button.icon().cacheKey() != before
    finally:
        theme.set_theme_mode("system")
