"""
Tests for the figure guard (``core.figure_lock``).

matplotlib is global: rcParams, the style context, and a figure's own
dpi/size while it is being saved. This app builds figures on the run
thread, draws them on the render thread and reads them on the GUI
thread, and before the guard those overlapped -- which is what "the
preview fails to render properly" was. Nothing else in the suite runs
two threads at matplotlib, so without these the bug comes back silently.
"""

import hashlib
import threading
import time

import numpy as np
import pandas as pd
import pytest

import ruyso_app.nodes  # noqa: F401 - registers the node classes
from ruyso_app.core.figure_lock import figure_guard
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.node_preview import (
    figure_to_png_bytes,
    figure_to_svg_bytes,
    window_size_for,
)
from ruyso_app.ui.preview_card import figure_aspect


NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture
def frame():
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "x": rng.normal(size=2000),
            "y": rng.normal(size=2000),
            "g": rng.choice(list("abc"), 2000),
        }
    )


def _plot(frame, **params):
    return NodeRegistry.get("matplotlib_plot")(
        params={
            "x": "x", "y": "y", "color_by": "g", "title": "A title",
            "show_legend": True, **params,
        }
    ).run(df=frame)["figure"]


@pytest.fixture
def busy_builder(frame):
    """A thread building figures, as the run thread does during a run."""
    stop = threading.Event()

    def build_forever():
        while not stop.is_set():
            _plot(frame, fig_width=5.5, axis_font_size=8, title_font_size=16)

    thread = threading.Thread(target=build_forever, daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=10)


def test_a_render_waits_for_a_figure_being_built(frame):
    """Building is what holds the guard from ``_plot_context``; a render
    starting meanwhile has to queue behind it rather than read a style
    that is half swapped."""
    figure = _plot(frame)
    finished = threading.Event()

    def render():
        figure_to_png_bytes(figure, width_px=128)
        finished.set()

    with figure_guard():  # stands in for a grapher building a figure
        thread = threading.Thread(target=render, daemon=True)
        thread.start()
        assert not finished.wait(0.4), "a render ran while a build held the guard"

    assert finished.wait(30)
    thread.join(timeout=30)


def test_a_build_waits_for_a_render_in_flight(frame):
    """And the other way round: ``savefig`` rewrites the figure it is
    saving, so a build must not enter its style context meanwhile."""
    started, finished = threading.Event(), threading.Event()

    def build():
        started.set()
        _plot(frame)
        finished.set()

    with figure_guard():  # stands in for a render on the render thread
        thread = threading.Thread(target=build, daemon=True)
        thread.start()
        assert started.wait(10)
        assert not finished.wait(0.4), "a build ran while a render held the guard"

    assert finished.wait(30)
    thread.join(timeout=30)


def test_a_render_is_unaffected_by_a_figure_being_built_elsewhere(frame, busy_builder):
    """The end-to-end version: without the guard this produced a
    different image nearly every time -- 21 distinct results in 25
    renders -- because the style context another thread was entering is
    a *global* rcParams swap. Timing-dependent, so the two tests above
    are the ones that pin the contract."""
    figure = _plot(frame)
    expected = hashlib.md5(figure_to_png_bytes(figure, width_px=512)).hexdigest()

    seen = set()
    deadline = time.perf_counter() + 1.5
    while time.perf_counter() < deadline:
        seen.add(hashlib.md5(figure_to_png_bytes(figure, width_px=512)).hexdigest())

    assert seen == {expected}


def test_a_figures_geometry_is_never_read_mid_save(frame):
    """``savefig`` rewrites the figure's size and dpi for the duration
    of the call: a 6.0 x 4.0 figure at 100 dpi reads as 5.953 x 3.917 at
    72 dpi. ``window_size_for`` *memoises* what it reads, so a window
    caught mid-save opened wrong and stayed wrong."""
    # A denser figure means longer saves, so the window in which the
    # figure reports its transient size is wide enough to hit.
    rng = np.random.default_rng(1)
    dense = pd.DataFrame(
        {"x": rng.normal(size=40_000), "y": rng.normal(size=40_000),
         "g": rng.choice(list("ab"), 40_000)}
    )
    figure = _plot(dense, fig_width=6.0, fig_height=4.0)
    quiet_aspect, quiet_size = figure_aspect(figure), window_size_for(figure).toTuple()

    stop = threading.Event()

    def render_forever():
        while not stop.is_set():
            figure_to_svg_bytes(figure)
            figure_to_png_bytes(figure, width_px=256)

    thread = threading.Thread(target=render_forever, daemon=True)
    thread.start()
    try:
        aspects, sizes = set(), set()
        deadline = time.perf_counter() + 3.0  # sample across whole saves
        while time.perf_counter() < deadline:
            aspects.add(round(figure_aspect(figure), 4))
            figure._ruyso_window_size = None  # force a fresh reading
            del figure._ruyso_window_size
            sizes.add(window_size_for(figure).toTuple())
            time.sleep(0.0005)
    finally:
        stop.set()
        thread.join(timeout=10)

    assert aspects == {round(quiet_aspect, 4)}
    assert sizes == {quiet_size}
