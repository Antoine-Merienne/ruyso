"""
Navigation for the pipeline canvas -- usable with a trackpad *or* with
a plain mouse (no trackpad required).

NodeGraphQt's viewer zooms on a plain wheel and does not handle pinch.
This event filter remaps navigation to what each device's user
expects:

Trackpad
* two-finger drag (pixel-scroll wheel)  -> pan, both axes, following
  the OS "natural scrolling" direction;
* pinch                                  -> zoom;
* hold Space + left-drag                 -> pan.

Mouse
* right-button drag                      -> pan;
* mouse wheel                            -> zoom to the cursor;
* Cmd / Ctrl + wheel                     -> zoom (either device).

A right *click* that never travels far enough to become a drag still
opens NodeGraphQt's "New Node" context menu (driven from the button
release here, so the menu never flashes up mid-pan).

Left-drag rubber-band selection, node dragging and middle-button pan
are left untouched.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QGraphicsView

#: On macOS Qt maps Cmd to ControlModifier; on Windows/Linux it's Ctrl.
_ZOOM_MODIFIERS = Qt.ControlModifier | Qt.MetaModifier

#: A pinch's ``value()`` is a small increment (~0.01 per step); scale it
#: up into the wheel-delta range NodeGraphQt's zoom expects.
_PINCH_GAIN = 400.0

#: A right-button press must travel at least this far (viewport pixels)
#: before it is treated as a pan rather than a context-menu click.
_RMB_DRAG_THRESHOLD = 4


class CanvasNavigation(QObject):
    """Installs on a NodeGraphQt viewer to remap pan / zoom gestures."""

    def __init__(self, viewer: QGraphicsView) -> None:
        super().__init__(viewer)
        self._viewer = viewer
        self._space_held = False
        self._panning = False  # Space + left-drag in progress
        self._rmb_active = False  # right button currently held down
        self._rmb_panning = False  # right-drag has passed the threshold
        self._rmb_press_pos: QPoint | None = None
        self._last_pos: QPoint | None = None
        viewer.installEventFilter(self)
        viewer.viewport().installEventFilter(self)

    # -- Qt event filter --------------------------------------------------

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        etype = event.type()
        if etype == QEvent.Wheel:
            return self._handle_wheel(event)
        if etype == QEvent.NativeGesture:
            return self._handle_gesture(event)
        if etype == QEvent.ContextMenu:
            # The context menu is driven from the right-button release
            # (see ``_end_rmb``) so a right-drag can pan without a menu
            # appearing. Swallow every automatic one.
            return True
        if etype in (QEvent.KeyPress, QEvent.KeyRelease):
            return self._handle_space_key(event)

        if etype == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            return self._begin_rmb(event)
        if self._rmb_active and etype == QEvent.MouseMove:
            return self._rmb_move(event)
        if (
            self._rmb_active
            and etype == QEvent.MouseButtonRelease
            and event.button() == Qt.RightButton
        ):
            return self._end_rmb(event)

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
        pixel = event.pixelDelta()
        # A real mouse wheel reports only angleDelta (no pixelDelta); a
        # trackpad two-finger scroll reports pixelDelta. Zoom for the
        # wheel (and for an explicit zoom modifier on either device),
        # pan for the trackpad.
        wheel_zoom = pixel.isNull() or bool(event.modifiers() & _ZOOM_MODIFIERS)
        if wheel_zoom:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta and hasattr(viewer, "_set_viewer_zoom"):
                viewer._set_viewer_zoom(delta, pos=event.position().toPoint())
            return True

        self._pan_by_pixels(pixel.x(), pixel.y())
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

    # -- right-button drag-pan / click-menu -------------------------

    def _begin_rmb(self, event: QEvent) -> bool:
        self._rmb_active = True
        self._rmb_panning = False
        self._rmb_press_pos = event.position().toPoint()
        self._last_pos = self._rmb_press_pos
        return True

    def _rmb_move(self, event: QEvent) -> bool:
        pos = event.position().toPoint()
        if not self._rmb_panning:
            travelled = (pos - self._rmb_press_pos).manhattanLength()
            if travelled < _RMB_DRAG_THRESHOLD:
                return True
            self._rmb_panning = True
            self._viewer.viewport().setCursor(Qt.ClosedHandCursor)
        self._pan_to(pos)
        return True

    def _end_rmb(self, event: QEvent) -> bool:
        was_pan = self._rmb_panning
        self._rmb_active = False
        self._rmb_panning = False
        self._rmb_press_pos = None
        self._viewer.viewport().unsetCursor()
        if not was_pan:
            self._open_context_menu(event.position().toPoint())
        return True

    def _open_context_menu(self, pos: QPoint) -> None:
        """Fire NodeGraphQt's own context menu at ``pos`` (viewport coords).

        Deferred to the next event-loop tick: the menu is modal
        (``exec_``), and opening it synchronously from inside this event
        filter while Qt is still delivering the mouse-release event is a
        re-entrancy hazard.
        """
        viewer = self._viewer
        handler = getattr(viewer, "contextMenuEvent", None)
        if handler is None:
            return
        # NodeGraphQt positions the menu from ``_previous_pos``.
        viewer._previous_pos = QPoint(pos)
        global_pos = viewer.viewport().mapToGlobal(pos)
        menu_event = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(pos), global_pos)
        QTimer.singleShot(0, lambda: handler(menu_event))

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
