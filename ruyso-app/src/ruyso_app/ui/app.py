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

import sys

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from ruyso_app.engine import cache, settings
from ruyso_app.ui import theme
from ruyso_app.ui.main_window import MainWindow


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


def main() -> int:
    """
    Run the pipeline builder application.

    Returns:
        The process exit code from the Qt event loop.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    theme.set_theme_mode(str(settings.get("appearance.theme")))
    theme.apply_to_app(app)

    window = MainWindow()
    window.restore_window_geometry()
    window.show()

    trimmer = _CacheTrimmer()
    trimmer.start()
    try:
        return app.exec()
    finally:
        # Never leave the thread running past the event loop: a QThread
        # destroyed while running is the shape of problem that ends in a
        # segfault during teardown.
        trimmer.wait(5000)


if __name__ == "__main__":
    sys.exit(main())
