"""
Summarising a step's output table for the Table tab's "Table
description" panel.

Pure, UI-free logic (only pandas, which the engine already requires),
so it is covered by headless tests. ``describe_table`` accepts anything
DataFrame-shaped; geopandas / time-indexed frames are recognised by
duck typing so no optional dependency is imported here.

The result splits the columns into two groups the panel renders as
small tables:

* **numeric** -- number dtypes and datetime columns: variable, type,
  mean, std. dev, min, max;
* **categorical** -- everything else (object / string / category /
  bool / timedelta): variable, type, number of distinct values.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

#: The four table kinds the spec asks the panel to distinguish.
PLAIN = "dataframe"
GEO = "geo-dataframe"
TIME = "time-indexed dataframe"
GEO_TIME = "geo-dataframe + time"


@dataclass(frozen=True)
class NumericVar:
    """One row of the numeric-variables table (values pre-formatted)."""

    name: str
    dtype: str
    mean: str
    std: str
    minimum: str
    maximum: str


@dataclass(frozen=True)
class CategoricalVar:
    """One row of the string / categorical variables table."""

    name: str
    dtype: str
    n_distinct: int


@dataclass(frozen=True)
class TableDescription:
    """Everything the description panel shows about one table."""

    table_type: str
    n_rows: int
    n_variables: int
    n_missing: int
    numeric_vars: list[NumericVar]
    categorical_vars: list[CategoricalVar]


def looks_like_dataframe(value: object) -> bool:
    """Duck-type check for a pandas(-like) DataFrame."""
    return hasattr(value, "columns") and hasattr(value, "dtypes") and hasattr(value, "iloc")


def _table_type(df: object) -> str:
    is_geo = type(df).__name__ == "GeoDataFrame" or "geometry" in list(df.columns)
    index_type = type(getattr(df, "index", None)).__name__
    is_time = index_type in ("DatetimeIndex", "PeriodIndex", "TimedeltaIndex")
    if is_geo and is_time:
        return GEO_TIME
    if is_geo:
        return GEO
    if is_time:
        return TIME
    return PLAIN


def _fmt(getter) -> str:
    """Run ``getter`` and format its result; return an em dash on failure."""
    try:
        value = getter()
    except (TypeError, ValueError):
        return "—"
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def describe_table(df: object) -> TableDescription:
    """
    Build a :class:`TableDescription` for ``df``.

    Missing values counts NaN/None cells plus empty-string cells in
    any column ("valeurs manquantes / vides" in the spec).
    """
    columns = list(df.columns)

    # Iterate by position, not label: a DataFrame can have duplicate
    # column names (e.g. after a column-wise concat), in which case
    # ``df[label]`` returns a DataFrame rather than a Series.
    n_missing = int(df.isna().sum().sum())
    for i in range(len(columns)):
        try:
            n_missing += int((df.iloc[:, i] == "").sum())
        except (TypeError, ValueError):
            pass

    numeric_vars: list[NumericVar] = []
    categorical_vars: list[CategoricalVar] = []
    for i, col in enumerate(columns):
        series = df.iloc[:, i]
        dtype_name = str(series.dtype)
        if not is_bool_dtype(series) and (
            is_numeric_dtype(series) or is_datetime64_any_dtype(series)
        ):
            numeric_vars.append(
                NumericVar(
                    name=str(col),
                    dtype=dtype_name,
                    mean=_fmt(series.mean),
                    std=_fmt(series.std),
                    minimum=_fmt(series.min),
                    maximum=_fmt(series.max),
                )
            )
        else:
            categorical_vars.append(
                CategoricalVar(
                    name=str(col),
                    dtype=dtype_name,
                    n_distinct=int(series.nunique(dropna=True)),
                )
            )

    return TableDescription(
        table_type=_table_type(df),
        n_rows=int(len(df.index)),
        n_variables=len(columns),
        n_missing=n_missing,
        numeric_vars=numeric_vars,
        categorical_vars=categorical_vars,
    )
