"""
Option lists for the Options panel's *reactive* dropdowns -- the ones
whose choices depend on the kind of the currently selected column
(see ``core.params.reactive_choice_field``).

Kinds are the strings produced by ``column_spec.dtype_kind``
(``"numeric"`` / ``"datetime"`` / ``"boolean"`` / ``"categorical"``);
``None`` means "no column selected / kind unknown" and falls back to
the full list.
"""

from __future__ import annotations

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

#: matplotlib_plot "colour by" colormap: qualitative maps for a column
#: whose values fall into buckets (text / category / bool), sequential
#: & diverging maps for a continuous column (numeric / datetime).
_DISCRETE_COLORMAPS = ["tab10", "tab20", "Set1", "Set2", "Set3", "Paired", "Dark2", "Accent"]
_CONTINUOUS_COLORMAPS = [
    "viridis", "plasma", "cividis", "magma", "coolwarm", "Spectral", "Blues", "Greens",
]
_COLORMAPS: dict[str | None, list[str]] = {
    "boolean": _DISCRETE_COLORMAPS,
    "categorical": _DISCRETE_COLORMAPS,
    "numeric": _CONTINUOUS_COLORMAPS,
    "datetime": _CONTINUOUS_COLORMAPS,
    None: _CONTINUOUS_COLORMAPS,
}

_GENERATORS = {
    "cast_types": _CAST_TARGET_TYPES,
    "row_operators": _ROW_OPERATORS,
    "colormaps": _COLORMAPS,
}


def options_for(generator: str, column_kind: str | None) -> list[str]:
    """Return the dropdown options for ``generator`` given a column kind."""
    table = _GENERATORS[generator]
    return list(table.get(column_kind, table[None]))
