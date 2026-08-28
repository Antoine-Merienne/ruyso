"""
The Table tab: inspect the output table of any pipeline step.

Layout (spec section 4): a left column with a step **navigator** on
top (a flat, execution-ordered list -- a file-navigator rather than
the mockups' miniature node diagram) and a **Table description** panel
below; a main area showing the selected table in a grid with
mouse-resizable columns. No Options panel, no run log.

Messages follow the spec:
* before any run:            "run pipeline and select table to display"
* after a run, no selection: "select table to display"
"""

from __future__ import annotations

from typing import Any

from NodeGraphQt import NodeGraph
from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ruyso_app.ui.dataframe_model import DataFrameTableModel
from ruyso_app.ui.table_description import (
    TableDescription,
    describe_table,
    looks_like_dataframe,
)
from ruyso_app.ui.table_nav import TableEntry, table_entries_from_graph

MESSAGE_BEFORE_RUN = "run pipeline and select table to display"
MESSAGE_NO_SELECTION = "select table to display"

#: Qt.UserRole payload on each list item: its TableEntry.
_ENTRY_ROLE = Qt.UserRole
#: Bool role: this table has been modified since the last successful run.
_MODIFIED_ROLE = Qt.UserRole + 1
#: Tag appended after a modified table's name, in pale yellow.
_MODIFIED_TAG = " · modified"
_MODIFIED_COLOR = QColor("#d8be55")


class _ModifiedTagDelegate(QStyledItemDelegate):
    """Draws the navigator label, then a pale-yellow ' · modified' tag."""

    def paint(
        self, painter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        super().paint(painter, option, index)
        if not index.data(_MODIFIED_ROLE):
            return
        label = index.data(Qt.DisplayRole) or ""
        metrics = option.fontMetrics
        x = option.rect.left() + 6 + metrics.horizontalAdvance(label)
        painter.save()
        painter.setPen(_MODIFIED_COLOR)
        painter.drawText(
            x,
            option.rect.top(),
            metrics.horizontalAdvance(_MODIFIED_TAG) + 8,
            option.rect.height(),
            int(Qt.AlignVCenter | Qt.AlignLeft),
            _MODIFIED_TAG,
        )
        painter.restore()


#: Column headers for the two variable tables in the description panel.
_NUMERIC_HEADERS = ["variable", "type", "mean", "std. dev", "min", "max"]
_CATEGORICAL_HEADERS = ["variable", "type", "# distinct values"]


class TableDescriptionWidget(QWidget):
    """The "Table description" panel; empty until a table is selected."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._empty = QLabel("No table selected.", self)
        self._empty.setWordWrap(True)

        # Scalar facts about the table (type, rows, variables, missing).
        self._summary_host = QWidget()
        self._summary = QFormLayout(self._summary_host)
        self._summary.setContentsMargins(0, 0, 0, 0)

        self._numeric_label = QLabel("<b>Numeric variables</b>")
        self._numeric_table = _make_stat_table(_NUMERIC_HEADERS)
        self._categorical_label = QLabel("<b>String / categorical variables</b>")
        self._categorical_table = _make_stat_table(_CATEGORICAL_HEADERS)

        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._summary_host)
        content_layout.addWidget(self._numeric_label)
        content_layout.addWidget(self._numeric_table)
        content_layout.addWidget(self._categorical_label)
        content_layout.addWidget(self._categorical_table)
        content_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._content)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel("<b>Table description</b>", self))
        layout.addWidget(self._empty)
        layout.addWidget(scroll, 1)
        self._content.setVisible(False)

    def clear(self) -> None:
        self._empty.setVisible(True)
        self._content.setVisible(False)

    def show_description(self, df: Any) -> None:
        description = describe_table(df)
        self._populate_summary(description)
        _fill_stat_table(
            self._numeric_table,
            [
                [v.name, v.dtype, v.mean, v.std, v.minimum, v.maximum]
                for v in description.numeric_vars
            ],
        )
        _fill_stat_table(
            self._categorical_table,
            [
                [v.name, v.dtype, str(v.n_distinct)]
                for v in description.categorical_vars
            ],
        )
        self._numeric_label.setVisible(bool(description.numeric_vars))
        self._numeric_table.setVisible(bool(description.numeric_vars))
        self._categorical_label.setVisible(bool(description.categorical_vars))
        self._categorical_table.setVisible(bool(description.categorical_vars))

        self._empty.setVisible(False)
        self._content.setVisible(True)

    def _populate_summary(self, description: TableDescription) -> None:
        while self._summary.rowCount():
            self._summary.removeRow(0)
        self._summary.addRow("Type", QLabel(description.table_type))
        self._summary.addRow("Rows", QLabel(str(description.n_rows)))
        self._summary.addRow("Variables", QLabel(str(description.n_variables)))
        self._summary.addRow("Missing / empty", QLabel(str(description.n_missing)))


class TablePage(QWidget):
    """Step navigator + table description + data grid."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._outputs: dict[str, dict] = {}
        self._has_run = False

        self._nav = QListWidget(self)
        self._nav.setSelectionMode(QAbstractItemView.SingleSelection)
        self._nav.setItemDelegate(_ModifiedTagDelegate(self._nav))
        self._nav.itemSelectionChanged.connect(self._on_selection_changed)

        self._description = TableDescriptionWidget(self)

        left = QSplitter(Qt.Vertical, self)
        left.addWidget(self._nav)
        left.addWidget(self._description)
        left.setStretchFactor(0, 1)
        left.setStretchFactor(1, 1)

        self._message = QLabel(MESSAGE_BEFORE_RUN, self)
        self._message.setAlignment(Qt.AlignCenter)

        self._table_view = QTableView(self)
        self._table_model = DataFrameTableModel(parent=self._table_view)
        self._table_view.setModel(self._table_model)
        self._table_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._table_view.horizontalHeader().setStretchLastSection(False)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._message)
        self._stack.addWidget(self._table_view)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(left)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(1, False)
        splitter.setSizes([320, 1080])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    # -- public API -----------------------------------------------------

    def refresh(
        self,
        graph: NodeGraph,
        outputs: dict[str, dict] | None,
        modified: set[str] | None = None,
    ) -> None:
        """
        Rebuild the navigator from the current pipeline and run outputs.

        Args:
            graph: The live canvas graph (for pipeline structure/order).
            outputs: The last run's ``{node_id: {port: value}}`` mapping,
                or ``None`` / empty if the pipeline has not been run.
            modified: Node ids whose output would now differ from that
                run; their still-shown table gets a "· modified" tag.
        """
        self._outputs = outputs or {}
        self._has_run = bool(self._outputs)
        modified = modified or set()

        previously = self._selected_entry()
        self._nav.blockSignals(True)
        self._nav.clear()
        for entry in table_entries_from_graph(graph):
            item = QListWidgetItem(entry.label)
            item.setData(_ENTRY_ROLE, entry)
            available = self._resolve_dataframe(entry) is not None
            if not available:
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
            item.setData(_MODIFIED_ROLE, available and entry.node_id in modified)
            self._nav.addItem(item)
            if previously is not None and (entry.node_id, entry.port) == previously:
                item.setSelected(True)
        self._nav.blockSignals(False)

        self._on_selection_changed()

    # kept for backwards compat with earlier phases' callers/tests
    def set_run_outputs(self, outputs: dict[str, dict]) -> None:
        self._outputs = outputs or {}
        self._has_run = bool(self._outputs)
        self._update_message()

    def current_message(self) -> str:
        return self._message.text()

    def apply_theme(self) -> None:
        """No themed surfaces of its own; kept for interface parity."""

    # -- internals ----------------------------------------------------

    def _selected_entry(self) -> tuple[str, str] | None:
        items = self._nav.selectedItems()
        if not items:
            return None
        entry: TableEntry = items[0].data(_ENTRY_ROLE)
        return (entry.node_id, entry.port)

    def _resolve_dataframe(self, entry: TableEntry) -> Any | None:
        value = self._outputs.get(entry.node_id, {}).get(entry.port)
        return value if looks_like_dataframe(value) else None

    def _on_selection_changed(self) -> None:
        items = self._nav.selectedItems()
        if not items:
            self._description.clear()
            self._update_message()
            return

        entry: TableEntry = items[0].data(_ENTRY_ROLE)
        df = self._resolve_dataframe(entry)
        if df is None:
            self._description.clear()
            self._update_message()
            return

        self._table_model.set_dataframe(df)
        self._description.show_description(df)
        self._stack.setCurrentWidget(self._table_view)

    def _update_message(self) -> None:
        self._message.setText(
            MESSAGE_NO_SELECTION if self._has_run else MESSAGE_BEFORE_RUN
        )
        self._stack.setCurrentWidget(self._message)


def _make_stat_table(headers: list[str]) -> QTableWidget:
    """A compact, read-only table for the description panel."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionMode(QAbstractItemView.NoSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    return table


def _fill_stat_table(table: QTableWidget, rows: list[list[str]]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem(value))
    table.resizeColumnsToContents()
    # Keep the widget just tall enough for its rows (plus header).
    row_h = table.verticalHeader().defaultSectionSize()
    header_h = table.horizontalHeader().height()
    table.setMaximumHeight(header_h + row_h * max(len(rows), 1) + 4)
