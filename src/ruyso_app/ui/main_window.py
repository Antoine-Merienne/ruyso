"""
Main application window: a single window with a custom three-tab band
(Pipeline / Table / Dashboard) over a stacked set of pages, plus a
global menu bar (Pipeline, Node, Dashboard, View). There is no
toolbar -- every action lives in a menu.

This module only wires widgets together and reacts to user actions --
it holds no pipeline-execution logic (``execution_worker.py``), no
node-building logic (``node_factory.py`` / ``canvas.py``), no
micro-type-swap logic (``node_editing.py``), and each tab's layout
lives in its own page module. Keeping it a thin assembly layer is what
makes each concern independently testable.

Menus:
    Pipeline  -- Open/Save JSON, Export as script, Run (always enabled;
                 the pipeline is one shared document across tabs).
    Edit      -- Undo / Redo, Preferences... (always).
    Node      -- New Node > <macro type>, Selected Node > Delete Node
                 (enabled only on the Pipeline tab).
    Dashboard -- Exporter... (enabled only on the Dashboard tab).
    Colormaps -- Designer / Manager (always).
    View      -- Theme, Auto-run (always).

Error reporting: a run's failures go to the Problems panel
(``ui.error_panel``) and the tab band's chip, never to a dialog. The
``QMessageBox`` in :meth:`MainWindow._show_error` is reserved for file
actions the person invoked -- Open, Save, Export -- where there is no
panel row that would make the failure obvious.
"""

from __future__ import annotations

from pathlib import Path

from NodeGraphQt import BaseNode
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ruyso_app.engine.codegen import save_script
from ruyso_app.engine.graph import GraphValidationError, PipelineGraph
from ruyso_app.core import toolboxes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine import settings
from ruyso_app.engine.errors import NodeError
from ruyso_app.engine.serialization import (
    CANVAS_KEY,
    DASHBOARD_KEY,
    load_document,
    save_document,
)
from ruyso_app.ui import render_queue, theme
from ruyso_app.ui.auto_run import AutoRunController
from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.column_spec import input_column_values, input_dataframe_columns
from ruyso_app.ui.dashboard_menus import fill_arrange_menu, fill_shape_menu
from ruyso_app.ui.dashboard_page import DashboardPage
from ruyso_app.ui.error_panel import GRAPH_PROBLEM
from ruyso_app.ui.execution_worker import PipelineExecutionWorker
from ruyso_app.ui.graph_bridge import (
    apply_canvas_layout,
    canvas_layout,
    canvas_to_pipeline,
    pipeline_to_canvas,
)
from ruyso_app.ui.node_editing import change_node_micro_type
from ruyso_app.ui.node_factory import (
    core_node_types_by_category,
    qt_type_for,
    register_all_nodes,
    register_node_context_menu_actions,
)
from ruyso_app.ui.node_menu import install_new_node_menu, refresh_new_node_menu
from ruyso_app.ui.node_preview import (
    NodePreviewOverlay,
    figure_axis_limits,
    resolve_figure,
    resolve_source_node,
)
from ruyso_app.ui.node_status import NodeStatusController
from ruyso_app.ui.pipeline_page import PipelinePage
from ruyso_app.ui.run_snapshot import modified_since_run, pipeline_signatures
from ruyso_app.ui.tab_bar import TabBar
from ruyso_app.ui.table_page import TablePage

#: Chord letter (after Cmd/Ctrl+P) that creates a node of each macro type.
_MACRO_SHORTCUT_LETTER: dict[str, str] = {
    "loading": "L",
    "transform": "T",
    "model": "M",
    "statistics": "S",
    "grapher": "G",
    "export": "E",
}

#: (key, label) for each tab, in display order (spec section 1).
TABS: list[tuple[str, str]] = [
    ("pipeline", "Pipeline"),
    ("table", "Table"),
    ("dashboard", "Dashboard"),
]


def _summarise(value: object) -> str:
    """
    One output, short enough for a log line.

    ``repr`` of a large DataFrame is both slow to build and long enough
    to bury everything else in the log, so the default is a shape. The
    full repr is behind Preferences > Advanced > verbose run log, for
    when it is the thing you actually want to read.
    """
    columns = getattr(value, "columns", None)
    index = getattr(value, "index", None)
    if columns is not None and index is not None:
        try:
            return f"DataFrame({len(index)} rows x {len(columns)} cols)"
        except TypeError:
            pass
    if hasattr(value, "savefig"):
        return "Figure"
    text = repr(value)
    return text if len(text) <= 200 else f"{text[:197]}..."


class MainWindow(QMainWindow):
    """The pipeline builder's main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ruyso-app - Pipeline Builder")
        self.resize(1400, 900)

        self._canvas = PipelineCanvas()
        self._graph = self._canvas.graph
        #: Path of the pipeline file on screen, or None for an unsaved one.
        #: With the undo stack's clean marker below, this is what lets the
        #: window behave like a document: a title that says what is open,
        #: a dot when it has unsaved edits, and a prompt before losing them.
        self._pipeline_path: str | None = None
        self._node_status = NodeStatusController(self._graph)
        self._worker: PipelineExecutionWorker | None = None
        self._last_outputs: dict[str, dict] = {}
        # Node ids that raised in the most recent (auto-)run; drives the
        # Dashboard tab's "· modified" flag on figures that failed.
        self._last_run_errors: dict[str, str] = {}
        # Whether a background auto-run has completed at least once
        # (until then the "auto" pill stays grey, like the run bar).
        self._auto_run_ran = False
        # Signatures of the pipeline as it was when last run successfully
        # (see ui.run_snapshot); drives the Table tab's "· modified" tags.
        self._run_snapshot: dict[str, str] = {}
        self._pending_snapshot: dict[str, str] = {}

        self._pipeline_page = PipelinePage(self._canvas)
        self._table_page = TablePage()
        self._dashboard_page = DashboardPage()
        self._options = self._pipeline_page.options_panel

        self._preview_overlay = NodePreviewOverlay(self._graph)
        # Clicking a figure preview selects its plot, so the Options
        # panel stays on that node while its pop-out window is open.
        self._preview_overlay.node_activated.connect(self._on_preview_clicked)
        self._preview_overlay.layout_changed.connect(self._on_canvas_layout_changed)

        self._tab_bar = TabBar(TABS)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._pipeline_page)
        self._stack.addWidget(self._table_page)
        self._stack.addWidget(self._dashboard_page)
        self._tab_index = {key: i for i, (key, _label) in enumerate(TABS)}

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._tab_bar)
        layout.addWidget(self._stack, 1)
        self.setCentralWidget(central)

        self._tab_bar.tab_changed.connect(self._on_tab_changed)
        self._tab_bar.run_button.clicked.connect(self._on_run_pipeline)
        self._dashboard_page.export_requested.connect(self._on_export_dashboard)
        self._dashboard_page.figure_block_selected.connect(
            self._on_dashboard_figure_selected
        )
        self._dashboard_page.options_panel.node_type_change_requested.connect(
            self._on_dashboard_node_type_change
        )
        self._options.node_type_change_requested.connect(self._on_node_type_change)
        self._graph.node_selection_changed.connect(self._on_selection_changed)
        self._pipeline_page.problems.problem_activated.connect(
            self._on_problem_activated
        )
        self._tab_bar.problems_chip.clicked.connect(self._on_problems_chip_clicked)

        install_new_node_menu(self._graph, self._on_pick_macro_type)
        register_node_context_menu_actions(
            self._graph, self._on_ctx_delete, self._on_ctx_add_to_dashboard
        )

        # Background auto-run: reload data / recompute whatever is ready
        # whenever the canvas changes, so results appear without Run.
        self._auto_run = AutoRunController(lambda: canvas_to_pipeline(self._graph), self)
        self._auto_run.finished.connect(self._on_auto_run_finished)
        self._auto_run.started.connect(lambda: self._refresh_auto_pill(running=True))
        # Per-node status dots: streamed from the auto-run worker.
        self._auto_run.node_status.connect(self._node_status.set_status)
        self._graph.node_created.connect(self._node_status.mark_new)
        for signal in (
            self._graph.node_created,
            self._graph.nodes_deleted,
            self._graph.port_connected,
            self._graph.port_disconnected,
        ):
            signal.connect(self._auto_run.schedule)
        # Param edits usually schedule an auto-run too -- except tickbox
        # edits, which the Options panel batches until it loses focus.
        self._graph.property_changed.connect(self._on_property_changed)
        self._options.recompute_requested.connect(self._auto_run.schedule)
        self._dashboard_page.options_panel.recompute_requested.connect(
            self._auto_run.schedule
        )

        self._build_menus()
        self._refresh_auto_pill()  # initial state + tooltip
        self._on_tab_changed(self._tab_bar.current_key())

        # "Unsaved changes" is exactly "the undo stack has moved since
        # the last save", which QUndoStack already tracks for free.
        self._graph.undo_stack().cleanChanged.connect(self._refresh_title)
        self._dashboard_page.undo_stack().cleanChanged.connect(self._refresh_title)
        self._graph.undo_stack().setClean()
        self._dashboard_page.undo_stack().setClean()
        self._refresh_title()
        self.apply_preferences()
        self._restore_session()

        # Follow the OS light/dark setting live while mode is "system".
        app = QApplication.instance()
        hints = app.styleHints() if app is not None else None
        if hints is not None and hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_system_color_scheme_changed)
        self._apply_theme()

    # -- construction ------------------------------------------------------

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()

        # -- Pipeline menu (always enabled) -----------------------------
        pipeline_menu = menu_bar.addMenu("Pipeline")
        pipeline_menu.addAction("Open Pipeline (JSON)...", self._on_load_pipeline)
        pipeline_menu.addAction("Save Pipeline (JSON)...", self._on_save_pipeline)
        pipeline_menu.addSeparator()
        pipeline_menu.addAction("Export as Script (.py)...", self._on_export_script)
        pipeline_menu.addSeparator()
        self._run_action = pipeline_menu.addAction("Run Pipeline", self._on_run_pipeline)
        self._run_action.setShortcut(QKeySequence("F5"))
        # Run reuses results nothing has changed for, so on a pipeline
        # that is already current it finishes in a blink. This is the way
        # back to "compute every step again, whatever you think you know"
        # -- also what Shift + the Run button does.
        self._force_run_action = pipeline_menu.addAction(
            "Force Full Run", self._on_force_run_pipeline
        )
        self._force_run_action.setShortcut(QKeySequence("Shift+F5"))

        # -- Edit menu (always) ---------------------------------------
        # NodeGraphQt records node creation, deletion, wiring and every
        # ``set_property`` on its own QUndoStack, so Undo/Redo come
        # straight off that stack rather than being reimplemented here.
        edit_menu = menu_bar.addMenu("Edit")
        stack = self._graph.undo_stack()
        # Deliberately *not* stack.createUndoAction(): the resync below
        # has to run only when history actually moves. Hanging it off
        # ``indexChanged`` instead would fire on every ordinary edit too
        # -- each keystroke pushes a command -- and rebuild the Options
        # form out from under the widget being typed in.
        self._undo_action = QAction("Undo", self)
        self._undo_action.setShortcut(QKeySequence.Undo)
        self._undo_action.setEnabled(stack.canUndo())
        self._undo_action.triggered.connect(self._on_undo)
        # Both stacks report in; which one is believed depends on the tab.
        stack.canUndoChanged.connect(lambda _c: self._refresh_undo_actions())
        self._dashboard_page.undo_stack().canUndoChanged.connect(
            lambda _c: self._refresh_undo_actions()
        )

        self._redo_action = QAction("Redo", self)
        self._redo_action.setShortcuts(
            [QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")]
        )
        self._redo_action.setEnabled(stack.canRedo())
        self._redo_action.triggered.connect(self._on_redo)
        stack.canRedoChanged.connect(lambda _c: self._refresh_undo_actions())
        self._dashboard_page.undo_stack().canRedoChanged.connect(
            lambda _c: self._refresh_undo_actions()
        )

        edit_menu.addAction(self._undo_action)
        edit_menu.addAction(self._redo_action)

        # -- Node menu (Pipeline tab only) ----------------------------
        self._node_menu = menu_bar.addMenu("Node")
        new_node_menu = self._node_menu.addMenu("New Node")
        available = core_node_types_by_category()
        #: Kept so the entries can be re-enabled when a toolbox is
        #: switched on or off (see _refresh_node_menus).
        self._macro_actions: dict[str, QAction] = {}
        for category, label in theme.MACRO_TYPE_LABELS.items():
            action = new_node_menu.addAction(label)
            letter = _MACRO_SHORTCUT_LETTER.get(category)
            if letter:
                # Two-key chord, e.g. Cmd/Ctrl+P then L for a data loader.
                action.setShortcut(QKeySequence(f"Ctrl+P, {letter}"))
            # Connected regardless: a macro type with nothing behind it
            # is disabled, and disabling is what a toolbox change flips.
            action.triggered.connect(
                lambda _checked=False, c=category: self._on_pick_macro_type(c, None)
            )
            action.setEnabled(category in available)
            self._macro_actions[category] = action

        selected_menu = self._node_menu.addMenu("Selected Node")
        self._delete_action = selected_menu.addAction("Delete Node")
        self._delete_action.setShortcuts(
            [QKeySequence("Ctrl+Backspace"), QKeySequence("Ctrl+Delete")]
        )
        self._delete_action.triggered.connect(self._on_delete_selected_nodes)

        selected_menu.addSeparator()
        copy_action = selected_menu.addAction("Copy")
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.triggered.connect(self._on_copy_nodes)
        cut_action = selected_menu.addAction("Cut")
        cut_action.setShortcut(QKeySequence.Cut)
        cut_action.triggered.connect(self._on_cut_nodes)
        paste_action = selected_menu.addAction("Paste")
        paste_action.setShortcut(QKeySequence.Paste)
        paste_action.triggered.connect(self._on_paste_nodes)
        duplicate_action = selected_menu.addAction("Duplicate")
        duplicate_action.setShortcut(QKeySequence("Ctrl+D"))
        duplicate_action.triggered.connect(self._on_duplicate_nodes)

        # -- Dashboard menu (Dashboard tab only) ---------------------
        self._dashboard_menu = menu_bar.addMenu("Dashboard")
        page = self._dashboard_page
        self._dashboard_menu.addAction(
            "Add Title", lambda: page.add_text_item(is_title=True)
        )
        self._dashboard_menu.addAction(
            "Add Text Box", lambda: page.add_text_item(is_title=False)
        )

        # The same two menus the canvas right-click and the Dashboard
        # tool strip offer -- built once, in ui/dashboard_menus.py.
        fill_shape_menu(self._dashboard_menu.addMenu("Add Shape"), page)
        self._dashboard_menu.addAction("Add Image...", page.import_image)
        fill_arrange_menu(self._dashboard_menu.addMenu("Arrange"), page)

        self._dashboard_menu.addSeparator()
        duplicate = self._dashboard_menu.addAction(
            "Duplicate Block", page.duplicate_selected
        )
        duplicate.setShortcut(QKeySequence("Ctrl+D"))
        self._dashboard_menu.addAction("Lock Block", page.lock_selected)
        # A locked block cannot be selected, so it cannot be unlocked
        # from its own inspector -- this is the way back.
        self._dashboard_menu.addAction("Unlock All", page.unlock_all)
        self._dashboard_menu.addSeparator()
        self._dashboard_menu.addAction("Exporter...", self._on_export_dashboard)

        # Preferences: PreferencesRole moves it under the application
        # menu at Cmd+, on macOS, and leaves it here everywhere else.
        self._preferences_action = QAction("Preferences...", self)
        self._preferences_action.setMenuRole(QAction.PreferencesRole)
        self._preferences_action.setShortcut(QKeySequence.Preferences)
        self._preferences_action.triggered.connect(self._on_open_preferences)
        edit_menu.addSeparator()
        edit_menu.addAction(self._preferences_action)

        # -- Colormaps menu (always) -------------------------------
        colormaps_menu = menu_bar.addMenu("Colormaps")
        colormaps_menu.addAction("Colormap Designer...", self._on_open_colormap_designer)
        colormaps_menu.addAction("Colormap Manager...", self._on_open_colormap_manager)

        # -- View menu (always) --------------------------------------
        view_menu = menu_bar.addMenu("View")
        theme_menu = view_menu.addMenu("Theme")
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        for label, mode in (("System", "system"), ("Dark", "dark"), ("Light", "light")):
            action = theme_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(theme.theme_mode() == mode)
            self._theme_group.addAction(action)
            action.triggered.connect(
                lambda _checked=False, m=mode: self._set_theme_mode(m)
            )

        view_menu.addSeparator()
        self._auto_run_action = view_menu.addAction("Auto-run")
        self._auto_run_action.setCheckable(True)
        self._auto_run_action.setChecked(True)
        self._auto_run_action.toggled.connect(self._on_toggle_auto_run)
        # Clicking the tab-band "auto" chip is the same switch.
        self._tab_bar.auto_pill.clicked.connect(self._auto_run_action.toggle)

    # -- document state --------------------------------------------------

    def is_modified(self) -> bool:
        """
        Whether the document has edits that have not been saved.

        Both histories count: the dashboard's layout is saved into the
        same file, so an hour spent arranging it is work that can be
        lost, and the title's dot and the close prompt have to know.

        Guarded against a stack being gone: ``cleanChanged`` can arrive
        while Qt is tearing the window down, and a RuntimeError raised
        inside a signal handler at that point is the shape of problem
        that ends in a segfault rather than a traceback.
        """
        try:
            return (
                not self._graph.undo_stack().isClean()
                or not self._dashboard_page.undo_stack().isClean()
                # A collapsed preview is saved with the pipeline but pushes
                # no undo command, so it needs a flag of its own.
                or getattr(self, "_layout_dirty", False)
            )
        except RuntimeError:  # a C++ stack is already deleted
            return False

    def _refresh_title(self, *_args: object) -> None:
        """``ruyso-app — <file> •``, the dot meaning unsaved edits."""
        name = Path(self._pipeline_path).name if self._pipeline_path else "Untitled"
        marker = " •" if self.is_modified() else ""
        try:
            self.setWindowTitle(f"ruyso-app - {name}{marker}")
        except RuntimeError:  # the window is being torn down
            return

    def _mark_saved(self, path: str) -> None:
        self._pipeline_path = path
        self._graph.undo_stack().setClean()
        self._dashboard_page.undo_stack().setClean()
        self._layout_dirty = False
        settings.set("general.last_pipeline", path)
        self._refresh_title()

    def _on_canvas_layout_changed(self) -> None:
        """A preview was collapsed or expanded -- saved with the document,
        but not an undoable edit, so it marks the document by hand."""
        self._layout_dirty = True
        self._refresh_title()

    def _dialog_folder(self) -> str:
        """Where a file dialog should open: the current file's folder,
        else the configured default, else wherever Qt would."""
        if self._pipeline_path:
            return str(Path(self._pipeline_path).parent)
        return str(settings.get("general.default_folder") or "")

    def confirm_discard_changes(self) -> bool:
        """
        Ask before throwing away unsaved edits. ``True`` to proceed.

        Silent when there is nothing to lose, or when the person turned
        the prompt off -- a confirmation nobody wanted is just a click.
        """
        if not self.is_modified() or not settings.get("general.confirm_on_close"):
            return True
        name = Path(self._pipeline_path).name if self._pipeline_path else "this pipeline"
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            f"Save changes to {name} before closing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            self._on_save_pipeline()
            return not self.is_modified()  # a cancelled Save cancels the close
        return True

    def _restore_session(self) -> None:
        """Reopen the last pipeline, if that preference is on."""
        if not settings.get("general.restore_last_pipeline"):
            return
        path = str(settings.get("general.last_pipeline") or "")
        if path and Path(path).is_file():
            self._open_pipeline_file(path)

    # -- preferences -----------------------------------------------------

    def apply_preferences(self) -> None:
        """Push every live preference into the widgets that honour it."""
        theme.set_theme_mode(str(settings.get("appearance.theme")))
        self._apply_theme()
        self._pipeline_page.apply_preferences()
        self._dashboard_page.apply_preferences()
        self._preview_overlay.apply_preferences()
        self._auto_run.apply_preferences()
        self._auto_run_action.setChecked(self._auto_run.is_user_enabled())
        self._refresh_auto_pill()

    # -- tab / menu state ------------------------------------------------

    def active_undo_stack(self):
        """
        The history Cmd+Z acts on: the tab in front owns it.

        The Dashboard is a separate scene with its own stack. Without
        this, editing the dashboard and pressing Cmd+Z would quietly
        undo something on the Pipeline tab instead -- a shortcut that
        appears to do nothing while changing a tab you are not looking
        at is worse than one that does nothing at all.
        """
        if self.current_tab() == "dashboard":
            return self._dashboard_page.undo_stack()
        return self._graph.undo_stack()

    def _on_undo(self) -> None:
        stack = self.active_undo_stack()
        if stack is self._graph.undo_stack():
            self._options.flush_recompute()  # fold in pending ticks first
        stack.undo()
        self._after_history_move()

    def _on_redo(self) -> None:
        self.active_undo_stack().redo()
        self._after_history_move()

    def _refresh_undo_actions(self) -> None:
        """
        Point the Edit menu at the active tab's history.

        Guarded: both stacks report their availability here, and one can
        arrive while Qt is tearing the window down. A RuntimeError
        raised inside a signal handler at that point is the shape of
        problem that ends in a segfault rather than a traceback.
        """
        try:
            stack = self.active_undo_stack()
            self._undo_action.setEnabled(stack.canUndo())
            self._redo_action.setEnabled(stack.canRedo())
        except RuntimeError:  # a C++ object is already gone
            return

    def _after_history_move(self) -> None:
        """Undo / redo rewrote node params behind the Options panel's
        back: rebuild the form from the node and recompute, or the panel
        would keep showing the value that was just undone."""
        self._on_selection_changed()
        self._refresh_undo_actions()
        self._auto_run.schedule()

    def _on_property_changed(self, *args: object) -> None:
        """Schedule an auto-run for a param edit, unless it's a batched tick.

        Also drops the red outline on the row that was just edited: the
        highlight points at the thing to fix, so it must not keep
        arguing with a value the person has already changed. Whether the
        edit *worked* is the next run's answer, not this one's.
        """
        if len(args) >= 2 and isinstance(args[1], str):
            self._options.clear_field_error(args[1])
        if not self._options.autorun_suppressed():
            self._auto_run.schedule()

    # -- auto-run status ("auto" pill in the tab band) -----------------

    def _on_toggle_auto_run(self, enabled: bool) -> None:
        """View > Auto-run / the "auto" chip: persist the choice. Turning
        it off interrupts any in-flight auto-run; turning it back on
        re-runs to catch up on changes missed while it was off."""
        self._auto_run.set_user_enabled(enabled)
        settings.set("execution.auto_run", enabled)
        if enabled:
            self._auto_run.schedule()
        else:
            self._auto_run.interrupt()
        self._refresh_auto_pill()

    def _refresh_auto_pill(self, running: bool = False) -> None:
        """Set the tab band's 'auto' dot from the current auto-run state."""
        pill = self._tab_bar.auto_pill
        pill.setToolTip(
            "Auto-run is on — click to pause"
            if self._auto_run.is_user_enabled()
            else "Auto-run is paused — click to resume"
        )
        manual_run_in_progress = not self._tab_bar.run_button.isEnabled()
        if not self._auto_run.is_user_enabled() or manual_run_in_progress:
            pill.set_state("idle")
        elif running:
            pill.set_state("running")
        elif not self._auto_run_ran:
            pill.set_state("idle")
        else:
            pill.set_state("error" if self._last_run_errors else "ok")

    # -- Colormaps menu ------------------------------------------------

    def _on_open_preferences(self) -> None:
        from ruyso_app.ui.preferences_dialog import PreferencesDialog

        dialog = PreferencesDialog(self, nodes_in_use=self._nodes_in_use)
        dialog.applied.connect(self._on_preferences_applied)
        dialog.exec()

    def _nodes_in_use(self) -> dict[str, list[str]]:
        """``{node_type: [display name, ...]}`` for the current canvas.

        The Toolbox page needs it to refuse switching off a family the
        pipeline is built on."""
        used: dict[str, list[str]] = {}
        for node in self._graph.all_nodes():
            node_type = getattr(type(node), "CORE_NODE_TYPE", None)
            if node_type:
                used.setdefault(node_type, []).append(node.name())
        return used

    def _on_preferences_applied(self) -> None:
        """Preferences were committed: push them into the live widgets."""
        self.apply_preferences()
        self._refresh_node_menus()  # a toolbox may have come or gone
        self._auto_run.schedule()  # figure defaults may have changed

    def _refresh_node_menus(self) -> None:
        """Re-enable / disable the macro-type entries for the toolboxes
        that are switched on now."""
        available = core_node_types_by_category()
        for category, action in self._macro_actions.items():
            action.setEnabled(category in available)
        refresh_new_node_menu(self._graph)

    def _on_open_colormap_designer(self) -> None:
        from ruyso_app.ui.colormap_designer import ColormapDesigner

        dialog = ColormapDesigner(self)
        dialog.changed.connect(self._on_colormaps_changed)
        dialog.exec()

    def _on_open_colormap_manager(self) -> None:
        from ruyso_app.ui.colormap_manager import ColormapManager

        dialog = ColormapManager(self)
        dialog.changed.connect(self._on_colormaps_changed)
        dialog.exec()

    def _on_colormaps_changed(self) -> None:
        """A custom colormap / the dropdown selection changed -- repaint
        swatches and repopulate every open colormap dropdown."""
        from ruyso_app.ui import swatches

        swatches.clear_cache()
        self._options.refresh_colormap_choices()
        self._dashboard_page.options_panel.refresh_colormap_choices()
        self._auto_run.schedule()  # re-render figures that use the changed map

    def _on_tab_changed(self, key: str) -> None:
        self._options.flush_recompute()  # commit any pending tickbox edits
        self._stack.setCurrentIndex(self._tab_index[key])
        self._node_menu.setEnabled(key == "pipeline")
        self._dashboard_menu.setEnabled(key == "dashboard")
        self._refresh_undo_actions()  # Cmd+Z follows the tab in front
        if key == "table":
            # Rebuild from the current canvas each time the tab is shown.
            self._table_page.refresh(
                self._graph, self._last_outputs, self._table_modified_set()
            )
        elif key == "dashboard":
            self._dashboard_page.sync_figures(
                self._graph,
                self._last_outputs,
                self._table_modified_set(),
                set(self._last_run_errors),
            )

    def current_tab(self) -> str:
        """The key of the currently visible tab (used by tests)."""
        return self._tab_bar.current_key()

    # -- node creation / selection ---------------------------------------

    def _on_pick_macro_type(
        self, category: str, pos: list[float] | None = None
    ) -> None:
        """
        Step 1 of the two-step flow: a macro type was chosen (from the
        canvas right-click menu or the Node menu). Create the first
        concrete node of that macro type and select it, so the Options
        panel opens with the micro-type dropdown ready to refine it.

        Args:
            category: The chosen macro type.
            pos: ``[x, y]`` scene position to place the node at -- the
                cursor position when invoked from the canvas right-click
                menu; ``None`` (from the Node menu / a shortcut) drops
                it in the middle of the view.
        """
        node_types = core_node_types_by_category().get(category, [])
        if not node_types:
            return
        node = self._graph.create_node(
            qt_type_for(node_types[0]), pos=pos or self._new_node_pos()
        )
        self._select_only(node)

    def _new_node_pos(self) -> list[float]:
        viewer = self._graph.viewer()
        center = viewer.mapToScene(viewer.viewport().rect().center())
        return [center.x(), center.y()]

    def _select_only(self, node: BaseNode) -> None:
        for other in self._graph.selected_nodes():
            # push_undo=False: BaseNode.set_selected() would push a
            # command per node, so selecting something would bury the
            # real edits under "undo the selection" steps and the first
            # Ctrl+Z presses would look like they did nothing. Clicking a
            # node on the canvas already bypasses the stack (NodeGraphQt
            # updates the item directly), so this just matches it.
            other.set_property("selected", False, push_undo=False)
        node.set_property("selected", True, push_undo=False)
        self._on_selection_changed([node], [])

    def _on_selection_changed(self, *_args: object) -> None:
        selected = self._graph.selected_nodes()
        ruyso_nodes = [n for n in selected if hasattr(type(n), "CORE_NODE_TYPE")]
        if len(ruyso_nodes) == 1:
            node = ruyso_nodes[0]
            self._options.show_node(
                node,
                core_node_types_by_category(),
                input_dataframe_columns(node, self._last_outputs),
                input_column_values(node, self._last_outputs),
            )
            self._options.set_axis_limits(self._axis_limits_for(node))
        else:
            self._options.clear()

    def _axis_limits_for(self, node: BaseNode) -> dict[str, str]:
        """The axis range this node's last-rendered plot used, if any."""
        figure = resolve_figure(node, self._last_outputs)
        return figure_axis_limits(figure)

    def _on_preview_clicked(self, node_id: str) -> None:
        """A figure thumbnail was clicked: select its node (NodeGraphQt's
        internal id, which is what the preview overlay keys on)."""
        node = next((n for n in self._graph.all_nodes() if n.id == node_id), None)
        if node is not None:
            self._select_only(node)

    def _on_node_type_change(self, new_type: str) -> None:
        """Macro or micro dropdown changed: recreate the node as ``new_type``."""
        node = self._options.current_node()
        if node is None:
            return
        new_node = change_node_micro_type(self._graph, node, new_type)
        self._select_only(new_node)

    # -- delete (three equivalent paths: menu, shortcut, right-click) ----

    def _on_delete_selected_nodes(self) -> None:
        selected = self._graph.selected_nodes()
        if not selected:
            self.statusBar().showMessage("No node selected to delete.", 4000)
            return
        self._graph.delete_nodes(selected)
        self._options.clear()
        self.statusBar().showMessage(f"Deleted {len(selected)} node(s).", 4000)

    def _on_ctx_delete(self, _graph: object, node: BaseNode) -> None:
        self._graph.delete_nodes([node])
        self._options.clear()

    # -- copy / cut / paste / duplicate (Pipeline tab) -----------------

    def _own_nodes(self, nodes: list[BaseNode]) -> list[BaseNode]:
        """Keep only nodes built by ``node_factory`` (drop NodeGraphQt built-ins)."""
        return [n for n in nodes if hasattr(type(n), "CORE_NODE_TYPE")]

    def _on_copy_nodes(self) -> None:
        selected = self._own_nodes(self._graph.selected_nodes())
        if not selected:
            self.statusBar().showMessage("No node selected to copy.", 4000)
            return
        self._graph.copy_nodes(selected)
        self.statusBar().showMessage(f"Copied {len(selected)} node(s).", 4000)

    def _on_cut_nodes(self) -> None:
        selected = self._own_nodes(self._graph.selected_nodes())
        if not selected:
            self.statusBar().showMessage("No node selected to cut.", 4000)
            return
        self._graph.cut_nodes(selected)
        self._options.clear()
        self._auto_run.schedule()
        self.statusBar().showMessage(f"Cut {len(selected)} node(s).", 4000)

    def _on_paste_nodes(self) -> None:
        pasted = self._own_nodes(list(self._graph.paste_nodes() or []))
        if not pasted:
            self.statusBar().showMessage("Nothing on the clipboard to paste.", 4000)
            return
        if len(pasted) == 1:
            self._select_only(pasted[0])
        else:
            self._on_selection_changed()
        self._auto_run.schedule()
        self.statusBar().showMessage(f"Pasted {len(pasted)} node(s).", 4000)

    def _on_duplicate_nodes(self) -> None:
        selected = self._own_nodes(self._graph.selected_nodes())
        if not selected:
            self.statusBar().showMessage("No node selected to duplicate.", 4000)
            return
        duplicated = self._own_nodes(list(self._graph.duplicate_nodes(selected) or []))
        if len(duplicated) == 1:
            self._select_only(duplicated[0])
        elif not duplicated:
            return
        self._auto_run.schedule()
        self.statusBar().showMessage(f"Duplicated {len(duplicated)} node(s).", 4000)

    def _on_ctx_add_to_dashboard(self, _graph: object, node: BaseNode) -> None:
        """Drop an ``export_to_dashboard`` node wired to this node's figure."""
        outputs = node.outputs()
        if "figure" not in outputs:
            self.statusBar().showMessage("This node has no figure output.", 4000)
            return
        pos = node.pos()
        export_node = self._graph.create_node(
            qt_type_for("export_to_dashboard"), pos=[pos[0] + 260, pos[1]]
        )
        outputs["figure"].connect_to(export_node.inputs()["figure"])
        self._select_only(export_node)
        self.statusBar().showMessage(
            f"Added an export_to_dashboard node after '{node.name()}'. "
            "Run the pipeline to see it on the Dashboard.",
            5000,
        )

    # -- Dashboard interaction -----------------------------------------

    def _on_dashboard_figure_selected(self, export_node_id: str) -> None:
        """A dashboard figure block was picked: edit its source plot's params."""
        node = next(
            (n for n in self._graph.all_nodes() if n.name() == export_node_id), None
        )
        source = resolve_source_node(node) if node is not None else None
        if source is None:
            self._dashboard_page.set_canvas_message(
                "This figure's source plot is disconnected — "
                "reconnect it in the Pipeline tab."
            )
            return
        self._dashboard_page.set_canvas_message(None)
        self._populate_dashboard_panel(source)

    def _populate_dashboard_panel(self, source_node: BaseNode) -> None:
        self._dashboard_page.options_panel.show_node(
            source_node,
            core_node_types_by_category(),
            input_dataframe_columns(source_node, self._last_outputs),
            input_column_values(source_node, self._last_outputs),
        )
        self._dashboard_page.options_panel.set_axis_limits(
            self._axis_limits_for(source_node)
        )
        self._dashboard_page.show_options_page()

    def _on_dashboard_node_type_change(self, new_type: str) -> None:
        node = self._dashboard_page.options_panel.current_node()
        if node is None:
            return
        new_node = change_node_micro_type(self._graph, node, new_type)
        self._populate_dashboard_panel(new_node)

    # -- Dashboard menu actions ------------------------------------------

    def _on_export_dashboard(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Dashboard", "", "PDF (*.pdf);;PNG image (*.png)"
        )
        if not path:
            return
        try:
            self._dashboard_page.export(path, dpi=200)
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            self._show_error("Could not export dashboard", exc)
        else:
            self.statusBar().showMessage(f"Exported dashboard to {path}", 5000)

    # -- View menu actions -----------------------------------------------

    def _set_theme_mode(self, mode: str) -> None:
        theme.set_theme_mode(mode)
        settings.set("appearance.theme", mode)  # the choice outlives the session
        self._apply_theme()

    def _on_system_color_scheme_changed(self, *_args: object) -> None:
        if theme.theme_mode() == "system":
            theme.refresh_from_system()
            self._apply_theme()

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            theme.apply_to_app(app)
        self._pipeline_page.apply_theme()
        self._table_page.apply_theme()
        self._dashboard_page.apply_theme()
        self._node_status.refresh_theme()
        self._preview_overlay.apply_theme()

    # -- Pipeline menu actions -----------------------------------------

    def _on_load_pipeline(self) -> None:
        if not self.confirm_discard_changes():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Pipeline", self._dialog_folder(), "Pipeline JSON (*.json)"
        )
        if path:
            self._open_pipeline_file(path)

    def _missing_toolboxes(self, pipeline: PipelineGraph) -> list:
        """
        Families that would have to be switched on for this pipeline.

        Asks whether each node's family is *enabled*, not whether the
        node happens to be in the registry. The registry is not a stable
        answer: working out which family owns a node type requires
        importing every module, so anything that has already done that
        -- opening Preferences, which imports them all to count nodes --
        would leave every type "known" and this returning nothing, right
        before the canvas failed to build the node anyway.
        """
        by_toolbox = toolboxes.node_types_by_toolbox()
        owner = {t: key for key, types in by_toolbox.items() for t in types}
        enabled = toolboxes.enabled_keys()

        needed: list = []
        for spec in pipeline.nodes.values():
            key = owner.get(spec.node_type)
            if key is None or key in enabled:
                continue
            toolbox = toolboxes.get(key)
            if toolbox is not None and toolbox not in needed:
                needed.append(toolbox)
        return needed

    def _enable_toolboxes_for(self, pipeline: PipelineGraph) -> bool:
        """
        Offer to switch a needed family back on. ``True`` to carry on.

        Asked rather than done silently: the preference is the person's,
        and a setting that changes itself behind your back is the sort
        of thing that is confusing weeks later.
        """
        missing = self._missing_toolboxes(pipeline)
        if not missing:
            return True
        names = ", ".join(toolbox.title for toolbox in missing)
        answer = QMessageBox.question(
            self,
            "Toolbox needed",
            f"This pipeline uses nodes from the {names} toolbox, which is "
            "switched off.\n\nEnable it and open the file?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return False
        enabled = set(settings.get(toolboxes.SETTING) or [])
        enabled.update(toolbox.key for toolbox in missing)
        settings.set(toolboxes.SETTING, sorted(enabled))
        register_all_nodes(self._graph)  # the newly enabled Qt classes
        self._refresh_node_menus()
        return True

    def _open_pipeline_file(self, path: str) -> None:
        try:
            pipeline, extras = load_document(path)
            if not self._enable_toolboxes_for(pipeline):
                return
            self._graph.clear_session()
            canvas_nodes = pipeline_to_canvas(pipeline, self._graph)
            # Nodes go back where they were saved. A file without a canvas
            # section (hand-written, or from before it existed) keeps the
            # row pipeline_to_canvas lays out.
            apply_canvas_layout(canvas_nodes, extras.get(CANVAS_KEY))
            # Opening a document replaces the document: a file with no
            # dashboard section means an empty dashboard, so blocks from
            # the pipeline that was open before cannot bleed into this
            # one and be saved into it.
            self._dashboard_page.restore(extras.get(DASHBOARD_KEY))
        except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
            self._show_error("Could not open pipeline", exc)
        else:
            # A freshly opened pipeline has no results yet. Its history
            # starts here too: undoing past a file load would unbuild the
            # opened pipeline into whatever was on the canvas before.
            self._graph.clear_undo_stack()
            self._last_outputs = {}
            self._run_snapshot = {}
            self._mark_saved(path)
            self.statusBar().showMessage(f"Opened {path}", 5000)

    def _on_save_pipeline(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Pipeline",
            self._pipeline_path or self._dialog_folder(),
            "Pipeline JSON (*.json)",
        )
        if not path:
            return
        try:
            pipeline = self._build_pipeline_or_raise()
            # The dashboard travels with the pipeline: one file is the
            # whole document, so sending someone a pipeline sends the
            # report with it.
            save_document(
                pipeline,
                path,
                {
                    DASHBOARD_KEY: self._dashboard_page.to_dict(),
                    CANVAS_KEY: canvas_layout(self._graph),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self._show_error("Could not save pipeline", exc)
        else:
            self._mark_saved(path)
            self.statusBar().showMessage(f"Saved {path}", 5000)

    def _on_export_script(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export as Script", self._dialog_folder(), "Python (*.py)"
        )
        if not path:
            return
        try:
            pipeline = self._build_pipeline_or_raise()
            save_script(pipeline, path, source_description="exported from the UI")
        except Exception as exc:  # noqa: BLE001
            self._show_error("Could not export script", exc)
        else:
            self.statusBar().showMessage(f"Exported script to {path}", 5000)

    def _on_force_run_pipeline(self) -> None:
        """Run every step, including the ones nothing has changed for."""
        self._on_run_pipeline(force=True)

    def _on_run_pipeline(self, *_args: object, force: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # a run is already in progress
        # Shift is the unlabelled half of Force Full Run: the button
        # carries no menu of its own to put the choice in.
        force = force or bool(
            QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier
        )

        self._options.flush_recompute()  # fold in any pending tickbox edits
        try:
            pipeline = self._build_pipeline_or_raise()
        except Exception as exc:  # noqa: BLE001
            self._show_error("Pipeline is not valid", exc)
            return

        self._run_action.setEnabled(False)
        self._tab_bar.run_button.setEnabled(False)
        self._auto_run.set_enabled(False)  # don't compete with the real run
        self._refresh_auto_pill()  # -> grey while the manual run is on
        self.statusBar().showMessage("Running pipeline...")
        self._pipeline_page.clear_log()
        self._tab_bar.progress.start(len(pipeline.nodes))
        # Remember exactly what is being run; promoted to _run_snapshot
        # only if this run succeeds.
        self._pending_snapshot = pipeline_signatures(pipeline)
        self._node_status.reset("pending")  # clear stale dots before streaming

        self._worker = PipelineExecutionWorker(
            pipeline, result_cache=None if force else self._auto_run.cache_snapshot()
        )
        self._worker.progress.connect(self._tab_bar.progress.set_progress)
        self._worker.node_status.connect(self._node_status.set_status)
        self._worker.succeeded.connect(self._on_run_succeeded)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.start()

    def _on_run_finished(self) -> None:
        self._run_action.setEnabled(True)
        self._tab_bar.run_button.setEnabled(True)
        self._auto_run.set_enabled(True)
        self._refresh_auto_pill()  # back to the last auto-run's state

    # -- execution callbacks (GUI thread, via Qt signals) ---------------

    def _on_run_succeeded(self, report) -> None:
        """A manual run finished. Nodes that ran are in ``report.outputs``
        whatever else failed, so their tables and figures still show."""
        outputs = report.outputs
        errors = dict(report.errors)
        verbose = bool(settings.get("advanced.verbose_log"))
        for node_id, node_outputs in outputs.items():
            for port_name, value in node_outputs.items():
                shown = repr(value) if verbose else _summarise(value)
                self._pipeline_page.append_log(f"[{node_id}] {port_name} = {shown}")
        for node_id, message in errors.items():
            self._pipeline_page.append_log(f"ERROR [{node_id}]: {message}")
            # dot is already red from the streamed phase; enrich the tooltip
            self._node_status.set_status(node_id, "error", message)

        # What this run computed is what the next background one reuses.
        worker_cache = getattr(self._worker, "result_cache", None)
        if worker_cache is not None:
            self._auto_run.adopt_cache(worker_cache)

        self._last_outputs = outputs
        self._last_run_errors = errors
        self._preview_overlay.set_run_outputs(outputs)
        self._dashboard_page.sync_figures(
            self._graph, outputs, self._table_modified_set(), set(errors)
        )
        self._table_page.refresh(self._graph, outputs, self._table_modified_set())

        self._show_problems(errors)
        if errors:
            # No dialog: a failing step is reported in the Problems panel,
            # which stays until the problem does and leads to the node.
            self.statusBar().showMessage("Pipeline finished with errors.", 5000)
            self._tab_bar.progress.finish_error()
            self._pipeline_page.show_problems()
        else:
            self.statusBar().showMessage("Pipeline finished.", 5000)
            self._tab_bar.progress.finish_success()
            self._run_snapshot = self._pending_snapshot

    def _on_run_failed(self, message: str) -> None:
        """The run could not start (structural validation failed)."""
        self.statusBar().showMessage("Pipeline failed.", 5000)
        self._tab_bar.progress.finish_error()
        self._pipeline_page.append_log(f"ERROR: {message}")
        # A structural problem belongs to the pipeline, not to any one
        # node, so it gets a row with no node to select.
        self._show_problems(
            {
                GRAPH_PROBLEM: NodeError(
                    node_id=GRAPH_PROBLEM,
                    node_type="",
                    kind="input",
                    title=message,
                    detail="The pipeline could not be started.",
                    raw=message,
                )
            }
        )
        self._pipeline_page.show_problems()

    # -- the Problems panel ---------------------------------------------

    def _show_problems(self, errors: dict) -> None:
        """Replace the Problems list and the tab-band chip's count."""
        problems = [error for error in errors.values() if isinstance(error, NodeError)]
        self._pipeline_page.problems.set_problems(problems)
        self._tab_bar.problems_chip.set_count(len(problems))

    def _on_problem_activated(self, node_id: str, field: str) -> None:
        """A row was clicked: go to that node, and point at the setting."""
        node = next(
            (n for n in self._graph.all_nodes() if n.name() == node_id), None
        )
        if node is None:
            return
        self._tab_bar.set_current_key("pipeline")
        self._select_only(node)
        if field:
            message = str(self._last_run_errors.get(node_id, ""))
            self._options.set_field_error(field, message)

    def _on_problems_chip_clicked(self) -> None:
        self._tab_bar.set_current_key("pipeline")
        self._pipeline_page.show_problems()

    def _on_auto_run_finished(self, report) -> None:
        """Merge a background auto-run's results without any dialog/log noise."""
        outputs = report.outputs
        self._last_run_errors = dict(report.errors)
        self._show_problems(self._last_run_errors)
        self._auto_run_ran = True
        self._refresh_auto_pill()  # -> green (clean) or red (raised)
        # the dot is already red from the streamed phase; add the message
        for node_id, message in self._last_run_errors.items():
            self._node_status.set_status(node_id, "error", message)
        if not outputs:
            # Nothing new computed, but the error set may have changed --
            # refresh the dashboard's "· modified" flags and bail.
            self._dashboard_page.sync_figures(
                self._graph, self._last_outputs,
                self._table_modified_set(), set(self._last_run_errors),
            )
            return
        self._last_outputs = {**self._last_outputs, **outputs}
        try:
            signatures = pipeline_signatures(canvas_to_pipeline(self._graph))
        except Exception:  # noqa: BLE001
            signatures = {}
        for node_id in outputs:
            if node_id in signatures:
                # Auto-run just recomputed this node -> it is current.
                self._run_snapshot[node_id] = signatures[node_id]

        self._preview_overlay.set_run_outputs(self._last_outputs)
        self._dashboard_page.sync_figures(
            self._graph, self._last_outputs,
            self._table_modified_set(), set(self._last_run_errors),
        )
        node = self._options.current_node()
        if node is not None:
            self._options.set_input_columns(
                input_dataframe_columns(node, self._last_outputs),
                input_column_values(node, self._last_outputs),
            )
            self._options.set_axis_limits(self._axis_limits_for(node))
        if self._dashboard_page.is_editing_figure():
            dsource = self._dashboard_page.options_panel.current_node()
            if dsource is not None:
                self._dashboard_page.options_panel.set_input_columns(
                    input_dataframe_columns(dsource, self._last_outputs),
                    input_column_values(dsource, self._last_outputs),
                )
                self._dashboard_page.options_panel.set_axis_limits(
                    self._axis_limits_for(dsource)
                )
        if self.current_tab() == "table":
            self._table_page.refresh(
                self._graph, self._last_outputs, self._table_modified_set()
            )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Confirm unsaved work, remember the window, then let any
        in-flight background run finish before the window dies."""
        if not self.confirm_discard_changes():
            event.ignore()
            return
        if settings.get("general.restore_window"):
            settings.set(
                "general.window_geometry",
                bytes(self.saveGeometry().toBase64()).decode("ascii"),
            )
        self._auto_run.set_enabled(False)
        for worker in (self._worker, getattr(self._auto_run, "_worker", None)):
            if worker is not None and worker.isRunning():
                worker.wait(3000)
        # The figure renderer outlives any one run, so it is stopped here
        # too: a QThread still going while Qt tears down is a segfault,
        # not a traceback.
        render_queue.shutdown()
        super().closeEvent(event)

    def restore_window_geometry(self) -> bool:
        """
        Put the window back where it was, if that preference is on.

        Called by the entry point rather than from ``__init__`` so a
        window built in a test keeps its deterministic default size.
        """
        if not settings.get("general.restore_window"):
            return False
        stored = str(settings.get("general.window_geometry") or "")
        if not stored:
            return False
        try:
            return self.restoreGeometry(QByteArray.fromBase64(stored.encode("ascii")))
        except Exception:  # noqa: BLE001 - a bad blob is not worth a crash
            return False

    # -- helpers --------------------------------------------------------

    def _build_pipeline_or_raise(self) -> PipelineGraph:
        pipeline = canvas_to_pipeline(self._graph)
        pipeline.validate()
        return pipeline

    def _table_modified_set(self) -> set[str]:
        """Node ids whose output would differ from the last successful run."""
        if not self._run_snapshot:
            return set()
        try:
            return modified_since_run(canvas_to_pipeline(self._graph), self._run_snapshot)
        except Exception:  # noqa: BLE001 - never let this break the Table tab
            return set()

    def _show_error(self, title: str, error: Exception | str) -> None:
        message = str(error)
        if isinstance(error, GraphValidationError):
            message = f"Pipeline is invalid: {message}"
        QMessageBox.critical(self, title, message)
