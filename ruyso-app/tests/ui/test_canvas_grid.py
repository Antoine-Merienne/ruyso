"""
Tests for the pipeline canvas's dot grid (``ui.canvas_grid``): small
round dots on a denser lattice, replacing NodeGraphQt's 5 px hard
squares 50 units apart.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from ruyso_app.ui import canvas_grid


class _FakeViewer:
    def __init__(self, zoom=0.0):
        self._zoom = zoom

    def get_zoom(self):
        return self._zoom


class _FakeScene:
    """Just the two things ``draw_round_dots`` asks a NodeScene for."""

    def __init__(self, zoom=0.0):
        self.grid_color = (80, 80, 80)
        self._viewer = _FakeViewer(zoom)

    def viewer(self):
        return self._viewer


class _RecordingPainter:
    """Records the pen and the points, so the dot shape can be asserted."""

    def __init__(self):
        self.pen = None
        self.points = []
        self.antialiasing = None

    def save(self):
        pass

    def restore(self):
        pass

    def setRenderHint(self, hint, on):  # noqa: N802 - Qt spelling
        if hint == QPainter.Antialiasing:
            self.antialiasing = on

    def setPen(self, pen):  # noqa: N802 - Qt spelling
        self.pen = pen

    def drawPoints(self, points):  # noqa: N802 - Qt spelling
        self.points = list(points)


def _paint(zoom=0.0, rect=QRectF(0, 0, 100, 100)):
    painter = _RecordingPainter()
    canvas_grid.draw_round_dots(_FakeScene(zoom), painter, rect, None, 50)
    return painter


def test_dots_are_round_and_small():
    painter = _paint()

    assert painter.pen.capStyle() == Qt.RoundCap  # square caps are the old look
    assert painter.pen.widthF() == canvas_grid.DOT_SIZE
    assert painter.antialiasing is True  # drawBackground turns it off for us


def test_the_lattice_is_denser_than_nodegraphqts_own():
    painter = _paint()
    xs = sorted({p.x() for p in painter.points})

    assert canvas_grid.DOT_SPACING < 50
    assert xs == [0.0, 25.0, 50.0, 75.0, 100.0]
    assert len(painter.points) == len(xs) ** 2


def test_the_dots_follow_the_scenes_grid_colour():
    assert _paint().pen.color() == QColor(80, 80, 80)


def test_zooming_out_thins_the_lattice_rather_than_letting_it_merge():
    close = _paint(zoom=0.0)
    far = _paint(zoom=-3.0)

    assert len(far.points) < len(close.points)
    assert far.pen.widthF() > close.pen.widthF()  # and stay visible when scaled


def test_an_off_lattice_rect_still_starts_on_the_lattice():
    """A panned viewport must not shift the grid with it."""
    painter = _paint(rect=QRectF(37, 37, 100, 100))

    assert all(p.x() % canvas_grid.DOT_SPACING == 0 for p in painter.points)
    assert all(p.y() % canvas_grid.DOT_SPACING == 0 for p in painter.points)


def test_real_painting_puts_ink_on_the_lattice_and_nowhere_else(qapp):
    image = QImage(80, 80, QImage.Format_RGB32)
    image.fill(Qt.white)
    painter = QPainter(image)
    canvas_grid.draw_round_dots(
        _FakeScene(), painter, QRectF(0, 0, 80, 80), None, 50
    )
    painter.end()

    def inked(x, y):
        return QColor(image.pixel(x, y)).value() < 250

    assert inked(25, 25)  # a dot NodeGraphQt's 50-unit grid would not draw
    assert inked(50, 50)
    assert not inked(37, 37)  # between dots
    assert not inked(31, 25)  # a 5 px-wide square dot would have reached here


def test_install_is_idempotent_and_replaces_nodegraphqts_method():
    from NodeGraphQt.widgets.scene import NodeScene

    canvas_grid.install_dot_grid()
    canvas_grid.install_dot_grid()

    assert NodeScene._draw_dots is canvas_grid.draw_round_dots
