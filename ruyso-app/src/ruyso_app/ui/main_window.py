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
    Node      -- New Node > <macro type>, Selected Node > Delete Node
                 (enabled only on the Pipeline tab).
    Dashboard -- Exporter... (enabled only on the Dashboard tab).
    View      -- Toggle dark / light theme (always).
"""

from __future__ import annotations

from NodeGraphQt import BaseNode
from PySide6.QtGui import QActionGroup, QKeySequence
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
from ruyso_app.engine.serialization import load_graph, save_graph
from ruyso_app.ui import theme
from ruyso_app.ui.auto_run import AutoRunController
from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.column_spec import input_column_values, input_dataframe_columns
from ruyso_app.ui.dashboard_page import DashboardPage
from ruyso_app.ui.execution_worker import PipelineExecutionWorker
from ruyso_app.ui.graph_bridge import canvas_to_pipeline, pipeline_to_canvas
from ruyso_app.ui.node_editing import change_node_micro_type
from ruyso_app.ui.node_factory import (
    core_node_types_by_category,
    qt_type_for,
    register_node_context_menu_actions,
)
from ruyso_app.ui.node_menu import install_new_node_menu
from ruyso_app.ui.node_preview import NodePreviewOverlay, resolve_source_node
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


class MainWindow(QMainWindow):
    """The pipeline builder's main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ruyso-app - Pipeline Builder")
        self.resize(1400, 900)

        self._canvas = PipelineCanvas()
        self._graph = self._canvas.graph
        self._worker: PipelineExecutionWorker | None = None
        self._last_outputs: dict[str, dict] = {}
        # Node ids that raised in the most recent (auto-)run; drives the
        # Dashboard tab's "· modified" flag on figures that failed.
        self._last_run_errors: dict[str, str] = {}
        # Signatures of the pipeline as it was when last run successfully
        # (see ui.run_snapshot); drives the Table tab's "· modified" tags.
        self._run_snapshot: dict[str, str] = {}
        self._pending_snapshot: dict[str, str] = {}

        self._pipeline_page = PipelinePage(self._canvas)
        self._table_page = TablePage()
        self._dashboard_page = DashboardPage()
        self._options = self._pipeline_page.options_panel

        self._preview_overlay = NodePreviewOverlay(self._graph)

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

        install_new_node_menu(self._graph, self._on_pick_macro_type)
        register_node_context_menu_actions(
            self._graph, self._on_ctx_delete, self._on_ctx_add_to_dashboard
        )

        # Background auto-run: reload data / recompute whatever is ready
        # whenever the canvas changes, so results appear without Run.
        self._auto_run = AutoRunController(lambda: canvas_to_pipeline(self._graph), self)
        self._auto_run.finished.connect(self._on_auto_run_finished)
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
        self._on_tab_changed(self._tab_bar.current_key())

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

        # -- Node menu (Pipeline tab only) ----------------------------
        self._node_menu = menu_bar.addMenu("Node")
        new_node_menu = self._node_menu.addMenu("New Node")
        available = core_node_types_by_category()
        for category, label in theme.MACRO_TYPE_LABELS.items():
            action = new_node_menu.addAction(label)
            letter = _MACRO_SHORTCUT_LETTER.get(category)
            if letter:
                # Two-key chord, e.g. Cmd/Ctrl+P then L for a data loader.
                action.setShortcut(QKeySequence(f"Ctrl+P, {letter}"))
            if category in available:
                action.triggered.connect(
                    lambda _checked=False, c=category: self._on_pick_macro_type(c, None)
                )
            else:
                action.setEnabled(False)

        selected_menu = self._node_menu.addMenu("Selected Node")
        self._delete_action = selected_menu.addAction("Delete Node")
        self._delete_action.setShortcuts(
            [QKeySequence("Ctrl+Backspace"), QKeySequence("Ctrl+Delete")]
        )
        self._delete_action.triggered.connect(self._on_delete_selected_nodes)

        # -- Dashboard menu (Dashboard tab only) ---------------------
        self._dashboard_menu = menu_bar.addMenu("Dashboard")
        self._dashboard_menu.addAction(
            "Add Title", lambda: self._dashboard_page.add_text_block(is_title=True)
        )
        self._dashboard_menu.addAction(
            "Add Text Box", lambda: self._dashboard_page.add_text_block(is_title=False)
        )
        self._dashboard_menu.addSeparator()
        self._dashboard_menu.addAction("Exporter...", self._on_export_dashboard)

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

    # -- tab / menu state ------------------------------------------------

    def _on_property_changed(self, *_args: object) -> None:
        """Schedule an auto-run for a param edit, unless it's a batched tick."""
        if not self._options.autorun_suppressed():
            self._auto_run.schedule()

    def _on_tab_changed(self, key: str) -> None:
        self._options.flush_recompute()  # commit any pending tickbox edits
        self._stack.setCurrentIndex(self._tab_index[key])
        self._node_menu.setEnabled(key == "pipeline")
        self._dashboard_menu.setEnabled(key == "dashboard")
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
            other.set_selected(False)
        node.set_selected(True)
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
        else:
            self._options.clear()

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

    # -- Pipeline menu actions -----------------------------------------

    def _on_load_pipeline(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open Pipeline", "", "Pipeline JSON (*.json)")
        if not path:
            return
        try:
            pipeline = load_graph(path)
            self._graph.clear_session()
            pipeline_to_canvas(pipeline, self._graph)
        except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
            self._show_error("Could not open pipeline", exc)
        else:
            # A freshly opened pipeline has no results yet.
            self._last_outputs = {}
            self._run_snapshot = {}
            self.statusBar().showMessage(f"Opened {path}", 5000)

    def _on_save_pipeline(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save Pipeline", "", "Pipeline JSON (*.json)")
        if not path:
            return
        try:
            pipeline = self._build_pipeline_or_raise()
            save_graph(pipeline, path)
        except Exception as exc:  # noqa: BLE001
            self._show_error("Could not save pipeline", exc)
        else:
            self.statusBar().showMessage(f"Saved {path}", 5000)

    def _on_export_script(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export as Script", "", "Python (*.py)")
        if not path:
            return
        try:
            pipeline = self._build_pipeline_or_raise()
            save_script(pipeline, path, source_description="exported from the UI")
        except Exception as exc:  # noqa: BLE001
            self._show_error("Could not export script", exc)
        else:
            self.statusBar().showMessage(f"Exported script to {path}", 5000)

    def _on_run_pipeline(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return  # a run is already in progress

        self._options.flush_recompute()  # fold in any pending tickbox edits
        try:
            pipeline = self._build_pipeline_or_raise()
        except Exception as exc:  # noqa: BLE001
            self._show_error("Pipeline is not valid", exc)
            return

        self._run_action.setEnabled(False)
        self._tab_bar.run_button.setEnabled(False)
        self._auto_run.set_enabled(False)  # don't compete with the real run
        self.statusBar().showMessage("Running pipeline...")
        self._pipeline_page.clear_log()
        self._tab_bar.progress.start(len(pipeline.nodes))
        # Remember exactly what is being run; promoted to _run_snapshot
        # only if this run succeeds.
        self._pending_snapshot = pipeline_signatures(pipeline)

        self._worker = PipelineExecutionWorker(pipeline)
        self._worker.progress.connect(self._tab_bar.progress.set_progress)
        self._worker.succeeded.connect(self._on_run_succeeded)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.finished.connect(self._on_run_finished)
        self._worker.start()

    def _on_run_finished(self) -> None:
        self._run_action.setEnabled(True)
        self._tab_bar.run_button.setEnabled(True)
        self._auto_run.set_enabled(True)

    # -- execution callbacks (GUI thread, via Qt signals) ---------------

    def _on_run_succeeded(self, outputs: dict[str, dict]) -> None:
        self.statusBar().showMessage("Pipeline finished.", 5000)
        self._tab_bar.progress.finish_success()
        for node_id, node_outputs in outputs.items():
            for port_name, value in node_outputs.items():
                self._pipeline_page.append_log(f"[{node_id}] {port_name} = {value!r}")
        self._last_outputs = outputs
        self._last_run_errors = {}
        self._run_snapshot = self._pending_snapshot
        self._preview_overlay.set_run_outputs(outputs)
        self._dashboard_page.sync_figures(
            self._graph, outputs, self._table_modified_set(), set()
        )
        self._table_page.refresh(self._graph, outputs, self._table_modified_set())

    def _on_run_failed(self, message: str) -> None:
        self.statusBar().showMessage("Pipeline failed.", 5000)
        self._tab_bar.progress.finish_error()
        self._pipeline_page.append_log(f"ERROR: {message}")
        self._show_error("Pipeline execution failed", message)

    def _on_auto_run_finished(self, outputs: dict[str, dict], errors: dict) -> None:
        """Merge a background auto-run's results without any dialog/log noise."""
        self._last_run_errors = dict(errors or {})
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
        if self._dashboard_page.is_editing_figure():
            dsource = self._dashboard_page.options_panel.current_node()
            if dsource is not None:
                self._dashboard_page.options_panel.set_input_columns(
                    input_dataframe_columns(dsource, self._last_outputs),
                    input_column_values(dsource, self._last_outputs),
                )
        if self.current_tab() == "table":
            self._table_page.refresh(
                self._graph, self._last_outputs, self._table_modified_set()
            )

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        """Let any in-flight background run finish before the window dies."""
        self._auto_run.set_enabled(False)
        for worker in (self._worker, getattr(self._auto_run, "_worker", None)):
            if worker is not None and worker.isRunning():
                worker.wait(3000)
        super().closeEvent(event)

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
