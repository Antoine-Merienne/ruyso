"""
Session-wide pytest fixtures.
"""

import sys

import pytest


@pytest.fixture(autouse=True)
def _close_pyplot_figures():
    """
    Close every matplotlib figure a test left open.

    Figures created via ``pyplot`` are retained until explicitly
    closed, so across a full run they pile up into the hundreds. When a
    later UI test's ``gc.collect()`` then has to reclaim that pile *and*
    NodeGraphQt's per-graph ``QUndoStack`` in the same pass, PySide6 can
    crash deep in ``QUndoStack`` teardown (SIGSEGV / exit code 139).
    Closing here keeps the figure count near zero between tests.

    ``sys.modules`` is checked directly so this never imports matplotlib
    for a test that does not use it.
    """
    yield
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is not None:
        plt.close("all")
