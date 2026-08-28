"""
Resolving and validating column-reference parameters in the Options
panel.

A parameter marked with ``core.params.column_field`` names one or more
columns of the node's input DataFrame. This module figures out which
columns are actually available (from the last run's outputs, following
the node's dataframe input wires) and classifies each parameter value
as OK / unknown column / unsupported type.
"""

from __future__ import annotations

from NodeGraphQt import BaseNode
from pandas.api.types import (
    is_bool_dtype,
    is_datetime64_any_dtype,
    is_numeric_dtype,
)

#: Column-kind names, matching core.params.COLUMN_DTYPE_KINDS.
NUMERIC = "numeric"
DATETIME = "datetime"
BOOLEAN = "boolean"
CATEGORICAL = "categorical"

#: Validation outcomes.
OK = None
UNKNOWN_COLUMN = "unknown_column"
UNSUPPORTED_TYPE = "unsupported_type"

#: Port dtypes whose values carry named columns.
_TABLE_DTYPES = frozenset({"dataframe", "geodataframe"})


def dtype_kind(dtype: object) -> str:
    """Map a pandas dtype to one of the column-kind names."""
    if is_bool_dtype(dtype):
        return BOOLEAN
    if is_datetime64_any_dtype(dtype):
        return DATETIME
    if is_numeric_dtype(dtype):
        return NUMERIC
    return CATEGORICAL


def kind_accepted(accepted: list[str] | None, kind: str) -> bool:
    """Whether ``kind`` satisfies an ``accepted`` list (``"any"`` allows all)."""
    if not accepted or "any" in accepted:
        return True
    return kind in accepted


def _columns_of(df: object) -> dict[str, str] | None:
    if df is None or not hasattr(df, "columns") or not hasattr(df, "dtypes"):
        return None
    return {str(name): dtype_kind(dtype) for name, dtype in df.dtypes.items()}


def input_dataframe_columns(
    node: BaseNode, outputs: dict[str, dict]
) -> dict[str, str] | None:
    """
    ``{column name: column kind}`` available to ``node``'s column params.

    For a node with a table input this is the upstream table's columns;
    for a *source* node (a loader, no table inputs) it is that node's
    own last-run output columns -- so a loader's ``datetime_columns``
    picker fills in once the file has been read. ``None`` when nothing
    is available yet, so the caller offers free text with no validation.
    """
    core_cls = getattr(type(node), "CORE_NODE_CLASS", None)
    if core_cls is None:
        return None

    table_inputs = [
        p for p in core_cls.inputs if getattr(p, "dtype", None) in _TABLE_DTYPES
    ]
    if table_inputs:
        columns: dict[str, str] = {}
        found = False
        for port in table_inputs:
            canvas_port = node.inputs().get(port.name)
            if canvas_port is None:
                continue
            for connected in canvas_port.connected_ports():
                upstream = outputs.get(connected.node().name(), {}).get(connected.name())
                cols = _columns_of(upstream)
                if cols is not None:
                    found = True
                    columns.update(cols)
        return columns if found else None

    # Source node: use its own produced table, if it has run.
    own = outputs.get(node.name(), {})
    for port in core_cls.outputs:
        if getattr(port, "dtype", None) in _TABLE_DTYPES:
            cols = _columns_of(own.get(port.name))
            if cols is not None:
                return cols
    return None


def validate_column_value(
    value: str, accepted: list[str] | None, columns: dict[str, str] | None
) -> str | None:
    """Classify one column name. Returns OK / UNKNOWN_COLUMN / UNSUPPORTED_TYPE."""
    if not value or columns is None:
        return OK
    if value not in columns:
        return UNKNOWN_COLUMN
    if not kind_accepted(accepted, columns[value]):
        return UNSUPPORTED_TYPE
    return OK


def warning_message(
    code: str, value: str, accepted: list[str] | None, columns: dict[str, str] | None
) -> str:
    """Human-readable text for a validation code (empty string for OK)."""
    if code == UNKNOWN_COLUMN:
        return f'"{value}" is not a column of the input data.'
    if code == UNSUPPORTED_TYPE:
        kind = (columns or {}).get(value, "?")
        needs = " or ".join(k for k in (accepted or []) if k != "any") or "another"
        return f'"{value}" is a {kind} column; this parameter needs a {needs} column.'
    return ""
