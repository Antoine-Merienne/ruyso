"""
Tests for ``ui.render_queue`` -- the one thread that draws figures.

What matters here is not speed but the three rules the UI depends on:
work leaves the GUI thread, a stale request never beats a newer one,
and a figure that is on screen in a window is drawn where its canvas
lives.
"""

import threading

import pytest
from matplotlib.figure import Figure

from ruyso_app.ui import render_queue


@pytest.fixture
def queue(qapp):
    yield render_queue.queue()
    render_queue.shutdown()


def test_a_figure_is_rendered_off_the_gui_thread(queue):
    results: list[tuple] = []
    queue.rendered.connect(lambda key, figure, result: results.append((key, result)))

    queue.submit("a", Figure(), lambda fig: threading.current_thread().name)

    assert queue.wait_idle(15_000)
    assert len(results) == 1
    key, thread_name = results[0]
    assert key == "a"
    assert thread_name != threading.main_thread().name


def test_a_newer_request_replaces_one_still_waiting(queue):
    """A zoom gesture asks for five sizes; only the last is worth drawing."""
    started = threading.Event()
    release = threading.Event()
    drawn: list[str] = []

    def blocking(_figure):
        started.set()
        release.wait(10.0)
        return "first"

    queue.submit("slow", Figure(), blocking)
    assert started.wait(10.0)  # the worker is busy, so the next two queue up

    queue.rendered.connect(lambda key, figure, result: drawn.append(result))
    queue.submit("card", Figure(), lambda _f: "stale")
    queue.submit("card", Figure(), lambda _f: "wanted")
    release.set()

    assert queue.wait_idle(15_000)
    assert "wanted" in drawn and "stale" not in drawn


def test_a_figure_shown_in_a_window_is_rendered_on_the_spot(queue):
    """``savefig`` swaps the figure's canvas out for the duration, so a
    worker drawing it would race the GUI thread painting that canvas."""
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg

    figure = Figure()
    FigureCanvasQTAgg(figure)  # what a pop-out FigureWindow attaches
    seen: list[str] = []
    queue.rendered.connect(lambda key, fig, result: seen.append(result))

    queue.submit("w", figure, lambda _f: threading.current_thread().name)

    # Delivered before submit() returned, on this very thread.
    assert seen == [threading.main_thread().name]
    assert queue.pending() == 0


def test_a_render_that_raises_is_reported_rather_than_swallowed(queue):
    """The receiver is waiting on this answer: one that never arrives
    leaves a card holding a request it will never make again."""
    delivered: list = []
    queue.rendered.connect(lambda key, fig, result: delivered.append((key, result)))

    def boom(_figure):
        raise RuntimeError("a plot that will not draw")

    queue.submit("bad", Figure(), boom)
    queue.submit("good", Figure(), lambda _f: "fine")

    assert queue.wait_idle(15_000)
    assert ("bad", None) in delivered
    assert ("good", "fine") in delivered
