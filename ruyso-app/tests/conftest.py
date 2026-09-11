"""
Session-wide pytest fixtures.
"""

import os
import sys

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_ruyso_config(tmp_path_factory):
    """Point ``engine.colormaps`` and ``engine.settings`` at a throwaway
    config dir so tests never touch (or depend on) the real
    ``~/.config/ruyso/``.

    The unsaved-changes prompt is switched off for the whole run: it is
    a *modal* dialog raised from ``MainWindow.closeEvent``, and every
    test that builds a window and closes it would sit waiting for a
    click that never comes. ``tests/ui/test_main_window.py`` exercises
    the prompt directly instead, with ``QMessageBox.question`` patched.
    """
    os.environ["RUYSO_CONFIG_DIR"] = str(tmp_path_factory.mktemp("ruyso-config"))

    from ruyso_app.engine import settings

    settings.reload()
    yield


@pytest.fixture(autouse=True)
def _never_prompt_on_close():
    """
    Keep the unsaved-changes prompt off for every test.

    Re-asserted per test rather than once per session because tests that
    exercise the settings store legitimately delete the file, which
    would otherwise restore the prompt's default (on) for everything
    that ran afterwards -- and a modal raised from ``closeEvent`` in a
    headless run does not fail, it *hangs*, waiting for a click.
    """
    from ruyso_app.engine import settings

    if settings.get("general.confirm_on_close"):
        settings.set("general.confirm_on_close", False)
    yield


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
