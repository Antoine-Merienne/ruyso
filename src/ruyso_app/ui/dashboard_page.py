"""
The Dashboard tab: an infinite pan/zoom canvas (:mod:`ui.dashboard_canvas`)
holding vector figure items and free-text items
(:mod:`ui.dashboard_items`), with a tool strip on the left
(:mod:`ui.dashboard_tools`) and a context-sensitive inspector on the
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
:class:`ui.dashboard_items.TextInspector`; images are imported from a
file and embedded. Every block's frame (contour, fill, corners) is set
in the shape inspector -- a figure's through its right-click "Cosmetic
Panel...", since a left click keeps opening its plot's options.

The canvas is **saved with the pipeline**, in a ``dashboard`` section of
the same JSON file (:meth:`DashboardPage.to_dict` /
:meth:`DashboardPage.restore`), so sending someone a pipeline sends the
report with it. What is stored is each block's description -- kind,
position, size, z-order, style, lock -- and for a figure the name of the
``export_to_dashboard`` node it came from, which is what re-binds it on
the next run. The rendered picture is *not* stored: it comes back from
running the pipeline, and a stale image on disk would be worse than
none, so a just-opened figure block shows the "· modified" tag until
something runs.

Each block describes itself through the same ``capture_state`` /
``apply_state`` pair the undo snapshots use -- saving a layout and
undoing an edit turned out to be the same question, so there is one
description of a block rather than two that could drift apart.

The canvas is exported to PDF / PNG (vector-preserving) from the
"Exporter..." entry -- the canvas context menu and the global Dashboard
menu share ``export_requested`` -> ``MainWindow._on_export_dashboard``.
"""

from __future__ import annotations

from typing import Any, Iterable

from PySide6.QtCore import QMarginsF, QPoint, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QImage, QPageSize, QPainter, QPdfWriter, QUndoStack
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QWidget,
)

from ruyso_app.engine import settings
from ruyso_app.ui.dashboard_canvas import DashboardView
from ruyso_app.ui import dashboard_layout, render_queue
from ruyso_app.ui.dashboard_items import (
    IMAGE_FILTER,
    FigureItem,
    ImageItem,
    TextInspector,
    TextItem,
)
from ruyso_app.ui.dashboard_menus import fill_arrange_menu, fill_shape_menu
from ruyso_app.ui.dashboard_shapes import SHAPE_LABELS, ShapeInspector, ShapeItem
from ruyso_app.ui.dashboard_tools import DashboardTools
from ruyso_app.ui.dashboard_undo import SceneEdit, SceneSnapshot, capture
from ruyso_app.ui.node_preview import figure_to_svg_bytes, resolve_figure, resolve_source_node
from ruyso_app.ui.options_panel import OptionsPanel

#: core node_type whose input figure becomes a dashboard figure item.
_EXPORT_NODE_TYPE = "export_to_dashboard"

#: This tab's half of the shared render queue (``ui/render_queue.py``),
#: whose other half is the canvas preview cards.
_DASHBOARD_JOB = "dashboard"

#: Right-pane stack indices.
_PAGE_OPTIONS = 0
_PAGE_TEXT = 1
_PAGE_SHAPE = 2
_PAGE_EMPTY = 3

_EMPTY_HINT = "Add figures to the dashboard using the export_to_dashboard node."
_EXPORT_MARGIN = 24.0

#: Version of the ``dashboard`` section written into a saved pipeline.
DASHBOARD_VERSION = 1

#: Item class -> the name it is saved under, and rebuilt from.
_ITEM_KINDS = {
    FigureItem: "figure",
    TextItem: "text",
    ShapeItem: "shape",
    ImageItem: "image",
}


def _dashboard_svg(figure: Any) -> bytes:
    """A dashboard block's vector art, drawn on a transparent background
    so the block's own fill shows behind the plot. With the default
    white fill it looks exactly as an opaque render did."""
    return figure_to_svg_bytes(figure, transparent=True)


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

        self._undo_stack = QUndoStack(self)
        #: State captured when the selection changed, so an inspector
        #: edit knows what it is undoing back to.
        self._pending_before: SceneSnapshot | None = None
        self._figure_items: dict[str, FigureItem] = {}
        #: The Figure object each item's SVG was rendered from, so an
        #: unchanged one is not serialised again (see sync_figures).
        self._rendered: dict[str, object] = {}
        self._source_message = ""
        render_queue.queue().rendered.connect(self._on_rendered)

        self._view = DashboardView(self)
        self._scene = self._view.scene()
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._view.context_menu_requested.connect(self._show_context_menu)
        self._view.delete_requested.connect(self.remove_selected)
        self._view.items_moved.connect(lambda: self._commit("Move"))
        self._view.nudge_requested.connect(self.nudge)

        # -- right pane: options form / text inspector / empty ----------
        self.options_panel = OptionsPanel(self)
        self._text_inspector = TextInspector(self)
        self._text_inspector.changed = lambda: self._commit("Restyle text")
        self._shape_inspector = ShapeInspector(self)
        self._shape_inspector.changed = lambda: self._commit("Restyle")
        self._empty = QLabel("Select a block to edit it.", self)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)

        self._inspector_stack = QStackedWidget(self)
        self._inspector_stack.addWidget(self.options_panel)  # _PAGE_OPTIONS
        self._inspector_stack.addWidget(self._text_inspector)  # _PAGE_TEXT
        self._inspector_stack.addWidget(self._shape_inspector)  # _PAGE_SHAPE
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

        # The tool strip is outside the splitter: it is a fixed-width
        # strip of buttons, not a pane anyone would want to resize.
        self.tools = DashboardTools(self, self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.tools)
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
            if figure is not None and figure is not self._rendered.get(name):
                # Serialising a figure to SVG is the most expensive thing
                # this tab does -- 4.6 s for a dense scatter -- so it goes
                # to the render thread and comes back at _on_rendered.
                # The skip cache returns the *same* Figure object for a
                # grapher nothing changed for, so identity tells us the
                # vector art on screen is already correct.
                self._rendered[name] = figure
                render_queue.queue().submit(
                    (_DASHBOARD_JOB, name), figure, _dashboard_svg
                )

            source = resolve_source_node(node)
            src_id = source.name() if source is not None else None
            item.set_stale(
                src_id is None
                or src_id in modified
                or src_id in errored
                or (figure is None and item.is_stale())
            )
        self._refresh_overlay()

    def _on_rendered(self, key: Any, figure: Any, data: Any) -> None:
        """One block's vector art, back from the render thread."""
        kind, name = key
        if kind != _DASHBOARD_JOB:
            return  # the preview cards' jobs share this queue
        item = self._figure_items.get(name)
        if data is None:  # the render failed; let the next run try again
            if self._rendered.get(name) is figure:
                self._rendered.pop(name, None)
            return
        # A newer run may have replaced the figure while this was drawing.
        if item is not None and self._rendered.get(name) is figure:
            item.set_svg(data)

    # -- text / title items -----------------------------------------

    def add_text_item(self, is_title: bool = False) -> TextItem:
        before = self._capture()
        item = TextItem(is_title=is_title)
        item.setPos(self._view.mapToScene(self._view.viewport().rect().center()))
        self._scene.addItem(item)
        self._select_only(item)
        self._commit("Add title" if is_title else "Add text box", before)
        return item

    #: Kept for the menu wiring that used to call it under this name.
    add_text_block = add_text_item

    def add_shape(self, kind: str = "rectangle") -> ShapeItem:
        """Drop a new shape in the middle of the view."""
        before = self._capture()
        item = ShapeItem(kind)
        item.setPos(self._view.mapToScene(self._view.viewport().rect().center()))
        self._scene.addItem(item)
        self._select_only(item)
        self._commit(f"Add {SHAPE_LABELS.get(kind, kind).lower()}", before)
        return item

    def add_image(self, path: str) -> ImageItem:
        """
        Import the image at ``path`` into the middle of the view.

        Raises ``OSError`` / ``ValueError`` for a file that cannot be
        read as an image; :meth:`import_image` reports those.
        """
        item = ImageItem.from_file(path)
        before = self._capture()
        centre = self._view.mapToScene(self._view.viewport().rect().center())
        item.setPos(centre - item.visual_rect().center())
        self._scene.addItem(item)
        self._select_only(item)
        self._commit("Add image", before)
        return item

    def import_image(self) -> None:
        """Ask for an image file and add it (the menu / tool-strip entry)."""
        path, _ = QFileDialog.getOpenFileName(self, "Import Image", "", IMAGE_FILTER)
        if not path:
            return
        try:
            self.add_image(path)
        except (OSError, ValueError) as exc:
            # A file action the person asked for: the one place a dialog
            # is the right way to say it did not happen.
            QMessageBox.warning(self, "Import Image", str(exc))

    def _select_only(self, item: Any) -> None:
        self._scene.clearSelection()
        item.setSelected(True)
        self._refresh_overlay()

    def remove_selected(self) -> None:
        """
        Delete the selection.

        A removed item is *kept alive* by the undo snapshot rather than
        destroyed, so undoing brings back the very same block -- a figure
        with its rendered SVG still in it, not a blank one waiting for
        the next run.
        """
        selected = list(self._scene.selectedItems())
        if not selected:
            return
        before = self._capture()
        for item in selected:
            if isinstance(item, FigureItem):
                self._figure_items.pop(item.export_node_id, None)
                self._rendered.pop(item.export_node_id, None)
            self._scene.removeItem(item)
        self._commit("Delete", before)
        self._refresh_overlay()

    def duplicate_selected(self) -> list:
        """Copy the selected shapes and text boxes, offset a little."""
        before = self._capture()
        made: list[Any] = []
        for item in list(self._scene.selectedItems()):
            copy = self._copy_of(item)
            if copy is None:
                continue  # a figure belongs to its export node; not copyable
            copy.setPos(item.pos().x() + 16, item.pos().y() + 16)
            self._scene.addItem(copy)
            made.append(copy)
        if not made:
            return []
        self._scene.clearSelection()
        for copy in made:
            copy.setSelected(True)
        self._commit("Duplicate", before)
        self._refresh_overlay()
        return made

    @staticmethod
    def _copy_of(item: Any) -> Any:
        if isinstance(item, ShapeItem):
            copy = ShapeItem(item.kind)
        elif isinstance(item, TextItem):
            copy = TextItem(is_title=item.is_title)
        elif isinstance(item, ImageItem):
            copy = ImageItem()
        else:
            return None
        copy.apply_state(item.capture_state())
        copy.setZValue(item.zValue())
        return copy

    # -- saving and reopening the layout ---------------------------

    def to_dict(self) -> dict:
        """
        The canvas as plain data, for the ``dashboard`` key of a saved
        pipeline. Empty when there is nothing on it, so a file only
        grows the key once it has a report to carry.

        Each block's own state is whatever it reports to the undo
        snapshots -- the two questions turned out to be the same one, so
        there is a single description of a block rather than two that
        could drift apart. A figure's rendered SVG is *not* saved: it
        comes back from running the pipeline, and a stale picture on
        disk would be worse than none.
        """
        blocks = self.blocks()
        if not blocks:
            return {}
        items = []
        for item in sorted(blocks, key=lambda i: i.zValue()):
            kind = _ITEM_KINDS.get(type(item))
            if kind is None:
                continue
            items.append(
                {
                    "type": kind,
                    "pos": [item.pos().x(), item.pos().y()],
                    "z": item.zValue(),
                    "state": item.capture_state(),
                }
            )
        return {"version": DASHBOARD_VERSION, "items": items}

    def restore(self, data: dict | None) -> None:
        """
        Replace the canvas with a saved layout.

        Opening a document replaces the document: ``None`` or empty data
        clears the canvas, so blocks from the pipeline you had open
        before cannot bleed into the one you just opened -- and be saved
        into it. Never raises: a layout that cannot be read costs the
        report, and the pipeline is the part worth protecting.
        """
        self.clear_blocks()
        for spec in (data or {}).get("items", []):
            item = self._item_from(spec)
            if item is None:
                continue
            self._scene.addItem(item)
            position = spec.get("pos", [0, 0])
            item.setPos(float(position[0]), float(position[1]))
            item.setZValue(float(spec.get("z", 0.0)))
            if isinstance(item, FigureItem):
                # Its picture comes from the next run; until then it is
                # honestly out of date. A block whose export node is
                # gone stays put, tagged, exactly as it does when that
                # node is deleted with the app open.
                self._figure_items[item.export_node_id] = item
                item.set_stale(True)
        self._undo_stack.clear()  # a freshly opened layout has no history
        self._undo_stack.setClean()
        self._pending_before = None
        self._refresh_overlay()

    @staticmethod
    def _item_from(spec: dict) -> Any:
        """Build one block from its saved description, or ``None``."""
        state = spec.get("state") or {}
        try:
            kind = spec.get("type")
            if kind == "figure":
                item = FigureItem(str(state.get("export_node_id", "")))
            elif kind == "text":
                item = TextItem(is_title=bool(state.get("is_title")))
            elif kind == "shape":
                item = ShapeItem(str(state.get("kind", "rectangle")))
            elif kind == "image":
                item = ImageItem()
            else:
                return None
            item.apply_state(state)
            return item
        except Exception:  # noqa: BLE001 - one bad block must not lose the rest
            return None

    def clear_blocks(self) -> None:
        """Take every block off the canvas and forget what was rendered."""
        for item in self.blocks():
            self._scene.removeItem(item)
        self._figure_items.clear()
        self._rendered.clear()
        self._refresh_overlay()

    # -- undo ------------------------------------------------------

    def undo_stack(self) -> QUndoStack:
        """The canvas's own history, separate from the pipeline's."""
        return self._undo_stack

    def blocks(self) -> list:
        """Every block on the canvas (not the rubber band or overlays)."""
        return [item for item in self._scene.items() if hasattr(item, "capture_state")]

    def _capture(self) -> SceneSnapshot:
        return capture(self._scene, self.blocks())

    def _commit(self, text: str, before: SceneSnapshot | None = None) -> None:
        """
        Record one finished operation on the undo stack.

        ``before`` is the snapshot taken *before* the change; callers
        that hand over ``None`` are edits made through an inspector,
        where the panel has already changed the item and the previous
        state was captured when the selection was bound.
        """
        if before is None:
            before = self._pending_before
        if before is None:
            return
        self._undo_stack.push(
            SceneEdit(self._scene, before, self._capture(), text)
        )
        self._pending_before = self._capture()

    def _arrange(self, text: str, operation) -> None:
        """Run a layout operation as one undoable step."""
        items = [i for i in self._scene.selectedItems() if hasattr(i, "capture_state")]
        if not items:
            return
        before = self._capture()
        operation(items)
        self._commit(text, before)

    # -- layout commands (menu / shortcut entry points) ------------

    def bring_to_front(self) -> None:
        self._arrange("Bring to front", lambda items: dashboard_layout.bring_to_front(items, self.blocks()))

    def send_to_back(self) -> None:
        self._arrange("Send to back", lambda items: dashboard_layout.send_to_back(items, self.blocks()))

    def bring_forward(self) -> None:
        self._arrange("Bring forward", lambda items: dashboard_layout.bring_forward(items))

    def send_backward(self) -> None:
        self._arrange("Send backward", lambda items: dashboard_layout.send_backward(items))

    def align(self, edge: str) -> None:
        self._arrange(f"Align {edge}", lambda items: dashboard_layout.align(items, edge))

    def distribute(self, axis: str) -> None:
        self._arrange("Distribute", lambda items: dashboard_layout.distribute(items, axis))

    def nudge(self, dx: float, dy: float) -> None:
        self._arrange("Move", lambda items: dashboard_layout.nudge(items, dx, dy))

    def lock_selected(self) -> None:
        self._arrange("Lock", lambda items: dashboard_layout.set_locked(items, True))

    def unlock_all(self) -> None:
        """
        Release every locked block.

        The only way back: a locked block cannot be selected, so it
        cannot be unlocked from its own inspector either.
        """
        locked = dashboard_layout.locked_items(self.blocks())
        if not locked:
            return
        before = self._capture()
        dashboard_layout.set_locked(locked, False)
        self._commit("Unlock all", before)

    def has_locked_blocks(self) -> bool:
        return bool(dashboard_layout.locked_items(self.blocks()))

    # -- right-pane routing ----------------------------------------

    def show_options_page(self) -> None:
        self._inspector_stack.setCurrentIndex(_PAGE_OPTIONS)

    def show_figure_options(self) -> None:
        """Right-click > Options Panel...: the selected figure's plot options
        (what a left click opens)."""
        figures = self._selected_figures()
        if figures:
            self.figure_block_selected.emit(figures[0].export_node_id)

    def show_figure_cosmetics(self) -> None:
        """Right-click > Cosmetic Panel...: the selected figures' frame --
        contour, background fill, corners."""
        figures = self._selected_figures()
        if not figures:
            return
        self._source_message = ""
        self._pending_before = self._capture()
        self._shape_inspector.set_items(figures)
        self._inspector_stack.setCurrentIndex(_PAGE_SHAPE)
        self._refresh_overlay()

    def _selected_figures(self) -> list[FigureItem]:
        return [i for i in self._scene.selectedItems() if isinstance(i, FigureItem)]

    def is_editing_figure(self) -> bool:
        return self._inspector_stack.currentIndex() == _PAGE_OPTIONS

    def set_canvas_message(self, text: str | None) -> None:
        """Show/clear the on-canvas hint (e.g. 'source plot disconnected')."""
        self._source_message = text or ""
        if self._source_message:
            self._inspector_stack.setCurrentIndex(_PAGE_EMPTY)
        self._refresh_overlay()

    def _on_selection_changed(self) -> None:
        """
        Bind the right-hand pane to what is selected.

        A selection of several shapes (or several text boxes) is bound
        as a group, so one colour change lands on all of them -- making
        blocks match by hand is the tedious part of assembling a report.
        A mixed selection has almost nothing in common to edit, so it
        falls back to the placeholder.
        """
        self._source_message = ""
        selected = self._scene.selectedItems()
        figures = [i for i in selected if isinstance(i, FigureItem)]
        texts = [i for i in selected if isinstance(i, TextItem)]
        # Images have no options of their own: their frame is all there
        # is to edit, in the same form a shape uses.
        shapes = [i for i in selected if isinstance(i, (ShapeItem, ImageItem))]
        # Whatever is selected now is the "before" for any edit the
        # inspector is about to make.
        self._pending_before = self._capture()

        if len(selected) == 1 and figures:
            # MainWindow fills the Options panel (and calls show_options_page)
            # if the figure has a live source plot; otherwise it posts a
            # canvas message and the pane stays on the placeholder.
            self._inspector_stack.setCurrentIndex(_PAGE_EMPTY)
            self.figure_block_selected.emit(figures[0].export_node_id)
        elif texts and len(texts) == len(selected):
            self._text_inspector.set_items(texts)
            self._inspector_stack.setCurrentIndex(_PAGE_TEXT)
        elif shapes and len(shapes) == len(selected):
            self._shape_inspector.set_items(shapes)
            self._inspector_stack.setCurrentIndex(_PAGE_SHAPE)
        else:
            self._text_inspector.set_items([])
            self._inspector_stack.setCurrentIndex(_PAGE_EMPTY)
        self.tools.set_has_selection(bool(selected))
        self._refresh_overlay()

    def _has_figures(self) -> bool:
        return any(isinstance(i, FigureItem) for i in self._scene.items())

    def _refresh_overlay(self) -> None:
        """
        Choose the hint drawn over the canvas.

        The empty hint is about *figures*, and a figure can only arrive
        through an ``export_to_dashboard`` node -- so it stays up until
        one does. Adding a title, a text box or a shape is not the thing
        it is asking for, and dismissing it there left someone who had
        typed a heading with no idea how to get their plot across.

        A contextual message ("source plot is disconnected") is about
        what is selected right now, so it wins while it is set.
        """
        if self._source_message:
            self._view.overlay.show_message(self._source_message)
        elif not self._has_figures():
            self._view.overlay.show_message(_EMPTY_HINT)
        else:
            self._view.overlay.show_message("")

    def _cascade_pos(self, index: int) -> QPointF:
        centre = self._view.mapToScene(self._view.viewport().rect().center())
        step = 28 * (index % 8)
        return centre + QPointF(step - 120, step - 90)

    # -- context menu ----------------------------------------------

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = self.build_context_menu()
        menu.exec(global_pos)

    def build_context_menu(self) -> QMenu:
        """
        The canvas menu: the same commands as the Dashboard menu, with
        the ones needing a selection shown only when there is one.

        Built apart from showing it so a test can look at it: ``exec``
        blocks until someone clicks, so a menu that is only ever built
        inside the handler is a menu nothing checks -- which is how it
        came to be raising ``NameError`` on every right-click.
        """
        menu = QMenu(self)
        selected = self._scene.selectedItems()
        if selected and all(isinstance(i, FigureItem) for i in selected):
            # A left click opens the plot's options; its frame is the
            # other thing worth editing on a figure.
            if len(selected) == 1:
                menu.addAction("Options Panel...", self.show_figure_options)
            menu.addAction("Cosmetic Panel...", self.show_figure_cosmetics)
            menu.addSeparator()
        menu.addAction("Add Title", lambda: self.add_text_item(is_title=True))
        menu.addAction("Add Text Box", lambda: self.add_text_item(is_title=False))
        fill_shape_menu(menu.addMenu("Add Shape"), self)
        menu.addAction("Add Image...", self.import_image)

        if self._scene.selectedItems():
            menu.addSeparator()
            fill_arrange_menu(menu.addMenu("Arrange"), self)
            menu.addAction("Duplicate", self.duplicate_selected)
            menu.addAction("Lock", self.lock_selected)
            menu.addAction("Delete", self.remove_selected)

        if self.has_locked_blocks():
            menu.addAction("Unlock All", self.unlock_all)

        menu.addSeparator()
        menu.addAction("Exporter...", self.export_requested.emit)
        return menu

    # -- export (vector-preserving) ------------------------------

    def export(self, path: str, dpi: int | None = None) -> None:
        """
        Render every item to ``path`` (``.pdf`` keeps vectors; else PNG).

        ``dpi`` defaults to the ``dashboard.export_dpi`` preference. A
        PDF is sized either to the content's own bounding box or to a
        standard page (``dashboard.page_size``), in which case the
        content is fitted inside it with its aspect ratio kept.
        """
        dpi = int(settings.get("dashboard.export_dpi")) if dpi is None else dpi
        self._scene.clearSelection()
        rect = self._scene.itemsBoundingRect()
        if rect.isEmpty():
            raise ValueError("The dashboard is empty - add a figure or text box first.")
        rect = rect.adjusted(-_EXPORT_MARGIN, -_EXPORT_MARGIN, _EXPORT_MARGIN, _EXPORT_MARGIN)

        if path.lower().endswith(".pdf"):
            writer = QPdfWriter(path)
            writer.setResolution(dpi)
            writer.setPageSize(self._page_size_for(rect))
            writer.setPageMargins(QMarginsF(0, 0, 0, 0))
            painter = QPainter(writer)
            # Qt.KeepAspectRatio matters only for a fixed page: with the
            # content's own box the two rectangles already agree.
            self._scene.render(
                painter, QRectF(painter.viewport()), rect, Qt.KeepAspectRatio
            )
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

    def _page_size_for(self, rect: QRectF) -> QPageSize:
        """The PDF page: a standard sheet, or the content's own extent."""
        choice = str(settings.get("dashboard.page_size") or "content").lower()
        standard = {
            "a4": QPageSize.A4,
            "letter": QPageSize.Letter,
        }.get(choice)
        if standard is not None:
            page = QPageSize(standard)
            # Landscape when the content is wider than it is tall, so a
            # wide row of figures is not squeezed onto a portrait sheet.
            if rect.width() > rect.height():
                size = page.sizePoints()
                return QPageSize(
                    QSizeF(size.height(), size.width()), QPageSize.Point
                )
            return page
        return QPageSize(
            QSizeF(rect.width() * 72.0 / 96.0, rect.height() * 72.0 / 96.0),
            QPageSize.Point,
        )

    # -- preferences ---------------------------------------------

    def apply_preferences(self) -> None:
        """Re-read the Dashboard preferences (grid, snapping, fonts)."""
        self._view.viewport().update()  # the grid may have appeared or gone
        for item in self._scene.items():
            if isinstance(item, TextItem):
                item.apply_font_preference()

    # -- theming -------------------------------------------------

    def apply_theme(self) -> None:
        self._view.apply_theme()
        self.options_panel.apply_theme()
        self.tools.apply_theme()  # the glyphs are painted in the text colour
