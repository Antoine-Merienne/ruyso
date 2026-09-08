"""
Option lists for the Options panel's *reactive* dropdowns -- the ones
whose choices depend on the kind of the currently selected column
(see ``core.params.reactive_choice_field``).

Kinds are the strings produced by ``column_spec.dtype_kind``
(``"numeric"`` / ``"datetime"`` / ``"boolean"`` / ``"categorical"``);
``None`` means "no column selected / kind unknown" and falls back to
the full list.

The ``"colormaps"`` generator is special: its lists are not constants
but come from :mod:`ruyso_app.engine.colormaps` (built-in maps plus the
user's custom maps, in the order set in the Colormap Manager).
"""

from __future__ import annotations

from ruyso_app.engine import colormaps as _colormaps

#: change_type: which target dtypes make sense for a source column of
#: each kind (casting to the same kind is pointless, so it's omitted).
_CAST_TARGET_TYPES: dict[str | None, list[str]] = {
    "numeric": ["str", "category", "bool", "datetime"],
    "boolean": ["int", "float", "str", "category"],
    "datetime": ["str", "int", "category"],
    "categorical": ["str", "category", "int", "float", "datetime", "bool"],
    None: ["str", "int", "float", "category", "bool", "datetime"],
}

#: RowFilter: which comparison operators apply to a column of each kind.
_ROW_OPERATORS: dict[str | None, list[str]] = {
    "numeric": [">", ">=", "<", "<=", "==", "!="],
    "datetime": [">", ">=", "<", "<=", "==", "!="],
    "boolean": ["==", "!="],
    "categorical": ["==", "!=", "contains"],
    None: [">", ">=", "<", "<=", "==", "!=", "contains"],
}

_GENERATORS = {
    "cast_types": _CAST_TARGET_TYPES,
    "row_operators": _ROW_OPERATORS,
}

#: A column of one of these kinds drives a *qualitative* colormap (values
#: fall into buckets); anything else drives a *continuous* one.
_COLUMN_KIND_TO_COLORMAP_KIND: dict[str | None, str] = {
    "boolean": _colormaps.QUALITATIVE,
    "categorical": _colormaps.QUALITATIVE,
    "numeric": _colormaps.CONTINUOUS,
    "datetime": _colormaps.CONTINUOUS,
    None: _colormaps.CONTINUOUS,
}


def colormap_choices(colormap_kind: str) -> list[str]:
    """Visible + ordered colormap names for a fixed ``"continuous"`` /
    ``"qualitative"`` field (``core.params.colormap_field``)."""
    return list(_colormaps.resolved_lists().get(colormap_kind, []))


def options_for(generator: str, column_kind: str | None) -> list[str]:
    """Return the dropdown options for ``generator`` given a column kind."""
    if generator == "colormaps":
        return colormap_choices(
            _COLUMN_KIND_TO_COLORMAP_KIND.get(column_kind, _colormaps.CONTINUOUS)
        )
    table = _GENERATORS[generator]
    return list(table.get(column_kind, table[None]))
