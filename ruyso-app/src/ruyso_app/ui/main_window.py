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
from PySide6.QtGui import QKeySequence
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
from ruyso_app.ui.column_spec import input_dataframe_columns
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
from ruyso_app.ui.node_preview import NodePreviewOverlay
from ruyso_app.ui.pipeline_page import PipelinePage
from ruyso_app.ui.run_snapshot import modified_since_run, pipeline_signatures
from ruyso_app.ui.tab_bar import TabBar
from ruyso_app.ui.table_page import TablePage

#: Chord letter (after Cmd/Ctrl+P) that creates a node of each macro type.
_MACRO_SHORTCUT_LETTER: dict[str, str] = {
    "loading": "L",
    "transform": "T",
    "model": "M",
    "statistical_test": "S",
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
        self._dashboard_page.export_requested.connect(self._on_export_dashboard)
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
            self._graph.property_changed,
        ):
            signal.connect(self._auto_run.schedule)

        self._build_menus()
        self._on_tab_changed(self._tab_bar.current_key())

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
        self._dashboard_menu.addAction("Exporter...", self._on_export_dashboard)

        # -- View menu (always) --------------------------------------
        view_menu = menu_bar.addMenu("View")
        view_menu.addAction("Toggle Dark / Light Theme", self._toggle_theme)

    # -- tab / menu state ------------------------------------------------

    def _on_tab_changed(self, key: str) -> None:
        self._stack.setCurrentIndex(self._tab_index[key])
        self._node_menu.setEnabled(key == "pipeline")
        self._dashboard_menu.setEnabled(key == "dashboard")
        if key == "table":
            # Rebuild from the current canvas each time the tab is shown.
            self._table_page.refresh(
                self._graph, self._last_outputs, self._table_modified_set()
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
        # Phase 4 turns this into a real dashboard figure block.
        self.statusBar().showMessage(
            f"'{node.name()}' queued for the dashboard (wired in a later phase).", 4000
        )

    # -- Dashboard menu actions ------------------------------------------

    def _on_export_dashboard(self) -> None:
        QMessageBox.information(
            self,
            "Export dashboard",
            "Dashboard export (PDF / PNG) is implemented in a later phase.",
        )

    # -- View menu actions -----------------------------------------------

    def _toggle_theme(self) -> None:
        theme.toggle_theme()
        self._apply_theme()

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.stylesheet_for())
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

        try:
            pipeline = self._build_pipeline_or_raise()
        except Exception as exc:  # noqa: BLE001
            self._show_error("Pipeline is not valid", exc)
            return

        self._run_action.setEnabled(False)
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
        self._auto_run.set_enabled(True)

    # -- execution callbacks (GUI thread, via Qt signals) ---------------

    def _on_run_succeeded(self, outputs: dict[str, dict]) -> None:
        self.statusBar().showMessage("Pipeline finished.", 5000)
        self._tab_bar.progress.finish_success()
        for node_id, node_outputs in outputs.items():
            for port_name, value in node_outputs.items():
                self._pipeline_page.append_log(f"[{node_id}] {port_name} = {value!r}")
        self._last_outputs = outputs
        self._run_snapshot = self._pending_snapshot
        self._preview_overlay.set_run_outputs(outputs)
        self._table_page.refresh(self._graph, outputs, self._table_modified_set())

    def _on_run_failed(self, message: str) -> None:
        self.statusBar().showMessage("Pipeline failed.", 5000)
        self._tab_bar.progress.finish_error()
        self._pipeline_page.append_log(f"ERROR: {message}")
        self._show_error("Pipeline execution failed", message)

    def _on_auto_run_finished(self, outputs: dict[str, dict], _errors: dict) -> None:
        """Merge a background auto-run's results without any dialog/log noise."""
        if not outputs:
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
        node = self._options.current_node()
        if node is not None:
            self._options.set_input_columns(
                input_dataframe_columns(node, self._last_outputs)
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
