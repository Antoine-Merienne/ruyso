"""
The Pipeline tab: the node-graph canvas with an empty-state hint, a
run log docked beneath it (resizable), and the Options panel on the
right (resizable).

The bottom strip is two tabs, **Log** and **Problems**: they answer
"what happened" and "what went wrong", and a failure is far easier to
find in a list of its own than in the log's scroll. The Problems tab
carries its own count, so the strip says how many there are without
being brought to the front.

This is the only tab that owns a canvas and a run log; the Table tab
has neither, and the Dashboard tab has its own free-form canvas. Each
tab being a self-contained widget (rather than window-global docks) is
what lets the run log and Options panel appear on some tabs and not
others with no show/hide bookkeeping.

Figures are not shown here anymore: each grapher / figure node carries
its own floating on-canvas preview (``ui.node_preview``), opened full
size in its own window on click.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QWidget,
)
from PySide6.QtCore import Qt

from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.canvas_overlay import EmptyCanvasHint
from ruyso_app.ui.error_panel import ProblemsPanel
from ruyso_app.ui.options_panel import OptionsPanel


class PipelinePage(QWidget):
    """Canvas + run log + Options panel, assembled for the Pipeline tab."""

    def __init__(self, canvas: PipelineCanvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = canvas

        self.log = QPlainTextEdit(self)
        self.log.setObjectName("ruysoRunLog")  # frameless: see theme.py
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Run output will appear here...")

        # The log and the problems share the bottom strip: they answer
        # "what happened" and "what went wrong", and a failure is much
        # easier to find in a list of its own than in the log's scroll.
        self.problems = ProblemsPanel(self)
        self.bottom_tabs = QTabWidget(self)
        self.bottom_tabs.setDocumentMode(True)  # no boxed-in pane frame
        self.bottom_tabs.addTab(self.log, "Log")
        self._problems_index = self.bottom_tabs.addTab(self.problems, "Problems")
        self.problems.count_changed.connect(self._on_problem_count_changed)

        self.empty_hint = EmptyCanvasHint(canvas.graph.viewer(), canvas.graph)

        self._vertical = QSplitter(Qt.Vertical, self)
        # No band between the canvas and the strip: the handle paints
        # only its grip dots (see theme.stylesheet_for), and 7px is
        # enough to grab on the strip's own top edge.
        self._vertical.setHandleWidth(7)
        self._vertical.addWidget(canvas.widget)
        self._vertical.addWidget(self.bottom_tabs)
        self._vertical.setStretchFactor(0, 1)
        self._vertical.setStretchFactor(1, 0)
        self._vertical.setCollapsible(0, False)
        self._vertical.setSizes([680, 160])

        self.options_panel = OptionsPanel(self)

        self._horizontal = QSplitter(Qt.Horizontal, self)
        self._horizontal.setHandleWidth(7)
        self._horizontal.addWidget(self._vertical)
        self._horizontal.addWidget(self.options_panel)
        self._horizontal.setStretchFactor(0, 1)
        self._horizontal.setStretchFactor(1, 0)
        self._horizontal.setCollapsible(0, False)
        self._horizontal.setCollapsible(1, False)
        self._horizontal.setSizes([980, 440])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._horizontal)

    # -- run-log helpers used by MainWindow's execution callbacks ---------

    def clear_log(self) -> None:
        self.log.clear()

    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    # -- problems ------------------------------------------------------------

    def _on_problem_count_changed(self, count: int) -> None:
        """Keep the tab's own label honest about how many there are."""
        self.bottom_tabs.setTabText(
            self._problems_index, "Problems" if not count else f"Problems ({count})"
        )

    def show_problems(self) -> None:
        """Bring the Problems list to the front of the bottom strip."""
        self.bottom_tabs.setCurrentIndex(self._problems_index)

    # -- preferences ----------------------------------------------------------

    def apply_preferences(self) -> None:
        """Show or hide the run log, and re-apply the canvas preferences."""
        from ruyso_app.engine import settings

        show_log = bool(settings.get("appearance.show_run_log"))
        self.bottom_tabs.setVisible(show_log)
        if show_log and self._vertical.sizes()[1] == 0:
            self._vertical.setSizes([680, 160])  # give it room again
        self.canvas.apply_preferences()

    # -- theming --------------------------------------------------------------

    def apply_theme(self) -> None:
        """Propagate a theme change to the canvas and the Options panel."""
        self.canvas.apply_theme()
        self.options_panel.apply_theme()
