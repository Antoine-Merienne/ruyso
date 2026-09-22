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

from ruyso_app.engine import settings
from ruyso_app.engine.graph import PipelineGraph
from ruyso_app.engine.run_cache import ResultCache
from ruyso_app.engine import errors as _errors
from ruyso_app.engine.scheduler import PipelineScheduler, RunReport

#: How long to wait after the last change before running (coalesces
#: bursts of edits / property changes into one run).
_DEBOUNCE_MS = 450


class _AutoRunWorker(QThread):
    """Runs ``PipelineScheduler.run_available`` off the GUI thread."""

    done = Signal(object)  # engine.scheduler.RunReport
    node_status = Signal(str, str)  # node_id, phase

    def __init__(
        self,
        pipeline: PipelineGraph,
        result_cache: ResultCache,
        skip_categories: frozenset[str] = frozenset(),
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline = pipeline
        #: A snapshot of the controller's cache, private to this run --
        #: see AutoRunController._fire for why it is not the live one.
        self.result_cache = result_cache
        self._skip_categories = skip_categories

    def run(self) -> None:
        try:
            report = PipelineScheduler().run_available(
                self._pipeline,
                node_callback=lambda node_id, phase: self.node_status.emit(
                    node_id, phase
                ),
                result_cache=self.result_cache,
                skip_categories=self._skip_categories,
            )
        except Exception as exc:  # noqa: BLE001 - auto-run must never surface
            report = RunReport(errors={"__auto_run__": _errors.translate(
                exc, node_id="__auto_run__", node_type="")})
        self.done.emit(report)


class AutoRunController(QObject):
    """Debounces change notifications and drives one auto-run at a time."""

    #: Emitted on the GUI thread with the run's ``RunReport``.
    finished = Signal(object)
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
        #: Node results carried across auto-runs, so an edit only
        #: re-executes what it actually affects.
        self._cache = ResultCache()
        #: The snapshot handed to the worker in flight, adopted as the
        #: live cache only if that run reaches _on_worker_done.
        self._pending_cache: ResultCache | None = None
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
        self.apply_preferences()

    def apply_preferences(self) -> None:
        """Re-read the Execution preferences (on/off, debounce)."""
        self._user_enabled = bool(settings.get("execution.auto_run"))
        try:
            delay = int(settings.get("execution.debounce_ms"))
        except (TypeError, ValueError):
            delay = _DEBOUNCE_MS
        self._timer.setInterval(max(50, min(delay, 10_000)))

    @staticmethod
    def _skip_categories() -> frozenset[str]:
        """Categories the background run leaves alone.

        With "re-render figures during auto-run" off, graphers keep
        whatever they last drew instead of being redrawn on every
        keystroke -- worth having on a slow plot even now that unchanged
        ones are skipped outright.
        """
        if bool(settings.get("execution.render_figures_in_autorun")):
            return frozenset()
        return frozenset({"grapher"})

    def set_enabled(self, enabled: bool) -> None:
        """Transient gate: lowered while a manual run is in progress."""
        self._enabled = enabled

    def set_user_enabled(self, enabled: bool) -> None:
        """The persistent View > Auto-run toggle (independent of manual runs)."""
        self._user_enabled = enabled

    def is_user_enabled(self) -> bool:
        return self._user_enabled

    def cache_snapshot(self) -> ResultCache:
        """
        A detached copy of what previous runs computed.

        Handed to a manual run so pressing Run does not redo work
        nothing has changed for; the window gives the filled copy back
        through :meth:`adopt_cache`.
        """
        return self._cache.snapshot()

    def adopt_cache(self, cache: ResultCache) -> None:
        """Take a finished run's results as the ones to reuse from now on."""
        self._cache = cache
        # Any background run still in flight was started from an older
        # copy; letting it land would throw this one away.
        self._pending_cache = None

    def interrupt(self) -> None:
        """Hard-stop auto-run now: cancel the pending timer and, if an
        auto-run is mid-flight on the worker thread, terminate it. Its
        partial results are discarded. Used when the user switches
        auto-run off (View > Auto-run, or the tab-band "auto" chip)."""
        self._rerun_pending = False
        self._timer.stop()
        self._pending_cache = None  # discard whatever the killed run built
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

        # The worker gets a *snapshot* to read from and add to, never the
        # live cache: interrupt() terminates the thread at an arbitrary
        # instruction, and a half-updated cache would then be believed by
        # every later run. A terminated worker's snapshot is simply
        # dropped, which costs one wasted run and nothing else.
        self._pending_cache = self._cache.snapshot()
        self._worker = _AutoRunWorker(
            pipeline, self._pending_cache, self._skip_categories(), self
        )
        self._worker.done.connect(self._on_worker_done)
        self._worker.node_status.connect(self.node_status)  # re-emit to MainWindow
        self._worker.start()
        self.started.emit()

    def _on_worker_done(self, report: RunReport) -> None:
        # Adopted here, on the GUI thread, once the run has finished --
        # the only point at which the snapshot is known to be complete.
        if self._pending_cache is not None:
            self._cache = self._pending_cache
            self._pending_cache = None
        self.finished.emit(report)
        if self._rerun_pending:
            self._rerun_pending = False
            self._timer.start()
