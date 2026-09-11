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
* *colour* (:func:`color_field`) -- a suggestions-style field plus a
  small "Choose..." button opening a colour dialog.
* *reactive choice* (:func:`reactive_choice_field`) -- a dropdown whose
  options depend on the current value of another field (e.g. the
  castable types for the selected column).
* *checkbox list* (:func:`checkbox_list_field`) -- a list value edited
  as a column of tickboxes.
* *category map* (:func:`category_map_field`) -- a JSON ``{old: new}``
  mapping edited as a table of the input column's distinct values, each
  facing a "new name" box (blank = keep).
* *code* (:func:`code_field`) -- a multi-line Python-source string,
  edited in a monospace text box with a read-only hint of the input
  DataFrame's column names underneath.
* *optimize bounds* (:func:`optimize_bounds_field`) -- a JSON
  ``{param: [lo, hi]}`` mapping edited as a table, one row per numeric
  field of the node's own schema, each with a checkbox + bound pair.
* *visible when* (any helper's ``visible_when=`` argument) -- the field
  is only shown while another field holds a given value;
  ``visible_when_set=`` shows it while another field holds any
  non-empty value; ``visible_when_unset=`` shows it while another field
  is empty; ``visible_unless=`` shows it while another field does *not*
  hold a given value; ``visible_when_kind=(field, kinds)`` shows it
  while the column named by ``field`` has one of ``kinds`` (or the
  kind is not known yet); ``visible_when_in=(field, values)`` shows it
  while another field's value is one of ``values`` (an "OR" version of
  ``visible_when=`` for more than one match). Conditions combine with AND.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.fields import FieldInfo

COLUMN_REF_KEY = "ruyso_column_ref"
SUGGESTIONS_KEY = "ruyso_suggestions"
COLOR_FIELD_KEY = "ruyso_color_field"
COLORMAP_FIELD_KEY = "ruyso_colormap_field"
REACTIVE_CHOICE_KEY = "ruyso_reactive_choice"
CHECKBOX_LIST_KEY = "ruyso_checkbox_list"
CATEGORY_MAP_KEY = "ruyso_category_map"
COLUMN_MAP_KEY = "ruyso_column_map"
UNIT_INTERVAL_KEY = "ruyso_unit_interval"
CODE_KEY = "ruyso_code"
OPTIMIZE_BOUNDS_KEY = "ruyso_optimize_bounds"
VISIBLE_WHEN_KEY = "ruyso_visible_when"
VISIBLE_WHEN_SET_KEY = "ruyso_visible_when_set"
VISIBLE_WHEN_UNSET_KEY = "ruyso_visible_when_unset"
VISIBLE_WHEN_KIND_KEY = "ruyso_visible_when_kind"
VISIBLE_UNLESS_KEY = "ruyso_visible_unless"
VISIBLE_WHEN_IN_KEY = "ruyso_visible_when_in"

#: Accepted values for a column reference's ``dtypes`` list. ``"any"``
#: means no type restriction.
COLUMN_DTYPE_KINDS = ("any", "numeric", "categorical", "datetime", "boolean")

#: Option-generator names understood by :func:`reactive_choice_field`.
REACTIVE_CHOICE_OPTIONS = ("cast_types", "row_operators", "colormaps")


def _merge(*parts: dict | None) -> dict:
    merged: dict[str, Any] = {}
    for part in parts:
        if part:
            merged.update(part)
    return merged


def _visible_markers(
    visible_when: tuple[str, str] | None,
    visible_when_set: str | None,
    visible_unless: tuple[str, str] | None = None,
    visible_when_unset: str | None = None,
    visible_when_kind: tuple[str, tuple[str, ...]] | None = None,
    visible_when_in: tuple[str, tuple[str, ...]] | None = None,
) -> dict | None:
    marker: dict[str, Any] = {}
    if visible_when is not None:
        field, equals = visible_when
        marker[VISIBLE_WHEN_KEY] = {"field": field, "equals": equals}
    if visible_when_set is not None:
        marker[VISIBLE_WHEN_SET_KEY] = {"field": visible_when_set}
    if visible_when_unset is not None:
        marker[VISIBLE_WHEN_UNSET_KEY] = {"field": visible_when_unset}
    if visible_when_kind is not None:
        field, kinds = visible_when_kind
        marker[VISIBLE_WHEN_KIND_KEY] = {"field": field, "kinds": list(kinds)}
    if visible_unless is not None:
        field, equals = visible_unless
        marker[VISIBLE_UNLESS_KEY] = {"field": field, "equals": equals}
    if visible_when_in is not None:
        field, values = visible_when_in
        marker[VISIBLE_WHEN_IN_KEY] = {"field": field, "values": list(values)}
    return marker or None


#: Every field helper accepts this set of visibility conditions as
#: keyword arguments; they are popped out of ``**field_kwargs`` here so
#: pydantic's ``Field`` never sees them.
_VISIBLE_KEYS = (
    "visible_when", "visible_when_set", "visible_unless",
    "visible_when_unset", "visible_when_kind", "visible_when_in",
)


def _pop_visible(field_kwargs: dict[str, Any]) -> dict | None:
    return _visible_markers(*(field_kwargs.pop(key, None) for key in _VISIBLE_KEYS))


def column_field(
    *,
    dtypes: tuple[str, ...] = ("any",),
    default: Any = ...,
    description: str | None = None,
    allow_none: bool = False,
    **field_kwargs: Any,
) -> Any:
    """Declare a parameter that names one or more input-DataFrame columns.

    ``allow_none=True`` gives a single-value picker an italic-grey
    "None" row at the top that clears the field (useful for optional
    "colour by this column" style parameters).
    """
    unknown = set(dtypes) - set(COLUMN_DTYPE_KINDS)
    if unknown:
        raise ValueError(f"Unknown column dtype kind(s): {sorted(unknown)}")
    extra = _merge(
        {COLUMN_REF_KEY: {"dtypes": list(dtypes), "allow_none": bool(allow_none)}},
        _pop_visible(field_kwargs),
    )
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def suggestions_field(
    *,
    suggestions: list[str],
    default: Any = ...,
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """Declare a free-text string parameter with a dropdown of suggested values."""
    extra = _merge({SUGGESTIONS_KEY: {"values": list(suggestions)}}, _pop_visible(field_kwargs))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def color_field(
    *,
    suggestions: list[str],
    default: Any = ...,
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """Declare a colour parameter: a suggestions dropdown of common
    colour names plus a small "Choose..." button opening a colour
    dialog. Any matplotlib colour string (name or ``#rrggbb``) is
    accepted as the value.
    """
    extra = _merge({COLOR_FIELD_KEY: {"values": list(suggestions)}}, _pop_visible(field_kwargs))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


AXIS_LIMIT_KEY = "ruyso_axis_limit"


def axis_limit_field(description: str | None = None, **field_kwargs: Any) -> Any:
    """
    Declare one edge of a manual axis range.

    Stored as a string so a *blank* value can mean "let the plot fit this
    edge to the data" -- a float field has no way to say that, and a
    number and an ISO date ("2020-01-01", for a time axis) have to share
    the one field. The value is parsed by ``nodes.viz._limit_value``.

    The marker is what tells the Options panel to fill the box with the
    limit the last run's plot actually used, so the four edges always
    show real numbers to edit rather than an empty box or a placeholder
    ``0.0`` that would silently crush the axis if left alone. That
    prefill is display-only: the parameter stays blank until the person
    types in it (see ``ui.options_panel._build_axis_limit_widget``).
    """
    extra = _merge({AXIS_LIMIT_KEY: {}}, _pop_visible(field_kwargs))
    return Field(default="", description=description, json_schema_extra=extra, **field_kwargs)


COLORMAP_FIELD_KINDS = ("continuous", "qualitative")


def colormap_field(
    *,
    kind: str,
    default: Any = ...,
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """Declare a colormap parameter with a *fixed* kind (not driven by a
    column). Rendered as the same gradient dropdown as the reactive
    colormap fields, populated from the user's continuous / qualitative
    list (built-ins + custom maps -- see ``engine.colormaps``). The
    stored value is a plain colormap name string.
    """
    if kind not in COLORMAP_FIELD_KINDS:
        raise ValueError(f"colormap_field kind must be one of {COLORMAP_FIELD_KINDS}")
    extra = _merge({COLORMAP_FIELD_KEY: {"kind": kind}}, _pop_visible(field_kwargs))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def unit_interval_field(
    default: float = 0.5,
    *,
    lo: float = 0.0,
    hi: float = 1.0,
    step: float = 0.01,
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """Declare a bounded ``float`` edited with a slider (``lo``..``hi``).

    Use for ratios / fractions / proportions. The value still
    round-trips as a plain float; only the widget changes.
    """
    extra = _merge(
        {UNIT_INTERVAL_KEY: {"lo": float(lo), "hi": float(hi), "step": float(step)}},
        _pop_visible(field_kwargs),
    )
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def reactive_choice_field(
    *,
    options: str,
    depends_on: str,
    default: Any = ...,
    description: str | None = None,
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
        _pop_visible(field_kwargs),
    )
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def checkbox_list_field(
    *,
    source: str | None = None,
    choices: list[str] | None = None,
    default: Any = None,
    description: str | None = None,
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
        _pop_visible(field_kwargs),
    )
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def category_map_field(
    *,
    column: str,
    default: Any = "{}",
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """
    Declare a ``{old category: new name}`` mapping stored as a JSON
    string and edited as a table.

    Args:
        column: Name of the sibling field naming the column whose
            distinct input-data values fill the table's left column.
    """
    extra = _merge({CATEGORY_MAP_KEY: {"column": column}}, _pop_visible(field_kwargs))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def column_map_field(
    *,
    keys: list[str],
    default: Any = "{}",
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """
    Declare a ``{key: column name}`` mapping stored as a JSON string and
    edited as a table: one fixed ``keys`` row each, with a dropdown of
    the input DataFrame's columns on the right (blank = unmapped).
    """
    extra = _merge(
        {COLUMN_MAP_KEY: {"keys": list(keys)}}, _pop_visible(field_kwargs)
    )
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def code_field(
    *,
    default: Any = "",
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """
    Declare a multi-line Python-source string field.

    Rendered as a monospace text box (``ui.options_panel._build_code_widget``)
    with a read-only hint of the input DataFrame's column names beneath
    it, so writing an expression against the data doesn't require
    leaving the panel. Like the tickbox / table fields, edits are
    batched -- the auto-run waits for focus-out rather than firing on
    every keystroke.
    """
    extra = _merge({CODE_KEY: {}}, _pop_visible(field_kwargs))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def optimize_bounds_field(
    *,
    default: Any = "{}",
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """
    Declare a ``{param: [lo, hi]}`` mapping stored as a JSON string and
    edited as a table (a fit node's "optimize" section -- see
    ``models.SklearnFitParams``): one row per *numeric* field of the
    same node's own parameter schema, each with a checkbox (include it
    in the search) and a lo/hi bound pair. Unlike
    :func:`column_map_field`, the row list is not given here -- the UI
    derives it from the params schema itself, so it never goes stale.
    """
    extra = _merge({OPTIMIZE_BOUNDS_KEY: {}}, _pop_visible(field_kwargs))
    return Field(default=default, description=description, json_schema_extra=extra, **field_kwargs)


def visible_field(
    default: Any = ...,
    *,
    description: str | None = None,
    **field_kwargs: Any,
) -> Any:
    """A plain field (any annotation) shown only while its
    ``visible_when`` / ``visible_when_set`` / ``visible_when_unset`` /
    ``visible_when_kind`` / ``visible_unless`` conditions all hold (AND).
    """
    marker = _pop_visible(field_kwargs)
    if marker is None:
        raise ValueError(
            "visible_field needs visible_when=, visible_when_set=, "
            "visible_when_unset=, visible_when_kind= or visible_unless="
        )
    return Field(default=default, description=description, json_schema_extra=marker, **field_kwargs)


# -- readers (used by ui.property_forms) --------------------------------


def _marker(field_info: FieldInfo, key: str) -> dict | None:
    extra = field_info.json_schema_extra
    if isinstance(extra, dict) and key in extra:
        return extra[key]
    return None


def column_ref_dtypes(field_info: FieldInfo) -> list[str] | None:
    marker = _marker(field_info, COLUMN_REF_KEY)
    return list(marker.get("dtypes", ["any"])) if marker is not None else None


def column_ref_allow_none(field_info: FieldInfo) -> bool:
    marker = _marker(field_info, COLUMN_REF_KEY)
    return bool(marker.get("allow_none", False)) if marker is not None else False


def field_suggestions(field_info: FieldInfo) -> list[str] | None:
    marker = _marker(field_info, SUGGESTIONS_KEY)
    return list(marker.get("values", [])) if marker is not None else None


def color_field_values(field_info: FieldInfo) -> list[str] | None:
    marker = _marker(field_info, COLOR_FIELD_KEY)
    return list(marker.get("values", [])) if marker is not None else None


def is_axis_limit_field(field_info: FieldInfo) -> bool:
    return _marker(field_info, AXIS_LIMIT_KEY) is not None


def colormap_field_kind(field_info: FieldInfo) -> str | None:
    marker = _marker(field_info, COLORMAP_FIELD_KEY)
    return marker.get("kind") if marker is not None else None


def reactive_choice_spec(field_info: FieldInfo) -> dict | None:
    marker = _marker(field_info, REACTIVE_CHOICE_KEY)
    return dict(marker) if marker is not None else None


def checkbox_list_spec(field_info: FieldInfo) -> dict | None:
    marker = _marker(field_info, CHECKBOX_LIST_KEY)
    return dict(marker) if marker is not None else None


def category_map_spec(field_info: FieldInfo) -> dict | None:
    marker = _marker(field_info, CATEGORY_MAP_KEY)
    return dict(marker) if marker is not None else None


def column_map_spec(field_info: FieldInfo) -> dict | None:
    marker = _marker(field_info, COLUMN_MAP_KEY)
    return dict(marker) if marker is not None else None


def unit_interval_spec(field_info: FieldInfo) -> dict | None:
    marker = _marker(field_info, UNIT_INTERVAL_KEY)
    return dict(marker) if marker is not None else None


def is_code_field(field_info: FieldInfo) -> bool:
    return _marker(field_info, CODE_KEY) is not None


def is_optimize_bounds_field(field_info: FieldInfo) -> bool:
    return _marker(field_info, OPTIMIZE_BOUNDS_KEY) is not None


def visible_when(field_info: FieldInfo) -> tuple[str, str] | None:
    marker = _marker(field_info, VISIBLE_WHEN_KEY)
    return (marker["field"], marker["equals"]) if marker is not None else None


def visible_when_set(field_info: FieldInfo) -> str | None:
    marker = _marker(field_info, VISIBLE_WHEN_SET_KEY)
    return marker["field"] if marker is not None else None


def visible_when_unset(field_info: FieldInfo) -> str | None:
    marker = _marker(field_info, VISIBLE_WHEN_UNSET_KEY)
    return marker["field"] if marker is not None else None


def visible_when_kind(field_info: FieldInfo) -> tuple[str, tuple[str, ...]] | None:
    marker = _marker(field_info, VISIBLE_WHEN_KIND_KEY)
    return (marker["field"], tuple(marker["kinds"])) if marker is not None else None


def visible_unless(field_info: FieldInfo) -> tuple[str, str] | None:
    marker = _marker(field_info, VISIBLE_UNLESS_KEY)
    return (marker["field"], marker["equals"]) if marker is not None else None


def visible_when_in(field_info: FieldInfo) -> tuple[str, tuple[str, ...]] | None:
    marker = _marker(field_info, VISIBLE_WHEN_IN_KEY)
    return (marker["field"], tuple(marker["values"])) if marker is not None else None
