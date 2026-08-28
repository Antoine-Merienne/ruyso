"""
The Pipeline tab: the node-graph canvas with an empty-state hint, a
run log docked beneath it (resizable), and the Options panel on the
right (resizable).

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

from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QSplitter, QWidget
from PySide6.QtCore import Qt

from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.canvas_overlay import EmptyCanvasHint
from ruyso_app.ui.options_panel import OptionsPanel


class PipelinePage(QWidget):
    """Canvas + run log + Options panel, assembled for the Pipeline tab."""

    def __init__(self, canvas: PipelineCanvas, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.canvas = canvas

        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Run output will appear here...")

        self.empty_hint = EmptyCanvasHint(canvas.graph.viewer(), canvas.graph)

        self._vertical = QSplitter(Qt.Vertical, self)
        self._vertical.addWidget(canvas.widget)
        self._vertical.addWidget(self.log)
        self._vertical.setStretchFactor(0, 1)
        self._vertical.setStretchFactor(1, 0)
        self._vertical.setCollapsible(0, False)
        self._vertical.setSizes([680, 160])

        self.options_panel = OptionsPanel(self)

        self._horizontal = QSplitter(Qt.Horizontal, self)
        self._horizontal.addWidget(self._vertical)
        self._horizontal.addWidget(self.options_panel)
        self._horizontal.setStretchFactor(0, 1)
        self._horizontal.setStretchFactor(1, 0)
        self._horizontal.setCollapsible(0, False)
        self._horizontal.setCollapsible(1, False)
        self._horizontal.setSizes([1120, 300])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._horizontal)

    # -- run-log helpers used by MainWindow's execution callbacks ---------

    def clear_log(self) -> None:
        self.log.clear()

    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    # -- theming --------------------------------------------------------------

    def apply_theme(self) -> None:
        """Propagate a theme change to the canvas and the Options panel."""
        self.canvas.apply_theme()
        self.options_panel.apply_theme()
