"""
Application entry point: creates the ``QApplication``, applies the
visual theme, shows the main window, and starts the Qt event loop.

Kept separate from ``main_window.py`` so ``MainWindow`` itself can be
imported and instantiated (e.g. in tests, with ``QT_QPA_PLATFORM=offscreen``)
without also starting a blocking event loop. The launch-time chores
that only make sense for a real session live here rather than in the
window: restoring its geometry, and trimming the disk cache.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from ruyso_app import __version__
from ruyso_app.engine import cache, settings
from ruyso_app.ui import theme
from ruyso_app.ui.main_window import MainWindow


#: Shown in the dock, the task bar, the About box and the window title.
APP_NAME = "Ruyso"

#: Libraries a first run would otherwise wait for. Nodes import these
#: inside ``run()`` -- ``core``/``nodes``/``engine`` must not pull a GUI
#: toolkit at module level, and a cold matplotlib costs the best part of
#: a second -- so the first plot of a session paid ~1.4 s of imports
#: before any actual work started. Loading them beside the event loop
#: moves that off the first run.
_PREWARM = (
    "matplotlib.pyplot",
    "seaborn",
    "sklearn.linear_model",
    "statsmodels.api",
)


class _Prewarmer(QThread):
    """
    Imports the heavy plotting / modelling libraries in the background.

    Safe to race with a node importing the same module: Python's import
    machinery locks per module, so the loser simply waits. One that
    cannot be imported at all is skipped, exactly as it would have been
    at use time -- this is a head start, never a requirement.
    """

    def run(self) -> None:
        for name in _PREWARM:
            try:
                importlib.import_module(name)
            except Exception:  # noqa: BLE001 - a head start is not a promise
                continue


class _CacheTrimmer(QThread):
    """
    Applies the cache size budget once, in the background.

    ``Memory.reduce_size`` walks the whole cache directory, which is not
    something to do on the way to showing a window -- and joblib 1.5
    removed the constructor argument that used to make this automatic,
    so it has to be an explicit pass. Startup is the right moment: the
    cache only grows while the app runs, and a budget is a disk
    allowance rather than a hard ceiling.
    """

    def run(self) -> None:
        cache.enforce_size_limit()


def _settle_frozen_environment() -> None:
    """
    The two things a packaged build gets wrong before it draws anything.

    A double-clicked bundle starts with the *filesystem root* as its
    working directory, so a relative export path ("plot.png") aims at
    "/plot.png" and fails; home is the only sane default.

    And ``n_jobs`` on a model node hands work to joblib, which starts
    workers by re-running ``sys.executable`` -- which in a bundle is the
    app itself, so a fork bomb of windows rather than a pool. Stdlib
    ``multiprocessing`` is handled by ``freeze_support()`` in
    ``__main__``; loky has its own spawn path that is unverified here,
    and the failure lands on the user's machine, so the packaged build
    does that work in-process until it is measured.
    """
    if not getattr(sys, "frozen", False):
        return
    os.environ.setdefault("JOBLIB_MULTIPROCESSING", "0")
    if Path.cwd() == Path(Path.cwd().anchor):
        os.chdir(Path.home())


def _apply_app_identity(app: QApplication) -> None:
    """Name, version and icon -- what the dock, the task bar and the
    About box read. Without it a packaged app is an unnamed generic."""
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(__version__)
    icon_path = Path(__file__).resolve().parent / "assets" / "app-icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))


def main() -> int:
    """
    Run the pipeline builder application.

    Returns:
        The process exit code from the Qt event loop.
    """
    if sys.stdout is None and {"--version", "--self-test"} & set(sys.argv):
        # A windowed Windows build has no console: leave the answer in a
        # file instead of printing into the void.
        sys.stdout = sys.stderr = open("ruyso.log", "w", encoding="utf-8")
    if "--version" in sys.argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--self-test" in sys.argv:
        from ruyso_app.selftest import run

        return run()

    _settle_frozen_environment()
    app = QApplication.instance() or QApplication(sys.argv)
    _apply_app_identity(app)
    theme.set_theme_mode(str(settings.get("appearance.theme")))
    theme.apply_to_app(app)

    window = MainWindow()
    window.restore_window_geometry()
    window.show()

    chores = [_Prewarmer(), _CacheTrimmer()]
    for chore in chores:
        chore.start()
    try:
        return app.exec()
    finally:
        # Never leave a thread running past the event loop: a QThread
        # destroyed while running is the shape of problem that ends in a
        # segfault during teardown.
        for chore in chores:
            chore.wait(5000)


if __name__ == "__main__":
    sys.exit(main())
