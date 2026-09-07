"""
The Dashboard tab: an infinite pan/zoom canvas (:mod:`ui.dashboard_canvas`)
holding vector figure items and free-text items
(:mod:`ui.dashboard_items`), with a context-sensitive inspector on the
right.

Figures reach the canvas through the ``export_to_dashboard`` node -- one
:class:`~ui.dashboard_items.FigureItem` per such node, keyed to it and
re-rendered from SVG in place by :meth:`DashboardPage.sync_figures` on
every pipeline run / auto-run. A figure whose source plot changed since
the last run, was disconnected, or errored gets the Table tab's yellow
"· modified" tag. Selecting exactly one figure shows the *source plot's*
own parameter form -- the very :class:`ui.options_panel.OptionsPanel`
used on the Pipeline tab -- so restyling a figure is the same act as
editing its grapher node (``MainWindow`` fills the panel and re-runs).
Text / title items are added by hand and restyled through
:class:`ui.dashboard_items.TextInspector`.

The canvas is **session state**: it is not serialised. The one persisted
piece is each ``export_to_dashboard`` node's ``title`` param, which seeds
its figure item's heading.

The canvas is exported to PDF / PNG (vector-preserving) from the
"Exporter..." entry -- the canvas context menu and the global Dashboard
menu share ``export_requested`` -> ``MainWindow._on_export_dashboard``.
"""

from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import QMarginsF, QPoint, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSplitter,
    QStackedWidget,
    QWidget,
)

from ruyso_app.ui.dashboard_canvas import DashboardView
from ruyso_app.ui.dashboard_items import FigureItem, TextInspector, TextItem
from ruyso_app.ui.node_preview import figure_to_svg_bytes, resolve_figure, resolve_source_node
from ruyso_app.ui.options_panel import OptionsPanel

#: core node_type whose input figure becomes a dashboard figure item.
_EXPORT_NODE_TYPE = "export_to_dashboard"

#: Right-pane stack indices.
_PAGE_OPTIONS = 0
_PAGE_TEXT = 1
_PAGE_EMPTY = 2

_EMPTY_HINT = "Add figures to the dashboard using the export_to_dashboard node."
_EXPORT_MARGIN = 24.0


class DashboardPage(QWidget):
    """Infinite canvas + context-sensitive inspector for the Dashboard tab."""

    #: Emitted with an ``export_to_dashboard`` node name when exactly its
    #: figure item is selected; ``MainWindow`` binds the Options panel to
    #: the source plot upstream of that node.
    figure_block_selected = Signal(str)
    #: Emitted when the person asks to export the dashboard.
    export_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._figure_items: dict[str, FigureItem] = {}
        self._source_message = ""

        self._view = DashboardView(self)
        self._scene = self._view.scene()
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._view.context_menu_requested.connect(self._show_context_menu)
        self._view.delete_requested.connect(self.remove_selected)

        # -- right pane: options form / text inspector / empty ----------
        self.options_panel = OptionsPanel(self)
        self._text_inspector = TextInspector(self)
        self._empty = QLabel("Select one block to edit it.", self)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)

        self._inspector_stack = QStackedWidget(self)
        self._inspector_stack.addWidget(self.options_panel)  # _PAGE_OPTIONS
        self._inspector_stack.addWidget(self._text_inspector)  # _PAGE_TEXT
        self._inspector_stack.addWidget(self._empty)  # _PAGE_EMPTY
        self._inspector_stack.setCurrentIndex(_PAGE_EMPTY)
        self._inspector_stack.setMinimumWidth(self.options_panel.minimumWidth())

        self._splitter = QSplitter(Qt.Horizontal, self)
        self._splitter.addWidget(self._view)
        self._splitter.addWidget(self._inspector_stack)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([980, 440])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._splitter)
        self._refresh_overlay()

    # -- figures from the pipeline -------------------------------------

    def sync_figures(
        self,
        graph: Any,
        outputs: dict[str, dict],
        modified_ids: Iterable[str] = (),
        error_ids: Iterable[str] = (),
    ) -> None:
        """
        Create / refresh one figure item per ``export_to_dashboard`` node
        in ``graph``. Items for a since-deleted export node are kept as
        their last snapshot (never removed here), flagged stale.
        """
        modified = set(modified_ids)
        errored = set(error_ids)
        for node in graph.all_nodes():
            if getattr(type(node), "CORE_NODE_TYPE", None) != _EXPORT_NODE_TYPE:
                continue
            name = node.name()
            item = self._figure_items.get(name)
            if item is None:
                title = ""
                try:
                    title = node.get_property("title") or ""
                except Exception:  # noqa: BLE001 - a missing prop is not fatal
                    title = ""
                item = FigureItem(name, title)
                item.setPos(self._cascade_pos(len(self._figure_items)))
                self._figure_items[name] = item
                self._scene.addItem(item)

            figure = resolve_figure(node, outputs)
            if figure is not None:
                item.set_svg(figure_to_svg_bytes(figure))

            source = resolve_source_node(node)
            src_id = source.name() if source is not None else None
            item.set_stale(
                src_id is None
                or src_id in modified
                or src_id in errored
                or (figure is None and item.is_stale())
            )
        self._refresh_overlay()

    # -- text / title items -----------------------------------------

    def add_text_item(self, is_title: bool = False) -> TextItem:
        item = TextItem(is_title=is_title)
        centre = self._view.mapToScene(self._view.viewport().rect().center())
        item.setPos(centre)
        self._scene.addItem(item)
        self._scene.clearSelection()
        item.setSelected(True)
        self._refresh_overlay()
        return item

    def remove_selected(self) -> None:
        for item in list(self._scene.selectedItems()):
            if isinstance(item, FigureItem):
                self._figure_items.pop(item.export_node_id, None)
            self._scene.removeItem(item)
        self._refresh_overlay()

    # -- right-pane routing ----------------------------------------

    def show_options_page(self) -> None:
        self._inspector_stack.setCurrentIndex(_PAGE_OPTIONS)

    def is_editing_figure(self) -> bool:
        return self._inspector_stack.currentIndex() == _PAGE_OPTIONS

    def set_canvas_message(self, text: str | None) -> None:
        """Show/clear the on-canvas hint (e.g. 'source plot disconnected')."""
        self._source_message = text or ""
        if self._source_message:
            self._inspector_stack.setCurrentIndex(_PAGE_EMPTY)
        self._refresh_overlay()

    def _on_selection_changed(self) -> None:
        self._source_message = ""
        selected = self._scene.selectedItems()
        figures = [i for i in selected if isinstance(i, FigureItem)]
        texts = [i for i in selected if isinstance(i, TextItem)]
        if len(selected) == 1 and figures:
            # MainWindow fills the Options panel (and calls show_options_page)
            # if the figure has a live source plot; otherwise it posts a
            # canvas message and the pane stays on the placeholder.
            self._inspector_stack.setCurrentIndex(_PAGE_EMPTY)
            self.figure_block_selected.emit(figures[0].export_node_id)
        elif len(selected) == 1 and texts:
            self._text_inspector.set_item(texts[0])
            self._inspector_stack.setCurrentIndex(_PAGE_TEXT)
        else:
            self._text_inspector.set_item(None)
            self._inspector_stack.setCurrentIndex(_PAGE_EMPTY)
        self._refresh_overlay()

    def _has_items(self) -> bool:
        return any(
            isinstance(i, (FigureItem, TextItem)) for i in self._scene.items()
        )

    def _refresh_overlay(self) -> None:
        if not self._has_items():
            self._view.overlay.show_message(_EMPTY_HINT)
        else:
            self._view.overlay.show_message(self._source_message)

    def _cascade_pos(self, index: int) -> QPointF:
        centre = self._view.mapToScene(self._view.viewport().rect().center())
        step = 28 * (index % 8)
        return centre + QPointF(step - 120, step - 90)

    # -- context menu ----------------------------------------------

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        menu.addAction("Add Title", lambda: self.add_text_item(is_title=True))
        menu.addAction("Add Text Box", lambda: self.add_text_item(is_title=False))
        if self._scene.selectedItems():
            menu.addAction("Delete", self.remove_selected)
        menu.addSeparator()
        menu.addAction("Exporter...", self.export_requested.emit)
        menu.exec(global_pos)

    # -- export (vector-preserving) ------------------------------

    def export(self, path: str, dpi: int = 200) -> None:
        """Render every item to ``path`` (``.pdf`` keeps vectors; else PNG)."""
        self._scene.clearSelection()
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            raise ValueError("The dashboard is empty - add a figure or text box first.")
        rect = rect.adjusted(-_EXPORT_MARGIN, -_EXPORT_MARGIN, _EXPORT_MARGIN, _EXPORT_MARGIN)

        if path.lower().endswith(".pdf"):
            writer = QPdfWriter(path)
            writer.setResolution(dpi)
            writer.setPageSize(
                QPageSize(
                    QSizeF(rect.width() * 72.0 / 96.0, rect.height() * 72.0 / 96.0),
                    QPageSize.Point,
                )
            )
            writer.setPageMargins(QMarginsF(0, 0, 0, 0))
            painter = QPainter(writer)
            self._scene.render(painter, QRectF(painter.viewport()), rect)
            painter.end()
        else:
            scale = dpi / 96.0
            image = QImage(
                max(1, round(rect.width() * scale)),
                max(1, round(rect.height() * scale)),
                QImage.Format_ARGB32,
            )
            image.fill(Qt.white)
            painter = QPainter(image)
            self._scene.render(painter, QRectF(image.rect()), rect)
            painter.end()
            image.save(path)

    # -- theming -------------------------------------------------

    def apply_theme(self) -> None:
        self._view.apply_theme()
        self.options_panel.apply_theme()
