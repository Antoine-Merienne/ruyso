"""
A read-only ``QAbstractTableModel`` over a pandas DataFrame, for the
Table tab's data grid.

Deliberately minimal: it exposes column names as horizontal headers
and the DataFrame index as vertical headers, and stringifies cell
values on demand. Column widths are left to the ``QTableView``'s
header (interactive resize), per the spec.

The Table tab keeps a single instance for the life of the view and
calls :meth:`set_dataframe` when the selected table changes, rather
than creating a fresh model per selection.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


class DataFrameTableModel(QAbstractTableModel):
    """Wraps a DataFrame for display in a ``QTableView`` (read-only)."""

    def __init__(self, df: Any | None = None, parent: object | None = None) -> None:
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()

    def set_dataframe(self, df: Any) -> None:
        """Swap in a new DataFrame, resetting the view."""
        self.beginResetModel()
        self._df = df
        self.endResetModel()

    # -- Qt model interface ----------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._df.index)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        value = self._df.iat[index.row(), index.column()]
        return "" if value is None else str(value)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(self._df.index[section])
