"""
How a node is drawn on the pipeline canvas.

NodeGraphQt paints a node as a slab of its own colour: a 4-unit-radius
box filled with the node's colour, a black 80-alpha strip behind the
title, and a 0.8-unit dark border. That reads nothing like the rest of
this app, where a surface is the panel colour, corners are 8, and
colour is an accent rather than a fill.

This module replaces that one paint method:

* the body is the theme's **panel colour** in both themes, so a node is
  a card on the canvas like every other surface in the window;
* the **macro-type colour is a thick contour** around it -- the type is
  still readable at a glance, but it no longer floods the node;
* the **name bar fills with that colour when the node is selected**,
  and the contour thickens. Unselected, the name bar is simply the top
  of the card: no divider, no tint, so the fill is unmistakable;
* corners are :data:`RADIUS`, the same 8 the QSS uses for buttons,
  menus, inputs and panels.

Text follows the same rule (:meth:`RuysoNodeItem._set_text_color`): the
name and the port labels take the theme's text colour, except the name
while the node is selected, which flips to whatever reads on the macro
colour -- white on the blue loader, near-black on the orange transform.

The status dot (``ui/node_status.py``) keeps painting into the icon item
to the left of the name; nothing here touches it.
"""

from __future__ import annotations

from NodeGraphQt.qgraphics.node_base import NodeItem
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from ruyso_app.ui import theme

#: Corner radius, in scene units.
RADIUS = 12.0

#: Contour width, unselected and selected. The contour is the only
#: thing carrying the macro type now, so it reads as a colour rather
#: than as an outline -- but a hair thinner than that first made it.
BORDER = 2.0
BORDER_SELECTED = 3.2

#: Diameter of the run-status dot, in scene units.
STATUS_DOT_SIZE = 9.0

#: Inset of the contour from the item's bounding rect. Half the widest
#: pen, so a selected node's contour is not clipped by its own bounds.
_MARGIN = BORDER_SELECTED / 2.0

#: Inset of the status dot from the card's left edge, so the rounder
#: corner does not cut into it.
_LEFT_INSET = 5.0


def readable_on(background: QColor) -> QColor:
    """
    Black or white, whichever reads on ``background``.

    The macro palette spans a dark blue and a bright orange, so a single
    fixed name colour is unreadable on one end or the other.
    """
    # Rec. 601 luma: close enough for a six-colour palette, and it does
    # not need the sRGB linearisation a contrast-ratio check would.
    luma = (
        0.299 * background.red()
        + 0.587 * background.green()
        + 0.114 * background.blue()
    )
    return QColor("#101010") if luma > 150 else QColor("#ffffff")


class RuysoNodeItem(NodeItem):
    """A :class:`NodeItem` painted as a panel-coloured card with a
    macro-type contour. Layout and sizing are NodeGraphQt's own."""

    def __init__(self, name="node", parent=None) -> None:
        super().__init__(name, parent)
        # NodeGraphQt's icon slot is a QGraphicsPixmapItem, so the
        # status dot painted into it was a 16-px bitmap and went
        # visibly blocky as soon as you zoomed in. It is drawn with the
        # rest of the node instead -- as a circle, at whatever
        # resolution the view is at.
        #
        # Drawn, rather than a child QGraphicsEllipseItem: a child item
        # is destroyed with its C++ parent while this object still
        # holds the Python wrapper, and collecting that wrapper
        # afterwards segfaults in NodeGraphQt's QUndoStack teardown.
        self._icon_item.setVisible(False)
        self._status_colour = QColor(theme.STATUS_COLORS["idle"])

    # -- run status ----------------------------------------------------

    def set_status_colour(self, colour: QColor) -> None:
        """Paint the status dot (see ``ui/node_status.py``)."""
        self._status_colour = QColor(colour)
        self.update()

    def status_colour(self) -> QColor:
        return QColor(self._status_colour)

    # -- painting ------------------------------------------------------

    def _paint_horizontal(self, painter, option, widget) -> None:  # noqa: N802
        painter.save()
        rect = self.boundingRect().adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN)
        body = QPainterPath()
        body.addRoundedRect(rect, RADIUS, RADIUS)
        accent = QColor(*self.color[:3])
        selected = self.selected

        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(body, QColor(theme.current_theme().panel_background))

        if selected:
            # Only the top strip takes the colour, and it keeps the
            # card's rounded top corners -- hence the intersection
            # rather than a rounded rect of its own.
            strip = QPainterPath()
            strip.addRect(
                QRectF(rect.left(), rect.top(), rect.width(), self.name_bar_height())
            )
            painter.fillPath(body.intersected(strip), accent)

        # The run-status dot, on the left of the name, vertically
        # centred on it and inset clear of the rounded corner.
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._status_colour)
        painter.drawEllipse(
            QRectF(
                rect.left() + _LEFT_INSET,
                self._text_item.boundingRect().center().y() - STATUS_DOT_SIZE / 2.0,
                STATUS_DOT_SIZE,
                STATUS_DOT_SIZE,
            )
        )

        pen = QPen(accent, BORDER_SELECTED if selected else BORDER)
        viewer = self.viewer()
        if viewer is not None:
            # Zoomed out, a scene-unit pen thins away to nothing; a
            # cosmetic one keeps the contour -- which is now the whole
            # signal of what type a node is -- visible.
            pen.setCosmetic(viewer.get_zoom() < 0.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(body)
        painter.restore()

    def name_bar_height(self) -> float:
        """
        Height of the filled name bar.

        The text item's own box, so the fill stops right below the name
        however the font is sized -- deliberately *not* the
        ``text height + 4`` that ``_draw_node_horizontal`` uses to place
        the first port row, which would leave a band of colour under the
        name.
        """
        return self._text_item.boundingRect().height()

    # -- text colours --------------------------------------------------

    def _set_text_color(self, color) -> None:
        """
        Colour the name and the port labels for the current theme.

        The requested colour is deliberately ignored: NodeGraphQt calls
        this from ``draw_node`` and from the ``text_color`` setter with
        its own white-on-dark default, which is invisible on the light
        theme's panel. Routing every one of those calls through the same
        rule is what keeps the labels right after a node is redrawn.
        """
        body_text = QColor(theme.current_theme().text_color)
        super()._set_text_color(
            (body_text.red(), body_text.green(), body_text.blue(), 235)
        )
        if self.selected:
            self._text_item.setDefaultTextColor(readable_on(QColor(*self.color[:3])))

    def apply_theme(self) -> None:
        """Re-read the theme (called on a dark/light toggle) and repaint."""
        self._set_text_color(self.text_color)
        self.update()

    # -- Qt overrides --------------------------------------------------

    def itemChange(self, change, value):  # noqa: N802 - Qt override
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            # The name text flips colour with the bar under it. Rubber
            # band selection never reaches a Python ``setSelected``, so
            # this is the only hook that catches every route in.
            self._set_text_color(self.text_color)
        return result

