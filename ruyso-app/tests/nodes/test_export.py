"""
Tests for the export nodes: ``export_figure`` / ``export_table`` /
``export_geodata`` write files in a chosen format; ``export_to_dashboard``
is a pass-through sink for the Dashboard tab.
"""

import matplotlib
import pandas as pd

matplotlib.use("Agg")  # headless backend before any pyplot import
import matplotlib.pyplot as plt
import pytest

from ruyso_app.nodes.export import (
    ExportFigure,
    ExportFigureParams,
    ExportGeodata,
    ExportGeodataParams,
    ExportTable,
    ExportTableParams,
    ExportToDashboard,
    ExportToDashboardParams,
)


@pytest.mark.parametrize(
    "fmt,ext", [("png", ".png"), ("jpeg", ".jpg"), ("pdf", ".pdf"), ("svg", ".svg")]
)
def test_export_figure_writes_the_chosen_format(tmp_path, fmt, ext):
    # filepath deliberately has no / a wrong extension -> node fixes it up
    node = ExportFigure(
        params=ExportFigureParams(filepath=str(tmp_path / "out"), format=fmt)
    )
    assert node.run(figure=plt.figure()) == {}
    written = tmp_path / f"out{ext}"
    assert written.exists() and written.stat().st_size > 0


@pytest.mark.parametrize("fmt", ["csv", "tsv", "xlsx", "parquet", "feather", "json"])
def test_export_table_round_trips_each_format(tmp_path, fmt):
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    node = ExportTable(
        params=ExportTableParams(filepath=str(tmp_path / "t"), format=fmt)
    )
    assert node.run(table=df) == {}
    assert next(tmp_path.glob("t.*")).stat().st_size > 0


def test_export_table_include_index_adds_a_column(tmp_path):
    df = pd.DataFrame({"a": [1, 2]}, index=["r1", "r2"])
    ExportTable(
        params=ExportTableParams(
            filepath=str(tmp_path / "t.csv"), format="csv", include_index=True
        )
    ).run(table=df)
    back = pd.read_csv(tmp_path / "t.csv")
    assert list(back.columns) == ["Unnamed: 0", "a"]  # the index came through

    ExportTable(
        params=ExportTableParams(filepath=str(tmp_path / "n.csv"), format="csv")
    ).run(table=df)
    assert list(pd.read_csv(tmp_path / "n.csv").columns) == ["a"]


def test_export_geodata_writes_geojson_and_geoparquet(tmp_path):
    import geopandas as gpd
    from shapely.geometry import Point

    gdf = gpd.GeoDataFrame(
        {"name": ["a", "b"]}, geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:4326"
    )
    ExportGeodata(
        params=ExportGeodataParams(filepath=str(tmp_path / "g"), format="geojson")
    ).run(gdf=gdf)
    ExportGeodata(
        params=ExportGeodataParams(filepath=str(tmp_path / "g"), format="geoparquet")
    ).run(gdf=gdf)
    assert (tmp_path / "g.geojson").exists()
    assert (tmp_path / "g.parquet").exists()
    assert gpd.read_file(tmp_path / "g.geojson").shape[0] == 2


def test_export_to_dashboard_is_a_sink():
    node = ExportToDashboard(params=ExportToDashboardParams(title="My chart"))
    assert node.run(figure=plt.figure()) == {}
    assert ExportToDashboard.category == "export"
    assert ExportToDashboard.outputs == []
    assert ExportToDashboard.cacheable is False
