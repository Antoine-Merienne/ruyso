"""
The "auto" status pill shown just right of the run-progress bar in the
tab band.

A fully-rounded chip: a small status **dot** followed by the word
``auto``. The dot mirrors, for the *background auto-run* as a whole,
the same colour language the per-node dots use:

* **grey**  -- auto-run is switched off (View > Auto-run), or a manual
  "Run Pipeline" is in progress;
* **blue**  -- an auto-run is running;
* **green** -- the last auto-run finished cleanly;
* **red**   -- the last auto-run raised.

The colours live in ``theme.stylesheet_for`` (the ``#ruysoAutoDot``
rules), keyed off a Qt dynamic property; this widget only flips that
property, so it restyles itself on a dark/light toggle with no code
here.

The chip is also a toggle: clicking it emits :attr:`clicked`, which
``MainWindow`` wires to the same switch as *View > Auto-run*.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

#: state -> the values the QSS ``[state="..."]`` selectors expect.
_STATES = ("idle", "running", "ok", "error")


class AutoStatusPill(QWidget):
    """A rounded ``[· auto]`` chip whose dot colour tracks the auto-run,
    and which toggles auto-run on / off when clicked."""

    #: Emitted on a left click (press + release within the chip).
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoAutoPill")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)

        self._dot = QLabel(self)
        self._dot.setObjectName("ruysoAutoDot")
        self._dot.setFixedSize(8, 8)

        label = QLabel("auto", self)
        label.setObjectName("ruysoAutoLabel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(9, 3, 11, 3)
        layout.setSpacing(6)
        layout.addWidget(self._dot, 0, Qt.AlignVCenter)
        layout.addWidget(label, 0, Qt.AlignVCenter)

        self._state = ""
        self._pressed = False
        self.set_state("idle")

    def state(self) -> str:
        """The current state string (one of :data:`_STATES`)."""
        return self._state

    # -- click-to-toggle ------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            self._pressed = True
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            if self.rect().contains(event.position().toPoint()):
                self.clicked.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def set_state(self, state: str) -> None:
        """Set the dot to ``idle`` / ``running`` / ``ok`` / ``error``."""
        if state not in _STATES:
            raise ValueError(f"Unknown auto-status state {state!r}")
        self._state = state
        self._dot.setProperty("state", state)
        for widget in (self, self._dot):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
