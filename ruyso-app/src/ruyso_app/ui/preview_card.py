"""
The figure preview card beneath a grapher node.

A card is a ``QGraphicsItem`` in the canvas scene -- not a widget laid
over it. That is the whole fix for the preview "lagging" behind a
dragged node: a widget over a ``QGraphicsView`` has to be re-placed from
outside, and the timer that did it caught up only every fourth frame (a
0 -> 6 -> 12 -> 18 px sawtooth). A scene item is re-placed from the
node's own ``itemChange`` (``ui/node_item.py``), in the same frame the
node moves, and it stacks with the canvas instead of always painting
over it: :data:`Z_VALUE` puts it above the wires and below every node.

It is deliberately **not** a child item of the node. A child is deleted
with its C++ parent while Python still holds the wrapper, and collecting
that wrapper afterwards segfaults in NodeGraphQt's ``QUndoStack``
teardown; a scene-owned item is removed explicitly and has no such
problem.

What is drawn:

* a rounded card in the theme's panel colour with a hairline border --
  the node keeps the macro-type colour as its identity;
* inside it the figure on its own white plate, as it will export;
* before a run, a muted placeholder line instead of the plate.

The figure is a **bitmap at the resolution it is shown at**: rasterised
for the plate's on-screen width times the device pixel ratio, rounded up
to a power of two (:func:`raster_bucket`) so zooming re-renders only at
real steps. Drawing a cached bitmap costs almost nothing on each frame
of a drag; the old preview was scaled at *logical* size and shown on a
2x screen, which is why its tick labels were unreadable.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem

from ruyso_app.core.figure_lock import figure_guard
from ruyso_app.ui import theme

#: Stacking: above the wires (NodeGraphQt's ``Z_VAL_PIPE`` is -1) and
#: below every node (``Z_VAL_NODE`` is 1), so a card never covers a
#: neighbouring node.
Z_VALUE = 0.0

#: Space between the bottom of the node and the top of its card.
GAP = 6.0

#: Corner radius of the card and of the plate inside it.
RADIUS = 12.0
PLATE_RADIUS = 7.0

#: Inset of the figure's plate from the card's edge.
PLATE_MARGIN = 6.0

#: Plate height / width before there is a figure to take it from, and
#: the range a figure's own proportions are clamped to -- a 6 x 2.2
#: strip stays a strip, but nothing becomes a ribbon or a tower.
DEFAULT_ASPECT = 2.0 / 3.0
MIN_ASPECT = 0.3
MAX_ASPECT = 1.2

#: Card width, in scene units, that ``appearance.thumbnail_width`` is
#: measured against: the default preference gives a card exactly as
#: wide as its node.
BASE_WIDTH = 180.0

#: Below this many on-screen pixels of plate width the plot is not
#: drawn -- only the white plate -- the way nodes drop to proxy mode.
PROXY_PIXELS = 70.0

#: Bounds on a rasterised bitmap's width, in device pixels.
MIN_RASTER_PX = 128
MAX_RASTER_PX = 2048

#: Font size of the placeholder, in scene units (so it zooms with the card).
PLACEHOLDER_PX = 10


def raster_bucket(pixels: float) -> int:
    """A wanted bitmap width rounded up to a power of two, and clamped."""
    wanted = max(float(pixels), 1.0)
    bucket = 2 ** math.ceil(math.log2(wanted))
    return int(min(max(bucket, MIN_RASTER_PX), MAX_RASTER_PX))


def figure_aspect(figure: Any) -> float:
    """
    The plate proportions for ``figure``: its height / width, clamped.

    Under the figure guard: a save in flight on the render thread
    temporarily rewrites the very numbers this reads, and a plate shaped
    from that reading does not match the picture that lands in it.
    """
    try:
        with figure_guard():
            width_in, height_in = figure.get_size_inches()
    except (AttributeError, TypeError, ValueError):
        return DEFAULT_ASPECT
    if not width_in or width_in <= 0:
        return DEFAULT_ASPECT
    return min(max(float(height_in) / float(width_in), MIN_ASPECT), MAX_ASPECT)


def _fit(bounds: QRectF, width: float, height: float) -> QRectF:
    """The largest ``width`` x ``height`` rectangle centred in ``bounds``."""
    if width <= 0 or height <= 0:
        return QRectF(bounds)
    scale = min(bounds.width() / width, bounds.height() / height)
    fitted_w, fitted_h = width * scale, height * scale
    return QRectF(
        bounds.center().x() - fitted_w / 2.0,
        bounds.center().y() - fitted_h / 2.0,
        fitted_w,
        fitted_h,
    )


class PreviewCard(QGraphicsItem):
    """One node's figure preview, as an item in the canvas scene."""

    def __init__(
        self,
        node_id: str,
        placeholder: str,
        request_render: Callable[[str, Any, int], None],
    ) -> None:
        super().__init__()
        #: NodeGraphQt's id of the node this card belongs to.
        self.node_id = node_id
        #: Called with ``node_id`` when the bitmap no longer matches the
        #: zoom; the manager batches these rather than re-rendering
        #: during a zoom gesture.
        self.request_upgrade: Callable[[str], None] | None = None
        #: Bitmap width the last paint asked for.
        self.wanted_px = 0
        #: Device pixels per scene unit at the last paint (view zoom times
        #: the screen's pixel ratio), or ``None`` before the first paint.
        self._device_scale: float | None = None

        #: Asks the manager for a bitmap; the answer comes back through
        #: :meth:`apply_render`, usually from the render thread.
        self._request_render = request_render
        self._placeholder = placeholder
        self._figure: Any = None
        self._aspect = DEFAULT_ASPECT
        self._width = BASE_WIDTH
        self._pixmap: QPixmap | None = None
        self._pixmap_px = 0
        #: The figure the bitmap on screen was drawn from, which is not
        #: the current one while a render is in flight.
        self._rendered_figure: Any = None
        #: Bitmap width already asked for and not yet delivered.
        self._pending_px = 0

        self.setZValue(Z_VALUE)
        self.setCursor(Qt.PointingHandCursor)
        # Clicks are handled by the manager's viewport filter: NodeGraphQt's
        # viewer treats anything that is not a node or a wire as empty
        # canvas and starts a rubber band before a press reaches the scene.
        self.setAcceptedMouseButtons(Qt.NoButton)

    # -- geometry ------------------------------------------------------

    def plate_width(self) -> float:
        return max(self._width - 2.0 * PLATE_MARGIN, 1.0)

    def plate_rect(self) -> QRectF:
        width = self.plate_width()
        return QRectF(PLATE_MARGIN, PLATE_MARGIN, width, width * self._aspect)

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        return QRectF(0.0, 0.0, self._width, self.plate_rect().height() + 2.0 * PLATE_MARGIN)

    def set_width(self, width: float) -> None:
        width = max(float(width), 40.0)
        if abs(width - self._width) < 0.01:
            return
        self.prepareGeometryChange()
        self._width = width

    # -- content -------------------------------------------------------

    def has_figure(self) -> bool:
        return self._figure is not None

    def figure(self) -> Any:
        return self._figure

    def placeholder(self) -> str:
        return self._placeholder

    def pixmap(self) -> QPixmap | None:
        return self._pixmap

    def pixmap_pixels(self) -> int:
        """Width, in device pixels, of the bitmap currently held."""
        return self._pixmap_px

    def show_placeholder(self, text: str) -> None:
        if self._figure is None and text == self._placeholder:
            return
        self.prepareGeometryChange()
        self._figure = None
        self._pixmap = None
        self._pixmap_px = 0
        self._rendered_figure = None
        self._pending_px = 0
        self._placeholder = text
        self._aspect = DEFAULT_ASPECT
        self.update()

    def set_figure(self, figure: Any, device_pixel_ratio: float = 1.0) -> None:
        """
        Show ``figure``, unless it is the one already shown.

        The skip cache hands an unchanged grapher's *same* Figure back
        rather than re-running it, so identity is exactly the right
        question: same object, same pixels, and rasterising it again on
        every keystroke-triggered background run would be pure waste.

        A new figure is rendered for the zoom the card was last *painted*
        at, not for 1:1. Auto-run hands back a new figure after every
        edit, and rendering each one at 1:1 left a zoomed-in card blurry
        after every change -- and cost a second render once the next
        paint noticed. ``device_pixel_ratio`` only matters before the
        card has been painted at all.

        The bitmap on screen is **kept** until the new one is drawn, and
        its shape with it: drawing happens on the render thread now, so
        dropping either here left the card blank -- or, worse, drew the
        old plot letterboxed inside the new plot's proportions -- for as
        long as the render took. The two belong together: a plate's
        shape describes the picture in it, not the figure queued behind.
        """
        if figure is self._figure and (
            self._pixmap is not None or self._pending_px
        ):
            return
        self._figure = figure
        self._pending_px = 0
        scale = self._device_scale if self._device_scale else float(device_pixel_ratio)
        self.rasterise_at(self.plate_width() * scale)

    def rasterise_at(self, pixels: float) -> None:
        """
        Ask for the bitmap of a plate ``pixels`` device pixels wide.

        Only ever *asks*: the drawing happens on the render thread and
        arrives at :meth:`apply_render`, so a slow figure no longer
        freezes the window while a run's results are merged. Until it
        lands the card keeps whatever it was showing.
        """
        if self._figure is None:
            return
        bucket = raster_bucket(pixels)
        if (
            self._pixmap is not None
            and bucket == self._pixmap_px
            and self._rendered_figure is self._figure
        ):
            return  # already showing exactly this, drawn from this figure
        if bucket == self._pending_px:
            return  # already asked for it
        self._pending_px = bucket
        self._request_render(self.node_id, self._figure, bucket)

    def apply_render(self, figure: Any, pixels: int, pixmap: QPixmap) -> None:
        """
        Take a finished bitmap, unless it is for a figure the card has
        already moved on from -- a render in flight when the next run
        lands is drawn from data nobody is showing any more.
        """
        if figure is not self._figure:
            return
        if pixmap is None or pixmap.isNull():
            self.render_failed(figure)
            return
        # The plate takes its shape from the picture now going into it,
        # which is why the aspect moves here and not in set_figure.
        aspect = figure_aspect(figure)
        if aspect != self._aspect:
            self.prepareGeometryChange()
            self._aspect = aspect
        self._pending_px = 0
        self._pixmap = pixmap
        self._pixmap_px = int(pixels)
        self._rendered_figure = figure
        self.update()

    def render_failed(self, figure: Any) -> None:
        """
        Forget a request that produced nothing.

        Without this the card holds ``_pending_px`` for a size it will
        never receive, and every later ask for that size is dropped as
        "already requested" -- a card stuck on an old picture, or on
        none at all, for as long as the figure lives.
        """
        if figure is self._figure:
            self._pending_px = 0

    # -- painting ------------------------------------------------------

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:
        palette = theme.current_theme()
        bounds = self.boundingRect()
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        card = QPainterPath()
        card.addRoundedRect(bounds.adjusted(0.5, 0.5, -0.5, -0.5), RADIUS, RADIUS)
        painter.fillPath(card, QColor(palette.panel_background))
        hairline = QPen(QColor(palette.border_color), 1.0)
        hairline.setCosmetic(True)  # one device pixel at every zoom
        painter.setPen(hairline)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(card)

        plate = self.plate_rect()
        if self._figure is None:
            font = QFont(painter.font())
            font.setPixelSize(PLACEHOLDER_PX)
            painter.setFont(font)
            painter.setPen(QColor(theme.muted_text_color(palette)))
            painter.drawText(plate, int(Qt.AlignCenter | Qt.TextWordWrap), self._placeholder)
            painter.restore()
            return

        plate_path = QPainterPath()
        plate_path.addRoundedRect(plate, PLATE_RADIUS, PLATE_RADIUS)
        painter.fillPath(plate_path, QColor("white"))

        scale = option.levelOfDetailFromTransform(painter.worldTransform())
        on_screen = plate.width() * scale
        if on_screen >= PROXY_PIXELS and self._pixmap is not None and not self._pixmap.isNull():
            painter.setClipPath(plate_path)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            painter.drawPixmap(
                _fit(plate, self._pixmap.width(), self._pixmap.height()),
                self._pixmap,
                QRectF(self._pixmap.rect()),
            )
            device = painter.device()
            ratio = device.devicePixelRatioF() if device is not None else 1.0
            self._device_scale = scale * ratio
            wanted = raster_bucket(on_screen * ratio)
            # Ask only when the wanted size *changes*. Asking on every paint
            # let any unrelated repaint -- a status-dot animation, a hover --
            # keep restarting the manager's debounce, so an upgrade fired
            # only once the canvas went quiet: always a zoom step behind.
            if wanted != self.wanted_px:
                self.wanted_px = wanted
                if wanted != self._pixmap_px and self.request_upgrade is not None:
                    self.request_upgrade(self.node_id)
        painter.restore()
