"""
Background execution of a pipeline.

Running a pipeline can take anywhere from milliseconds to minutes,
depending on the data and models involved. ``PipelineExecutionWorker``
runs it on a background ``QThread`` via ``PipelineScheduler`` so the
canvas and the rest of the window stay responsive and repaintable
while it's in progress, and reports back to the GUI thread through Qt
signals rather than a return value (which would block the caller).
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from ruyso_app.engine.graph import PipelineGraph
from ruyso_app.engine.scheduler import PipelineScheduler


class PipelineExecutionWorker(QThread):
    """
    Runs a ``PipelineGraph`` on a background thread.

    Usage:
        worker = PipelineExecutionWorker(pipeline)
        worker.succeeded.connect(on_success)   # slot(engine.scheduler.RunReport)
        worker.failed.connect(on_failure)      # slot(str)
        worker.start()

    The worker owns no reference back to any UI widget: it only knows
    about the engine layer, which keeps it trivially testable without
    a running window.
    """

    #: Emitted when the run completes, carrying the whole
    #: :class:`~ruyso_app.engine.scheduler.RunReport`: what ran, what
    #: raised (as ``NodeError``s the Problems panel can render), and
    #: what never got to run.
    succeeded = Signal(object)

    #: Emitted only if the run could not start at all (e.g. the graph
    #: failed structural validation), with a human-readable message.
    failed = Signal(str)

    #: Emitted as nodes finish, with ``(done, total)`` counts.
    progress = Signal(int, int)

    #: Emitted as each node is reached: ``(node_id, phase)`` where phase
    #: is "running" / "ok" / "error" / "blocked".
    node_status = Signal(str, str)

    def __init__(
        self,
        pipeline: PipelineGraph,
        scheduler: PipelineScheduler | None = None,
        parent=None,
    ) -> None:
        """
        Args:
            pipeline: The pipeline to execute.
            scheduler: Scheduler to run it with. Defaults to a fresh
                ``PipelineScheduler()`` (with the default on-disk
                joblib cache).
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._pipeline = pipeline
        self._scheduler = scheduler if scheduler is not None else PipelineScheduler()

    def run(self) -> None:
        """Entry point invoked by Qt on the background thread (do not call directly)."""
        try:
            report = self._scheduler.run(
                self._pipeline,
                progress_callback=lambda done, total: self.progress.emit(done, total),
                node_callback=lambda node_id, phase: self.node_status.emit(node_id, phase),
            )
        except Exception as exc:  # noqa: BLE001 - reported to the UI, never swallowed
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(report)
