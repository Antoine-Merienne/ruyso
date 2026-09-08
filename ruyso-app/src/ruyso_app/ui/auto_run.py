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
    node_status = Signal(str, str)  # node_id, phase

    def __init__(self, pipeline: PipelineGraph, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pipeline = pipeline

    def run(self) -> None:
        try:
            outputs, errors = PipelineScheduler().run_available(
                self._pipeline,
                node_callback=lambda node_id, phase: self.node_status.emit(
                    node_id, phase
                ),
            )
        except Exception as exc:  # noqa: BLE001 - auto-run must never surface
            outputs, errors = {}, {"__auto_run__": str(exc)}
        self.done.emit(outputs, errors)


class AutoRunController(QObject):
    """Debounces change notifications and drives one auto-run at a time."""

    #: Emitted on the GUI thread with ``(outputs, errors)`` from a run.
    finished = Signal(dict, dict)
    #: Emitted on the GUI thread the moment a background auto-run starts
    #: (drives the tab band's "auto" pill to its blue "loading" state).
    started = Signal()
    #: Re-emitted from the worker: ``(node_id, phase)`` for the per-node
    #: canvas status dots.
    node_status = Signal(str, str)

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
        #: Transient gate -- lowered by MainWindow only while a manual
        #: "Run Pipeline" is in progress.
        self._enabled = True
        #: Persistent user preference (View > Auto-run); survives manual
        #: runs. Auto-run happens only when *both* are true.
        self._user_enabled = True

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_DEBOUNCE_MS)
        self._timer.timeout.connect(self._fire)

    def set_enabled(self, enabled: bool) -> None:
        """Transient gate: lowered while a manual run is in progress."""
        self._enabled = enabled

    def set_user_enabled(self, enabled: bool) -> None:
        """The persistent View > Auto-run toggle (independent of manual runs)."""
        self._user_enabled = enabled

    def is_user_enabled(self) -> bool:
        return self._user_enabled

    def interrupt(self) -> None:
        """Hard-stop auto-run now: cancel the pending timer and, if an
        auto-run is mid-flight on the worker thread, terminate it. Its
        partial results are discarded. Used when the user switches
        auto-run off (View > Auto-run, or the tab-band "auto" chip)."""
        self._rerun_pending = False
        self._timer.stop()
        worker = self._worker
        self._worker = None
        if worker is not None:
            if worker.isRunning():
                worker.terminate()
                worker.wait(2000)
            worker.deleteLater()

    def _active(self) -> bool:
        return self._enabled and self._user_enabled

    def schedule(self, *_args: object) -> None:
        """Request an auto-run soon (safe to call from any graph signal)."""
        if self._active():
            self._timer.start()

    # -- internals ------------------------------------------------------

    def _fire(self) -> None:
        if not self._active():
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
        self._worker.node_status.connect(self.node_status)  # re-emit to MainWindow
        self._worker.start()
        self.started.emit()

    def _on_worker_done(self, outputs: dict, errors: dict) -> None:
        self.finished.emit(outputs, errors)
        if self._rerun_pending:
            self._rerun_pending = False
            self._timer.start()
