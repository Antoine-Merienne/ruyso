"""
Helpers for declaring node parameters, kept in the core layer so nodes
can describe their parameters richly without depending on the UI.

At the moment this covers one thing: marking a parameter as a
*column reference* -- a value (or list of values) that must name a
column of the node's input DataFrame. The UI reads this marker to
offer a picker of the available columns and to warn when a chosen
column is missing or has an unsupported type. The engine ignores it.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo

#: Key placed in a field's ``json_schema_extra`` to mark it as a column
#: reference. Its value is ``{"dtypes": [...]}``.
COLUMN_REF_KEY = "ruyso_column_ref"

#: Accepted values for a column reference's ``dtypes`` list. ``"any"``
#: means no type restriction.
COLUMN_DTYPE_KINDS = ("any", "numeric", "categorical", "datetime", "boolean")


def column_field(
    *,
    dtypes: tuple[str, ...] = ("any",),
    default: Any = ...,
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """
    Declare a parameter that names one or more input-DataFrame columns.

    Args:
        dtypes: Column kinds this parameter accepts (see
            ``COLUMN_DTYPE_KINDS``). Used by the UI only.
        default: Field default (``...`` = required), as for ``Field``.
        description: Field description.
        **field_kwargs: Forwarded to ``pydantic.Field``.

    Returns:
        A ``pydantic.Field`` carrying the column-reference marker.
    """
    unknown = set(dtypes) - set(COLUMN_DTYPE_KINDS)
    if unknown:
        raise ValueError(f"Unknown column dtype kind(s): {sorted(unknown)}")
    extra = {COLUMN_REF_KEY: {"dtypes": list(dtypes)}}
    return Field(
        default=default,
        description=description,
        json_schema_extra=extra,
        **field_kwargs,
    )


def column_ref_dtypes(field_info: FieldInfo) -> list[str] | None:
    """
    Return the accepted column kinds if ``field_info`` is a column
    reference, else ``None``.
    """
    extra = field_info.json_schema_extra
    if isinstance(extra, dict) and COLUMN_REF_KEY in extra:
        return list(extra[COLUMN_REF_KEY].get("dtypes", ["any"]))
    return None
