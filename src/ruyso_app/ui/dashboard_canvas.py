"""
The Dashboard canvas: an infinite, pannable / zoomable
``QGraphicsView`` with the same navigation feel as the Pipeline tab
(:mod:`ui.canvas_nav`) and **no scroll bars**.

* :class:`DashboardView` -- the view + its scene; left-drag rubber-band
  multi-selects, and a multi-selection drags as a group.
* :class:`DashboardNavigation` -- an event filter that maps trackpad
  two-finger drag / right-button drag to pan, and pinch / wheel /
  Ctrl+wheel to zoom-to-cursor. A right *click* (no travel) raises the
  canvas context menu instead of panning.
* :class:`DashboardOverlay` -- a click-through hint drawn over the
  viewport: the empty-state prompt, or the "source plot disconnected"
  message when such a figure is selected.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView, QLabel, QWidget

from ruyso_app.engine import settings
from ruyso_app.ui import theme

#: On macOS Qt maps Cmd to ControlModifier; on Windows/Linux it's Ctrl.
_ZOOM_MODIFIERS = Qt.ControlModifier | Qt.MetaModifier
#: Right-press travel (viewport px) before it pans rather than opens a menu.
_RMB_DRAG_THRESHOLD = 4
#: A pinch ``value()`` is a small increment; treat it as a scale delta.
_PINCH_GAIN = 1.0
#: Arrow-key nudge distances, in scene units.
_NUDGE = 1.0
_NUDGE_LARGE = 10.0

#: Absolute zoom clamp (view transform scale factor).
_ZOOM_MIN = 0.1
_ZOOM_MAX = 8.0


class DashboardOverlay(QLabel):
    """Centered, click-through hint drawn over the canvas viewport."""

    def __init__(self, viewport: QWidget) -> None:
        super().__init__(viewport)
        self.setObjectName("ruysoDashboardHint")  # styled in theme.stylesheet_for
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def show_message(self, text: str) -> None:
        self.setText(text or "")
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.setVisible(bool(text))
        self.raise_()


class DashboardView(QGraphicsView):
    """Infinite pan/zoom canvas hosting the dashboard's figure & text items."""

    #: Emitted with a global position for a right-click that did not pan.
    context_menu_requested = Signal(QPoint)
    #: Emitted on Delete / Backspace while no text item is being edited.
    delete_requested = Signal()
    #: Emitted after a drag that actually moved the selection, so the
    #: page can record it as one undoable step.
    items_moved = Signal()
    #: Emitted with ``(dx, dy)`` in scene units for an arrow-key nudge.
    nudge_requested = Signal(float, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-200_000, -200_000, 400_000, 400_000)
        self.setScene(self._scene)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setFrameShape(QFrame.NoFrame)

        self._nav = DashboardNavigation(self)
        self.overlay = DashboardOverlay(self.viewport())
        self.apply_theme()

    # -- helpers used by the navigation filter ------------------------

    def zoom_at(self, factor: float, viewport_pos: QPoint) -> None:
        current = self.transform().m11()
        target = current * factor
        if target < _ZOOM_MIN:
            factor = _ZOOM_MIN / current
        elif target > _ZOOM_MAX:
            factor = _ZOOM_MAX / current
        if abs(factor - 1.0) < 1e-4:
            return
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        before = self.mapToScene(viewport_pos)
        self.scale(factor, factor)
        after = self.mapToScene(viewport_pos)
        delta = after - before
        self.translate(delta.x(), delta.y())
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)

    def pan_by(self, dx: float, dy: float) -> None:
        hbar, vbar = self.horizontalScrollBar(), self.verticalScrollBar()
        hbar.setValue(int(hbar.value() - dx))
        vbar.setValue(int(vbar.value() - dy))

    # -- Qt overrides ------------------------------------------------

    def resizeEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self.overlay.setGeometry(self.viewport().rect())

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        super().mouseReleaseEvent(event)
        self.snap_selection()
        # A drag that actually moved something is one undoable step. The
        # threshold keeps a plain click -- which Qt also reports as a
        # press and a release -- from pushing an empty one.
        start = getattr(self, "_press_pos", None)
        moved = (
            start is not None
            and (event.position().toPoint() - start).manhattanLength() > 2
        )
        if moved and self._scene.selectedItems():
            self.items_moved.emit()
        self._press_pos = None

    def select_block_at(self, pos: QPoint) -> None:
        """
        Make a right-click act on the block under it.

        A block outside the selection becomes the selection, as in any
        drawing tool; one already in it keeps the whole selection, so a
        group can still be right-clicked as a group. Empty canvas leaves
        the selection alone.
        """
        item = self.itemAt(pos)
        while item is not None and not hasattr(item, "capture_state"):
            item = item.parentItem()
        if item is not None and not item.isSelected():
            self._scene.clearSelection()
            item.setSelected(True)

    def snap_selection(self) -> None:
        """
        Round the selected items' positions to the grid.

        On release rather than during the drag: snapping continuously
        makes the item lag the pointer, which reads as the drag being
        broken rather than as alignment help.
        """
        size = self.grid_size()
        if not self.snapping_enabled():
            return
        for item in self._scene.selectedItems():
            position = item.pos()
            item.setPos(
                round(position.x() / size) * size, round(position.y() / size) * size
            )

    def keyPressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if self._editing_text():
            super().keyPressEvent(event)  # the keys belong to the text box
            return

        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_requested.emit()
            return

        step = _NUDGE_LARGE if event.modifiers() & Qt.ShiftModifier else _NUDGE
        delta = {
            Qt.Key_Left: (-step, 0.0),
            Qt.Key_Right: (step, 0.0),
            Qt.Key_Up: (0.0, -step),
            Qt.Key_Down: (0.0, step),
        }.get(event.key())
        if delta is not None and self._scene.selectedItems():
            self.nudge_requested.emit(*delta)
            return
        super().keyPressEvent(event)

    def _editing_text(self) -> bool:
        """Whether a text box has the keyboard, so arrows and Delete are its."""
        focus = self._scene.focusItem()
        return (
            focus is not None
            and getattr(focus, "textInteractionFlags", None) is not None
            and focus.textInteractionFlags() != Qt.NoTextInteraction
        )

    def apply_theme(self) -> None:
        self.setBackgroundBrush(QColor(*theme.current_theme().canvas_background))
        self.viewport().update()

    def grid_size(self) -> int:
        """Spacing of the dashboard grid, in scene units (0 = disabled)."""
        try:
            size = int(settings.get("dashboard.grid_size"))
        except (TypeError, ValueError):
            return 0
        return size if size > 1 else 0

    def snapping_enabled(self) -> bool:
        return bool(settings.get("dashboard.snap")) and self.grid_size() > 0

    def drawBackground(self, painter, rect) -> None:  # noqa: N802 - Qt override
        """
        Paint the optional alignment grid behind the items.

        Drawn here rather than as scene items so it costs nothing to
        hide, never appears in the exported PDF/PNG (``QGraphicsScene.render``
        does not call a *view's* background), and cannot be selected or
        dragged by accident.
        """
        super().drawBackground(painter, rect)
        size = self.grid_size()
        if not size or not settings.get("dashboard.show_grid"):
            return
        colour = QColor(*theme.current_theme().canvas_background)
        colour = colour.lighter(112) if colour.value() < 128 else colour.darker(106)
        painter.setPen(QPen(colour, 0))
        left = int(rect.left()) - (int(rect.left()) % size)
        top = int(rect.top()) - (int(rect.top()) % size)
        for x in range(left, int(rect.right()) + 1, size):
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
        for y in range(top, int(rect.bottom()) + 1, size):
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)


class DashboardNavigation(QObject):
    """Event filter remapping pan / zoom gestures on a :class:`DashboardView`."""

    def __init__(self, view: DashboardView) -> None:
        super().__init__(view)
        self._view = view
        self._rmb_active = False
        self._rmb_panning = False
        self._press_pos: QPoint | None = None
        self._last_pos: QPoint | None = None
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        etype = event.type()
        if etype == QEvent.Wheel:
            return self._handle_wheel(event)
        if etype == QEvent.NativeGesture:
            return self._handle_gesture(event)
        if etype == QEvent.ContextMenu:
            return True  # driven from the right-button release below
        if etype == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            self._rmb_active = True
            self._rmb_panning = False
            self._press_pos = event.position().toPoint()
            self._last_pos = self._press_pos
            return True
        if self._rmb_active and etype == QEvent.MouseMove:
            return self._rmb_move(event)
        if (
            self._rmb_active
            and etype == QEvent.MouseButtonRelease
            and event.button() == Qt.RightButton
        ):
            return self._end_rmb(event)
        return False

    def _handle_wheel(self, event: QEvent) -> bool:
        pixel = event.pixelDelta()
        wheel_zoom = pixel.isNull() or bool(event.modifiers() & _ZOOM_MODIFIERS)
        if wheel_zoom:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                self._view.zoom_at(1.0015 ** delta, event.position().toPoint())
            return True
        self._view.pan_by(pixel.x(), pixel.y())
        return True

    def _handle_gesture(self, event: QEvent) -> bool:
        if event.gestureType() != Qt.ZoomNativeGesture:
            return False
        value = event.value()
        if value:
            self._view.zoom_at(1.0 + value * _PINCH_GAIN, event.position().toPoint())
        return True

    def _rmb_move(self, event: QEvent) -> bool:
        pos = event.position().toPoint()
        if not self._rmb_panning:
            if (pos - self._press_pos).manhattanLength() < _RMB_DRAG_THRESHOLD:
                return True
            self._rmb_panning = True
            self._view.viewport().setCursor(Qt.ClosedHandCursor)
        if self._last_pos is not None:
            self._view.pan_by(pos.x() - self._last_pos.x(), pos.y() - self._last_pos.y())
        self._last_pos = pos
        return True

    def _end_rmb(self, event: QEvent) -> bool:
        was_pan = self._rmb_panning
        self._rmb_active = False
        self._rmb_panning = False
        self._view.viewport().unsetCursor()
        if not was_pan:
            self._view.select_block_at(event.position().toPoint())
            global_pos = event.globalPosition().toPoint()
            self._view.context_menu_requested.emit(global_pos)
        return True
