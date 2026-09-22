"""
Tests for ``ui.app``'s startup chores -- the work that runs beside the
event loop so a first run does not pay for it.
"""

import sys

from ruyso_app.ui.app import _PREWARM, _Prewarmer


def test_the_prewarmer_loads_every_library_it_names(qapp):
    """A typo here would be invisible: the thread swallows what it
    cannot import, so nothing would ever report the miss."""
    thread = _Prewarmer()
    thread.start()
    assert thread.wait(120_000)

    for name in _PREWARM:
        assert name in sys.modules, f"{name} was not imported"
