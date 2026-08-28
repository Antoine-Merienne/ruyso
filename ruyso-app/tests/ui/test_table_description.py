"""
Tests for ``ui.table_description.describe_table``.
"""

import numpy as np
import pandas as pd

from ruyso_app.ui.table_description import (
    GEO,
    GEO_TIME,
    PLAIN,
    TIME,
    describe_table,
    looks_like_dataframe,
)


def _frame():
    return pd.DataFrame(
        {
            "age": [20, 30, 40],
            "income": [1.0, np.nan, 3.0],
            "city": ["x", "", "z"],
            "active": [True, False, True],
        }
    )


def test_scalar_facts_include_row_count():
    d = describe_table(_frame())
    assert d.table_type == PLAIN
    assert d.n_rows == 3
    assert d.n_variables == 4
    assert d.n_missing == 2  # one NaN in income + one empty string in city


def test_numeric_vars_table_has_stats_and_excludes_bool():
    d = describe_table(_frame())
    names = {v.name for v in d.numeric_vars}
    assert names == {"age", "income"}  # "active" is bool -> categorical

    age = next(v for v in d.numeric_vars if v.name == "age")
    assert age.dtype == "int64"
    assert age.mean == "30"
    assert age.minimum == "20"
    assert age.maximum == "40"
    assert age.std  # some formatted value, not empty


def test_categorical_vars_table_counts_distinct_values():
    d = describe_table(_frame())
    by_name = {v.name: v for v in d.categorical_vars}
    assert set(by_name) == {"city", "active"}
    assert by_name["city"].n_distinct == 3
    assert by_name["active"].n_distinct == 2


def test_datetime_column_goes_in_the_numeric_table():
    df = pd.DataFrame({"when": pd.date_range("2020-01-01", periods=3)})
    d = describe_table(df)
    assert [v.name for v in d.numeric_vars] == ["when"]
    assert d.categorical_vars == []
    when = d.numeric_vars[0]
    assert "2020-01-01" in when.minimum
    assert "2020-01-03" in when.maximum


def test_time_indexed_dataframe():
    df = _frame()
    df.index = pd.date_range("2020-01-01", periods=3)
    assert describe_table(df).table_type == TIME


def test_geo_dataframe_detected_by_geometry_column():
    df = _frame()
    df["geometry"] = [0, 1, 2]
    assert describe_table(df).table_type == GEO


def test_geo_and_time_dataframe():
    df = _frame()
    df["geometry"] = [0, 1, 2]
    df.index = pd.period_range("2020-01-01", periods=3, freq="D")
    assert describe_table(df).table_type == GEO_TIME


def test_looks_like_dataframe():
    assert looks_like_dataframe(_frame())
    assert not looks_like_dataframe([1, 2, 3])
    assert not looks_like_dataframe(None)
