"""
Turning figures into pictures, off the GUI thread.

Drawing a plot is by far the most expensive thing this app does with a
figure -- a 500k-point scatter takes 3.6 s to rasterise and 4.6 s to
serialise to SVG -- and it used to happen on the GUI thread, inside the
handler that receives a finished run. The window froze for exactly as
long as the drawing took, every time a run produced a figure.

Agg gives the GIL up while it draws: with a 4.5 s render running on
another thread, this thread's ticks stayed at 13 ms. So handing the
call to a worker genuinely keeps the window alive, rather than merely
moving the stall.

**One thread, never a pool.** ``savefig`` swaps a canvas onto the
figure for the duration of the call and puts the old one back after,
so the same figure rendered twice at once is a race. A single worker
keeps every render of every figure serialised behind the others.

**Latest request wins.** Jobs carry a key -- one per card, one per
dashboard block -- and a new job replaces one still queued under the
same key: a zoom gesture asks for five sizes and only the last is
worth drawing.

**A figure with a live Qt canvas is rendered here, on the spot.** That
is a figure open in a pop-out window, which the GUI thread paints from
that canvas whenever it pleases; a worker swapping the canvas out
mid-paint is the one race a queue of one cannot prevent. Rendering it
inline is what the whole app did before this module existed, so the
fallback is merely the old behaviour, kept for the rare case.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import (
    QCoreApplication,
    QMutex,
    QMutexLocker,
    QThread,
    QWaitCondition,
    Signal,
)

#: How long :meth:`RenderQueue.wait_idle` waits before giving up.
DEFAULT_TIMEOUT_MS = 30_000


def _has_live_qt_canvas(figure: Any) -> bool:
    """Whether ``figure`` is attached to an on-screen Qt canvas."""
    canvas = getattr(figure, "canvas", None)
    if canvas is None:
        return False
    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    except Exception:  # noqa: BLE001 - no Qt backend: nothing can be on screen
        return False
    return isinstance(canvas, FigureCanvasQTAgg)


class RenderQueue(QThread):
    """One worker thread rendering figures, one at a time."""

    #: ``(key, figure, result)`` on the GUI thread -- ``result`` is
    #: whatever the job's own render callable returned, or ``None`` if
    #: it raised. A failure is still delivered: the receiver is waiting
    #: on this answer, and one that never arrives leaves a card with a
    #: request outstanding that it will never ask for again. The figure
    #: is carried along so a receiver can drop a result that a newer run
    #: has already superseded.
    rendered = Signal(object, object, object)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._mutex = QMutex()
        self._work = QWaitCondition()
        self._idle = QWaitCondition()
        self._jobs: dict[Any, tuple[Any, Callable[[Any], Any]]] = {}
        self._rendering = False
        self._stopping = False

    # -- submitting -----------------------------------------------------

    def submit(self, key: Any, figure: Any, render: Callable[[Any], Any]) -> None:
        """
        Render ``figure`` with ``render`` and emit :attr:`rendered`.

        Replaces any job still queued under ``key``. Runs inline (and
        emits before returning) for a figure that is on screen in a
        window -- see the module docstring.
        """
        if _has_live_qt_canvas(figure):
            try:
                result = render(figure)
            except Exception:  # noqa: BLE001 - reported as a failed render
                result = None
            self.rendered.emit(key, figure, result)
            return

        with QMutexLocker(self._mutex):
            if self._stopping:
                return
            self._jobs[key] = (figure, render)
            self._work.wakeAll()
        if not self.isRunning():
            self.start()

    # -- the worker -----------------------------------------------------

    def run(self) -> None:  # noqa: D102 - QThread override
        while True:
            with QMutexLocker(self._mutex):
                while not self._jobs and not self._stopping:
                    self._work.wait(self._mutex)
                if self._stopping:
                    return
                key = next(iter(self._jobs))
                figure, render = self._jobs.pop(key)
                self._rendering = True
            result = None
            try:
                result = render(figure)
            except Exception:  # noqa: BLE001 - a plot that will not draw is
                result = None  # not a reason to take the app down
            # Emit *before* going idle: ``wait_idle`` processes events
            # once it sees the queue empty, so a result posted after
            # that check would not have been delivered when it returns.
            self.rendered.emit(key, figure, result)
            with QMutexLocker(self._mutex):
                self._rendering = False
                self._idle.wakeAll()

    # -- lifecycle ------------------------------------------------------

    def pending(self) -> int:
        """Jobs queued, plus the one being rendered."""
        with QMutexLocker(self._mutex):
            return len(self._jobs) + int(self._rendering)

    def wait_idle(self, timeout_ms: int = DEFAULT_TIMEOUT_MS) -> bool:
        """
        Block until every submitted render has been delivered.

        For tests and for shutdown; nothing in the running app waits on
        a render. Pending Qt events are processed as it goes, so the
        ``rendered`` handlers have run by the time it returns.
        """
        remaining = timeout_ms
        while remaining > 0:
            with QMutexLocker(self._mutex):
                idle = not self._jobs and not self._rendering
                if not idle:
                    self._idle.wait(self._mutex, 25)
            app = QCoreApplication.instance()
            if app is not None:
                app.processEvents()
            if idle:
                return True
            remaining -= 25
        return False

    def stop(self) -> None:
        """Drop anything queued and end the thread. Safe to call twice."""
        with QMutexLocker(self._mutex):
            self._stopping = True
            self._jobs.clear()
            self._work.wakeAll()
        if self.isRunning():
            self.wait(5000)


_QUEUE: RenderQueue | None = None


def queue() -> RenderQueue:
    """The app-wide render queue, started on its first job."""
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = RenderQueue()
        app = QCoreApplication.instance()
        if app is not None:
            # A QThread still running when the interpreter tears down is
            # the shape of problem that ends in a segfault rather than a
            # traceback.
            app.aboutToQuit.connect(shutdown)
    return _QUEUE


def shutdown() -> None:
    """Stop the queue, if one was ever started."""
    global _QUEUE
    if _QUEUE is not None:
        _QUEUE.stop()
        _QUEUE = None
