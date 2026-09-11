"""
Tests for transformation nodes (DropNA, Scaler): known input DataFrame
-> expected output DataFrame.
"""

import numpy as np
import pandas as pd
import pytest

from ruyso_app.nodes.transforms import (
    DropNA,
    DropNAParams,
    Scaler,
    ScalerParams,
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


def test_scaler_standard_method_produces_zero_mean_unit_variance():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    node = Scaler(params=ScalerParams())  # method="standard" is the default

    result = node.run(df=df)["df"]

    assert np.isclose(result["x"].mean(), 0.0, atol=1e-9)
    assert np.isclose(result["x"].std(ddof=0), 1.0, atol=1e-9)


def test_scaler_only_scales_requested_columns():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [100.0, 200.0, 300.0]})
    node = Scaler(params=ScalerParams(columns=["x"]))

    result = node.run(df=df)["df"]

    # "y" must be untouched.
    assert result["y"].tolist() == [100.0, 200.0, 300.0]
    assert np.isclose(result["x"].mean(), 0.0, atol=1e-9)


def test_scaler_standard_with_mean_or_std_off():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    no_center = Scaler(params=ScalerParams(with_mean=False)).run(df=df)["df"]
    assert not np.isclose(no_center["x"].mean(), 0.0, atol=1e-6)  # not centred

    no_scale = Scaler(params=ScalerParams(with_std=False)).run(df=df)["df"]
    assert np.isclose(no_scale["x"].mean(), 0.0, atol=1e-9)
    assert not np.isclose(no_scale["x"].std(ddof=0), 1.0, atol=1e-6)  # not unit variance


def test_scaler_minmax_rescales_into_the_feature_range():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    result = Scaler(
        params=ScalerParams(method="minmax", feature_range_min=-1.0, feature_range_max=1.0)
    ).run(df=df)["df"]
    assert np.isclose(result["x"].min(), -1.0)
    assert np.isclose(result["x"].max(), 1.0)


def test_scaler_minmax_rejects_an_inverted_range():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0]})
    with pytest.raises(ValueError, match="feature_range_max"):
        Scaler(
            params=ScalerParams(method="minmax", feature_range_min=1.0, feature_range_max=0.0)
        ).run(df=df)


def test_scaler_maxabs_divides_by_the_largest_absolute_value():
    df = pd.DataFrame({"x": [-4.0, 2.0, 4.0]})
    result = Scaler(params=ScalerParams(method="maxabs")).run(df=df)["df"]
    assert np.isclose(result["x"].abs().max(), 1.0)
    assert result["x"].tolist() == [-1.0, 0.5, 1.0]


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


# -- Sample / Head / Tail / Sort / ResetIndex ------------------------

from ruyso_app.nodes.transforms import (  # noqa: E402
    Aggregate,
    AggregateParams,
    GroupBy,
    GroupByParams,
    Head,
    HeadParams,
    Merge,
    MergeParams,
    ResetIndex,
    ResetIndexParams,
    Sample,
    SampleParams,
    Sort,
    SortParams,
    Tail,
    TailParams,
)


def test_sample_by_count_and_fraction_are_reproducible():
    df = pd.DataFrame({"x": range(20)})
    a = Sample(params=SampleParams(mode="count", n=5, random_state=7)).run(df=df)["df"]
    b = Sample(params=SampleParams(mode="count", n=5, random_state=7)).run(df=df)["df"]
    assert len(a) == 5 and a["x"].tolist() == b["x"].tolist()
    frac = Sample(params=SampleParams(mode="fraction", frac=0.25, random_state=7)).run(df=df)["df"]
    assert len(frac) == 5


def test_head_and_tail():
    df = pd.DataFrame({"x": range(10)})
    assert Head(params=HeadParams(n=3)).run(df=df)["df"]["x"].tolist() == [0, 1, 2]
    assert Tail(params=TailParams(n=3)).run(df=df)["df"]["x"].tolist() == [7, 8, 9]


def test_sort_by_columns_descending_and_passthrough():
    df = pd.DataFrame({"a": [3, 1, 2], "b": ["z", "x", "y"]})
    out = Sort(params=SortParams(columns=["a"], ascending=False)).run(df=df)["df"]
    assert out["a"].tolist() == [3, 2, 1]
    assert Sort(params=SortParams(columns=None)).run(df=df)["df"]["a"].tolist() == [3, 1, 2]


def test_reset_index_drop_and_keep():
    df = pd.DataFrame({"v": [1, 2]}, index=pd.Index([10, 20]))
    dropped = ResetIndex(params=ResetIndexParams(drop=True)).run(df=df)["df"]
    assert dropped.index.tolist() == [0, 1]
    kept = ResetIndex(params=ResetIndexParams(drop=False, index_name="orig")).run(df=df)["df"]
    assert list(kept.columns) == ["orig", "v"]
    assert kept["orig"].tolist() == [10, 20]


# -- GroupBy -----------------------------------------------------


def test_group_by_reduction_keeps_keys_as_columns():
    df = pd.DataFrame({"g": ["a", "a", "b"], "x": [1, 2, 3], "y": [10.0, 20.0, 30.0]})
    out = GroupBy(params=GroupByParams(by=["g"], method="sum")).run(df=df)["df"]
    assert out.set_index("g")["x"].to_dict() == {"a": 3, "b": 3}
    assert out.set_index("g")["y"].to_dict() == {"a": 30.0, "b": 30.0}


def test_group_by_size():
    df = pd.DataFrame({"g": ["a", "a", "b"], "x": [1, 2, 3]})
    out = GroupBy(params=GroupByParams(by=["g"], method="size")).run(df=df)["df"]
    assert out.set_index("g")["size"].to_dict() == {"a": 2, "b": 1}


def test_group_by_empty_keys_is_passthrough():
    df = pd.DataFrame({"g": ["a"], "x": [1]})
    assert list(GroupBy(params=GroupByParams(by=None)).run(df=df)["df"].columns) == ["g", "x"]


# -- Aggregate -------------------------------------------------


def test_aggregate_grouped_produces_flat_column_function_names():
    df = pd.DataFrame({"g": ["a", "a", "b"], "x": [1, 3, 5], "y": [10.0, 30.0, 50.0]})
    out = Aggregate(
        params=AggregateParams(by=["g"], columns=["x", "y"], functions=["sum", "mean"])
    ).run(df=df)["df"]
    assert set(out.columns) == {"g", "x_sum", "x_mean", "y_sum", "y_mean"}
    row_a = out.set_index("g").loc["a"]
    assert row_a["x_sum"] == 4 and row_a["x_mean"] == 2.0


def test_aggregate_whole_frame_single_and_multi_function():
    df = pd.DataFrame({"x": [2, 4, 6]})
    one = Aggregate(params=AggregateParams(columns=["x"], functions=["mean"])).run(df=df)["df"]
    assert one.shape == (1, 1) and one["x_mean"].iloc[0] == 4.0
    many = Aggregate(params=AggregateParams(columns=["x"], functions=["sum", "max"])).run(df=df)["df"]
    assert many["x_sum"].iloc[0] == 12 and many["x_max"].iloc[0] == 6


def test_aggregate_no_functions_is_passthrough():
    df = pd.DataFrame({"x": [1, 2]})
    assert Aggregate(params=AggregateParams(functions=None)).run(df=df)["df"]["x"].tolist() == [1, 2]


# -- Merge ---------------------------------------------------


def test_merge_on_key_with_each_how():
    left = pd.DataFrame({"k": [1, 2, 3], "v": ["a", "b", "c"]})
    right = pd.DataFrame({"k": [2, 3, 4], "w": ["x", "y", "z"]})
    inner = Merge(params=MergeParams(on=["k"], how="inner")).run(df1=left, df2=right)["df"]
    assert inner["k"].tolist() == [2, 3]
    left_join = Merge(params=MergeParams(on=["k"], how="left")).run(df1=left, df2=right)["df"]
    assert left_join["k"].tolist() == [1, 2, 3]
    outer = Merge(params=MergeParams(on=["k"], how="outer")).run(df1=left, df2=right)["df"]
    assert sorted(outer["k"].tolist()) == [1, 2, 3, 4]


def test_merge_overlapping_columns_get_suffixes():
    left = pd.DataFrame({"k": [1], "v": ["L"]})
    right = pd.DataFrame({"k": [1], "v": ["R"]})
    out = Merge(
        params=MergeParams(on=["k"], suffix_left="_l", suffix_right="_r")
    ).run(df1=left, df2=right)["df"]
    assert "v_l" in out.columns and "v_r" in out.columns


def test_merge_requires_both_inputs():
    ports = {p.name: p.required for p in Merge.inputs}
    assert ports == {"df1": True, "df2": True}


# -- Pivot / Unpivot / PivotTable ---------------------------------

from ruyso_app.nodes.transforms import (  # noqa: E402
    Pivot,
    PivotParams,
    PivotTable,
    PivotTableParams,
    Unpivot,
    UnpivotParams,
)


def _long():
    return pd.DataFrame(
        {
            "date": ["d1", "d1", "d2", "d2"],
            "city": ["NYC", "LA", "NYC", "LA"],
            "sales": [10, 20, 30, 40],
            "units": [1, 2, 3, 4],
        }
    )


def test_pivot_flattens_and_resets_index():
    out = Pivot(
        params=PivotParams(index=["date"], columns=["city"], values=["sales"])
    ).run(df=_long())["df"]
    assert list(out.columns) == ["date", "LA", "NYC"]
    assert out.set_index("date")["NYC"].to_dict() == {"d1": 10, "d2": 30}


def test_pivot_multi_value_columns_flatten_to_value_header():
    out = Pivot(
        params=PivotParams(index=["date"], columns=["city"], values=["sales", "units"])
    ).run(df=_long())["df"]
    assert set(out.columns) == {"date", "sales_LA", "sales_NYC", "units_LA", "units_NYC"}


def test_pivot_on_duplicate_pairs_raises_a_helpful_error():
    dup = pd.DataFrame({"a": ["x", "x"], "b": ["y", "y"], "v": [1, 2]})
    with pytest.raises(ValueError, match="pivot_table"):
        Pivot(params=PivotParams(index=["a"], columns=["b"], values=["v"])).run(df=dup)


def test_pivot_missing_keys_is_passthrough():
    df = _long()
    assert list(Pivot(params=PivotParams()).run(df=df)["df"].columns) == list(df.columns)


def test_unpivot_melts_selected_value_columns():
    out = Unpivot(
        params=UnpivotParams(
            id_vars=["date", "city"],
            value_vars=["sales", "units"],
            var_name="metric",
            value_name="amount",
        )
    ).run(df=_long())["df"]
    assert list(out.columns) == ["date", "city", "metric", "amount"]
    assert len(out) == 8
    assert set(out["metric"]) == {"sales", "units"}


def test_pivot_table_multi_function_flat_columns_and_fill_value():
    out = PivotTable(
        params=PivotTableParams(
            index=["date"],
            columns=["city"],
            values=["sales"],
            functions=["sum", "mean"],
            fill_value="0",
        )
    ).run(df=_long())["df"]
    assert set(out.columns) == {
        "date", "sum_sales_LA", "sum_sales_NYC", "mean_sales_LA", "mean_sales_NYC",
    }


def test_pivot_table_margins_adds_totals():
    out = PivotTable(
        params=PivotTableParams(
            index=["date"], columns=["city"], values=["sales"],
            functions=["sum"], margins=True,
        )
    ).run(df=_long())["df"]
    assert "sales_All" in out.columns
    assert "All" in out["date"].tolist()


def test_pivot_table_no_keys_is_passthrough():
    df = _long()
    assert list(PivotTable(params=PivotTableParams()).run(df=df)["df"].columns) == list(df.columns)


from ruyso_app.nodes.transforms import Bin, BinParams  # noqa: E402


def _bin_df():
    return pd.DataFrame({"score": list(range(1, 21)), "grp": ["a", "b"] * 10})


def test_bin_equal_width_adds_a_category_column_and_keeps_the_original():
    out = Bin(params=BinParams(column="score", method="equal_width", bin_count=4)).run(
        df=_bin_df()
    )["df"]
    assert "score" in out.columns and "score_bin" in out.columns
    assert str(out["score_bin"].dtype) == "category"
    assert out["score_bin"].nunique() == 4


def test_bin_quantile_makes_equal_count_groups():
    out = Bin(params=BinParams(column="score", method="quantile", bin_count=4)).run(
        df=_bin_df()
    )["df"]
    counts = out["score_bin"].value_counts()
    assert set(counts) == {5}  # 20 rows / 4 quantile bins


def test_bin_explicit_cutoffs_make_one_more_bin_than_cutoffs():
    # scores 1..20; one cutoff at 10 -> two bins (<=10, >10).
    out = Bin(
        params=BinParams(
            column="score", method="explicit", cut_points="10", output_name="band"
        )
    ).run(df=_bin_df())["df"]
    assert "band" in out.columns and "score_bin" not in out.columns
    assert out["band"].nunique() == 2
    assert out.loc[out["score"] <= 10, "band"].nunique() == 1
    assert out.loc[out["score"] <= 10, "band"].iloc[0] != out.loc[out["score"] > 10, "band"].iloc[0]

    # two cutoffs -> three bins; semicolons are the separator
    three = Bin(
        params=BinParams(column="score", method="explicit", cut_points="7; 14")
    ).run(df=_bin_df())["df"]
    assert three["score_bin"].nunique() == 3


def test_bin_explicit_needs_at_least_one_cutoff():
    with pytest.raises(ValueError, match="at least one cutoff"):
        Bin(params=BinParams(column="score", method="explicit", cut_points="  ")).run(
            df=_bin_df()
        )


def test_bin_bool_output_requires_exactly_two_bins():
    ok = Bin(
        params=BinParams(column="score", method="equal_width", bin_count=2, output_type="bool")
    ).run(df=_bin_df())["df"]
    assert str(ok["score_bin"].dtype) == "boolean"
    assert ok["score_bin"].tolist() == [False] * 10 + [True] * 10

    with pytest.raises(ValueError, match="exactly 2 bins"):
        Bin(
            params=BinParams(
                column="score", method="equal_width", bin_count=3, output_type="bool"
            )
        ).run(df=_bin_df())


def test_bin_integer_output_is_a_nullable_int_index():
    out = Bin(
        params=BinParams(
            column="score", method="equal_width", bin_count=4, output_type="integer"
        )
    ).run(df=_bin_df())["df"]
    assert str(out["score_bin"].dtype) == "Int64"
    assert set(out["score_bin"].tolist()) == {0, 1, 2, 3}


def test_bin_string_output_uses_the_typed_labels_and_checks_the_count():
    out = Bin(
        params=BinParams(
            column="score",
            method="equal_width",
            bin_count=3,
            output_type="string",
            labels="low, mid, high",
        )
    ).run(df=_bin_df())["df"]
    assert list(out["score_bin"].cat.categories) == ["low", "mid", "high"]

    with pytest.raises(ValueError, match="needs 3 names"):
        Bin(
            params=BinParams(
                column="score",
                method="equal_width",
                bin_count=3,
                output_type="string",
                labels="low, high",
            )
        ).run(df=_bin_df())


from ruyso_app.nodes.transforms import (  # noqa: E402
    RenameCategories,
    RenameCategoriesParams,
)


def _grade_df():
    return pd.DataFrame(
        {"grade": pd.Categorical(["lo", "hi", "lo", "mid"]), "n": [1, 2, 3, 4]}
    )


def test_rename_categories_relabels_only_the_filled_in_entries():
    out = RenameCategories(
        params=RenameCategoriesParams(column="grade", renames='{"lo": "Low"}')
    ).run(df=_grade_df())["df"]
    assert set(out["grade"].cat.categories) == {"Low", "hi", "mid"}
    assert out["grade"].tolist() == ["Low", "hi", "Low", "mid"]


def test_rename_categories_merges_two_old_values_mapped_to_one_name():
    out = RenameCategories(
        params=RenameCategoriesParams(
            column="grade", renames='{"lo": "x", "mid": "x"}'
        )
    ).run(df=_grade_df())["df"]
    assert set(out["grade"].cat.categories) == {"x", "hi"}
    assert out["grade"].tolist() == ["x", "hi", "x", "x"]


def test_rename_categories_empty_or_invalid_mapping_is_a_pass_through():
    df = _grade_df()
    assert RenameCategories(
        params=RenameCategoriesParams(column="grade", renames="{}")
    ).run(df=df)["df"] is df
    assert RenameCategories(
        params=RenameCategoriesParams(column="grade", renames="not json")
    ).run(df=df)["df"] is df


def test_rename_categories_works_on_a_plain_object_column():
    df = pd.DataFrame({"city": ["ny", "la", "ny"]})
    out = RenameCategories(
        params=RenameCategoriesParams(column="city", renames='{"ny": "New York"}')
    ).run(df=df)["df"]
    assert out["city"].tolist() == ["New York", "la", "New York"]


# -- OneHotEncode / OrdinalEncode -----------------------------------------

from ruyso_app.nodes.transforms import (  # noqa: E402
    OneHotEncode,
    OneHotEncodeParams,
    OrdinalEncode,
    OrdinalEncodeParams,
)


def _encoder_df():
    return pd.DataFrame(
        {
            "city": ["ny", "la", "ny", "sf"],
            "size": pd.Categorical(["s", "m", "l", "m"]),
            "n": [1, 2, 3, 4],
        }
    )


def test_one_hot_encode_auto_detects_categorical_columns():
    out = OneHotEncode(params=OneHotEncodeParams()).run(df=_encoder_df())["df"]
    assert "n" in out.columns  # numeric column untouched
    assert {"city_ny", "city_la", "city_sf", "size_s", "size_m", "size_l"} <= set(out.columns)
    assert "city" not in out.columns  # replaced by default
    assert set(out["city_ny"].unique()) <= {0, 1}


def test_one_hot_encode_drop_first_and_keep_original():
    out = OneHotEncode(
        params=OneHotEncodeParams(columns=["size"], drop_first=True, replace=False)
    ).run(df=_encoder_df())["df"]
    assert "size" in out.columns  # kept alongside
    size_dummies = [c for c in out.columns if c.startswith("size_")]
    assert len(size_dummies) == 2  # 3 levels - 1 dropped


def test_ordinal_encode_replaces_with_sorted_integer_codes():
    out = OrdinalEncode(params=OrdinalEncodeParams(columns=["city"])).run(
        df=_encoder_df()
    )["df"]
    # categories sorted: la=0, ny=1, sf=2
    assert out["city"].tolist() == [1, 0, 1, 2]
    assert str(out["city"].dtype) == "Int64"


def test_ordinal_encode_keep_original_adds_suffixed_column():
    out = OrdinalEncode(
        params=OrdinalEncodeParams(columns=["size"], replace=False)
    ).run(df=_encoder_df())["df"]
    assert "size" in out.columns and "size_ordinal" in out.columns


def test_encoders_pass_through_when_no_categorical_columns():
    num = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    assert OneHotEncode(params=OneHotEncodeParams()).run(df=num)["df"] is num
    assert OrdinalEncode(params=OrdinalEncodeParams()).run(df=num)["df"] is num


# -- datetime: combine / split / resample --------------------------------

import json  # noqa: E402

from ruyso_app.nodes.transforms import (  # noqa: E402
    CombineDatetime,
    CombineDatetimeParams,
    ResampleDatetime,
    ResampleDatetimeParams,
    SplitDatetime,
    SplitDatetimeParams,
)


def test_combine_datetime_assembles_from_numeric_parts():
    df = pd.DataFrame({"yr": [2021, 2022], "mo": [1, 12], "dy": [15, 31], "hr": [9, 23]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "yr", "month": "mo", "day": "dy", "hour": "hr"})
        )
    ).run(df=df)["df"]
    assert pd.api.types.is_datetime64_any_dtype(out["datetime"])
    assert out["datetime"].iloc[0] == pd.Timestamp("2021-01-15 09:00:00")
    assert "yr" in out.columns  # sources kept by default


def test_combine_datetime_quarter_and_replace():
    df = pd.DataFrame({"y": [2020, 2021], "q": [1, 4]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "y", "quarter": "q"}),
            output_column="dt", replace=True,
        )
    ).run(df=df)["df"]
    assert list(out.columns) == ["dt"]
    assert out["dt"].tolist() == [pd.Timestamp("2020-01-01"), pd.Timestamp("2021-10-01")]


def test_combine_datetime_day_of_year_handles_leap():
    df = pd.DataFrame({"y": [2024], "doy": [60]})
    out = CombineDatetime(
        params=CombineDatetimeParams(mapping=json.dumps({"year": "y", "dayofyear": "doy"}))
    ).run(df=df)["df"]
    assert out["datetime"].iloc[0] == pd.Timestamp("2024-02-29")


def test_combine_datetime_parses_a_single_text_column():
    df = pd.DataFrame({"raw": ["2023-03-15", "2023-11-01"]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "raw"}), datetime_format="%Y-%m-%d"
        )
    ).run(df=df)["df"]
    assert pd.api.types.is_datetime64_any_dtype(out["datetime"])
    assert out["datetime"].iloc[1] == pd.Timestamp("2023-11-01")


def test_combine_datetime_empty_mapping_is_a_passthrough():
    df = pd.DataFrame({"a": [1, 2]})
    assert CombineDatetime(params=CombineDatetimeParams()).run(df=df)["df"] is df


# -- combine_datetime: display format ------------------------------------
#
# The format is display metadata, never a dtype change: the column has to
# stay a real datetime or sorting, resampling and the date axes break.

from ruyso_app.core import dtformat  # noqa: E402


def test_combine_datetime_records_the_display_format_without_changing_dtype():
    df = pd.DataFrame({"y": [2020, 2019], "m": [2, 7]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "y", "month": "m"}), display_format="%Y-%m"
        )
    ).run(df=df)["df"]

    assert pd.api.types.is_datetime64_any_dtype(out["datetime"])
    assert dtformat.display_formats(out) == {"datetime": "%Y-%m"}
    assert dtformat.format_value(out["datetime"].iloc[0], "%Y-%m") == "2020-02"


def test_combine_datetime_display_format_follows_a_renamed_output_column():
    df = pd.DataFrame({"y": [2020], "m": [2]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "y", "month": "m"}),
            output_column="period", display_format="%Y-%m",
        )
    ).run(df=df)["df"]
    assert dtformat.display_formats(out) == {"period": "%Y-%m"}


def test_combine_datetime_without_a_display_format_infers_one():
    """A column of whole days must not render a constant 00:00:00."""
    df = pd.DataFrame({"y": [2020], "m": [2]})
    out = CombineDatetime(
        params=CombineDatetimeParams(mapping=json.dumps({"year": "y", "month": "m"}))
    ).run(df=df)["df"]
    assert dtformat.display_formats(out) == {}
    assert dtformat.display_format_for(out, "datetime") == "%Y-%m-%d"


def test_combine_datetime_display_format_applies_to_a_parsed_text_column():
    df = pd.DataFrame({"raw": ["2023-03-15"]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "raw"}),
            datetime_format="%Y-%m-%d", display_format="%d/%m/%Y",
        )
    ).run(df=df)["df"]
    # The input format read the column; the display format only renders it.
    assert out["datetime"].iloc[0] == pd.Timestamp("2023-03-15")
    assert dtformat.display_formats(out) == {"datetime": "%d/%m/%Y"}


# -- combine_datetime: last of period ------------------------------------


@pytest.mark.parametrize(
    "mapping, first, last",
    [
        ({"year": "y"}, "2020-01-01", "2020-12-31"),
        ({"year": "y", "quarter": "q"}, "2020-01-01", "2020-03-31"),
        ({"year": "y", "month": "m"}, "2020-02-01", "2020-02-29"),  # leap year
        ({"year": "y", "week": "w"}, "2020-01-06", "2020-01-12"),
    ],
)
def test_combine_datetime_last_of_period(mapping, first, last):
    df = pd.DataFrame({"y": [2020], "q": [1], "m": [2], "w": [2]})
    encoded = json.dumps(mapping)

    default = CombineDatetime(
        params=CombineDatetimeParams(mapping=encoded)
    ).run(df=df)["df"]
    assert default["datetime"].iloc[0] == pd.Timestamp(first)

    end = CombineDatetime(
        params=CombineDatetimeParams(mapping=encoded, last_of_period=True)
    ).run(df=df)["df"]
    assert end["datetime"].iloc[0] == pd.Timestamp(last)


def test_combine_datetime_last_of_period_lands_at_midnight():
    """"Last unit at midnight", not the last instant (23:59:59.999999)."""
    df = pd.DataFrame({"y": [2020], "m": [2]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "y", "month": "m"}), last_of_period=True
        )
    ).run(df=df)["df"]
    stamp = out["datetime"].iloc[0]
    assert (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) == (0, 0, 0, 0)


def test_combine_datetime_last_of_period_is_a_no_op_at_day_resolution():
    df = pd.DataFrame({"y": [2020], "m": [2], "d": [10]})
    encoded = json.dumps({"year": "y", "month": "m", "day": "d"})
    out = CombineDatetime(
        params=CombineDatetimeParams(mapping=encoded, last_of_period=True)
    ).run(df=df)["df"]
    assert out["datetime"].iloc[0] == pd.Timestamp("2020-02-10")


def test_combine_datetime_last_of_period_still_adds_the_time_parts():
    df = pd.DataFrame({"y": [2020], "m": [2], "h": [9]})
    out = CombineDatetime(
        params=CombineDatetimeParams(
            mapping=json.dumps({"year": "y", "month": "m", "hour": "h"}),
            last_of_period=True,
        )
    ).run(df=df)["df"]
    assert out["datetime"].iloc[0] == pd.Timestamp("2020-02-29 09:00:00")


def _dt_df():
    return pd.DataFrame(
        {
            "t": pd.to_datetime(
                ["2021-01-15 09:30:00", "2022-06-03 14:00:00", "2023-12-31 23:59:59"]
            ),
        }
    )


def test_split_datetime_components_mode():
    out = SplitDatetime(
        params=SplitDatetimeParams(column="t", parts=["year", "quarter", "week", "hour"])
    ).run(df=_dt_df())["df"]
    assert {"t_year", "t_quarter", "t_week", "t_hour"} <= set(out.columns)
    assert out["t_year"].tolist() == [2021, 2022, 2023]
    assert out["t_quarter"].tolist() == [1, 2, 4]
    assert str(out["t_year"].dtype) == "Int64"


def test_split_datetime_string_mode_and_replace():
    out = SplitDatetime(
        params=SplitDatetimeParams(
            column="t", mode="string", datetime_format="%Y/%m", replace=True
        )
    ).run(df=_dt_df())["df"]
    assert list(out.columns) == ["t_str"]
    assert out["t_str"].tolist() == ["2021/01", "2022/06", "2023/12"]


def _series_df(n=30):
    return pd.DataFrame(
        {
            "ts": pd.date_range("2021-01-01", periods=n, freq="D"),
            "v": np.arange(float(n)),
            "lbl": ["a"] * (n // 2) + ["b"] * (n - n // 2),
        }
    )


def test_resample_datetime_downsamples_with_the_aggregator():
    out = ResampleDatetime(
        params=ResampleDatetimeParams(datetime_column="ts", rule="W", agg="mean")
    ).run(df=_series_df())["df"]
    assert "ts" in out.columns and len(out) == 5
    assert out["v"].iloc[0] == 1.0  # mean of days 0..2 (first partial week)
    assert set(out["lbl"].dropna()) <= {"a", "b"}  # non-numeric -> first


def test_resample_datetime_upsamples_and_fills():
    out = ResampleDatetime(
        params=ResampleDatetimeParams(
            datetime_column="ts", rule="12h", agg="mean", fill="ffill"
        )
    ).run(df=_series_df(n=5))["df"]
    assert len(out) == 9  # 5 days -> 12-hourly
    assert not out["v"].isna().any()  # forward-filled


def test_resample_datetime_ohlc_flattens_columns():
    out = ResampleDatetime(
        params=ResampleDatetimeParams(datetime_column="ts", rule="W", agg="ohlc")
    ).run(df=_series_df())["df"]
    assert {"v_open", "v_high", "v_low", "v_close"} <= set(out.columns)


def _monthly_df():
    return pd.DataFrame(
        {"ts": pd.date_range("2020-01-01", periods=70, freq="D"), "v": range(70)}
    )


def test_resample_datetime_last_of_period_relabels_the_bins():
    default = ResampleDatetime(
        params=ResampleDatetimeParams(datetime_column="ts", rule="MS", agg="mean")
    ).run(df=_monthly_df())["df"]
    assert default["ts"].tolist()[:2] == [
        pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")
    ]

    end = ResampleDatetime(
        params=ResampleDatetimeParams(
            datetime_column="ts", rule="MS", agg="mean", last_of_period=True
        )
    ).run(df=_monthly_df())["df"]
    assert end["ts"].tolist()[:2] == [
        pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29")
    ]


def test_resample_datetime_last_of_period_only_moves_the_label():
    """Relabelling must not change which rows fall in which bin."""
    kwargs = dict(datetime_column="ts", rule="MS", agg="mean")
    default = ResampleDatetime(params=ResampleDatetimeParams(**kwargs)).run(
        df=_monthly_df()
    )["df"]
    end = ResampleDatetime(
        params=ResampleDatetimeParams(**kwargs, last_of_period=True)
    ).run(df=_monthly_df())["df"]
    assert default["v"].tolist() == end["v"].tolist()


def test_resample_datetime_last_of_period_is_a_no_op_for_unit_rules():
    out = ResampleDatetime(
        params=ResampleDatetimeParams(
            datetime_column="ts", rule="D", agg="mean", last_of_period=True
        )
    ).run(df=_monthly_df())["df"]
    assert out["ts"].iloc[0] == pd.Timestamp("2020-01-01")


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------

from ruyso_app.nodes.transforms import Diff, DiffParams  # noqa: E402


def test_diff_default_lag_on_all_numeric_columns():
    df = pd.DataFrame({"v": [10.0, 12.0, 15.0, 15.0], "lbl": ["a", "b", "c", "d"]})
    out = Diff(params=DiffParams()).run(df=df)["df"]

    assert "v_diff_1" in out.columns and "lbl_diff_1" not in out.columns
    assert out["v_diff_1"].tolist()[1:] == [2.0, 3.0, 0.0]
    assert pd.isna(out["v_diff_1"].iloc[0])
    assert list(out["lbl"]) == ["a", "b", "c", "d"]  # untouched, kept


def test_diff_multiple_lags_and_selected_columns():
    df = pd.DataFrame({"v": [1.0, 2.0, 4.0, 8.0], "w": [0.0, 0.0, 0.0, 0.0]})
    out = Diff(params=DiffParams(columns=["v"], lags="1, 2")).run(df=df)["df"]

    assert {"v_diff_1", "v_diff_2"} <= set(out.columns)
    assert "w_diff_1" not in out.columns
    assert out["v_diff_2"].tolist()[2:] == [3.0, 6.0]


def test_diff_replace_drops_the_source_columns():
    df = pd.DataFrame({"v": [1.0, 3.0, 6.0]})
    out = Diff(params=DiffParams(columns=["v"], replace=True)).run(df=df)["df"]
    assert list(out.columns) == ["v_diff_1"]


def test_diff_unknown_column_raises():
    df = pd.DataFrame({"v": [1.0, 2.0]})
    with pytest.raises(ValueError, match="not found"):
        Diff(params=DiffParams(columns=["nope"])).run(df=df)


def test_diff_malformed_lags_raises():
    df = pd.DataFrame({"v": [1.0, 2.0]})
    with pytest.raises(ValueError, match="lags"):
        Diff(params=DiffParams(lags="one")).run(df=df)


def test_diff_selects_multiple_columns_via_tickboxes():
    df = pd.DataFrame({"a": [10.0, 12.0, 15.0], "b": [1.0, 3.0, 6.0], "c": [0.0, 0.0, 0.0]})
    out = Diff(params=DiffParams(columns=["a", "b"], lags="1")).run(df=df)["df"]
    assert {"a_diff_1", "b_diff_1"} <= set(out.columns)
    assert "c_diff_1" not in out.columns


def test_diff_first_value_handling():
    df = pd.DataFrame({"v": [10.0, 12.0, 15.0, 19.0]})

    nan = Diff(params=DiffParams(columns=["v"], lags="1, 2", first_value="nan")).run(df=df)["df"]
    assert pd.isna(nan["v_diff_1"].iloc[0]) and pd.isna(nan["v_diff_2"].iloc[1])

    zero = Diff(params=DiffParams(columns=["v"], lags="1, 2", first_value="zero")).run(df=df)["df"]
    assert zero["v_diff_1"].iloc[0] == 0.0
    assert zero["v_diff_2"].tolist()[:2] == [0.0, 0.0]

    keep = Diff(
        params=DiffParams(columns=["v"], lags="1, 2", first_value="keep_original")
    ).run(df=df)["df"]
    assert keep["v_diff_1"].iloc[0] == 10.0  # starts from the level
    assert keep["v_diff_2"].tolist()[:2] == [10.0, 12.0]
    assert keep["v_diff_1"].tolist()[1:] == [2.0, 3.0, 4.0]  # then changes


def test_diff_first_value_keep_original_for_negative_lag():
    df = pd.DataFrame({"v": [10.0, 12.0, 15.0, 19.0]})
    out = Diff(
        params=DiffParams(columns=["v"], lags="-1", first_value="keep_original")
    ).run(df=df)["df"]
    assert out["v_diff_-1"].iloc[-1] == 19.0  # trailing row kept as the level


# --------------------------------------------------------------------------
# CustomOperation
# --------------------------------------------------------------------------

from ruyso_app.nodes.transforms import CustomOperation, CustomOperationParams  # noqa: E402


def test_custom_operation_evaluates_an_expression_against_the_dataframe():
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "c": [0.0, 0.0, 0.0]})
    out = CustomOperation(
        params=CustomOperationParams(code="df['b'] = df['a'] / np.exp(df['c'])")
    ).run(df=df)["df"]
    assert out["b"].tolist() == [1.0, 2.0, 3.0]  # exp(0) == 1


def test_custom_operation_can_use_pandas_and_python_builtins():
    df = pd.DataFrame({"a": [1, 2, 3]})
    out = CustomOperation(
        params=CustomOperationParams(
            code="df['total'] = sum(df['a'])\ndf['n'] = len(df)"
        )
    ).run(df=df)["df"]
    assert out["total"].tolist() == [6, 6, 6]
    assert out["n"].tolist() == [3, 3, 3]


def test_custom_operation_blank_code_is_a_passthrough():
    df = pd.DataFrame({"a": [1, 2]})
    out = CustomOperation(params=CustomOperationParams(code="")).run(df=df)["df"]
    assert out is df


def test_custom_operation_does_not_mutate_the_input_dataframe():
    df = pd.DataFrame({"a": [1, 2]})
    CustomOperation(params=CustomOperationParams(code="df['b'] = df['a'] * 2")).run(df=df)
    assert "b" not in df.columns


def test_custom_operation_syntax_error_is_a_clear_value_error():
    df = pd.DataFrame({"a": [1, 2]})
    with pytest.raises(ValueError, match="syntax error"):
        CustomOperation(params=CustomOperationParams(code="df['b'] =")).run(df=df)


def test_custom_operation_runtime_error_is_a_clear_value_error():
    df = pd.DataFrame({"a": [1, 2]})
    with pytest.raises(ValueError, match="custom_operation"):
        CustomOperation(params=CustomOperationParams(code="1 / 0")).run(df=df)


def test_custom_operation_cannot_import():
    df = pd.DataFrame({"a": [1, 2]})
    with pytest.raises(ValueError):
        CustomOperation(params=CustomOperationParams(code="import os")).run(df=df)


def test_custom_operation_rejects_a_non_dataframe_result():
    df = pd.DataFrame({"a": [1, 2]})
    with pytest.raises(ValueError, match="DataFrame"):
        CustomOperation(params=CustomOperationParams(code="df = 42")).run(df=df)


# --------------------------------------------------------------------------
# CovarianceMatrix
# --------------------------------------------------------------------------

from ruyso_app.nodes.transforms import CovarianceMatrix, CovarianceMatrixParams  # noqa: E402


def _cov_df():
    rng = np.random.default_rng(0)
    n = 200
    a = rng.normal(size=n)
    b = a * 0.7 + rng.normal(scale=0.5, size=n)
    c = rng.normal(size=n)
    return pd.DataFrame({"a": a, "b": b, "c": c})


def test_covariance_matrix_is_symmetric_and_square():
    out = CovarianceMatrix(params=CovarianceMatrixParams()).run(df=_cov_df())["df"]
    assert list(out.columns) == ["variable", "a", "b", "c"]
    assert list(out["variable"]) == ["a", "b", "c"]
    values = out[["a", "b", "c"]].to_numpy()
    np.testing.assert_allclose(values, values.T, atol=1e-9)


def test_covariance_matrix_normalize_gives_a_correlation_matrix():
    out = CovarianceMatrix(params=CovarianceMatrixParams(normalize=True)).run(df=_cov_df())["df"]
    diag = [out.loc[out["variable"] == v, v].iloc[0] for v in ("a", "b", "c")]
    np.testing.assert_allclose(diag, 1.0, atol=1e-9)
    assert (out[["a", "b", "c"]].to_numpy() <= 1.0001).all()
    assert (out[["a", "b", "c"]].to_numpy() >= -1.0001).all()


def test_covariance_matrix_column_subset():
    out = CovarianceMatrix(params=CovarianceMatrixParams(columns=["a", "b"])).run(
        df=_cov_df()
    )["df"]
    assert list(out.columns) == ["variable", "a", "b"]


def test_covariance_matrix_needs_at_least_two_columns():
    with pytest.raises(ValueError, match="at least 2"):
        CovarianceMatrix(params=CovarianceMatrixParams(columns=["a"])).run(df=_cov_df())


def test_covariance_matrix_unknown_column_raises():
    with pytest.raises(ValueError, match="not found"):
        CovarianceMatrix(params=CovarianceMatrixParams(columns=["a", "nope"])).run(
            df=_cov_df()
        )
