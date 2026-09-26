"""
Tests for ``ui.dataframe_model.DataFrameTableModel``.
"""

import pandas as pd
import pytest
from PySide6.QtCore import Qt

from ruyso_app.core import dtformat
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


# -- datetime columns render through core.dtformat ----------------------


def _column(model, count):
    return [model.data(model.index(r, 0), Qt.DisplayRole) for r in range(count)]


def test_a_date_column_does_not_render_a_constant_midnight(qapp):
    """``str(Timestamp)`` would spell out '2020-02-01 00:00:00' on every row."""
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01", "2019-07-15"])})
    assert _column(DataFrameTableModel(df), 2) == ["2020-02-01", "2019-07-15"]


def test_a_column_with_times_keeps_them(qapp):
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01 09:30", "2020-02-02 14:00"])})
    assert _column(DataFrameTableModel(df), 2) == [
        "2020-02-01 09:30", "2020-02-02 14:00"
    ]


def test_an_explicit_display_format_is_honoured(qapp):
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01", "2019-07-15"])})
    dtformat.set_display_format(df, "t", "%Y-%m")
    assert _column(DataFrameTableModel(df), 2) == ["2020-02", "2019-07"]


def test_a_missing_timestamp_renders_as_an_empty_cell(qapp):
    df = pd.DataFrame({"t": pd.to_datetime(["2020-02-01", None])})
    assert _column(DataFrameTableModel(df), 2) == ["2020-02-01", ""]


def test_set_dataframe_re_resolves_the_formats(qapp):
    model = DataFrameTableModel(pd.DataFrame({"t": pd.to_datetime(["2020-02-01"])}))
    assert _column(model, 1) == ["2020-02-01"]

    swapped = pd.DataFrame({"t": pd.to_datetime(["2020-02-01 09:30"])})
    model.set_dataframe(swapped)
    assert _column(model, 1) == ["2020-02-01 09:30"]


def test_non_datetime_columns_are_untouched(qapp):
    df = pd.DataFrame({"v": [1.5, 2.5], "s": ["a", "b"]})
    model = DataFrameTableModel(df)
    assert model.data(model.index(0, 0), Qt.DisplayRole) == "1.5"
    assert model.data(model.index(1, 1), Qt.DisplayRole) == "b"


# -- the Data-display preferences ---------------------------------------

from ruyso_app.engine import settings as app_settings  # noqa: E402


@pytest.fixture
def _restore_settings():
    yield
    app_settings.reset()


def test_a_float_is_capped_at_the_configured_decimals(qapp, _restore_settings):
    app_settings.set("data.float_precision", 3)
    df = pd.DataFrame({"v": [0.1 + 0.2, 1.23456789]})
    model = DataFrameTableModel(df)

    assert _column(model, 2) == ["0.3", "1.235"]


def test_capping_only_shortens_it_never_pads(qapp, _restore_settings):
    """1.5 must not become 1.5000 just because a cap exists."""
    app_settings.set("data.float_precision", 4)
    assert _column(DataFrameTableModel(pd.DataFrame({"v": [1.5, 2.0]})), 2) == ["1.5", "2"]


def test_a_very_large_float_keeps_its_own_notation(qapp, _restore_settings):
    model = DataFrameTableModel(pd.DataFrame({"v": [1e20]}))
    assert "e+" in _column(model, 1)[0]


def test_missing_values_use_the_configured_text(qapp, _restore_settings):
    import numpy as np

    app_settings.set("data.missing_display", "—")
    model = DataFrameTableModel(pd.DataFrame({"v": [1.0, np.nan]}))
    assert _column(model, 2) == ["1", "—"]


def test_the_preview_is_capped_to_the_configured_rows(qapp, _restore_settings):
    app_settings.set("data.max_preview_rows", 10)
    model = DataFrameTableModel(pd.DataFrame({"v": range(500)}))

    assert model.rowCount() == 10
    assert model.truncated_rows() == 490


def test_a_frame_shorter_than_the_cap_is_shown_whole(qapp, _restore_settings):
    app_settings.set("data.max_preview_rows", 100)
    model = DataFrameTableModel(pd.DataFrame({"v": range(5)}))

    assert model.rowCount() == 5
    assert model.truncated_rows() == 0
