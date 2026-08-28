"""
Tests for ``ui.dataframe_model.DataFrameTableModel``.
"""

import pandas as pd
from PySide6.QtCore import Qt

from ruyso_app.ui.dataframe_model import DataFrameTableModel


def test_shape_headers_and_cell_values(qapp):
    df = pd.DataFrame({"x": [10, 20], "y": ["a", "b"]}, index=["r0", "r1"])
    model = DataFrameTableModel(df)

    assert model.rowCount() == 2
    assert model.columnCount() == 2
    assert model.headerData(0, Qt.Horizontal) == "x"
    assert model.headerData(1, Qt.Horizontal) == "y"
    assert model.headerData(1, Qt.Vertical) == "r1"

    idx = model.index(1, 0)
    assert model.data(idx, Qt.DisplayRole) == "20"


def test_non_display_role_returns_none(qapp):
    model = DataFrameTableModel(pd.DataFrame({"x": [1]}))
    assert model.data(model.index(0, 0), Qt.BackgroundRole) is None
