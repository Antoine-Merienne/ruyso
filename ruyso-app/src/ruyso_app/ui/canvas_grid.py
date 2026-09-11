"""
The pipeline canvas's dotted background.

NodeGraphQt draws its dot grid with ``painter.drawPoint`` through a pen
whose width is ``grid_size / 10`` -- 5 px at the built-in 50-unit
spacing -- with antialiasing switched off, so every dot is a large hard
square and they sit far apart. This module replaces that one method
with a denser field of small round dots.

It is a monkey-patch of ``NodeGraphQt.widgets.scene.NodeScene`` rather
than a subclass because the scene is constructed by NodeGraphQt's own
viewer (``NodeViewer.__init__`` calls ``setScene(NodeScene(self))``),
with no hook to hand it a different class -- and swapping the scene
afterwards would orphan the live-pipe and cursor-text items the viewer
has already parented to it.

:func:`install_dot_grid` is idempotent and is called from
:class:`ui.canvas.PipelineCanvas`.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

#: Scene units between dots. NodeGraphQt's own constant is 50.
DOT_SPACING = 25

#: Diameter of a dot, in scene units, at 1:1 zoom. NodeGraphQt's dots
#: were ``grid_size / 10`` -- 5 units -- and hard-edged squares.
DOT_SIZE = 2.4

#: Set on the patched class so a second install is a no-op.
_PATCHED_FLAG = "_ruyso_round_dots"


def draw_round_dots(scene, painter, rect, pen, grid_size) -> None:
    """
    Paint the dot grid over ``rect`` (scene coordinates).

    Signature matches the ``NodeScene._draw_dots`` it replaces, so
    NodeGraphQt's ``drawBackground`` calls it unchanged; ``pen`` and
    ``grid_size`` are ignored -- the colour comes from the scene (which
    is what ``ui.theme`` drives) and the spacing from :data:`DOT_SPACING`.

    Dots are drawn as points through a round-capped wide pen rather than
    as ellipses: one ``drawPoints`` call covers the whole viewport,
    where an ellipse per dot is a few thousand painter calls per repaint
    on a pan.
    """
    spacing = DOT_SPACING
    viewer = scene.viewer()
    zoom = viewer.get_zoom() if viewer is not None else 0.0
    if zoom < 0:
        # Zoomed out the dots would merge into a wash, so thin them out
        # the way NodeGraphQt does, and grow them a little so they stay
        # visible once the view scales them down.
        spacing = int(abs(zoom) / 0.3 + 1) * spacing

    left = int(rect.left()) - (int(rect.left()) % spacing)
    top = int(rect.top()) - (int(rect.top()) % spacing)
    points = [
        QPointF(x, y)
        for x in range(left, int(rect.right()) + 1, spacing)
        for y in range(top, int(rect.bottom()) + 1, spacing)
    ]
    if not points:
        return

    dot = QPen(QColor(*scene.grid_color), DOT_SIZE * (spacing / DOT_SPACING) ** 0.5)
    dot.setCapStyle(Qt.RoundCap)  # what makes the dot round rather than square

    painter.save()
    # drawBackground turns antialiasing off before calling us; without it
    # a round cap is rasterised as a blocky square again.
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(dot)
    painter.drawPoints(points)
    painter.restore()


def install_dot_grid() -> None:
    """Replace NodeGraphQt's square-dot grid with :func:`draw_round_dots`."""
    from NodeGraphQt.widgets.scene import NodeScene

    if getattr(NodeScene, _PATCHED_FLAG, False):
        return
    NodeScene._draw_dots = draw_round_dots
    setattr(NodeScene, _PATCHED_FLAG, True)
