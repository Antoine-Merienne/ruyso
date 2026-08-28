"""
Helpers for declaring node parameters, kept in the core layer so nodes
can describe their parameters richly without depending on the UI.

Every helper stashes a small marker dict in the field's
``json_schema_extra``; only the UI reads them, the engine ignores them:

* *column reference* (:func:`column_field`) -- the value names one or
  more columns; the UI offers a picker of the available columns and
  warns on a missing / wrong-typed name.
* *suggestions* (:func:`suggestions_field`) -- a free-text string field
  with a dropdown of a few common values.
* *reactive choice* (:func:`reactive_choice_field`) -- a dropdown whose
  options depend on the current value of another field (e.g. the
  castable types for the selected column).
* *checkbox list* (:func:`checkbox_list_field`) -- a list value edited
  as a column of tickboxes.
* *visible when* (any helper's ``visible_when=`` argument) -- the field
  is only shown while another field holds a given value.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo

COLUMN_REF_KEY = "ruyso_column_ref"
SUGGESTIONS_KEY = "ruyso_suggestions"
REACTIVE_CHOICE_KEY = "ruyso_reactive_choice"
CHECKBOX_LIST_KEY = "ruyso_checkbox_list"
VISIBLE_WHEN_KEY = "ruyso_visible_when"

#: Accepted values for a column reference's ``dtypes`` list. ``"any"``
#: means no type restriction.
COLUMN_DTYPE_KINDS = ("any", "numeric", "categorical", "datetime", "boolean")

#: Option-generator names understood by :func:`reactive_choice_field`.
REACTIVE_CHOICE_OPTIONS = ("cast_types", "row_operators")


def _merge(*parts: dict | None) -> dict:
    merged: dict[str, Any] = {}
    for part in parts:
        if part:
            merged.update(part)
    return merged


def _visible_marker(visible_when: tuple[str, str] | None) -> dict | None:
    if visible_when is None:
        return None
    field, equals = visible_when
    return {VISIBLE_WHEN_KEY: {"field": field, "equals": equals}}


def column_field(
    *,
    dtypes: tuple[str, ...] = ("any",),
    default: Any = ...,
    description: str | None = None,
    visible_when: tuple[str, str] | None = None,
    **field_kwargs: Any,
) -> Any:
    """Declare a parameter that names one or more input-DataFrame columns."""
    unknown = set(dtypes) - set(COLUMN_DTYPE_KINDS)
    if unknown:
        raise ValueError(f"Unknown column dtype kind(s): {sorted(unknown)}")
    extra = _merge({COLUMN_REF_KEY: {"dtypes": list(dtypes)}}, _visible_marker(visible_when))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def suggestions_field(
    *,
    suggestions: list[str],
    default: Any = ...,
    description: str | None = None,
    visible_when: tuple[str, str] | None = None,
    **field_kwargs: Any,
) -> Any:
    """Declare a free-text string parameter with a dropdown of suggested values."""
    extra = _merge({SUGGESTIONS_KEY: {"values": list(suggestions)}}, _visible_marker(visible_when))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def reactive_choice_field(
    *,
    options: str,
    depends_on: str,
    default: Any = ...,
    description: str | None = None,
    visible_when: tuple[str, str] | None = None,
    **field_kwargs: Any,
) -> Any:
    """
    Declare a dropdown whose choices are recomputed from another field.

    Args:
        options: One of ``REACTIVE_CHOICE_OPTIONS`` -- names a
            UI-side generator.
        depends_on: Name of the field whose value drives the choices
            (typically a column-reference field).
    """
    if options not in REACTIVE_CHOICE_OPTIONS:
        raise ValueError(f"Unknown reactive-choice generator {options!r}")
    extra = _merge(
        {REACTIVE_CHOICE_KEY: {"options": options, "depends_on": depends_on}},
        _visible_marker(visible_when),
    )
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def checkbox_list_field(
    *,
    source: str | None = None,
    choices: list[str] | None = None,
    default: Any = None,
    description: str | None = None,
    visible_when: tuple[str, str] | None = None,
    **field_kwargs: Any,
) -> Any:
    """
    Declare a list value edited as a column of tickboxes.

    Exactly one of ``source`` / ``choices`` should be given:
    ``source="columns"`` fills the tickboxes from the input DataFrame's
    columns; ``choices=[...]`` is a fixed set of labels.
    """
    extra = _merge(
        {CHECKBOX_LIST_KEY: {"source": source, "choices": list(choices) if choices else None}},
        _visible_marker(visible_when),
    )
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def visible_field(
    default: Any = ...,
    *,
    visible_when: tuple[str, str],
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """A plain field (any annotation) that is only shown when ``visible_when`` holds."""
    return Field(
        default=default,
        description=description,
        json_schema_extra=_visible_marker(visible_when),
        **field_kwargs,
    )


# -- readers (used by ui.property_forms) --------------------------------


def _marker(field_info: FieldInfo, key: str) -> dict | None:
    extra = field_info.json_schema_extra
    if isinstance(extra, dict) and key in extra:
        return extra[key]
    return None


def column_ref_dtypes(field_info: FieldInfo) -> list[str] | None:
    marker = _marker(field_info, COLUMN_REF_KEY)
    return list(marker.get("dtypes", ["any"])) if marker is not None else None


def field_suggestions(field_info: FieldInfo) -> list[str] | None:
    marker = _marker(field_info, SUGGESTIONS_KEY)
    return list(marker.get("values", [])) if marker is not None else None


def reactive_choice_spec(field_info: FieldInfo) -> dict | None:
    marker = _marker(field_info, REACTIVE_CHOICE_KEY)
    return dict(marker) if marker is not None else None


def checkbox_list_spec(field_info: FieldInfo) -> dict | None:
    marker = _marker(field_info, CHECKBOX_LIST_KEY)
    return dict(marker) if marker is not None else None


def visible_when(field_info: FieldInfo) -> tuple[str, str] | None:
    marker = _marker(field_info, VISIBLE_WHEN_KEY)
    return (marker["field"], marker["equals"]) if marker is not None else None
