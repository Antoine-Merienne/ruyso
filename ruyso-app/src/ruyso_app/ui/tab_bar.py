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

from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QSizePolicy, QWidget
from PySide6.QtCore import QSize, Qt, Signal

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QStyle, QStyleOptionButton

from ruyso_app.ui.auto_status import AutoStatusPill
from ruyso_app.ui.problems_chip import ProblemsChip
from ruyso_app.ui.run_progress import RunProgressBar

#: Fallback chrome around a tab's text -- the QSS margins, border and
#: padding -- used only if the style cannot be asked (see below).
_TAB_CHROME = 2 * 2 + 2 + 2 * 20


def _reserve_bold_width(button: QPushButton) -> None:
    """
    Make a tab as wide as its label in **bold**.

    The active tab is bold (see the ``#ruysoTabButton:checked`` rule),
    but Qt sizes the button from the regular font it is built with, so
    the widest label -- "Dashboard" -- was clipped the moment it became
    the active one.

    The chrome around the text is measured by asking the style, not by
    adding up the numbers in the stylesheet: a first attempt at this
    counted the padding and the border but forgot the margins, and came
    out four pixels short -- enough to still elide "Dashboard".
    """
    bold = button.font()
    bold.setBold(True)
    metrics = QFontMetrics(bold)
    text = QSize(
        metrics.horizontalAdvance(button.text()), metrics.height()
    )

    button.ensurePolished()  # the stylesheet rules must be resolved first
    option = QStyleOptionButton()
    option.initFrom(button)
    option.text = button.text()
    option.fontMetrics = metrics
    size = button.style().sizeFromContents(
        QStyle.CT_PushButton, option, text, button
    )
    button.setMinimumWidth(max(size.width(), text.width() + _TAB_CHROME))


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
        # Needed for the QSS border-bottom (the divider baseline the
        # active folder tab sits on) to actually paint on a bare QWidget.
        self.setAttribute(Qt.WA_StyledBackground, True)

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
            _reserve_bold_width(button)
            button.clicked.connect(lambda _checked, k=key: self.set_current_key(k))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        #: "Run Pipeline" button, then the progress indicator, at the far
        #: right of the band (vertically centred, away from the tabs).
        self.run_button = QPushButton("Run Pipeline", self)
        self.run_button.setObjectName("ruysoRunButton")
        self.run_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        layout.addWidget(self.run_button, 0, Qt.AlignVCenter)
        layout.addSpacing(10)

        self.progress = RunProgressBar(self)
        layout.addWidget(self.progress, 0, Qt.AlignVCenter)
        layout.addSpacing(10)

        #: Background auto-run status ("· auto"), driven by MainWindow.
        self.auto_pill = AutoStatusPill(self)
        layout.addWidget(self.auto_pill, 0, Qt.AlignVCenter)

        #: Appears only when the pipeline has failures; clicking it goes
        #: to the Problems panel on the Pipeline tab.
        self.problems_chip = ProblemsChip(self)
        layout.addWidget(self.problems_chip, 0, Qt.AlignVCenter)
        layout.addSpacing(14)

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
