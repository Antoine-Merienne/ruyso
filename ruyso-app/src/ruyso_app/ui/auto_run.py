"""
Automatic background execution of whatever part of the pipeline can
already run.

Whenever the canvas changes in a way that could affect data -- a data
file is chosen, a node is wired up, a parameter is edited -- the app
kicks off a debounced, best-effort run on a background thread
(``PipelineScheduler.run_available``). Nodes that are fully wired and
valid produce their tables/figures immediately; unfinished or broken
branches are silently skipped, with no error dialog. This is what
makes column pickers populate and previews appear without the user
having to press Run.

``AutoRunController`` owns the debounce timer and the worker; it does
not touch any widget -- ``MainWindow`` connects to :attr:`finished`
and merges the results.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ruyso_app.engine.graph import PipelineGraph
from ruyso_app.engine.scheduler import PipelineScheduler

#: How long to wait after the last change before running (coalesces
#: bursts of edits / property changes into one run).
_DEBOUNCE_MS = 450


class _AutoRunWorker(QThread):
    """Runs ``PipelineScheduler.run_available`` off the GUI thread."""

    done = Signal(dict, dict)  # outputs, errors

    def __init__(self, pipeline: PipelineGraph, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pipeline = pipeline

    def run(self) -> None:
        try:
            outputs, errors = PipelineScheduler().run_available(self._pipeline)
        except Exception as exc:  # noqa: BLE001 - auto-run must never surface
            outputs, errors = {}, {"__auto_run__": str(exc)}
        self.done.emit(outputs, errors)


class AutoRunController(QObject):
    """Debounces change notifications and drives one auto-run at a time."""

    #: Emitted on the GUI thread with ``(outputs, errors)`` from a run.
    finished = Signal(dict, dict)

    def __init__(self, build_pipeline, parent: QObject | None = None) -> None:
        """
        Args:
            build_pipeline: Zero-arg callable returning the current
                ``PipelineGraph`` (normally ``canvas_to_pipeline`` bound
                to the live graph). May raise; that is treated as
                "nothing to run".
        """
        super().__init__(parent)
        self._build_pipeline = build_pipeline
        self._worker: _AutoRunWorker | None = None
        self._rerun_pending = False
        self._enabled = True

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._fire)

    def set_enabled(self, enabled: bool) -> None:
        """Disable while a manual run is in progress, then re-enable."""
        self._enabled = enabled

    def schedule(self, *_args: object) -> None:
        """Request an auto-run soon (safe to call from any graph signal)."""
        if self._enabled:
            self._timer.start()

    # -- internals ------------------------------------------------------

    def _fire(self) -> None:
        if not self._enabled:
            return
        if self._worker is not None and self._worker.isRunning():
            self._rerun_pending = True
            return
        try:
            pipeline = self._build_pipeline()
        except Exception:  # noqa: BLE001 - canvas not translatable right now
            return

        self._worker = _AutoRunWorker(pipeline, self)
        self._worker.done.connect(self._on_worker_done)
        self._worker.start()

    def _on_worker_done(self, outputs: dict, errors: dict) -> None:
        self.finished.emit(outputs, errors)
        if self._rerun_pending:
            self._rerun_pending = False
            self._timer.start()
