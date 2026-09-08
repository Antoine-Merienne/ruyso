"""
The pipeline-run progress indicator shown on the right of the tab band.

A slim bar that fills as nodes complete during a manual **Run
Pipeline**, with the completion percentage written just to its right.
On finish it settles into a solid **green** bar on success or **red**
on failure and stays there until the next run starts. It is always
visible -- a flat **grey** track before the first manual run.

Colour comes from a Qt dynamic property (``state`` =
``idle`` / ``running`` / ``success`` / ``error``) styled in
``theme.stylesheet_for``; this widget only sets values and toggles
that property.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QWidget

#: Fixed on-screen size of the bar itself, in pixels. Deliberately slim.
_BAR_WIDTH = 190
_BAR_HEIGHT = 5


class RunProgressBar(QWidget):
    """A slim determinate progress bar + percentage, with end states."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._bar = QProgressBar(self)
        self._bar.setObjectName("ruysoRunProgress")
        self._bar.setFixedSize(_BAR_WIDTH, _BAR_HEIGHT)
        self._bar.setTextVisible(False)
        self._bar.setRange(0, 1)
        self._bar.setValue(0)

        self._percent = QLabel("", self)
        self._percent.setObjectName("ruysoRunPercent")
        self._percent.setFixedWidth(34)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._bar, 0, Qt.AlignVCenter)
        layout.addWidget(self._percent, 0, Qt.AlignVCenter)

        self._set_state("idle")

    # -- driven by MainWindow's run callbacks -----------------------------

    def start(self, total: int) -> None:
        """Begin a run of ``total`` nodes."""
        self._bar.setRange(0, max(total, 1))
        self._bar.setValue(0)
        self._percent.setText("0%")
        self._set_state("running")
        self.setVisible(True)

    def set_progress(self, done: int, total: int) -> None:
        """Update after ``done`` of ``total`` nodes have finished."""
        total = max(total, 1)
        self._bar.setRange(0, total)
        self._bar.setValue(done)
        self._percent.setText(f"{round(100 * done / total)}%")

    def finish_success(self) -> None:
        self._bar.setValue(self._bar.maximum())
        self._percent.setText("100%")
        self._set_state("success")

    def finish_error(self) -> None:
        self._set_state("error")

    # -- test conveniences ------------------------------------------------

    def value(self) -> int:
        return self._bar.value()

    def maximum(self) -> int:
        return self._bar.maximum()

    def percent_text(self) -> str:
        return self._percent.text()

    # -- internals ------------------------------------------------------

    def _set_state(self, state: str) -> None:
        # Set on both the container (so callers can read it) and the
        # bar (so the [state="..."] chunk-colour rules apply).
        for widget in (self, self._bar, self._percent):
            widget.setProperty("state", state)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
