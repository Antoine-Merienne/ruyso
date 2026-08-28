"""
The Table tab: inspect the output table of any pipeline step.

Per the spec this tab has a left column (a simplified read-only mini
diagram of the pipeline on top, a "Table description" panel below) and
a main area showing the selected step's dataframe. It has no Options
panel and no run log.

Phase 1 scope: a placeholder that shows the correct spec message for
the "nothing run yet" state. The mini diagram, the description panel
and the data table are built in a later phase; ``set_run_outputs`` and
the selection wiring are stubbed here so ``MainWindow`` can already
call them.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

#: Shown before the pipeline has ever been run.
MESSAGE_BEFORE_RUN = "run pipeline and select table to display"
#: Shown after a run, while no step is selected.
MESSAGE_NO_SELECTION = "select table to display"


class TablePage(QWidget):
    """Placeholder implementation of the Table tab (Phase 1)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._has_run = False

        self._message = QLabel(MESSAGE_BEFORE_RUN, self)
        self._message.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(self._message)

    def set_run_outputs(self, outputs: dict[str, dict]) -> None:
        """
        Record the results of a pipeline run.

        Phase 1 only flips the placeholder message from the
        "before run" to the "no selection" wording; later phases will
        populate the mini diagram and enable table selection from this.
        """
        self._has_run = True
        self._message.setText(MESSAGE_NO_SELECTION)

    def current_message(self) -> str:
        """The text currently shown in the main area (used by tests)."""
        return self._message.text()

    def apply_theme(self) -> None:
        """No themed surfaces of its own yet; kept for interface parity."""
