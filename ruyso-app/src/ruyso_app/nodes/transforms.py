"""
Data cleaning / transformation nodes: take a DataFrame in, produce a
modified DataFrame out. Each node performs a single, well-defined
transformation so pipelines stay easy to read and to compose.
"""

from typing import Any, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    checkbox_list_field,
    column_field,
    reactive_choice_field,
    visible_field,
)
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


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
        errors: "raise" fails on an un-convertible value; "coerce"
            turns it into NaN/NaT (numeric / datetime targets only).
    """

    column: str = column_field(dtypes=("any",))
    target_type: str = reactive_choice_field(
        options="cast_types", depends_on="column", default="str"
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
            df[col] = pd.to_datetime(series, errors=errors)
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
