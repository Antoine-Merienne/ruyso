"""
Data cleaning / transformation nodes: take a DataFrame in, produce a
modified DataFrame out. Each node performs a single, well-defined
transformation so pipelines stay easy to read and to compose.
"""

from typing import Any, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    category_map_field,
    checkbox_list_field,
    code_field,
    column_field,
    column_map_field,
    reactive_choice_field,
    suggestions_field,
    unit_interval_field,
    visible_field,
)
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

#: strptime patterns offered (non-binding) by every datetime-related
#: field in this module (``change_type`` -> datetime, ``combine_datetime``,
#: ``split_datetime``).
_COMMON_DATETIME_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d", "ISO8601",
]


class DropNAParams(NodeParams):
    """
    Parameters for DropNA.

    Attributes:
        columns: Columns the NA-check looks at (chosen via tickboxes).
            An empty selection is a pass-through -- tick at least one
            column for the node to drop anything.
        how: "any" drops a row if at least one checked value is NA;
            "all" drops a row only if every checked value is NA.
    """

    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    how: Literal["any", "all"] = "any"


@register_node
class DropNA(Node):
    """
    Remove rows with missing values in the selected columns.
    """

    node_type = "drop_na"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = DropNAParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        columns = [c for c in (self.params.columns or []) if c in df.columns]
        if not columns:
            return {"df": df}
        return {"df": df.dropna(subset=columns, how=self.params.how)}


class StandardScalerParams(NodeParams):
    """
    Parameters for StandardScalerNode.

    Attributes:
        columns: Numeric columns to scale. If None (default), every
            numeric column in the DataFrame is scaled.
    """

    columns: list[str] | None = column_field(dtypes=("numeric",), default=None)


@register_node
class StandardScalerNode(Node):
    """
    Standardize numeric columns to zero mean and unit variance, using
    scikit-learn's StandardScaler.
    """

    node_type = "standard_scaler"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = StandardScalerParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Scale the configured (or auto-detected numeric) columns.

        Args:
            df: Input pandas.DataFrame (via the "df" input port).

        Returns:
            {"df": pandas.DataFrame} with the target columns scaled.
        """
        self.validate_inputs(inputs)
        from sklearn.preprocessing import StandardScaler

        df = inputs["df"].copy()
        columns = self.params.columns or df.select_dtypes(
            include="number"
        ).columns.tolist()
        df[columns] = StandardScaler().fit_transform(df[columns])
        return {"df": df}


# --------------------------------------------------------------------------
# ChangeType
# --------------------------------------------------------------------------


class ChangeTypeParams(NodeParams):
    """
    Parameters for ChangeType.

    Attributes:
        column: The column whose dtype to change.
        target_type: Target dtype -- one of str / category / bool /
            int / float / datetime. The Options panel narrows this list
            to the conversions that make sense for ``column``.
        datetime_format: strptime pattern used only when ``target_type``
            is "datetime" (blank = let pandas infer).
        errors: "raise" fails on an un-convertible value; "coerce"
            turns it into NaN/NaT (numeric / datetime targets only).
    """

    column: str = column_field(dtypes=("any",))
    target_type: str = reactive_choice_field(
        options="cast_types", depends_on="column", default="str"
    )
    datetime_format: str = suggestions_field(
        suggestions=_COMMON_DATETIME_FORMATS,
        default="",
        description="strptime format, e.g. %Y-%m-%d. Blank = infer.",
        visible_when=("target_type", "datetime"),
    )
    errors: Literal["raise", "coerce"] = "raise"


@register_node
class ChangeType(Node):
    """Change the dtype of a single column."""

    node_type = "change_type"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ChangeTypeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        df = inputs["df"].copy()
        col = self.params.column
        target = self.params.target_type
        errors = self.params.errors
        if col not in df.columns:
            raise ValueError(f"change_type: column {col!r} is not in the data")

        series = df[col]
        if target in ("int", "float"):
            numeric = pd.to_numeric(series, errors=errors)
            df[col] = numeric.astype("Int64" if target == "int" else "float64")
        elif target == "datetime":
            df[col] = pd.to_datetime(
                series, format=self.params.datetime_format or None, errors=errors
            )
        elif target == "bool":
            df[col] = series.astype("boolean")
        elif target == "category":
            df[col] = series.astype("category")
        else:  # "str"
            df[col] = series.astype("string")
        return {"df": df}


# --------------------------------------------------------------------------
# ColumnFilter
# --------------------------------------------------------------------------


class ColumnFilterParams(NodeParams):
    """
    Parameters for ColumnFilter.

    Attributes:
        columns: Columns the filter acts on (chosen via tickboxes).
            An empty selection is a pass-through.
        mode: "keep" keeps only the selected columns; "drop" removes
            them.
    """

    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    mode: Literal["keep", "drop"] = "keep"


@register_node
class ColumnFilter(Node):
    """Keep or drop a chosen subset of columns."""

    node_type = "column_filter"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ColumnFilterParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        selected = [c for c in (self.params.columns or []) if c in df.columns]
        if not selected:
            return {"df": df}
        if self.params.mode == "keep":
            return {"df": df[selected]}
        return {"df": df.drop(columns=selected)}


# --------------------------------------------------------------------------
# RowFilter
# --------------------------------------------------------------------------

_NUMERIC_OPS = {
    ">": lambda s, v: s > v,
    ">=": lambda s, v: s >= v,
    "<": lambda s, v: s < v,
    "<=": lambda s, v: s <= v,
    "==": lambda s, v: s == v,
    "!=": lambda s, v: s != v,
}


class RowFilterParams(NodeParams):
    """
    Parameters for RowFilter.

    Attributes:
        mode: "position" filters on row position (0-based); "value"
            filters on a column's value.
        position_op / position_value: e.g. ``position < 100``.
        column / value_op / value: e.g. ``price >= 9.99`` or
            ``city contains "port"``. ``value`` is parsed to the
            column's type at run time.
    """

    mode: Literal["position", "value"] = "position"

    position_op: Literal[">", ">=", "<", "<="] = visible_field(
        "<", visible_when=("mode", "position")
    )
    position_value: int = visible_field(0, visible_when=("mode", "position"))

    column: str = column_field(
        dtypes=("any",), default="", visible_when=("mode", "value")
    )
    value_op: str = reactive_choice_field(
        options="row_operators",
        depends_on="column",
        default="==",
        visible_when=("mode", "value"),
    )
    value: str = visible_field("", visible_when=("mode", "value"))


@register_node
class RowFilter(Node):
    """Keep rows matching a position rule or a column-value rule."""

    node_type = "row_filter"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = RowFilterParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import numpy as np
        import pandas as pd
        import pandas.api.types as pat

        df = inputs["df"]
        p = self.params

        if p.mode == "position":
            positions = np.arange(len(df))
            mask = _NUMERIC_OPS[p.position_op](positions, p.position_value)
            return {"df": df.iloc[np.flatnonzero(mask)]}

        if p.column not in df.columns:
            raise ValueError(f"row_filter: column {p.column!r} is not in the data")
        series = df[p.column]

        if p.value_op == "contains":
            mask = series.astype("string").str.contains(p.value, na=False, regex=False)
            return {"df": df[mask.fillna(False)]}

        raw = p.value
        if pat.is_numeric_dtype(series) and not pat.is_bool_dtype(series):
            target: Any = float(raw)
        elif pat.is_datetime64_any_dtype(series):
            target = pd.Timestamp(raw)
        elif pat.is_bool_dtype(series):
            target = raw.strip().lower() in ("true", "1", "yes")
        else:
            target = raw
        mask = _NUMERIC_OPS[p.value_op](series, target)
        return {"df": df[mask.fillna(False)]}


# --------------------------------------------------------------------------
# DtypeFilter
# --------------------------------------------------------------------------

_DTYPE_KINDS = ["str", "category", "numeric", "other"]


class DtypeFilterParams(NodeParams):
    """
    Parameters for DtypeFilter.

    Attributes:
        kinds: Keep only columns whose kind is ticked -- ``str``,
            ``category``, ``numeric``, or ``other`` (datetime, bool,
            geometry, ...). An empty selection is a pass-through.
    """

    kinds: list[str] | None = checkbox_list_field(choices=_DTYPE_KINDS, default=None)


def _column_kind(series: Any) -> str:
    import pandas as pd
    import pandas.api.types as pat

    if isinstance(series.dtype, pd.CategoricalDtype):
        return "category"
    if pat.is_bool_dtype(series):
        return "other"
    if pat.is_numeric_dtype(series):
        return "numeric"
    if pat.is_string_dtype(series.dtype) or series.dtype == object:
        return "str"
    return "other"


@register_node
class DtypeFilter(Node):
    """Keep only the columns whose dtype kind is selected."""

    node_type = "dtype_filter"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = DtypeFilterParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        kinds = set(self.params.kinds or [])
        if not kinds:
            return {"df": df}
        keep = [c for c in df.columns if _column_kind(df[c]) in kinds]
        return {"df": df[keep]}


# --------------------------------------------------------------------------
# FillNA
# --------------------------------------------------------------------------

_FILL_METHODS = [
    "forward fill",
    "backward fill",
    "mean",
    "median",
    "most frequent",
    "zero",
    "constant",
]


class FillNAParams(NodeParams):
    """
    Parameters for FillNA.

    Attributes:
        columns: Columns to fill (chosen via tickboxes). An empty
            selection is a pass-through.
        method: How to fill -- forward / backward fill, a summary
            statistic (mean / median / most frequent), zero, or a
            constant value.
        value: The constant to use when ``method`` is "constant".
    """

    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    method: Literal[
        "forward fill",
        "backward fill",
        "mean",
        "median",
        "most frequent",
        "zero",
        "constant",
    ] = "forward fill"
    value: str = visible_field("", visible_when=("method", "constant"))


def _coerce_fill_value(text: str, series: Any) -> Any:
    import pandas as pd
    import pandas.api.types as pat

    if pat.is_numeric_dtype(series) and not pat.is_bool_dtype(series):
        return float(text)
    if pat.is_datetime64_any_dtype(series):
        return pd.Timestamp(text)
    if pat.is_bool_dtype(series):
        return text.strip().lower() in ("true", "1", "yes")
    return text


@register_node
class FillNA(Node):
    """Fill missing values in the selected columns."""

    node_type = "fill_na"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = FillNAParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        columns = [c for c in (self.params.columns or []) if c in df.columns]
        if not columns:
            return {"df": df}

        method = self.params.method
        df = df.copy()
        for col in columns:
            series = df[col]
            if method == "forward fill":
                df[col] = series.ffill()
            elif method == "backward fill":
                df[col] = series.bfill()
            elif method in ("mean", "median"):
                if _column_kind(series) != "numeric":
                    raise ValueError(
                        f"fill_na: {method!r} needs a numeric column, but "
                        f"{col!r} is {series.dtype}"
                    )
                stat = series.mean() if method == "mean" else series.median()
                df[col] = series.fillna(stat)
            elif method == "most frequent":
                modes = series.mode(dropna=True)
                if len(modes):
                    df[col] = series.fillna(modes.iloc[0])
            elif method == "zero":
                df[col] = series.fillna(0)
            else:  # "constant"
                df[col] = series.fillna(_coerce_fill_value(self.params.value, series))
        return {"df": df}


# --------------------------------------------------------------------------
# Concat
# --------------------------------------------------------------------------


class ConcatParams(NodeParams):
    """
    Parameters for Concat.

    Attributes:
        axis: "rows" stacks df2 under df1; "columns" places it beside.
        join: "outer" keeps every label; "inner" keeps only labels
            present in both.
        reset_index: replace the result's index with a fresh 0..n-1.
    """

    axis: Literal["rows", "columns"] = "rows"
    join: Literal["outer", "inner"] = "outer"
    reset_index: bool = False


@register_node
class Concat(Node):
    """Concatenate two DataFrames."""

    node_type = "concat"
    category = "transform"
    inputs = [
        Port(name="df1", dtype="dataframe"),
        Port(name="df2", dtype="dataframe", required=False),
    ]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ConcatParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        df1 = inputs["df1"]
        df2 = inputs.get("df2")
        if df2 is None:
            return {"df": df1}

        result = pd.concat(
            [df1, df2],
            axis=0 if self.params.axis == "rows" else 1,
            join=self.params.join,
            ignore_index=self.params.reset_index,
        )
        return {"df": result}


# --------------------------------------------------------------------------
# Sample / Head / Tail
# --------------------------------------------------------------------------


class SampleParams(NodeParams):
    """
    Parameters for Sample.

    Attributes:
        mode: "count" draws ``n`` rows; "fraction" draws a share ``frac``.
        n / frac: how much to draw.
        replace: sample with replacement.
        random_state: seed, for a reproducible draw.
    """

    mode: Literal["count", "fraction"] = "count"
    n: int = visible_field(100, visible_when=("mode", "count"))
    frac: float = unit_interval_field(
        0.1, lo=0.0, hi=1.0, visible_when=("mode", "fraction")
    )
    replace: bool = False
    random_state: int = 0


@register_node
class Sample(Node):
    """Draw a random sample of rows."""

    node_type = "sample"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = SampleParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        p = self.params
        kwargs: dict[str, Any] = {
            "replace": p.replace,
            "random_state": p.random_state,
        }
        if p.mode == "fraction":
            kwargs["frac"] = p.frac
        else:
            kwargs["n"] = min(p.n, len(df)) if not p.replace else p.n
        return {"df": df.sample(**kwargs)}


class HeadParams(NodeParams):
    """Parameters for Head. ``n``: number of leading rows to keep."""

    n: int = 5


@register_node
class Head(Node):
    """Keep the first ``n`` rows."""

    node_type = "head"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = HeadParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {"df": inputs["df"].head(self.params.n)}


class TailParams(NodeParams):
    """Parameters for Tail. ``n``: number of trailing rows to keep."""

    n: int = 5


@register_node
class Tail(Node):
    """Keep the last ``n`` rows."""

    node_type = "tail"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = TailParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {"df": inputs["df"].tail(self.params.n)}


# --------------------------------------------------------------------------
# Sort
# --------------------------------------------------------------------------


class SortParams(NodeParams):
    """
    Parameters for Sort.

    Attributes:
        columns: Sort keys, in priority order (chosen via tickboxes).
            An empty selection is a pass-through.
        ascending: sort ascending (unchecked = descending), for all keys.
        na_position: put missing values "last" or "first".
    """

    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    ascending: bool = True
    na_position: Literal["last", "first"] = "last"


@register_node
class Sort(Node):
    """Sort rows by one or more columns."""

    node_type = "sort"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = SortParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        keys = [c for c in (self.params.columns or []) if c in df.columns]
        if not keys:
            return {"df": df}
        return {
            "df": df.sort_values(
                by=keys,
                ascending=self.params.ascending,
                na_position=self.params.na_position,
            )
        }


# --------------------------------------------------------------------------
# ResetIndex
# --------------------------------------------------------------------------


class ResetIndexParams(NodeParams):
    """
    Parameters for ResetIndex.

    Attributes:
        drop: discard the current index (checked) or turn it into a
            column (unchecked).
        index_name: name for that column, when the index is kept.
    """

    drop: bool = True
    index_name: str = visible_field("index", visible_when=("drop", "False"))


@register_node
class ResetIndex(Node):
    """Replace the index with a fresh 0..n-1 range."""

    node_type = "reset_index"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ResetIndexParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        if self.params.drop:
            return {"df": df.reset_index(drop=True)}
        out = df.reset_index(drop=False)
        name = (self.params.index_name or "").strip()
        if name and "index" in out.columns:
            out = out.rename(columns={"index": name})
        return {"df": out}


# --------------------------------------------------------------------------
# GroupBy
# --------------------------------------------------------------------------

_GROUP_METHODS = [
    "sum", "mean", "count", "min", "max", "median", "std", "size", "first", "last",
]
_GROUP_NUMERIC_ONLY = {"sum", "mean", "median", "std"}


class GroupByParams(NodeParams):
    """
    Parameters for GroupBy.

    Attributes:
        by: Key columns to group on (tickboxes). Empty = pass-through.
        method: A single reduction applied to every other column.
        dropna: drop groups whose key is missing.
    """

    by: list[str] | None = checkbox_list_field(source="columns", default=None)
    method: Literal[
        "sum", "mean", "count", "min", "max", "median", "std", "size", "first", "last"
    ] = "sum"
    dropna: bool = True


@register_node
class GroupBy(Node):
    """Group rows by key columns and reduce each other column with one function."""

    node_type = "group_by"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = GroupByParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        by = [c for c in (self.params.by or []) if c in df.columns]
        if not by:
            return {"df": df}

        grouped = df.groupby(by, dropna=self.params.dropna, as_index=False)
        method = self.params.method
        if method == "size":
            return {"df": grouped.size()}
        func = getattr(grouped, method)
        try:
            result = func(numeric_only=True) if method in _GROUP_NUMERIC_ONLY else func()
        except TypeError:
            result = func()
        return {"df": result}


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------

_AGG_FUNCTIONS = [
    "sum", "mean", "count", "min", "max", "median", "std", "var",
    "first", "last", "nunique",
]


class AggregateParams(NodeParams):
    """
    Parameters for Aggregate.

    Attributes:
        by: Optional group-key columns (tickboxes). Empty = aggregate
            the whole frame into a single row.
        columns: Columns to aggregate (tickboxes). Empty = every
            non-key column.
        functions: One or more aggregation functions (tickboxes). The
            output has one ``column_function`` column per pair.
    """

    by: list[str] | None = checkbox_list_field(source="columns", default=None)
    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    functions: list[str] | None = checkbox_list_field(
        choices=_AGG_FUNCTIONS, default=None
    )


def _flatten_agg_columns(columns: Any) -> list[str]:
    flat = []
    for col in columns:
        if isinstance(col, tuple):
            head, tail = col[0], col[1] if len(col) > 1 else ""
            flat.append(str(head) if tail in ("", None) else f"{head}_{tail}")
        else:
            flat.append(str(col))
    return flat


@register_node
class Aggregate(Node):
    """Aggregate columns with one or more functions, optionally per group."""

    node_type = "aggregate"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = AggregateParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        df = inputs["df"]
        functions = list(self.params.functions or [])
        if not functions:
            return {"df": df}

        by = [c for c in (self.params.by or []) if c in df.columns]
        columns = [
            c
            for c in (self.params.columns or [])
            if c in df.columns and c not in by
        ] or [c for c in df.columns if c not in by]
        spec = {c: functions for c in columns}

        if by:
            out = df.groupby(by, as_index=False).agg(spec)
            out.columns = _flatten_agg_columns(out.columns)
            return {"df": out}

        aggregated = df[columns].agg(functions)
        row: dict[str, Any] = {}
        for c in columns:
            for f in functions:
                if isinstance(aggregated, pd.Series):  # single function
                    row[f"{c}_{f}"] = [aggregated[c]]
                else:
                    row[f"{c}_{f}"] = [aggregated.loc[f, c]]
        return {"df": pd.DataFrame(row)}


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------


class MergeParams(NodeParams):
    """
    Parameters for Merge (SQL-style join).

    Attributes:
        on: Key column(s) present in both frames (tickboxes). Empty =
            join on the row index.
        how: join type -- inner / left / right / outer.
        suffix_left / suffix_right: appended to overlapping non-key
            column names.
    """

    on: list[str] | None = checkbox_list_field(source="columns", default=None)
    how: Literal["inner", "left", "right", "outer"] = "inner"
    suffix_left: str = "_x"
    suffix_right: str = "_y"


@register_node
class Merge(Node):
    """Join two DataFrames on key columns (or on the index)."""

    node_type = "merge"
    category = "transform"
    inputs = [
        Port(name="df1", dtype="dataframe"),
        Port(name="df2", dtype="dataframe"),
    ]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = MergeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        left = inputs["df1"]
        right = inputs["df2"]
        p = self.params
        keys = [c for c in (p.on or []) if c in left.columns and c in right.columns]
        kwargs = dict(how=p.how, suffixes=(p.suffix_left, p.suffix_right))
        if keys:
            return {"df": pd.merge(left, right, on=keys, **kwargs)}
        return {
            "df": pd.merge(left, right, left_index=True, right_index=True, **kwargs)
        }


# --------------------------------------------------------------------------
# Pivot / Unpivot / PivotTable
# --------------------------------------------------------------------------


def _flatten_columns(columns: Any) -> list[str]:
    """Join any MultiIndex column tuple into a single ``a_b_c`` string."""
    flat = []
    for col in columns:
        if isinstance(col, tuple):
            parts = [str(p) for p in col if p not in ("", None)]
            flat.append("_".join(parts) if parts else "")
        else:
            flat.append(str(col))
    return flat


class PivotParams(NodeParams):
    """
    Parameters for Pivot (``DataFrame.pivot`` -- no aggregation).

    Attributes:
        index: Column(s) whose values become the new row labels.
        columns: Column(s) whose values become the new column headers.
        values: Column(s) to fill the cells with (empty = every
            remaining column). The result is flattened and its index
            reset so the pivot keys come back as plain columns.
    """

    index: list[str] | None = checkbox_list_field(source="columns", default=None)
    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    values: list[str] | None = checkbox_list_field(source="columns", default=None)


@register_node
class Pivot(Node):
    """Reshape long -> wide with unique index/column pairs (no aggregation)."""

    node_type = "pivot"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = PivotParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        index = [c for c in (self.params.index or []) if c in df.columns]
        columns = [c for c in (self.params.columns or []) if c in df.columns]
        if not index or not columns:
            return {"df": df}
        values = [c for c in (self.params.values or []) if c in df.columns] or None

        try:
            result = df.pivot(
                index=index if len(index) > 1 else index[0],
                columns=columns if len(columns) > 1 else columns[0],
                values=values if not values or len(values) > 1 else values[0],
            )
        except ValueError as exc:
            raise ValueError(
                f"pivot: index/columns pairs are not unique -- use pivot_table "
                f"to aggregate the duplicates instead ({exc})"
            ) from exc

        result = result.reset_index()
        result.columns = _flatten_columns(result.columns)
        return {"df": result}


class UnpivotParams(NodeParams):
    """
    Parameters for Unpivot (``DataFrame.melt``).

    Attributes:
        id_vars: Columns kept as identifiers (empty = none).
        value_vars: Columns to unpivot into rows (empty = every
            non-id column).
        var_name / value_name: names for the two produced columns.
    """

    id_vars: list[str] | None = checkbox_list_field(source="columns", default=None)
    value_vars: list[str] | None = checkbox_list_field(source="columns", default=None)
    var_name: str = "variable"
    value_name: str = "value"


@register_node
class Unpivot(Node):
    """Reshape wide -> long (melt)."""

    node_type = "unpivot"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = UnpivotParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"]
        id_vars = [c for c in (self.params.id_vars or []) if c in df.columns] or None
        value_vars = [c for c in (self.params.value_vars or []) if c in df.columns] or None
        return {
            "df": df.melt(
                id_vars=id_vars,
                value_vars=value_vars,
                var_name=self.params.var_name or "variable",
                value_name=self.params.value_name or "value",
            )
        }


_PIVOT_TABLE_FUNCTIONS = ["mean", "sum", "count", "min", "max", "median", "std"]


class PivotTableParams(NodeParams):
    """
    Parameters for PivotTable (``pandas.pivot_table`` -- with aggregation).

    Attributes:
        index / columns: pivot keys (tickboxes). At least one is needed.
        values: columns to aggregate (empty = every numeric column).
        functions: one or more aggregations (tickboxes); each adds its
            own set of value columns.
        fill_value: value for empty cells (blank = leave NaN).
        margins: add an "All" totals row and column.
        dropna: drop columns whose entries are all NaN.
        observed: for categorical keys, only keep combinations that
            occur in the data.
    """

    index: list[str] | None = checkbox_list_field(source="columns", default=None)
    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    values: list[str] | None = checkbox_list_field(source="columns", default=None)
    functions: list[str] | None = checkbox_list_field(
        choices=_PIVOT_TABLE_FUNCTIONS, default=None
    )
    fill_value: str = ""
    margins: bool = False
    dropna: bool = True
    observed: bool = False


@register_node
class PivotTable(Node):
    """Cross-tabulate and aggregate (long -> wide, with a reduction)."""

    node_type = "pivot_table"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = PivotTableParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        df = inputs["df"]
        p = self.params
        index = [c for c in (p.index or []) if c in df.columns]
        columns = [c for c in (p.columns or []) if c in df.columns]
        if not index and not columns:
            return {"df": df}
        values = [c for c in (p.values or []) if c in df.columns] or None
        functions = list(p.functions or []) or ["mean"]

        raw_fill = (p.fill_value or "").strip()
        if not raw_fill:
            fill_value: Any = None
        else:
            try:
                fill_value = float(raw_fill)
            except ValueError:
                fill_value = raw_fill

        result = pd.pivot_table(
            df,
            index=index or None,
            columns=columns or None,
            values=values,
            aggfunc=functions if len(functions) > 1 else functions[0],
            fill_value=fill_value,
            margins=p.margins,
            dropna=p.dropna,
            observed=p.observed,
        )

        if index:
            result = result.reset_index()
        result.columns = _flatten_columns(result.columns)
        return {"df": result}


class BinParams(NodeParams):
    """
    Parameters for Bin.

    Attributes:
        column: Numeric column to group into bins.
        output_name: Name of the new column (blank -> "<column>_bin").
        method: How the cut points are chosen -- "equal_width" splits
            the value range into equal intervals, "quantile" makes
            equal-count bins, "explicit" uses the cutoff points typed
            into ``cut_points``.
        bin_count: Number of bins for the equal_width / quantile methods.
        cut_points: Cutoff points for the "explicit" method, separated
            by semicolons (e.g. ``10; 20; 30``). Values up to and
            including the first cutoff go in the first bin, values above
            the last cutoff in the last bin -- so n cutoffs make n+1
            bins.
        output_type: dtype of the new column -- "category" (interval
            labels), "bool" (only for 2 bins: lower=False, upper=True),
            "integer" (0-based bin index) or "string" (the names typed
            into ``labels``).
        labels: Comma-separated names for the bins, used when
            ``output_type`` is "string" (must match the bin count).
    """

    column: str = column_field(dtypes=("numeric",), description="Numeric column to bin.")
    output_name: str = ""
    method: Literal["equal_width", "quantile", "explicit"] = "equal_width"
    bin_count: int = visible_field(
        4, visible_unless=("method", "explicit"), description="Number of bins."
    )
    cut_points: str = visible_field(
        "",
        visible_when=("method", "explicit"),
        description="Cutoff points separated by semicolons, e.g. '10; 20; 30' "
        "(n cutoffs -> n+1 bins).",
    )
    output_type: Literal["category", "bool", "integer", "string"] = "category"
    labels: str = visible_field(
        "",
        visible_when=("output_type", "string"),
        description="Comma-separated bin names, one per bin.",
    )


@register_node
class Bin(Node):
    """Group a numeric column's values into a new categorical column."""

    node_type = "bin"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = BinParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        p = self.params
        df = inputs["df"]
        if p.column not in df.columns:
            raise ValueError(f"Bin: column {p.column!r} is not in the input data.")

        series = pd.to_numeric(df[p.column], errors="coerce")

        if p.method == "explicit":
            tokens = [v.strip() for v in p.cut_points.split(";") if v.strip()]
            try:
                cutoffs = sorted({float(v) for v in tokens})
            except ValueError:
                raise ValueError(
                    f"Bin: could not read cutoff points {p.cut_points!r}; separate "
                    f"them with semicolons, e.g. '10; 20; 30'."
                ) from None
            if not cutoffs:
                raise ValueError("Bin: 'explicit' method needs at least one cutoff point.")
            # A cutoff at x sends values <= x to the bin on its left; the
            # open ends catch everything below / above the given points.
            binned = pd.cut(series, bins=[float("-inf"), *cutoffs, float("inf")])
        elif p.method == "quantile":
            binned = pd.qcut(series, q=max(int(p.bin_count), 2), duplicates="drop")
        else:  # equal_width
            binned = pd.cut(series, bins=max(int(p.bin_count), 2))

        binned = pd.Categorical(binned, ordered=True)
        n_bins = len(binned.categories)
        codes = pd.Series(binned.codes, index=df.index)

        if p.output_type == "bool":
            if n_bins != 2:
                raise ValueError(f"Bin: 'bool' output needs exactly 2 bins, got {n_bins}.")
            result = codes.map({0: False, 1: True}).astype("boolean")
        elif p.output_type == "integer":
            result = codes.where(codes >= 0).astype("Int64")
        else:
            if p.output_type == "string":
                names = [
                    s.strip() for s in p.labels.replace(";", ",").split(",") if s.strip()
                ]
                if len(names) != n_bins:
                    raise ValueError(
                        f"Bin: 'string' output needs {n_bins} names in 'labels', "
                        f"got {len(names)}."
                    )
            else:  # category -- readable interval labels, kept in bin order
                names = [str(c) for c in binned.categories]
            result = pd.Categorical.from_codes(binned.codes, categories=names, ordered=True)

        out_name = (p.output_name or "").strip() or f"{p.column}_bin"
        out = df.copy()
        out[out_name] = result
        return {"df": out}


class RenameCategoriesParams(NodeParams):
    """
    Parameters for RenameCategories.

    Attributes:
        column: The categorical / boolean column to relabel.
        renames: JSON ``{old category: new name}`` mapping, edited in
            the Options panel as a table of the column's distinct
            values. Any value left blank keeps its old name; two old
            values mapped to the same new name are merged.
    """

    column: str = column_field(
        dtypes=("categorical", "boolean"), description="Column whose categories to rename."
    )
    renames: str = category_map_field(
        column="column",
        default="{}",
        description="Map of old category -> new name (blank keeps the old name).",
    )


@register_node
class RenameCategories(Node):
    """Relabel the categories of a categorical column."""

    node_type = "rename_categories"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = RenameCategoriesParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import json

        import pandas as pd

        p = self.params
        df = inputs["df"]
        if p.column not in df.columns:
            raise ValueError(
                f"RenameCategories: column {p.column!r} is not in the input data."
            )

        try:
            raw = json.loads(p.renames or "{}")
        except (ValueError, TypeError):
            raw = {}
        mapping = {
            str(old): str(new).strip()
            for old, new in raw.items()
            if str(new).strip() and str(new).strip() != str(old)
        }
        if not mapping:
            return {"df": df}

        out = df.copy()
        was_category = str(out[p.column].dtype) == "category"
        remapped = out[p.column].astype("object").map(
            lambda v: mapping.get(str(v), v) if pd.notna(v) else v
        )
        if was_category:
            ordered = [v for v in pd.unique(remapped) if pd.notna(v)]
            out[p.column] = pd.Categorical(remapped, categories=ordered)
        else:
            out[p.column] = remapped
        return {"df": out}


# --------------------------------------------------------------------------
# Categorical encoders (one-hot / ordinal)
# --------------------------------------------------------------------------


def _categorical_columns(df: Any) -> list[str]:
    """Non-numeric, non-bool, non-datetime columns of ``df`` (object /
    string / category)."""
    from pandas.api.types import (
        is_bool_dtype,
        is_datetime64_any_dtype,
        is_numeric_dtype,
    )

    out: list[str] = []
    for name, dtype in df.dtypes.items():
        if (
            is_bool_dtype(dtype)
            or is_numeric_dtype(dtype)
            or is_datetime64_any_dtype(dtype)
        ):
            continue
        out.append(str(name))
    return out


class OneHotEncodeParams(NodeParams):
    """
    Parameters for OneHotEncode.

    Attributes:
        columns: Columns to encode (tickboxes). Empty = every
            object / string / category column.
        drop_first: Drop the first level of each column (k-1 dummies),
            to avoid collinearity.
        replace: Replace the original columns with the dummy columns;
            if off, the dummies are added alongside the originals.
    """

    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    drop_first: bool = False
    replace: bool = True


@register_node
class OneHotEncode(Node):
    """
    One-hot (dummy) encode categorical columns into 0/1 indicator
    columns named ``<column>_<value>``.

    Fitted on whatever DataFrame it receives (stateless, like
    ``standard_scaler``); ``handle_unknown='ignore'`` so it never
    raises on an unseen value.
    """

    node_type = "one_hot_encode"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = OneHotEncodeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd
        from sklearn.preprocessing import OneHotEncoder

        p = self.params
        df = inputs["df"]
        cols = [c for c in (p.columns or []) if c in df.columns]
        if not cols:
            cols = _categorical_columns(df)
        if not cols:
            return {"df": df}

        encoder = OneHotEncoder(
            handle_unknown="ignore",
            drop="first" if p.drop_first else None,
            sparse_output=False,
            dtype=int,
        )
        matrix = encoder.fit_transform(df[cols])
        dummies = pd.DataFrame(
            matrix,
            columns=encoder.get_feature_names_out(cols),
            index=df.index,
        )
        base = df.drop(columns=cols) if p.replace else df
        return {"df": pd.concat([base, dummies], axis=1)}


class OrdinalEncodeParams(NodeParams):
    """
    Parameters for OrdinalEncode.

    Attributes:
        columns: Columns to encode (tickboxes). Empty = every
            object / string / category column.
        replace: Replace the original columns with the integer codes;
            if off, ``<column>_ordinal`` columns are added alongside.
    """

    columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    replace: bool = True


@register_node
class OrdinalEncode(Node):
    """
    Ordinal-encode categorical columns to integer codes (0-based,
    categories in sorted order). Fitted on whatever DataFrame it
    receives (stateless); an unseen value would map to ``-1``.
    """

    node_type = "ordinal_encode"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = OrdinalEncodeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd
        from sklearn.preprocessing import OrdinalEncoder

        p = self.params
        df = inputs["df"]
        cols = [c for c in (p.columns or []) if c in df.columns]
        if not cols:
            cols = _categorical_columns(df)
        if not cols:
            return {"df": df}

        encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
        codes = encoder.fit_transform(df[cols])

        out = df.copy()
        for i, col in enumerate(cols):
            series = pd.Series(codes[:, i], index=df.index).astype("Int64")
            out[col if p.replace else f"{col}_ordinal"] = series
        return {"df": out}


# --------------------------------------------------------------------------
# Datetime: combine parts -> datetime / split datetime -> parts / resample
# --------------------------------------------------------------------------

#: Time components the combine / split nodes understand, coarse -> fine.
_DT_COMPONENTS = [
    "year", "quarter", "month", "week", "dayofyear", "day",
    "hour", "minute", "second", "microsecond",
]

#: A few common target frequencies for the resample node's ``rule``.
_RESAMPLE_RULES = ["YS", "QS", "MS", "W", "D", "h", "30min", "15min", "min", "s"]


class CombineDatetimeParams(NodeParams):
    """
    Parameters for CombineDatetime.

    Attributes:
        mapping: JSON ``{component: column}`` -- link each time part
            (year / month / day / hour / ...) to a dataframe column. A
            single mapped column that is *text* is parsed whole (using
            ``datetime_format``); several numeric columns are assembled.
        datetime_format: strptime pattern, used only when the single
            mapped source column is text.
        output_column: Name of the produced datetime column.
        replace: Drop the mapped source columns (default: keep them).
    """

    mapping: str = column_map_field(
        keys=_DT_COMPONENTS,
        default="{}",
        description="Link each time component to a column (blank = unused).",
    )
    datetime_format: str = suggestions_field(
        suggestions=_COMMON_DATETIME_FORMATS, default="",
        description="strptime format for a single text source column.",
    )
    output_column: str = "datetime"
    replace: bool = False


@register_node
class CombineDatetime(Node):
    """Build a datetime column from separate time-component columns."""

    node_type = "combine_datetime"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = CombineDatetimeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import json

        import pandas as pd
        from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

        p = self.params
        df = inputs["df"]
        try:
            raw = json.loads(p.mapping or "{}")
        except (ValueError, TypeError):
            raw = {}
        mapping = {
            k: v
            for k, v in raw.items()
            if k in _DT_COMPONENTS and isinstance(v, str) and v in df.columns
        }
        if not mapping:
            return {"df": df}

        out = df.copy()
        out_name = p.output_column or "datetime"

        # Single non-numeric source column -> parse it directly.
        if len(mapping) == 1:
            (col,) = mapping.values()
            if is_datetime64_any_dtype(df[col]):
                result = df[col]
            elif not is_numeric_dtype(df[col]):
                result = pd.to_datetime(
                    df[col], format=(p.datetime_format or None), errors="coerce"
                )
            else:
                result = self._assemble(df, mapping)
        else:
            result = self._assemble(df, mapping)

        out[out_name] = result
        if p.replace:
            drop = [c for c in set(mapping.values()) if c != out_name and c in out.columns]
            out = out.drop(columns=drop)
        return {"df": out}

    @staticmethod
    def _assemble(df: Any, mapping: dict[str, str]) -> Any:
        import pandas as pd

        def num(component: str) -> Any:
            return pd.to_numeric(df[mapping[component]], errors="coerce")

        if "year" not in mapping:
            raise ValueError(
                "combine_datetime: assembling from parts needs at least a 'year' column."
            )
        year = num("year").round().astype("Int64")

        if "dayofyear" in mapping:
            doy = num("dayofyear").round()
            base = pd.to_datetime(
                {"year": year, "month": 1, "day": 1}
            ) + pd.to_timedelta(doy - 1, unit="D")
        elif "week" in mapping:
            week = num("week").round().astype("Int64")
            base = pd.to_datetime(
                year.astype(str) + "-W" + week.astype(str).str.zfill(2) + "-1",
                format="%G-W%V-%u", errors="coerce",
            )
        else:
            month = (
                (num("quarter").round() - 1) * 3 + 1
                if "quarter" in mapping and "month" not in mapping
                else (num("month") if "month" in mapping else pd.Series(1, index=df.index))
            )
            day = num("day") if "day" in mapping else pd.Series(1, index=df.index)
            base = pd.to_datetime(
                {
                    "year": year,
                    "month": month.round().astype("Int64"),
                    "day": day.round().astype("Int64"),
                },
                errors="coerce",
            )

        seconds = pd.Series(0.0, index=df.index)
        for component, factor in (("hour", 3600), ("minute", 60), ("second", 1)):
            if component in mapping:
                seconds = seconds + num(component).fillna(0) * factor
        result = base + pd.to_timedelta(seconds, unit="s")
        if "microsecond" in mapping:
            result = result + pd.to_timedelta(num("microsecond").fillna(0), unit="us")
        return result


_SPLIT_PARTS = [
    "year", "quarter", "month", "week", "dayofyear", "day", "dayofweek",
    "hour", "minute", "second",
]


class SplitDatetimeParams(NodeParams):
    """
    Parameters for SplitDatetime.

    Attributes:
        column: The datetime column to break apart.
        mode: "components" adds one integer column per ticked part
            (``<column>_<part>``); "string" adds one text column
            ``<column>_str`` via strftime.
        parts: Which components to extract (components mode).
        datetime_format: strftime pattern (string mode).
        replace: Drop the source datetime column (default: keep it).
    """

    column: str = column_field(dtypes=("datetime",))
    mode: Literal["components", "string"] = "components"
    parts: list[str] | None = checkbox_list_field(
        choices=_SPLIT_PARTS, default=["year", "month", "day"],
        visible_when=("mode", "components"),
    )
    datetime_format: str = visible_field(
        "%Y-%m-%d", visible_when=("mode", "string")
    )
    replace: bool = False


@register_node
class SplitDatetime(Node):
    """Break a datetime column into component columns (or a formatted string)."""

    node_type = "split_datetime"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = SplitDatetimeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        p = self.params
        df = inputs["df"]
        if p.column not in df.columns:
            raise ValueError(f"split_datetime: column {p.column!r} is not in the data.")
        series = pd.to_datetime(df[p.column], errors="coerce")
        out = df.copy()

        if p.mode == "string":
            out[f"{p.column}_str"] = series.dt.strftime(p.datetime_format or "%Y-%m-%d")
        else:
            parts = [x for x in (p.parts or []) if x in _SPLIT_PARTS]
            if not parts:
                return {"df": df}
            for part in parts:
                if part == "week":
                    values = series.dt.isocalendar().week
                else:
                    values = getattr(series.dt, part)
                out[f"{p.column}_{part}"] = pd.Series(values, index=df.index).astype("Int64")

        if p.replace:
            out = out.drop(columns=[p.column])
        return {"df": out}


class ResampleDatetimeParams(NodeParams):
    """
    Parameters for ResampleDatetime.

    Attributes:
        datetime_column: The datetime column used as the resampling key.
        rule: Target frequency (pandas offset alias, e.g. ``D`` / ``W``
            / ``MS`` / ``h`` / ``15min``).
        agg: Down-sampling aggregation applied to numeric columns
            (non-numeric columns take the first value in the bin).
        fill: Up-sampling fill for the gaps a finer rule creates.
    """

    datetime_column: str = column_field(dtypes=("datetime",))
    rule: str = suggestions_field(suggestions=_RESAMPLE_RULES, default="D")
    agg: Literal[
        "mean", "sum", "median", "min", "max", "first", "last", "count", "ohlc"
    ] = "mean"
    fill: Literal[
        "none", "ffill", "bfill", "interpolate_linear", "interpolate_time", "nearest"
    ] = "none"


@register_node
class ResampleDatetime(Node):
    """Resample the rows to a target frequency on a datetime key column."""

    node_type = "resample_datetime"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ResampleDatetimeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        p = self.params
        df = inputs["df"]
        if p.datetime_column not in df.columns:
            raise ValueError(
                f"resample_datetime: column {p.datetime_column!r} is not in the data."
            )
        rule = p.rule or "D"
        key = pd.to_datetime(df[p.datetime_column], errors="coerce")
        work = df.drop(columns=[p.datetime_column]).copy()
        work.index = pd.DatetimeIndex(key)
        work = work[work.index.notna()].sort_index()
        if work.empty:
            raise ValueError("resample_datetime: no valid datetime values to resample on.")

        numeric = work.select_dtypes(include="number")
        other = work.drop(columns=list(numeric.columns))

        if p.agg in ("first", "last", "count"):
            res = getattr(work.resample(rule), p.agg)()
        elif p.agg == "ohlc":
            ohlc = numeric.resample(rule).ohlc()
            ohlc.columns = [f"{col}_{field}" for col, field in ohlc.columns]
            res = pd.concat([ohlc, other.resample(rule).first()], axis=1)
        else:
            agg_numeric = getattr(numeric.resample(rule), p.agg)()
            res = pd.concat([agg_numeric, other.resample(rule).first()], axis=1)

        if p.fill == "ffill":
            res = res.ffill()
        elif p.fill == "bfill":
            res = res.bfill()
        elif p.fill == "nearest":
            res = res.interpolate(method="nearest")
        elif p.fill == "interpolate_linear":
            res = res.interpolate(method="linear")
        elif p.fill == "interpolate_time":
            res = res.interpolate(method="time")

        return {"df": res.reset_index(names=p.datetime_column)}


# --------------------------------------------------------------------------
# Diff (time-series row-order difference)
# --------------------------------------------------------------------------


class DiffParams(NodeParams):
    """
    Parameters for Diff.

    Attributes:
        columns: Numeric columns to difference. Blank (default) = every
            numeric column.
        lags: Comma-separated period(s) to diff over, e.g. ``1`` or
            ``1, 7, 30``. Each produces one ``<column>_diff_<lag>``
            column (``Series.diff(periods=lag)``; a negative lag looks
            forward instead of back). Assumes the rows are already
            ordered by time (see the ``sort`` node) -- this is a plain
            row-order difference, not aware of any datetime column.
        replace: Drop the source columns, keeping only the diff columns.
    """

    columns: list[str] | None = column_field(dtypes=("numeric",), default=None)
    lags: str = "1"
    replace: bool = False


@register_node
class Diff(Node):
    """Row-order difference of numeric columns (e.g. a time series already sorted by time)."""

    node_type = "diff"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = DiffParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import pandas as pd

        p = self.params
        df = inputs["df"].copy()
        columns = p.columns or df.select_dtypes(include="number").columns.tolist()
        missing = [c for c in columns if c not in df.columns]
        if missing:
            raise ValueError(f"diff: column(s) not found in the input data: {missing}")

        try:
            lags = [int(v.strip()) for v in p.lags.split(",") if v.strip()]
        except ValueError:
            raise ValueError(
                f"diff: could not read lags {p.lags!r}; separate them with commas, "
                f"e.g. '1, 7'."
            ) from None
        if not lags:
            raise ValueError("diff: at least one lag is required.")

        for column in columns:
            series = pd.to_numeric(df[column], errors="coerce")
            for lag in lags:
                df[f"{column}_diff_{lag}"] = series.diff(periods=lag)

        if p.replace:
            df = df.drop(columns=columns)
        return {"df": df}


# --------------------------------------------------------------------------
# CustomOperation (user-written Python against the DataFrame)
# --------------------------------------------------------------------------

#: Builtins left available inside a ``custom_operation`` node's code --
#: everything else (``import``, ``open``, ``exec``, ``eval``, ...) is
#: not, so a typo or a pasted snippet can't reach the filesystem or the
#: network by accident. This is a light guard rail, not a security
#: sandbox: the app runs locally and the code is the user's own.
_CUSTOM_OPERATION_BUILTINS = (
    "abs", "all", "any", "bool", "dict", "enumerate", "filter", "float",
    "int", "len", "list", "map", "max", "min", "range", "reversed",
    "round", "set", "sorted", "str", "sum", "tuple", "zip",
)

#: ``math`` functions/constants bound by name alongside ``pd`` / ``np``.
#: Kept in sync with ``ui.options_panel.OptionsPanel._CODE_HINT_GLOBALS``,
#: the hint shown under the code editor.
_CUSTOM_OPERATION_MATH_NAMES = (
    "exp", "log", "log2", "log10", "sqrt", "sin", "cos", "tan",
    "floor", "ceil", "pi", "e",
)


class CustomOperationParams(NodeParams):
    """
    Parameters for CustomOperation.

    Attributes:
        code: Python statements run against the input DataFrame, bound
            to the name ``df`` -- mutate it in place or reassign it,
            e.g. ``df['b'] = df['a'] / np.exp(df['c'])``. ``pd``
            (pandas), ``np`` (numpy) and the common ``math`` functions
            (exp, log, log2, log10, sqrt, sin, cos, tan, floor, ceil,
            pi, e) are already available by name; a reduced builtins
            set is used (no import / open / exec / eval) as a light
            guard rail, not a security sandbox.
    """

    code: str = code_field(default="")


@register_node
class CustomOperation(Node):
    """Run user-written Python against the input DataFrame (bound as ``df``)."""

    node_type = "custom_operation"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = CustomOperationParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import builtins
        import math

        import numpy as np
        import pandas as pd

        code = self.params.code
        df = inputs["df"]
        if not code.strip():
            return {"df": df}

        namespace: dict[str, Any] = {
            "__builtins__": {n: getattr(builtins, n) for n in _CUSTOM_OPERATION_BUILTINS},
            "df": df.copy(),
            "pd": pd,
            "np": np,
            **{n: getattr(math, n) for n in _CUSTOM_OPERATION_MATH_NAMES},
        }
        try:
            exec(compile(code, "<custom_operation>", "exec"), namespace)  # noqa: S102
        except SyntaxError as exc:
            raise ValueError(f"custom_operation: syntax error - {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
            raise ValueError(f"custom_operation: {type(exc).__name__}: {exc}") from exc

        result = namespace.get("df")
        if not isinstance(result, pd.DataFrame):
            got = "nothing" if result is None else type(result).__name__
            raise ValueError(
                f"custom_operation: 'df' must still be a DataFrame after your code "
                f"runs (got {got})."
            )
        return {"df": result}
