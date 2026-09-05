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


def _is_dataframe(df: object) -> bool:
    return df is not None and hasattr(df, "columns") and hasattr(df, "dtypes")


def _input_dataframes(node: BaseNode, outputs: dict[str, dict]) -> list:
    """The DataFrame(s) feeding ``node``'s table inputs.

    For a *source* node (a loader, no table inputs) this is instead its
    own last-run output. Empty when nothing has run yet.
    """
    core_cls = getattr(type(node), "CORE_NODE_CLASS", None)
    if core_cls is None:
        return []

    table_inputs = [
        p for p in core_cls.inputs if getattr(p, "dtype", None) in _TABLE_DTYPES
    ]
    frames: list = []
    if table_inputs:
        for port in table_inputs:
            canvas_port = node.inputs().get(port.name)
            if canvas_port is None:
                continue
            for connected in canvas_port.connected_ports():
                df = outputs.get(connected.node().name(), {}).get(connected.name())
                if _is_dataframe(df):
                    frames.append(df)
        return frames

    own = outputs.get(node.name(), {})
    for port in core_cls.outputs:
        if getattr(port, "dtype", None) in _TABLE_DTYPES and _is_dataframe(
            own.get(port.name)
        ):
            frames.append(own[port.name])
    return frames


def input_dataframe_columns(
    node: BaseNode, outputs: dict[str, dict]
) -> dict[str, str] | None:
    """
    ``{column name: column kind}`` available to ``node``'s column params.

    For a node with a table input this is the upstream table's columns;
    for a *source* node (a loader, no table inputs) it is that node's
    own last-run output columns -- so a source node's column pickers,
    if it has any, fill in once the file has been read. ``None`` when
    nothing is available yet, so the caller offers free text with no
    validation.
    """
    frames = _input_dataframes(node, outputs)
    if not frames:
        return None
    columns: dict[str, str] = {}
    for df in frames:
        columns.update(
            {str(name): dtype_kind(dtype) for name, dtype in df.dtypes.items()}
        )
    return columns


#: Cap on distinct values surfaced per categorical column (keeps the
#: rename-categories editor bounded on messy data).
_MAX_DISTINCT_VALUES = 200


def input_column_values(
    node: BaseNode, outputs: dict[str, dict]
) -> dict[str, list[str]]:
    """
    ``{column: [distinct string values]}`` for the categorical / bool
    columns of ``node``'s input DataFrame -- powers the
    rename-categories editor. Empty dict when nothing has run yet.
    """
    result: dict[str, list[str]] = {}
    for df in _input_dataframes(node, outputs):
        for name, dtype in df.dtypes.items():
            key = str(name)
            if key in result or dtype_kind(dtype) not in (CATEGORICAL, BOOLEAN):
                continue
            try:
                uniques = df[name].dropna().unique()
            except Exception:  # noqa: BLE001
                continue
            result[key] = sorted(str(v) for v in list(uniques)[:_MAX_DISTINCT_VALUES])
    return result


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
