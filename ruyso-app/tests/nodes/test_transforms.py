"""
Tests for transformation nodes (DropNA, StandardScalerNode): known
input DataFrame -> expected output DataFrame.
"""

import numpy as np
import pandas as pd
import pytest

from ruyso_app.nodes.transforms import (
    DropNA,
    DropNAParams,
    StandardScalerNode,
    StandardScalerParams,
)


def test_drop_na_removes_rows_with_any_missing_value_in_selected_columns():
    df = pd.DataFrame({"a": [1, None, 3], "b": [10, 20, None]})
    node = DropNA(params=DropNAParams(columns=["a", "b"]))

    result = node.run(df=df)["df"]

    assert result.shape == (1, 2)
    assert result.iloc[0].tolist() == [1.0, 10.0]


def test_drop_na_with_no_selected_columns_is_a_passthrough():
    df = pd.DataFrame({"a": [1, None, 3], "b": [10, 20, None]})
    result = DropNA(params=DropNAParams()).run(df=df)["df"]
    assert result.shape == (3, 2)


def test_drop_na_respects_column_subset_and_how_all():
    df = pd.DataFrame({"a": [1, None, None], "b": [10, None, 30]})
    node = DropNA(params=DropNAParams(columns=["a", "b"], how="all"))

    result = node.run(df=df)["df"]

    # Only the row where BOTH a and b are missing should be dropped.
    assert result.shape == (2, 2)


def test_standard_scaler_produces_zero_mean_unit_variance():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    node = StandardScalerNode(params=StandardScalerParams())

    result = node.run(df=df)["df"]

    assert np.isclose(result["x"].mean(), 0.0, atol=1e-9)
    assert np.isclose(result["x"].std(ddof=0), 1.0, atol=1e-9)


def test_standard_scaler_only_scales_requested_columns():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [100.0, 200.0, 300.0]})
    node = StandardScalerNode(params=StandardScalerParams(columns=["x"]))

    result = node.run(df=df)["df"]

    # "y" must be untouched.
    assert result["y"].tolist() == [100.0, 200.0, 300.0]
    assert np.isclose(result["x"].mean(), 0.0, atol=1e-9)


# -- ChangeType ---------------------------------------------------------

from ruyso_app.nodes.transforms import (  # noqa: E402
    ChangeType,
    ChangeTypeParams,
    ColumnFilter,
    ColumnFilterParams,
    DtypeFilter,
    DtypeFilterParams,
    RowFilter,
    RowFilterParams,
)


def test_change_type_string_to_int_coerces_bad_values():
    df = pd.DataFrame({"a": ["1", "2", "x"]})
    out = ChangeType(
        params=ChangeTypeParams(column="a", target_type="int", errors="coerce")
    ).run(df=df)["df"]
    assert str(out["a"].dtype) == "Int64"
    assert out["a"].tolist()[:2] == [1, 2]
    assert pd.isna(out["a"].iloc[2])


def test_change_type_to_datetime():
    df = pd.DataFrame({"d": ["2021-01-01", "2021-06-15"]})
    out = ChangeType(params=ChangeTypeParams(column="d", target_type="datetime")).run(
        df=df
    )["df"]
    assert pd.api.types.is_datetime64_any_dtype(out["d"])


def test_change_type_missing_column_raises():
    with pytest.raises(ValueError, match="not in the data"):
        ChangeType(params=ChangeTypeParams(column="nope", target_type="str")).run(
            df=pd.DataFrame({"a": [1]})
        )


# -- ColumnFilter -----------------------------------------------------


def test_column_filter_keep_and_drop():
    df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
    kept = ColumnFilter(params=ColumnFilterParams(columns=["a", "c"], mode="keep")).run(
        df=df
    )["df"]
    assert list(kept.columns) == ["a", "c"]
    dropped = ColumnFilter(
        params=ColumnFilterParams(columns=["a", "c"], mode="drop")
    ).run(df=df)["df"]
    assert list(dropped.columns) == ["b"]


def test_column_filter_empty_selection_is_passthrough():
    df = pd.DataFrame({"a": [1], "b": [2]})
    out = ColumnFilter(params=ColumnFilterParams(columns=None)).run(df=df)["df"]
    assert list(out.columns) == ["a", "b"]


# -- RowFilter ------------------------------------------------------


def test_row_filter_by_position():
    df = pd.DataFrame({"x": range(10)})
    out = RowFilter(
        params=RowFilterParams(mode="position", position_op="<", position_value=3)
    ).run(df=df)["df"]
    assert out["x"].tolist() == [0, 1, 2]


def test_row_filter_by_numeric_value():
    df = pd.DataFrame({"price": [5.0, 15.0, 25.0]})
    out = RowFilter(
        params=RowFilterParams(mode="value", column="price", value_op=">=", value="15")
    ).run(df=df)["df"]
    assert out["price"].tolist() == [15.0, 25.0]


def test_row_filter_text_contains():
    df = pd.DataFrame({"city": ["Portland", "Seattle", "Southport"]})
    out = RowFilter(
        params=RowFilterParams(
            mode="value", column="city", value_op="contains", value="port"
        )
    ).run(df=df)["df"]
    assert out["city"].tolist() == ["Southport"]


def test_row_filter_missing_column_raises():
    with pytest.raises(ValueError, match="not in the data"):
        RowFilter(
            params=RowFilterParams(mode="value", column="nope", value_op="==", value="x")
        ).run(df=pd.DataFrame({"a": [1]}))


# -- DtypeFilter --------------------------------------------------


def test_dtype_filter_keeps_selected_kinds():
    df = pd.DataFrame(
        {
            "s": pd.Series(["a", "b"], dtype="string"),
            "n": [1, 2],
            "cat": pd.Categorical(["x", "y"]),
            "d": pd.to_datetime(["2020-01-01", "2020-02-01"]),
        }
    )
    out = DtypeFilter(params=DtypeFilterParams(kinds=["numeric", "category"])).run(
        df=df
    )["df"]
    assert set(out.columns) == {"n", "cat"}


def test_dtype_filter_empty_is_passthrough():
    df = pd.DataFrame({"a": [1], "b": ["x"]})
    out = DtypeFilter(params=DtypeFilterParams(kinds=None)).run(df=df)["df"]
    assert list(out.columns) == ["a", "b"]


# -- FillNA -----------------------------------------------------------

from ruyso_app.nodes.transforms import FillNA, FillNAParams  # noqa: E402


def test_fill_na_forward_and_backward():
    df = pd.DataFrame({"x": [1.0, None, 3.0]})
    assert FillNA(
        params=FillNAParams(columns=["x"], method="forward fill")
    ).run(df=df)["df"]["x"].tolist() == [1.0, 1.0, 3.0]
    assert FillNA(
        params=FillNAParams(columns=["x"], method="backward fill")
    ).run(df=df)["df"]["x"].tolist() == [1.0, 3.0, 3.0]


def test_fill_na_mean_and_zero_and_constant():
    df = pd.DataFrame({"x": [2.0, None, 4.0]})
    assert FillNA(params=FillNAParams(columns=["x"], method="mean")).run(df=df)[
        "df"
    ]["x"].tolist() == [2.0, 3.0, 4.0]
    assert FillNA(params=FillNAParams(columns=["x"], method="zero")).run(df=df)[
        "df"
    ]["x"].tolist() == [2.0, 0.0, 4.0]
    assert FillNA(
        params=FillNAParams(columns=["x"], method="constant", value="9.5")
    ).run(df=df)["df"]["x"].tolist() == [2.0, 9.5, 4.0]


def test_fill_na_most_frequent_on_text():
    df = pd.DataFrame({"s": ["p", None, "p", "q"]})
    out = FillNA(params=FillNAParams(columns=["s"], method="most frequent")).run(
        df=df
    )["df"]
    assert out["s"].tolist() == ["p", "p", "p", "q"]


def test_fill_na_mean_on_non_numeric_raises():
    df = pd.DataFrame({"s": ["a", None]})
    with pytest.raises(ValueError, match="needs a numeric column"):
        FillNA(params=FillNAParams(columns=["s"], method="mean")).run(df=df)


def test_fill_na_empty_selection_is_passthrough():
    df = pd.DataFrame({"x": [1.0, None]})
    out = FillNA(params=FillNAParams(columns=None)).run(df=df)["df"]
    assert pd.isna(out["x"].iloc[1])


# -- Concat ---------------------------------------------------------

from ruyso_app.nodes.transforms import Concat, ConcatParams  # noqa: E402


def test_concat_rows_and_reset_index():
    a = pd.DataFrame({"k": [1, 2]})
    b = pd.DataFrame({"k": [3, 4]})
    out = Concat(params=ConcatParams(axis="rows", reset_index=True)).run(
        df1=a, df2=b
    )["df"]
    assert out["k"].tolist() == [1, 2, 3, 4]
    assert out.index.tolist() == [0, 1, 2, 3]


def test_concat_columns_inner_join():
    a = pd.DataFrame({"k": [1, 2, 3]})
    b = pd.DataFrame({"m": [9, 9]})
    out = Concat(params=ConcatParams(axis="columns", join="inner")).run(
        df1=a, df2=b
    )["df"]
    assert list(out.columns) == ["k", "m"]
    assert len(out) == 2  # inner join drops the unmatched row


def test_concat_without_second_input_passes_the_first_through():
    a = pd.DataFrame({"k": [1, 2]})
    out = Concat(params=ConcatParams()).run(df1=a)["df"]
    assert out["k"].tolist() == [1, 2]


def test_concat_declares_an_optional_second_input():
    ports = {p.name: p.required for p in Concat.inputs}
    assert ports == {"df1": True, "df2": False}
