"""
Main application window: assembles the canvas together with the node
palette, the properties panel, a run log, a figure preview, and the
toolbar actions (load, save, export to script, run).

This module only wires widgets together and reacts to user actions --
it contains no pipeline-execution logic itself (that's
``execution_worker.py``) and no NodeGraphQt-node-building logic (that's
``node_factory.py`` / ``canvas.py``). Keeping it a thin assembly layer
is what makes each concern independently testable.
"""

from __future__ import annotations

from pathlib import Path

from NodeGraphQt import PropertiesBinWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QToolBar,
)

from ruyso_app.engine.codegen import save_script
from ruyso_app.engine.graph import GraphValidationError, PipelineGraph
from ruyso_app.engine.serialization import load_graph, save_graph
from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.execution_worker import PipelineExecutionWorker
from ruyso_app.ui.figure_viewer import FigureViewer
from ruyso_app.ui.graph_bridge import canvas_to_pipeline, pipeline_to_canvas


class MainWindow(QMainWindow):
    """The pipeline builder's main window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ruyso-app - Pipeline Builder")
        self.resize(1400, 900)

        self._canvas = PipelineCanvas()
        self._worker: PipelineExecutionWorker | None = None

        self.setCentralWidget(self._canvas.widget)
        self._build_properties_dock()
        self._build_log_dock()
        self._build_figure_dock()
        self._build_toolbar()

    # -- dock/toolbar construction ---------------------------------------

    def _build_properties_dock(self) -> None:
        """Right-hand dock: auto-generated parameter form for the selected node."""
        properties_bin = PropertiesBinWidget(node_graph=self._canvas.graph)
        self._canvas.graph.node_double_clicked.connect(properties_bin.add_node)

        dock = QDockWidget("Node Properties", self)
        dock.setWidget(properties_bin)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _build_log_dock(self) -> None:
        """Bottom dock: plain-text log of the most recent run's outputs/errors."""
        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setPlaceholderText("Run output will appear here...")

        dock = QDockWidget("Run Log", self)
        dock.setWidget(self._log)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)

    def _build_figure_dock(self) -> None:
        """Bottom dock (tabbed with the log): preview of the last figure produced."""
        self._figure_viewer = FigureViewer(self)

        dock = QDockWidget("Figure Preview", self)
        dock.setWidget(self._figure_viewer)
        self.addDockWidget(Qt.BottomDockWidgetArea, dock)
        self.tabifyDockWidget(self.findChild(QDockWidget, "Run Log") or dock, dock)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        self.addToolBar(toolbar)

        load_action = QAction("Load Pipeline...", self)
        load_action.triggered.connect(self._on_load_pipeline)
        toolbar.addAction(load_action)

        save_action = QAction("Save Pipeline...", self)
        save_action.triggered.connect(self._on_save_pipeline)
        toolbar.addAction(save_action)

        export_action = QAction("Export as Script...", self)
        export_action.triggered.connect(self._on_export_script)
        toolbar.addAction(export_action)

        toolbar.addSeparator()

        self._run_action = QAction("Run Pipeline", self)
        self._run_action.triggered.connect(self._on_run_pipeline)
        toolbar.addAction(self._run_action)

    # -- toolbar actions --------------------------------------------------

    def _on_load_pipeline(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Pipeline", "", "Pipeline JSON (*.json)")
        if not path:
            return
        try:
            pipeline = load_graph(path)
            self._canvas.graph.clear_session()
            pipeline_to_canvas(pipeline, self._canvas.graph)
        except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
            self._show_error("Could not load pipeline", exc)
        else:
            self.statusBar().showMessage(f"Loaded {path}", 5000)

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
        self._log.clear()

        self._worker = PipelineExecutionWorker(pipeline)
        self._worker.succeeded.connect(self._on_run_succeeded)
        self._worker.failed.connect(self._on_run_failed)
        self._worker.finished.connect(lambda: self._run_action.setEnabled(True))
        self._worker.start()

    # -- execution callbacks (run on the GUI thread via Qt signals) --------

    def _on_run_succeeded(self, outputs: dict[str, dict]) -> None:
        self.statusBar().showMessage("Pipeline finished.", 5000)
        for node_id, node_outputs in outputs.items():
            for port_name, value in node_outputs.items():
                self._log.appendPlainText(f"[{node_id}] {port_name} = {value!r}")
                if _looks_like_figure(value):
                    self._figure_viewer.show_figure(value)

    def _on_run_failed(self, message: str) -> None:
        self.statusBar().showMessage("Pipeline failed.", 5000)
        self._log.appendPlainText(f"ERROR: {message}")
        self._show_error("Pipeline execution failed", message)

    # -- helpers ------------------------------------------------------------

    def _build_pipeline_or_raise(self) -> PipelineGraph:
        pipeline = canvas_to_pipeline(self._canvas.graph)
        pipeline.validate()
        return pipeline

    def _show_error(self, title: str, error: Exception | str) -> None:
        message = str(error)
        if isinstance(error, GraphValidationError):
            message = f"Pipeline is invalid: {message}"
        QMessageBox.critical(self, title, message)


def _looks_like_figure(value: object) -> bool:
    """Duck-type check so this module never needs to import matplotlib directly."""
    return hasattr(value, "savefig") and hasattr(value, "axes")
