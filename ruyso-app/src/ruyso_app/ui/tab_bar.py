"""
The horizontal tab band shown at the top of the main window.

The mockups (ruyso_ui_principles.pptx) show a strip of three tabs --
Pipeline, Table, Dashboard -- where the active one is a lighter
surface and the others sit on the dark window background. Qt's native
``QTabWidget`` styles its tabs in a platform-specific way that does not
match that look, so this is a small purpose-built widget instead: a
row of exclusive checkable buttons that only emits a signal; the
actual page switching is done by whoever owns a ``QStackedWidget``
alongside it (see ``main_window.py``).

Styling lives entirely in ``ui.theme.stylesheet_for`` (the
``#ruysoTabBar`` / ``#ruysoTabButton`` rules), so the band restyles
itself on a dark/light theme toggle with no code here.
"""

from __future__ import annotations

from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget
from PySide6.QtCore import Signal


class TabBar(QWidget):
    """A row of exclusive tabs; emits ``tab_changed(key)`` on selection."""

    #: Emitted with the string key of the newly selected tab.
    tab_changed = Signal(str)

    def __init__(self, tabs: list[tuple[str, str]], parent: QWidget | None = None) -> None:
        """
        Args:
            tabs: ``(key, label)`` pairs, in display order. ``key`` is
                the stable identifier passed around in code and emitted
                by ``tab_changed``; ``label`` is the visible text.
            parent: Optional Qt parent.
        """
        super().__init__(parent)
        self.setObjectName("ruysoTabBar")

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        for key, label in tabs:
            button = QPushButton(label, self)
            button.setObjectName("ruysoTabButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, k=key: self.set_current_key(k))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        if tabs:
            self._current_key = tabs[0][0]
            self._buttons[self._current_key].setChecked(True)
        else:  # pragma: no cover - the app always passes a non-empty list
            self._current_key = ""

    def current_key(self) -> str:
        """The key of the currently selected tab."""
        return self._current_key

    def set_current_key(self, key: str) -> None:
        """
        Select the tab identified by ``key``.

        A no-op (and emits nothing) if ``key`` is already current, so
        callers can wire this to both button clicks and external
        navigation without causing signal loops.
        """
        if key not in self._buttons:
            raise KeyError(f"Unknown tab key {key!r}; expected one of {sorted(self._buttons)}")
        if key == self._current_key and self._buttons[key].isChecked():
            return
        self._current_key = key
        self._buttons[key].setChecked(True)
        self.tab_changed.emit(key)
