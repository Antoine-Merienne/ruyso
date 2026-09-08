"""
Tests for ``ui.file_filters``: the node_type -> QFileDialog filter map.
"""

from ruyso_app.ui.file_filters import DEFAULT_FILTER, filter_for


def test_known_node_types_have_specific_filters():
    assert "*.csv" in filter_for("csv_loader")
    assert "*.png" in filter_for("export_figure")
    assert "*.xlsx" in filter_for("excel_loader")
    assert "*.parquet" in filter_for("parquet_loader")
    assert "*.geojson" in filter_for("geojson_loader")
    assert "*.gpkg" in filter_for("geopackage_loader")


def test_unknown_or_missing_node_type_falls_back_to_default():
    assert filter_for("something_else") == DEFAULT_FILTER
    assert filter_for(None) == DEFAULT_FILTER
