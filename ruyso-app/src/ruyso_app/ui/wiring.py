"""
How ports and the links between them are drawn.

NodeGraphQt ships a palette of its own for this -- teal ports with a
green ring, orange links, a cyan one when selected, a yellow one on a
selected node's links -- none of which belongs to this app's two
themes. This module replaces all of it:

* a **port** is the theme's :attr:`~ui.theme.Theme.wire_color` (white on
  the dark theme, black on the light one): a ring filled with the node
  card's colour while nothing is plugged into it, a solid disc once
  something is, so wiring state is legible without a second colour. Hovering it takes the accent, the
  same colour a link takes when you select it;
* a **link** is that same wire colour at rest, and the **accent** while
  it is selected or while either end's node is;
* a link **being dragged** is its origin node's macro-type colour,
  desaturated -- it reads as "this node's, not committed yet" -- or
  :data:`INVALID_COLOR` over a target it cannot connect to;
* the **direction arrow** on a long link is :data:`ARROW_SIZE`, a little
  over half NodeGraphQt's, and **solid in the link's colour**. Upstream
  fills it with ``color.darker(200)`` inside a ``color`` outline, which
  is what made it read as two-tone.

Ports go through NodeGraphQt's supported hook -- ``add_input(...,
painter_func=)`` -- but links have none: ``PipeItem`` hard-codes the
enum colours inside ``reset`` / ``activate`` / ``highlight``, so those
three, plus the styling and live-drag methods, are patched on the class
(:func:`install_wiring`), the way ``ui/canvas_grid.py`` patches the dot
grid. Every patched method reads the theme when it runs, so a dark/light
toggle only needs :func:`refresh_wiring` to re-apply the current state.
"""

from __future__ import annotations

from typing import Any

from NodeGraphQt.constants import PipeEnum
from NodeGraphQt.qgraphics.pipe import PIPE_STYLES, LivePipeItem, PipeItem
from NodeGraphQt.qgraphics.port import CustomPortItem, PortItem
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

from ruyso_app.ui import theme

#: Outline width of a port, in scene units.
PORT_PEN = 1.4

#: Half-width of the direction arrow, in scene units. NodeGraphQt's is 6.0.
ARROW_SIZE = 3.5

#: Link width at rest, and while selected / on a selected node.
PIPE_WIDTH = 1.6
PIPE_WIDTH_ACTIVE = 2.6

#: How far a dragged link's colour is pulled toward grey (0 = untouched).
LIVE_DESATURATION = 0.55

#: A link being dragged somewhere it cannot connect.
INVALID_COLOR = "#d1495b"

#: Set on ``PipeItem`` once the class has been patched.
_PATCHED_FLAG = "_ruyso_wiring"


def wire_color() -> QColor:
    """The theme's colour for ports and links."""
    return QColor(theme.current_theme().wire_color)


def accent_color() -> QColor:
    """The app's accent -- a hovered port, a selected link."""
    return QColor(theme.accent_color() or theme.current_theme().highlight_color)


def desaturated(color: QColor) -> QColor:
    """
    ``color`` pulled toward grey, keeping its hue.

    A link being dragged is the origin node's colour held back a step:
    recognisably that node's, visibly not yet a connection.
    """
    hue, saturation, value, alpha = color.getHsvF()
    if hue < 0:  # achromatic: nothing to desaturate
        return QColor(color)
    return QColor.fromHsvF(
        hue, max(saturation * (1.0 - LIVE_DESATURATION), 0.0), value, alpha
    )


def _as_qcolor(color: Any) -> QColor:
    """NodeGraphQt passes ``(r, g, b[, a])``; this module passes QColors."""
    if isinstance(color, QColor):
        return QColor(color)
    try:
        return QColor(*color)
    except (TypeError, ValueError):
        return wire_color()


def _arrow_polygon() -> QPolygonF:
    size = ARROW_SIZE
    arrow = QPolygonF()
    arrow.append(QPointF(-size, size))
    arrow.append(QPointF(0.0, -size * 1.5))
    arrow.append(QPointF(size, size))
    return arrow


# --------------------------------------------------------------------------
# ports
# --------------------------------------------------------------------------


def paint_port(painter: QPainter, rect: Any, info: dict) -> None:
    """
    Draw one port: a ring in the wire colour, filled once it is connected.

    Handed to every generated node's ports by ``ui/node_factory.py``.
    NodeGraphQt's own ``PortItem.paint`` only consults a port's colour
    while it is idle -- a hovered or *connected* port falls back to the
    hard-coded enum colours -- so a painter is the only way to hold one
    colour through every state.
    """
    colour = accent_color() if info.get("hovered") else wire_color()
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(colour, PORT_PEN))
    # Unplugged: filled with the node card's colour, so the contour it
    # sits on does not show through the ring.
    fill = colour if info.get("connected") else QColor(theme.current_theme().panel_background)
    painter.setBrush(QBrush(fill))
    # Inset by half the pen, or the ring is clipped by the port's own rect.
    painter.drawEllipse(rect.adjusted(PORT_PEN / 2, PORT_PEN / 2, -PORT_PEN / 2, -PORT_PEN / 2))
    painter.restore()


# --------------------------------------------------------------------------
# links
# --------------------------------------------------------------------------


def _set_pipe_styling(self, color, width=2, style=0) -> None:
    """Replaces ``PipeItem.set_pipe_styling``: smaller, solid arrow."""
    colour = _as_qcolor(color)

    pen = self.pen()
    pen.setWidthF(float(width))
    pen.setColor(colour)
    pen.setStyle(PIPE_STYLES.get(style, Qt.SolidLine))
    pen.setJoinStyle(Qt.MiterJoin)
    pen.setCapStyle(Qt.RoundCap)
    self.setPen(pen)
    self.setBrush(QBrush(Qt.NoBrush))

    pointer = self._dir_pointer
    pointer.setPolygon(_arrow_polygon())
    pen = pointer.pen()
    pen.setJoinStyle(Qt.MiterJoin)
    pen.setCapStyle(Qt.RoundCap)
    # Hairline outline in the same colour: the fill *is* the arrow. A
    # wide outline around a small triangle swallows it.
    pen.setWidthF(0.0)
    pen.setColor(colour)
    pointer.setPen(pen)
    pointer.setBrush(colour)


def _reset(self) -> None:
    """A link at rest is the theme's wire colour."""
    self._active = False
    self._highlight = False
    self.set_pipe_styling(color=wire_color(), width=PIPE_WIDTH, style=self.style)
    self._draw_direction_pointer()


def _activate(self) -> None:
    """Selected (or hovered): the app's accent."""
    self._active = True
    self.set_pipe_styling(
        color=accent_color(),
        width=PIPE_WIDTH_ACTIVE,
        style=PipeEnum.DRAW_TYPE_DEFAULT.value,
    )


def _highlight(self) -> None:
    """One end's node is selected: the accent again, so a selection shows
    its whole neighbourhood in one colour."""
    self._highlight = True
    self.set_pipe_styling(
        color=accent_color(),
        width=PIPE_WIDTH_ACTIVE,
        style=PipeEnum.DRAW_TYPE_DEFAULT.value,
    )


def live_color(start_port: Any, invalid: bool) -> QColor:
    """The colour of a link being dragged out of ``start_port``."""
    if invalid:
        return QColor(INVALID_COLOR)
    node = getattr(start_port, "node", None)
    node_colour = getattr(node, "color", None)
    if not node_colour:
        return desaturated(wire_color())
    return desaturated(QColor(*tuple(node_colour)[:3]))


def _live_draw_path(self, start_port, end_port=None, cursor_pos=None, color=None) -> None:
    """
    Replaces ``LivePipeItem.draw_path``.

    ``color`` is only ever passed by the viewer when the pointer is over
    something the link cannot attach to, which is exactly the invalid
    case -- so it is read as a flag rather than used as a colour.
    """
    PipeItem.draw_path(self, start_port, end_port, cursor_pos)
    self.set_pipe_styling(
        color=live_color(start_port, invalid=color is not None),
        width=PIPE_WIDTH_ACTIVE,
        style=PipeEnum.DRAW_TYPE_DASHED.value,
    )
    self.draw_index_pointer(start_port, cursor_pos, color)


def _live_index_pointer(self, start_port, cursor_pos, color=None) -> None:
    """The cursor arrow and the port label follow the live link's colour."""
    _ORIGINAL_INDEX_POINTER(self, start_port, cursor_pos, color)
    colour = live_color(start_port, invalid=color is not None)
    pointer = self._idx_pointer
    pen = pointer.pen()
    pen.setColor(colour)
    pointer.setPen(pen)
    pointer.setBrush(colour)
    self._idx_text.setDefaultTextColor(colour)


#: Captured before patching, so the replacement can reuse its geometry.
_ORIGINAL_INDEX_POINTER = LivePipeItem.draw_index_pointer


def install_wiring() -> None:
    """Patch NodeGraphQt's link classes. Idempotent."""
    if getattr(PipeItem, _PATCHED_FLAG, False):
        return
    PipeItem.set_pipe_styling = _set_pipe_styling
    PipeItem.reset = _reset
    PipeItem.activate = _activate
    PipeItem.highlight = _highlight
    LivePipeItem.draw_path = _live_draw_path
    LivePipeItem.draw_index_pointer = _live_index_pointer
    setattr(PipeItem, _PATCHED_FLAG, True)


def refresh_wiring(graph: Any) -> None:
    """
    Re-apply the current theme to every port and link on ``graph``.

    Each patched method reads the theme as it runs, so re-running the
    state a link is already in is all a dark/light toggle needs.
    """
    viewer = graph.viewer()
    scene = viewer.scene() if viewer is not None else None
    if scene is None:
        return
    for item in scene.items():
        if isinstance(item, LivePipeItem):
            continue  # only visible mid-drag, and coloured on every redraw
        if isinstance(item, PipeItem):
            if item.active():
                item.activate()
            elif item.highlighted():
                item.highlight()
            else:
                item.reset()
        elif isinstance(item, (CustomPortItem, PortItem)):
            item.update()
