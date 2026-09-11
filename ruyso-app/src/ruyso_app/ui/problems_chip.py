"""
The "problems" chip in the tab band, right of the "auto" pill.

A count of the failures in the pipeline as it currently stands, kept
where the eye already goes for run state. It is **hidden while there
are none**: an always-present "0 problems" is a thing to learn to
ignore, and the point of the chip is that it appears.

Clicking it takes you to the Problems panel on the Pipeline tab, so the
chip is a route to the detail rather than a second place the detail is
written. Styling comes from ``theme.stylesheet_for``'s
``#ruysoProblemsChip`` rules, keyed off a Qt dynamic property, so it
restyles itself on a dark/light toggle with no code here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class ProblemsChip(QWidget):
    """A rounded ``[● 3 problems]`` chip; hidden when the count is zero."""

    #: Emitted on a left click (press + release within the chip).
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoProblemsChip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)

        self._dot = QLabel(self)
        self._dot.setObjectName("ruysoProblemsDot")
        self._dot.setFixedSize(8, 8)

        self._label = QLabel("", self)
        self._label.setObjectName("ruysoProblemsLabel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 10, 2)
        layout.setSpacing(6)
        layout.addWidget(self._dot, 0, Qt.AlignVCenter)
        layout.addWidget(self._label, 0, Qt.AlignVCenter)

        self._count = 0
        self.set_count(0)

    def set_count(self, count: int) -> None:
        """Show ``count`` problems, or hide the chip when there are none."""
        self._count = max(0, int(count))
        self._label.setText(
            "1 problem" if self._count == 1 else f"{self._count} problems"
        )
        self.setToolTip(
            "" if not self._count else "Click to see what went wrong"
        )
        self.setVisible(bool(self._count))

    def count(self) -> int:
        return self._count

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)
