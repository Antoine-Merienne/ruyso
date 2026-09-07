"""
Tests for the geospatial loader nodes: each reads a vector file back
into a GeoDataFrame with a geometry column. Loaders do not coerce
dtypes -- see ``tests/nodes/test_loaders.py``.
"""

import geopandas as gpd
import pytest
from shapely.geometry import Point

from ruyso_app.nodes.geo_loaders import (
    GeoFeatherLoader,
    GeoJSONLoader,
    GeoPackageLoader,
    GeoPackageLoaderParams,
    GeoParquetLoader,
    ShapefileLoader,
)
from ruyso_app.nodes.loaders import LoaderParams


@pytest.fixture
def gdf():
    return gpd.GeoDataFrame(
        {
            "name": ["a", "b", "c"],
            "when": ["2020-01-01", "2020-02-01", "2020-03-01"],
            "geometry": [Point(0, 0), Point(1, 1), Point(2, 2)],
        },
        crs="EPSG:4326",
    )


def test_geojson_loader(tmp_path, gdf):
    path = tmp_path / "s.geojson"
    gdf.to_file(path, driver="GeoJSON")
    out = GeoJSONLoader(params=LoaderParams(filepath=str(path))).run()["gdf"]
    assert isinstance(out, gpd.GeoDataFrame)
    assert "geometry" in out.columns
    assert len(out) == 3


def test_shapefile_loader(tmp_path, gdf):
    path = tmp_path / "s.shp"
    gdf.to_file(path)
    out = ShapefileLoader(params=LoaderParams(filepath=str(path))).run()["gdf"]
    assert isinstance(out, gpd.GeoDataFrame)
    assert out.geometry.iloc[1] == Point(1, 1)


def test_geopackage_loader_with_layer(tmp_path, gdf):
    path = tmp_path / "s.gpkg"
    gdf.to_file(path, layer="places", driver="GPKG")
    out = GeoPackageLoader(
        params=GeoPackageLoaderParams(filepath=str(path), layer="places")
    ).run()["gdf"]
    assert list(out["name"]) == ["a", "b", "c"]


def test_geoparquet_loader_reconstructs_geometry_and_crs(tmp_path, gdf):
    path = tmp_path / "s.parquet"
    gdf.to_parquet(path)

    out = GeoParquetLoader(params=LoaderParams(filepath=str(path))).run()["gdf"]

    assert isinstance(out, gpd.GeoDataFrame)
    assert out.crs.to_epsg() == 4326
    assert out.geometry.iloc[2] == Point(2, 2)


def test_geofeather_loader_reconstructs_geometry_and_crs(tmp_path, gdf):
    path = tmp_path / "s.feather"
    gdf.to_feather(path)

    out = GeoFeatherLoader(params=LoaderParams(filepath=str(path))).run()["gdf"]

    assert isinstance(out, gpd.GeoDataFrame)
    assert out.crs.to_epsg() == 4326
    assert list(out["name"]) == ["a", "b", "c"]


def test_plain_parquet_loader_cannot_read_geoparquet_geometry(tmp_path, gdf):
    # Why the dedicated node exists: the tabular loader yields raw WKB bytes.
    from ruyso_app.nodes.loaders import ParquetLoader, ParquetLoaderParams

    path = tmp_path / "s.parquet"
    gdf.to_parquet(path)
    out = ParquetLoader(params=ParquetLoaderParams(filepath=str(path))).run()["df"]
    assert not isinstance(out, gpd.GeoDataFrame)
    assert isinstance(out["geometry"].iloc[0], bytes)
