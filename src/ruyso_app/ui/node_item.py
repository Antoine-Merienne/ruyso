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
* corners are :data:`RADIUS`.

Text follows the same rule (:meth:`RuysoNodeItem._set_text_color`): the
name and the port labels take the theme's text colour, except the name
while the node is selected, which flips to whatever reads on the macro
colour -- white on the blue loader, near-black on the orange transform.

Two things here exist for the figure preview beneath a grapher node
(``ui/node_preview.py``):

* **geometry notifications** -- the item sends ``ItemPositionHasChanged``
  and reports :meth:`draw_node` resizes to ``geometry_listener``, so the
  preview card is re-placed in the *same frame* the node moves. The
  preview used to be a widget re-placed by a timer, which trailed the
  node by up to four frames and made every drag look jagged;
* the **collapse chevron** on the right of the name bar, drawn only on
  a node that has a preview (:attr:`has_preview`), pointing down while
  the preview shows and right while it is collapsed.
"""

from __future__ import annotations

from typing import Callable

from NodeGraphQt.qgraphics.node_base import NodeItem
from PySide6.QtCore import QPointF, QRectF, Qt
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

#: Size of the preview collapse chevron's box, in scene units.
CHEVRON_SIZE = 9.0

#: Extra slop around the chevron for clicking it: a 9-unit target is
#: a fiddly thing to hit at 1:1 zoom.
CHEVRON_HIT_SLOP = 5.0

#: Inset of the contour from the item's bounding rect. Half the widest
#: pen, so a selected node's contour is not clipped by its own bounds.
_MARGIN = BORDER_SELECTED / 2.0

#: Inset of the status dot and the chevron from the card's side edges,
#: so the rounded corners do not cut into them.
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

        # Without this flag Qt never calls itemChange for a move, and
        # the preview card would have nothing to follow the node by.
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        #: Called with this item whenever it moves or is re-laid out.
        #: A plain callable rather than a Qt signal: QGraphicsItem is not
        #: a QObject, and the preview manager is the only listener.
        self.geometry_listener: Callable[[RuysoNodeItem], None] | None = None
        #: Whether this node has a figure preview (and so a chevron).
        self.has_preview = False
        #: Whether that preview is collapsed. Kept on the node rather
        #: than on the card, so it survives the card being rebuilt --
        #: which is what deleting a node and undoing it does.
        self.preview_collapsed = False

    # -- run status ----------------------------------------------------

    def set_status_colour(self, colour: QColor) -> None:
        """Paint the status dot (see ``ui/node_status.py``)."""
        self._status_colour = QColor(colour)
        self.update()

    def status_colour(self) -> QColor:
        return QColor(self._status_colour)

    # -- figure preview ------------------------------------------------

    def set_preview_collapsed(self, collapsed: bool) -> None:
        """Collapse or expand this node's preview, and tell the listener."""
        collapsed = bool(collapsed)
        if collapsed == self.preview_collapsed:
            return
        self.preview_collapsed = collapsed
        self.update()
        self._notify_geometry()

    def chevron_rect(self) -> QRectF:
        """The chevron's box, in item coordinates."""
        rect = self._card_rect()
        return QRectF(
            rect.right() - _LEFT_INSET - CHEVRON_SIZE,
            self._text_item.boundingRect().center().y() - CHEVRON_SIZE / 2.0,
            CHEVRON_SIZE,
            CHEVRON_SIZE,
        )

    def chevron_hit(self, scene_pos: QPointF) -> bool:
        """Whether ``scene_pos`` lands on this node's chevron."""
        if not self.has_preview:
            return False
        target = self.chevron_rect().adjusted(
            -CHEVRON_HIT_SLOP, -CHEVRON_HIT_SLOP, CHEVRON_HIT_SLOP, CHEVRON_HIT_SLOP
        )
        return target.contains(self.mapFromScene(scene_pos))

    def _notify_geometry(self) -> None:
        listener = getattr(self, "geometry_listener", None)
        if listener is None:
            return
        try:
            listener(self)
        except RuntimeError:  # the card is already gone during teardown
            pass

    # -- painting ------------------------------------------------------

    def _card_rect(self) -> QRectF:
        return self.boundingRect().adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN)

    def _paint_horizontal(self, painter, option, widget) -> None:  # noqa: N802
        painter.save()
        rect = self._card_rect()
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

        if self.has_preview:
            self._paint_chevron(painter, accent, selected)

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

    def _paint_chevron(self, painter: QPainter, accent: QColor, selected: bool) -> None:
        """A down-pointing chevron while the preview shows, right while collapsed.

        Drawn in the name's own colour -- including the flip to whatever
        reads on the macro colour while the name bar is filled -- so it
        belongs to the title rather than competing with it.
        """
        box = self.chevron_rect()
        colour = (
            readable_on(accent)
            if selected
            else QColor(theme.current_theme().text_color)
        )
        colour.setAlpha(200)
        pen = QPen(colour, 1.6)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inset = box.width() * 0.2
        if self.preview_collapsed:  # >
            points = [
                QPointF(box.left() + inset * 1.5, box.top() + inset * 0.5),
                QPointF(box.right() - inset * 1.5, box.center().y()),
                QPointF(box.left() + inset * 1.5, box.bottom() - inset * 0.5),
            ]
        else:  # v
            points = [
                QPointF(box.left() + inset * 0.5, box.top() + inset * 1.5),
                QPointF(box.center().x(), box.bottom() - inset * 1.5),
                QPointF(box.right() - inset * 0.5, box.top() + inset * 1.5),
            ]
        painter.drawPolyline(points)

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

    def _align_ports_horizontal(self, v_offset) -> None:
        """Centre ports on the contour line, not on the item's outer edge."""
        super()._align_ports_horizontal(v_offset)
        for ports, items, dx in (
            (self.inputs, self._input_items, _MARGIN),
            (self.outputs, self._output_items, -_MARGIN),
        ):
            for port in ports:
                port.moveBy(dx, 0.0)
                items[port].moveBy(dx, 0.0)

    def draw_node(self) -> None:
        """Re-lay the node out, then let the preview follow its new size."""
        super().draw_node()
        self._notify_geometry()

    def itemChange(self, change, value):  # noqa: N802 - Qt override
        result = super().itemChange(change, value)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            # The name text flips colour with the bar under it. Rubber
            # band selection never reaches a Python ``setSelected``, so
            # this is the only hook that catches every route in.
            self._set_text_color(self.text_color)
        elif change == QGraphicsItem.ItemPositionHasChanged:
            self._notify_geometry()
        return result
