"""
Tests for ``ui.column_ops.options_for`` -- the reactive dropdown lists.
"""

from ruyso_app.ui.column_ops import options_for


def test_cast_types_depend_on_column_kind():
    numeric = options_for("cast_types", "numeric")
    assert "int" not in numeric and "float" not in numeric  # already numeric
    assert set(numeric) == {"str", "category", "bool", "datetime"}

    unknown = options_for("cast_types", None)
    assert "int" in unknown and "float" in unknown  # full list when kind unknown


def test_row_operators_depend_on_column_kind():
    assert options_for("row_operators", "numeric") == [">", ">=", "<", "<=", "==", "!="]
    assert options_for("row_operators", "categorical") == ["==", "!=", "contains"]
    assert options_for("row_operators", "boolean") == ["==", "!="]
    assert "contains" in options_for("row_operators", None)


def test_colormaps_are_discrete_for_buckets_and_continuous_otherwise():
    discrete = options_for("colormaps", "categorical")
    assert options_for("colormaps", "boolean") == discrete
    assert "tab10" in discrete and "viridis" not in discrete

    continuous = options_for("colormaps", "numeric")
    assert options_for("colormaps", "datetime") == continuous
    assert options_for("colormaps", None) == continuous  # unknown kind -> continuous
    assert "viridis" in continuous and "tab10" not in continuous
