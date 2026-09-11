"""
The Problems panel: what went wrong, in the words of the person's own
pipeline rather than of the traceback.

Failures used to arrive as a modal ``QMessageBox`` holding whatever
``str(exception)`` produced -- a pydantic dump, most often -- which
interrupted the work, said nothing actionable, and was gone the moment
it was dismissed. This panel is the opposite on each count: it sits
beside the run log, it renders the plain sentences from
:mod:`ruyso_app.engine.errors`, it stays until the problem does, and
each row is a way *to* the failing node rather than a description of it.

Only nodes that actually raised get a row. Blocked nodes -- the ones a
failure stopped from running -- are left to the canvas's grey dots and
their tooltips: one bad parameter can block eight steps, and eight rows
saying so would bury the one row that matters. A graph too broken to
run at all has no node to blame, so it gets a single row of its own.

The panel knows nothing about the canvas: it emits which node (and
which setting) a person asked to see, and ``MainWindow`` does the
selecting.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ruyso_app.engine.errors import NodeError, field_label
from ruyso_app.ui import theme

#: Node id used for a problem that belongs to the pipeline as a whole
#: (a cycle, an unsatisfied required port) rather than to one node.
GRAPH_PROBLEM = "__pipeline__"


class ProblemRow(QFrame):
    """One failure: a clickable headline, with the details folded away."""

    #: ``(node_id, field)`` -- the node to select, and the setting to
    #: highlight (``""`` when the failure names no particular one).
    activated = Signal(str, str)

    def __init__(self, error: NodeError, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.error = error
        self.setObjectName("ruysoProblemRow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        layout.addLayout(self._build_header())
        self._details = self._build_details()
        self._details.setVisible(False)
        layout.addWidget(self._details)

    # -- construction ----------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(6)

        dot = QLabel("●", self)
        dot.setStyleSheet(f"color: {theme.STATUS_COLORS['error']};")
        header.addWidget(dot, 0, Qt.AlignTop)

        self._headline = QPushButton(self._headline_text(), self)
        self._headline.setFlat(True)
        self._headline.setCursor(Qt.PointingHandCursor)
        self._headline.setStyleSheet("text-align: left; border: none; padding: 0;")
        self._headline.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._headline.clicked.connect(
            lambda: self.activated.emit(self.error.node_id, self.error.field or "")
        )
        header.addWidget(self._headline, 1)

        self._expander = QToolButton(self)
        self._expander.setArrowType(Qt.RightArrow)
        self._expander.setAutoRaise(True)
        self._expander.setCheckable(True)
        self._expander.toggled.connect(self._on_expanded)
        header.addWidget(self._expander, 0, Qt.AlignTop)
        return header

    def _headline_text(self) -> str:
        error = self.error
        if error.node_id == GRAPH_PROBLEM:
            return error.title
        return f"{error.node_id}  ·  {error.title}"

    def _build_details(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 0, 0, 0)
        layout.setSpacing(4)

        if self.error.detail:
            detail = QLabel(self.error.detail, panel)
            detail.setWordWrap(True)
            layout.addWidget(detail)

        if self.error.field and self.error.node_id != GRAPH_PROBLEM:
            fix = QPushButton(
                f"Fix in Options ▸ {field_label(self.error.field)}", panel
            )
            fix.setFlat(True)
            fix.setCursor(Qt.PointingHandCursor)
            fix.setStyleSheet(
                f"text-align: left; border: none; padding: 0;"
                f" color: {theme.current_theme().highlight_color};"
            )
            fix.clicked.connect(
                lambda: self.activated.emit(self.error.node_id, self.error.field or "")
            )
            layout.addWidget(fix, 0, Qt.AlignLeft)

        layout.addWidget(self._build_technical(panel))
        return panel

    def _build_technical(self, parent: QWidget) -> QWidget:
        """The original traceback, folded away behind a disclosure.

        The friendly sentence above is a best-effort reading; this is the
        ground truth, and the thing to paste into a bug report.
        """
        box = QWidget(parent)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        toggle = QToolButton(box)
        toggle.setText("Show technical details")
        toggle.setCheckable(True)
        toggle.setAutoRaise(True)
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setArrowType(Qt.RightArrow)
        layout.addWidget(toggle, 0, Qt.AlignLeft)

        self._raw = QPlainTextEdit(self.error.raw, box)
        self._raw.setReadOnly(True)
        self._raw.setMaximumHeight(140)
        self._raw.setVisible(False)
        layout.addWidget(self._raw)

        copy = QPushButton("Copy", box)
        copy.setVisible(False)
        copy.clicked.connect(self._copy_raw)
        layout.addWidget(copy, 0, Qt.AlignLeft)

        def _toggled(checked: bool) -> None:
            toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
            self._raw.setVisible(checked)
            copy.setVisible(checked)

        toggle.toggled.connect(_toggled)
        return box

    # -- behaviour --------------------------------------------------------

    def _on_expanded(self, checked: bool) -> None:
        self._expander.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self._details.setVisible(checked)

    def set_expanded(self, expanded: bool) -> None:
        self._expander.setChecked(expanded)

    def is_expanded(self) -> bool:
        return self._expander.isChecked()

    def _copy_raw(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.error.raw)


class ProblemsPanel(QScrollArea):
    """The list of failures from the most recent run."""

    #: ``(node_id, field)`` -- forwarded from whichever row was clicked.
    problem_activated = Signal(str, str)
    #: Emitted with the new count whenever the list is replaced.
    count_changed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        self._rows: list[ProblemRow] = []
        self._body = QWidget(self)
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)

        self._empty = QLabel("No problems.", self._body)
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setEnabled(False)
        self._layout.addWidget(self._empty)
        self._layout.addStretch(1)

        self.setWidget(self._body)

    # -- content ----------------------------------------------------------

    def set_problems(self, errors: list[NodeError]) -> None:
        """
        Replace the list.

        Rows are rebuilt rather than reconciled: the list is short, it
        changes only when a run finishes, and rebuilding keeps the order
        the scheduler reported (dependency order, so the earliest
        failure -- usually the cause of the rest -- is at the top).
        """
        for row in self._rows:
            self._layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()

        for index, error in enumerate(errors):
            row = ProblemRow(error, self._body)
            row.activated.connect(self.problem_activated)
            self._layout.insertWidget(index, row)
            self._rows.append(row)

        self._empty.setVisible(not errors)
        self.count_changed.emit(len(errors))

    def clear(self) -> None:
        self.set_problems([])

    def count(self) -> int:
        return len(self._rows)

    def rows(self) -> list[ProblemRow]:
        """The row widgets, in order (used by tests)."""
        return list(self._rows)
