
"""
Application entry point: creates the ``QApplication``, applies the
visual theme, shows the main window, and starts the Qt event loop.
 
Kept separate from ``main_window.py`` so ``MainWindow`` itself can be
imported and instantiated (e.g. in tests, with ``QT_QPA_PLATFORM=offscreen``)
without also starting a blocking event loop.
"""
 
from __future__ import annotations
 
import sys
 
from PySide6.QtWidgets import QApplication
 
from ruyso_app.ui import theme
from ruyso_app.ui.main_window import MainWindow
 
 
def main() -> int:
    """
    Run the pipeline builder application.
 
    Returns:
        The process exit code from the Qt event loop.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    theme.set_theme_mode("system")
    theme.apply_to_app(app)
 
    window = MainWindow()
    window.show()
 
    return app.exec()
 
 
if __name__ == "__main__":
    sys.exit(main())
 
