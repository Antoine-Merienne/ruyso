"""
Tests for the Dashboard blocks' frames, text-box resizing, the figure
right-click panels, and imported images (``ui.dashboard_items``,
``ui.dashboard_page``, ``ui.dashboard_shapes``).
"""

import json

import matplotlib

matplotlib.use("Agg")
from matplotlib.figure import Figure
from PySide6.QtCore import QByteArray, QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsSceneMouseEvent, QMenu

from ruyso_app.ui.dashboard_items import FigureItem, ImageItem, TextItem
from ruyso_app.ui.dashboard_page import _PAGE_SHAPE, _PAGE_TEXT, DashboardPage
from ruyso_app.ui.node_preview import figure_to_svg_bytes


def _labels(menu: QMenu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _mouse(kind, x, y=0.0):
    event = QGraphicsSceneMouseEvent(kind)
    event.setPos(QPointF(x, y))
    event.setButton(Qt.LeftButton)
    event.setButtons(Qt.LeftButton)
    return event


def _png(tmp_path, name="pic.png", w=200, h=100):
    image = QImage(w, h, QImage.Format_ARGB32)
    image.fill(QColor("#ff0000"))
    path = tmp_path / name
    assert image.save(str(path))
    return path


# -- text boxes ---------------------------------------------------------


def test_dragging_a_text_box_handle_sets_its_width_and_the_height_follows(qapp):
    page = DashboardPage()
    item = page.add_text_item()
    item.setPlainText("several words that will need to wrap onto more lines " * 3)
    tall_before = item.boundingRect().height()
    handle = item._handle_rect().center()

    item.mousePressEvent(_mouse(QEvent.GraphicsSceneMousePress, handle.x(), handle.y()))
    item.mouseMoveEvent(_mouse(QEvent.GraphicsSceneMouseMove, 120.0))
    item.mouseReleaseEvent(_mouse(QEvent.GraphicsSceneMouseRelease, 120.0))

    assert item.textWidth() == 120.0
    assert item.boundingRect().height() > tall_before  # more lines, taller


def test_a_text_box_cannot_be_dragged_narrower_than_a_word(qapp):
    item = TextItem("hello")
    item.setSelected(True)
    item._resizing = True
    item.mouseMoveEvent(_mouse(QEvent.GraphicsSceneMouseMove, -50.0))
    assert item.textWidth() == 40.0


def test_the_text_panel_carries_a_frame_section_that_styles_the_box(qapp):
    page = DashboardPage()
    item = page.add_text_item(is_title=True)

    assert page._inspector_stack.currentIndex() == _PAGE_TEXT
    frame = page._text_inspector.frame
    frame._stroke_width.setValue(3.0)
    frame._radius.setValue(10)

    assert item.style()["stroke_width"] == 3.0
    assert item.style()["radius"] == 10.0
    assert frame._heading.text() == "Frame"
    # Rotation and locking are shape-only.
    assert not frame._form.isRowVisible(frame._rotation)


def test_a_text_frame_edit_is_undoable(qapp):
    page = DashboardPage()
    item = page.add_text_item()
    page._text_inspector.frame._stroke_width.setValue(4.0)
    assert item.style()["stroke_width"] == 4.0

    page.undo_stack().undo()
    restored = next(b for b in page.blocks() if isinstance(b, TextItem))
    assert restored.style()["stroke_width"] == 0.0


def test_a_text_box_saved_before_frames_existed_still_opens(qapp):
    page = DashboardPage()
    old = {
        "version": 1,
        "items": [{
            "type": "text", "pos": [0, 0], "z": 0,
            "state": {
                "text": "Old caption", "is_title": False, "width": 300,
                "style": {"bold": False, "italic": False, "size": 12,
                          "color": "#202020", "align": "left", "family": "",
                          "locked": False},
            },
        }],
    }
    page.restore(old)
    (item,) = page.blocks()
    assert item.toPlainText() == "Old caption"
    assert item.style()["stroke_width"] == 0.0  # the default, not a KeyError


# -- figures ------------------------------------------------------------


def test_a_right_clicked_figure_offers_its_two_panels(qapp):
    page = DashboardPage()
    figure = FigureItem("Board 1", "Sales")
    page._scene.addItem(figure)
    figure.setSelected(True)

    labels = _labels(page.build_context_menu())
    assert labels[:2] == ["Options Panel...", "Cosmetic Panel..."]


def test_the_menu_offers_no_figure_panels_for_a_text_box(qapp):
    page = DashboardPage()
    page.add_text_item()
    assert "Cosmetic Panel..." not in _labels(page.build_context_menu())


def test_the_cosmetic_panel_restyles_a_figure_frame(qapp):
    page = DashboardPage()
    figure = FigureItem("Board 1")
    page._scene.addItem(figure)
    figure.setSelected(True)

    page.show_figure_cosmetics()
    assert page._inspector_stack.currentIndex() == _PAGE_SHAPE
    inspector = page._shape_inspector
    assert inspector._heading.text() == "Figure"
    assert inspector._radius.isEnabled()  # a figure's corners can round

    inspector._radius.setValue(16)
    inspector._stroke_width.setValue(0.0)
    assert figure.style()["radius"] == 16.0
    assert figure.style()["stroke_width"] == 0.0

    page.undo_stack().undo()  # the width, then the radius: one step each
    assert figure.style()["stroke_width"] == 1.0
    page.undo_stack().undo()
    assert figure.style()["radius"] == 0.0


def test_the_options_panel_entry_reopens_the_plot_options(qapp):
    page = DashboardPage()
    figure = FigureItem("Board 1")
    page._scene.addItem(figure)
    figure.setSelected(True)
    seen = []
    page.figure_block_selected.connect(seen.append)

    page.show_figure_cosmetics()
    page.show_figure_options()
    assert seen[-1] == "Board 1"


def test_a_figure_frame_survives_save_and_reopen(qapp):
    page = DashboardPage()
    figure = FigureItem("Board 1")
    page._scene.addItem(figure)
    figure.set_style(fill="#fef3c7", radius=12.0)

    reopened = DashboardPage()
    reopened.restore(json.loads(json.dumps(page.to_dict())))
    (block,) = reopened.blocks()
    assert block.style()["fill"] == "#fef3c7"
    assert block.style()["radius"] == 12.0


def test_a_dashboard_figure_is_rendered_on_a_transparent_background(qapp):
    """So the block's fill shows behind the plot; an ordinary render
    keeps its white one."""
    figure = Figure(figsize=(2, 2))
    figure.add_subplot().plot([0, 1], [0, 1])

    def corner(svg: bytes) -> QColor:
        image = QImage(100, 100, QImage.Format_ARGB32)
        image.fill(QColor("#ff0000"))
        painter = QPainter(image)
        QSvgRenderer(QByteArray(svg)).render(painter)
        painter.end()
        return image.pixelColor(1, 1)

    assert corner(figure_to_svg_bytes(figure)) == QColor("#ffffff")
    assert corner(figure_to_svg_bytes(figure, transparent=True)) == QColor("#ff0000")


# -- right-click selects the block under it -----------------------------


def test_a_right_click_on_an_unselected_block_selects_it(qapp):
    page = DashboardPage()
    page.resize(800, 600)
    text = page.add_text_item()
    figure = FigureItem("Board 1")
    page._scene.addItem(figure)
    figure.setPos(text.pos() + QPointF(0, 400))
    page._view.centerOn(figure)
    assert text.isSelected()

    centre = figure.mapToScene(figure.visual_rect().center())
    page._view.select_block_at(page._view.mapFromScene(centre))

    assert figure.isSelected() and not text.isSelected()


# -- images -------------------------------------------------------------


def test_an_imported_image_keeps_its_aspect_and_is_styled_as_a_block(qapp, tmp_path):
    page = DashboardPage()
    item = page.add_image(str(_png(tmp_path, w=200, h=100)))

    rect = item.visual_rect()
    assert rect.width() == 200.0 and rect.height() == 100.0
    assert page._inspector_stack.currentIndex() == _PAGE_SHAPE
    assert page._shape_inspector._heading.text() == "Image"


def test_a_large_image_arrives_at_a_sensible_width(qapp, tmp_path):
    page = DashboardPage()
    item = page.add_image(str(_png(tmp_path, w=3000, h=1500)))
    assert item.visual_rect().width() == 480.0
    assert item.visual_rect().height() == 240.0


def test_an_image_is_embedded_in_the_saved_file(qapp, tmp_path):
    path = _png(tmp_path)
    page = DashboardPage()
    page.add_image(str(path))
    saved = json.loads(json.dumps(page.to_dict()))  # plain JSON all the way

    path.unlink()  # the file is gone; the pipeline must not need it
    reopened = DashboardPage()
    reopened.restore(saved)
    (image,) = reopened.blocks()
    assert isinstance(image, ImageItem)
    assert image._image is not None and image._image.width() == 200


def test_an_svg_image_stays_a_vector(qapp, tmp_path):
    path = tmp_path / "logo.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'
        '<rect width="120" height="60" fill="#00f"/></svg>'
    )
    item = DashboardPage().add_image(str(path))
    assert item._svg is not None and item._image is None
    assert item.visual_rect().height() == item.visual_rect().width() / 2


def test_a_file_that_is_not_an_image_is_refused(qapp, tmp_path):
    path = tmp_path / "notes.png"
    path.write_text("not an image")
    page = DashboardPage()
    try:
        page.add_image(str(path))
    except ValueError as exc:
        assert "notes.png" in str(exc)
    else:
        raise AssertionError("an unreadable file was accepted")
    assert page.blocks() == []


def test_an_image_can_be_duplicated_and_its_deletion_undone(qapp, tmp_path):
    page = DashboardPage()
    page.add_image(str(_png(tmp_path)))
    copies = page.duplicate_selected()
    assert len(copies) == 1 and isinstance(copies[0], ImageItem)
    assert copies[0]._image.width() == 200

    page.remove_selected()
    assert len(page.blocks()) == 1
    page.undo_stack().undo()
    assert len(page.blocks()) == 2


def test_the_strip_and_the_canvas_menu_offer_add_image(qapp):
    page = DashboardPage()
    assert "Add image" in [b.toolTip() for b in page.tools.buttons()]
    assert "Add Image..." in _labels(page.build_context_menu())
