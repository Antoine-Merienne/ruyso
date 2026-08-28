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
from ruyso_app.ui.canvas import PipelineCanvas
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
from ruyso_app.ui.tab_bar import TabBar
from ruyso_app.ui.table_page import TablePage

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
        self._options.micro_type_change_requested.connect(self._on_micro_type_change)
        self._graph.node_selection_changed.connect(self._on_selection_changed)

        install_new_node_menu(self._graph, self._on_pick_macro_type)
        register_node_context_menu_actions(
            self._graph, self._on_ctx_delete, self._on_ctx_add_to_dashboard
        )

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
            if category in available:
                action.triggered.connect(
                    lambda _checked=False, c=category: self._on_pick_macro_type(c)
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

    def current_tab(self) -> str:
        """The key of the currently visible tab (used by tests)."""
        return self._tab_bar.current_key()

    # -- node creation / selection ---------------------------------------

    def _on_pick_macro_type(self, category: str) -> None:
        """
        Step 1 of the two-step flow: a macro type was chosen (from the
        canvas right-click menu or the Node menu). Create the first
        concrete node of that macro type and select it, so the Options
        panel opens with the micro-type dropdown ready to refine it.
        """
        node_types = core_node_types_by_category().get(category, [])
        if not node_types:
            return
        node = self._graph.create_node(
            qt_type_for(node_types[0]), pos=self._new_node_pos()
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
            category = type(node).CORE_NODE_CLASS.category
            siblings = core_node_types_by_category().get(category, [])
            self._options.show_node(node, siblings)
        else:
            self._options.clear()

    def _on_micro_type_change(self, new_type: str) -> None:
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
        self.statusBar().showMessage("Running pipeline...")
        self._pipeline_page.clear_log()

        self._worker = PipelineExecutionWorker(pipeline)
        self._worker.succeeded.connect(self._on_run_succeeded)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.finished.connect(lambda: self._run_action.setEnabled(True))
        self._worker.start()

    # -- execution callbacks (GUI thread, via Qt signals) ---------------

    def _on_run_succeeded(self, outputs: dict[str, dict]) -> None:
        self.statusBar().showMessage("Pipeline finished.", 5000)
        for node_id, node_outputs in outputs.items():
            for port_name, value in node_outputs.items():
                self._pipeline_page.append_log(f"[{node_id}] {port_name} = {value!r}")
        self._preview_overlay.set_run_outputs(outputs)
        self._table_page.set_run_outputs(outputs)

    def _on_run_failed(self, message: str) -> None:
        self.statusBar().showMessage("Pipeline failed.", 5000)
        self._pipeline_page.append_log(f"ERROR: {message}")
        self._show_error("Pipeline execution failed", message)

    # -- helpers --------------------------------------------------------

    def _build_pipeline_or_raise(self) -> PipelineGraph:
        pipeline = canvas_to_pipeline(self._graph)
        pipeline.validate()
        return pipeline

    def _show_error(self, title: str, error: Exception | str) -> None:
        message = str(error)
        if isinstance(error, GraphValidationError):
            message = f"Pipeline is invalid: {message}"
        QMessageBox.critical(self, title, message)
