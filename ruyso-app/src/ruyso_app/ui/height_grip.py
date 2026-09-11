"""
A drag handle that caps the height of the widget above it.

The Table tab's description panel scrolls, so its two variable tables
cannot be sized by a ``QSplitter`` -- a splitter needs a fixed viewport
to divide, and there isn't one inside a scroll area. This is the small
alternative, drawn with the same three dots as the splitter handles
(``ruysoHeightGrip`` in :mod:`ui.theme`) so the two read as the same
affordance.

It is a **cap**, not a height. A table stays exactly as tall as its
rows; the grip only matters once there are more rows than fit, and then
it decides how much of the panel that table is allowed to take before it
starts scrolling inside itself. Dragging back down past the content
returns it to following the content, and the grip hides itself again --
there is nothing left for it to do.

Resizing happens only while a drag is in progress. Acting on every
mouse-move made the table jump the moment the pointer crossed the grip,
because a move event with no button held carries no drag to measure
against.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

#: Height of the grip bar itself.
GRIP_HEIGHT = 9
#: The smallest a capped widget may become.
MIN_TARGET_HEIGHT = 48
#: How tall a table is allowed to grow before it is capped and scrolls.
DEFAULT_CAP = 200


class HeightGrip(QWidget):
    """Drag to cap ``target``'s height; double-click to restore the default."""

    def __init__(
        self,
        target: QWidget,
        cap: int = DEFAULT_CAP,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoHeightGrip")  # styled in theme.stylesheet_for
        # A bare QWidget paints no stylesheet background without this,
        # so the grip resized the table while showing nothing at all.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(GRIP_HEIGHT)
        self.setCursor(Qt.SizeVerCursor)

        self._target = target
        self._default_cap = int(cap)
        self._cap = int(cap)
        self._content = int(cap)
        self._dragging = False
        self._press_y = 0
        self._press_height = 0

    # -- what the panel drives ----------------------------------------

    def set_content_height(self, height: int) -> None:
        """Tell the grip how tall the target's content wants to be."""
        self._content = max(MIN_TARGET_HEIGHT, int(height))
        self._apply()
        self._refresh_visibility()

    def height_of_target(self) -> int:
        """The height the target is currently held at."""
        return min(self._content, self._cap)

    def resize_target(self, height: int) -> None:
        """Cap the target at ``height`` (clamped to the minimum)."""
        self._cap = max(MIN_TARGET_HEIGHT, int(height))
        self._apply()

    def reset(self) -> None:
        """Back to the default cap -- a drag is easy to overshoot."""
        self._cap = self._default_cap
        self._apply()
        self._refresh_visibility()

    def is_capping(self) -> bool:
        """Whether the cap is actually holding the content back."""
        return self._content > self._cap

    # -- Qt overrides --------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        self._dragging = True
        self._press_y = int(event.globalPosition().y())
        self._press_height = self.height_of_target()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Without this guard the target jumps to an arbitrary height the
        # moment the pointer crosses the grip: a hover move has no press
        # to measure the drag from.
        if not self._dragging:
            event.ignore()
            return
        delta = int(event.globalPosition().y()) - self._press_y
        self.resize_target(self._press_height + delta)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if not self._dragging:
            event.ignore()
            return
        self._dragging = False
        # Only now: hiding the grip mid-drag would end the drag under
        # the pointer.
        self._refresh_visibility()
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.reset()
        event.accept()

    # -- internals -----------------------------------------------------

    def _apply(self) -> None:
        self._target.setFixedHeight(self.height_of_target())

    def _refresh_visibility(self) -> None:
        """Show the grip only while capping the table does something."""
        self.setVisible(self.is_capping())
