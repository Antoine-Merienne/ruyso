"""
The Dashboard tab: a free-form canvas, bounded by a frame representing
the exportable page, holding draggable/resizable figure, title and
text blocks, plus the Options panel on the right.

Figures and statistical-test results reach this canvas through the
"add to dashboard" action on a grapher/statistical_test node (see the
Pipeline tab); the person can also add title and free-text blocks by
hand. The canvas is exported to PDF/PNG from a right-click "Exporter..."
entry or the global "Dashboard" menu.

Phase 1 scope: the tab exists with its Options panel and an empty
hatched canvas placeholder, and the "Exporter..." context-menu entry
is present and routed through ``export_requested`` so the Dashboard
menu and the context menu share one handler later. The block widgets
and the export dialog are built in a later phase.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QSplitter, QWidget
from PySide6.QtCore import Qt, Signal

from ruyso_app.ui.options_panel import OptionsPanel


class DashboardPage(QWidget):
    """Placeholder implementation of the Dashboard tab (Phase 1)."""

    #: Emitted when the person asks to export the dashboard (from the
    #: canvas context menu; the global Dashboard menu connects here too).
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._canvas_area = QLabel("Dashboard page (empty)", self)
        self._canvas_area.setAlignment(Qt.AlignCenter)
        self._canvas_area.setContextMenuPolicy(Qt.CustomContextMenu)
        self._canvas_area.customContextMenuRequested.connect(self._show_context_menu)

        self.options_panel = OptionsPanel(self)

        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.addWidget(self._canvas_area)
        self._splitter.addWidget(self.options_panel)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([1120, 300])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._splitter)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        export_action = menu.addAction("Exporter...")
        export_action.triggered.connect(self.export_requested.emit)
        menu.exec(self._canvas_area.mapToGlobal(pos))

    def apply_theme(self) -> None:
        self.options_panel.apply_theme()
