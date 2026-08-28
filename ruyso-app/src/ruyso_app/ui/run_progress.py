"""
The pipeline-run progress bar shown on the right of the tab band.

It fills as nodes complete during a manual **Run Pipeline**, then
settles into a solid **green** bar on success or **red** on failure
and stays there until the next run starts (so a glance at the band
tells you how the last run went). It is hidden before the first run.

Colour comes from a Qt dynamic property (``state`` =
``running`` / ``success`` / ``error``) styled in
``theme.stylesheet_for``; this widget only sets values and toggles
that property.
"""

from __future__ import annotations

from PySide6.QtWidgets import QProgressBar, QWidget

#: Fixed on-screen size in the tab band.
_BAR_WIDTH = 220
_BAR_HEIGHT = 14


class RunProgressBar(QProgressBar):
    """A slim determinate progress bar with success / error end states."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoRunProgress")
        self.setFixedSize(_BAR_WIDTH, _BAR_HEIGHT)
        self.setTextVisible(False)
        self.setRange(0, 1)
        self.setValue(0)
        self._set_state("idle")
        self.setVisible(False)

    # -- driven by MainWindow's run callbacks -----------------------------

    def start(self, total: int) -> None:
        """Begin a run of ``total`` nodes."""
        self.setRange(0, max(total, 1))
        self.setValue(0)
        self._set_state("running")
        self.setVisible(True)

    def set_progress(self, done: int, total: int) -> None:
        """Update after ``done`` of ``total`` nodes have finished."""
        self.setRange(0, max(total, 1))
        self.setValue(done)

    def finish_success(self) -> None:
        self.setValue(self.maximum())
        self._set_state("success")

    def finish_error(self) -> None:
        self._set_state("error")

    # -- internals ------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self.setProperty("state", state)
        # Re-evaluate the stylesheet against the new property value.
        self.style().unpolish(self)
        self.style().polish(self)
