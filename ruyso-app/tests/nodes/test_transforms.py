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
