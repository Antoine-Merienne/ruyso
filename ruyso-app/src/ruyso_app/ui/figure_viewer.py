"""
Small widget that displays a matplotlib ``Figure`` produced by a
pipeline node (e.g. ``matplotlib_plot``), embedded directly in the main
window rather than opened in a separate pop-up window.
"""

from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget


class FigureViewer(QWidget):
    """A QWidget that displays a single matplotlib Figure at a time."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._canvas: FigureCanvasQTAgg | None = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

    def show_figure(self, figure: Figure) -> None:
        """
        Replace whatever is currently displayed with ``figure``.

        Args:
            figure: A matplotlib Figure, typically taken from a
                ``matplotlib_plot`` node's "figure" output port.
        """
        if self._canvas is not None:
            self._layout.removeWidget(self._canvas)
            self._canvas.deleteLater()

        self._canvas = FigureCanvasQTAgg(figure)
        self._layout.addWidget(self._canvas)
        self._canvas.draw()
