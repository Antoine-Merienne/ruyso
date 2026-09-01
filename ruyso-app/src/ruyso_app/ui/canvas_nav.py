"""
Trackpad-first navigation for the pipeline canvas.

NodeGraphQt's viewer zooms on a plain wheel / two-finger scroll and
does not handle pinch. This event filter remaps navigation to what a
trackpad user expects:

* two-finger drag (plain wheel / pixel-scroll)  -> pan, both axes,
  following the OS "natural scrolling" direction;
* pinch                                          -> zoom;
* Cmd / Ctrl + wheel                             -> zoom (for a mouse);
* hold Space + left-drag                         -> pan (middle-button
  drag already pans in NodeGraphQt).

Left-drag rubber-band selection, node dragging and the right-click
"New Node" menu are left untouched.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QGraphicsView

#: On macOS Qt maps Cmd to ControlModifier; on Windows/Linux it's Ctrl.
_ZOOM_MODIFIERS = Qt.ControlModifier | Qt.MetaModifier

#: A pinch's ``value()`` is a small increment (~0.01 per step); scale it
#: up into the wheel-delta range NodeGraphQt's zoom expects.
_PINCH_GAIN = 400.0


class CanvasNavigation(QObject):
    """Installs on a NodeGraphQt viewer to remap pan / zoom gestures."""

    def __init__(self, viewer: QGraphicsView) -> None:
        super().__init__(viewer)
        self._viewer = viewer
        self._space_held = False
        self._panning = False
        self._last_pos = None
        viewer.installEventFilter(self)
        viewer.viewport().installEventFilter(self)

    # -- Qt event filter --------------------------------------------------

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        etype = event.type()
        if etype == QEvent.Wheel:
            return self._handle_wheel(event)
        if etype == QEvent.NativeGesture:
            return self._handle_gesture(event)
        if etype in (QEvent.KeyPress, QEvent.KeyRelease):
            return self._handle_space_key(event)
        if self._space_held and etype == QEvent.MouseButtonPress:
            return self._begin_space_pan(event)
        if self._panning and etype == QEvent.MouseMove:
            self._pan_to(event.position().toPoint())
            return True
        if self._panning and etype == QEvent.MouseButtonRelease:
            return self._end_space_pan(event)
        return False

    # -- gesture handlers ---------------------------------------------

    def _handle_wheel(self, event: QEvent) -> bool:
        viewer = self._viewer
        if event.modifiers() & _ZOOM_MODIFIERS:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta and hasattr(viewer, "_set_viewer_zoom"):
                viewer._set_viewer_zoom(delta, pos=event.position().toPoint())
            return True

        pixel = event.pixelDelta()
        if not pixel.isNull():
            dx, dy = pixel.x(), pixel.y()
        else:
            angle = event.angleDelta()
            dx, dy = angle.x() / 8.0, angle.y() / 8.0
        self._pan_by_pixels(dx, dy)
        return True

    def _handle_gesture(self, event: QEvent) -> bool:
        if event.gestureType() != Qt.ZoomNativeGesture:
            return False
        value = event.value()
        if value and hasattr(self._viewer, "_set_viewer_zoom"):
            self._viewer._set_viewer_zoom(
                value * _PINCH_GAIN, pos=event.position().toPoint()
            )
        return True

    def _handle_space_key(self, event: QEvent) -> bool:
        if event.key() != Qt.Key_Space or event.isAutoRepeat():
            return False
        viewport = self._viewer.viewport()
        if event.type() == QEvent.KeyPress:
            self._space_held = True
            if not self._panning:
                viewport.setCursor(Qt.OpenHandCursor)
        else:
            self._space_held = False
            self._panning = False
            viewport.unsetCursor()
        return True

    def _begin_space_pan(self, event: QEvent) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        self._panning = True
        self._last_pos = event.position().toPoint()
        self._viewer.viewport().setCursor(Qt.ClosedHandCursor)
        return True

    def _end_space_pan(self, event: QEvent) -> bool:
        if event.button() != Qt.LeftButton:
            return False
        self._panning = False
        cursor = Qt.OpenHandCursor if self._space_held else Qt.ArrowCursor
        self._viewer.viewport().setCursor(cursor)
        return True

    # -- panning -----------------------------------------------------

    def _pan_by_pixels(self, dx: float, dy: float) -> None:
        viewer = self._viewer
        scene_range = getattr(viewer, "_scene_range", None)
        if scene_range is None or not hasattr(viewer, "_set_viewer_pan"):
            return
        per_px_x = scene_range.width() / max(viewer.viewport().width(), 1)
        per_px_y = scene_range.height() / max(viewer.viewport().height(), 1)
        viewer._set_viewer_pan(-dx * per_px_x, -dy * per_px_y)

    def _pan_to(self, pos: object) -> None:
        viewer = self._viewer
        if self._last_pos is None or not hasattr(viewer, "_set_viewer_pan"):
            return
        delta = viewer.mapToScene(self._last_pos) - viewer.mapToScene(pos)
        viewer._set_viewer_pan(delta.x(), delta.y())
        self._last_pos = pos
