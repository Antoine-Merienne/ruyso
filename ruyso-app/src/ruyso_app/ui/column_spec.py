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

_DATAFRAME_DTYPE = "dataframe"


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


def input_dataframe_columns(
    node: BaseNode, outputs: dict[str, dict]
) -> dict[str, str] | None:
    """
    ``{column name: column kind}`` for the DataFrame(s) feeding ``node``.

    Returns ``None`` when no upstream table is available (the node has
    no connected dataframe input, or the pipeline has not produced one
    yet) -- the caller then offers free text with no validation.
    """
    core_cls = getattr(type(node), "CORE_NODE_CLASS", None)
    if core_cls is None:
        return None

    columns: dict[str, str] = {}
    found = False
    for port in core_cls.inputs:
        if getattr(port, "dtype", None) != _DATAFRAME_DTYPE:
            continue
        canvas_port = node.inputs().get(port.name)
        if canvas_port is None:
            continue
        for connected in canvas_port.connected_ports():
            df = outputs.get(connected.node().name(), {}).get(connected.name())
            if df is not None and hasattr(df, "columns") and hasattr(df, "dtypes"):
                found = True
                for name, dtype in df.dtypes.items():
                    columns[str(name)] = dtype_kind(dtype)
    return columns if found else None


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
