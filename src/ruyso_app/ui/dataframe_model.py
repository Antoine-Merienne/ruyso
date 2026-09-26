"""
A read-only ``QAbstractTableModel`` over a pandas DataFrame, for the
Table tab's data grid.

Deliberately minimal: it exposes column names as horizontal headers
and the DataFrame index as vertical headers, and stringifies cell
values on demand. Column widths are left to the ``QTableView``'s
header (interactive resize), per the spec.

Datetime columns are the one exception to "stringify on demand".
``str(Timestamp)`` always spells out ``2020-02-01 00:00:00``, so a
column of plain dates used to drag a meaningless ``00:00:00`` across
every row, and a format chosen upstream had no way to reach the screen.
Instead each datetime column is rendered through
:mod:`ruyso_app.core.dtformat`: the format a node set explicitly if
there is one, else the coarsest pattern that loses nothing. The
formats are resolved once per DataFrame in :meth:`set_dataframe`, not
per cell -- ``data()`` is called for every visible cell on every repaint.

The Table tab keeps a single instance for the life of the view and
calls :meth:`set_dataframe` when the selected table changes, rather
than creating a fresh model per selection.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

from ruyso_app.core import dtformat
from ruyso_app.engine import settings


#: Past this magnitude, fixed-point formatting is a wall of digits and
#: Python's own repr (which switches to exponent form) reads far better.
_FIXED_POINT_LIMIT = 1e16


def _format_float(value: float, precision: int) -> str:
    """
    A float as text, capped at ``precision`` decimals.

    Trailing zeros are stripped, so the cap only ever *shortens*: 1.5
    stays "1.5" rather than becoming "1.5000", while
    0.1 + 0.2 stops being "0.30000000000000004". Padding would align
    columns more neatly but would change how every clean number in the
    app already reads, for no gain.
    """
    if precision < 0 or not float("-inf") < value < float("inf"):
        return str(value)
    if abs(value) >= _FIXED_POINT_LIMIT:
        return repr(value)
    text = f"{value:.{precision}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class DataFrameTableModel(QAbstractTableModel):
    """Wraps a DataFrame for display in a ``QTableView`` (read-only)."""

    def __init__(self, df: Any | None = None, parent: object | None = None) -> None:
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()
        self._datetime_formats = self._resolve_formats(self._df)

    def set_dataframe(self, df: Any) -> None:
        """Swap in a new DataFrame, resetting the view."""
        self.beginResetModel()
        self._df = df
        self._datetime_formats = self._resolve_formats(df)
        self.endResetModel()

    @staticmethod
    def _resolve_formats(df: Any) -> dict[int, str]:
        """``{column position: strftime pattern}`` for the datetime columns."""
        formats: dict[int, str] = {}
        for position, column in enumerate(df.columns):
            try:
                fmt = dtformat.display_format_for(df, column)
            except Exception:  # noqa: BLE001 - a odd column must not blank the table
                fmt = None
            if fmt:
                formats[position] = fmt
        return formats

    # -- Qt model interface ----------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        # A preview, not the data: a million-row frame would build a
        # million QModelIndexes for a grid showing thirty of them. The
        # cap is a preference because "how much is worth scrolling" is
        # a matter of taste and of machine.
        cap = int(settings.get("data.max_preview_rows") or 0)
        rows = len(self._df.index)
        return min(rows, cap) if cap > 0 else rows

    def truncated_rows(self) -> int:
        """How many rows the preview cap is hiding (0 when showing all)."""
        return max(0, len(self._df.index) - self.rowCount())

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        value = self._df.iat[index.row(), index.column()]
        fmt = self._datetime_formats.get(index.column())
        if fmt is not None:
            return dtformat.format_value(value, fmt)
        return self._render(value)

    @staticmethod
    def _render(value: Any) -> str:
        """One cell as text, honouring the Data-display preferences."""
        if value is None:
            return str(settings.get("data.missing_display"))
        if isinstance(value, float):
            if value != value:  # NaN
                return str(settings.get("data.missing_display"))
            return _format_float(value, int(settings.get("data.float_precision")))
        try:
            if value is pd.NaT or (pd.isna(value) and not isinstance(value, (list, tuple))):
                return str(settings.get("data.missing_display"))
        except (TypeError, ValueError):
            pass
        return str(value)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ) -> Any:
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return str(self._df.columns[section])
        return str(self._df.index[section])
