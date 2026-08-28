"""
Tests for the geopandas <-> pandas transformer nodes.
"""

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point

from ruyso_app.nodes.geo_transforms import (
    DataFrameToGeo,
    DataFrameToGeoParams,
    GeoToDataFrame,
    GeoToDataFrameParams,
    Reproject,
    ReprojectParams,
)


@pytest.fixture
def gdf():
    return gpd.GeoDataFrame(
        {"name": ["a", "b"], "geometry": [Point(1.0, 2.0), Point(3.0, 4.0)]},
        crs="EPSG:4326",
    )


def test_geo_to_dataframe_drop(gdf):
    out = GeoToDataFrame(params=GeoToDataFrameParams(geometry="drop")).run(gdf=gdf)["df"]
    assert type(out) is pd.DataFrame
    assert list(out.columns) == ["name"]


def test_geo_to_dataframe_wkt(gdf):
    out = GeoToDataFrame(
        params=GeoToDataFrameParams(geometry="wkt", wkt_column="wkt")
    ).run(gdf=gdf)["df"]
    assert "wkt" in out.columns
    assert out["wkt"].iloc[0].startswith("POINT")


def test_geo_to_dataframe_xy(gdf):
    out = GeoToDataFrame(
        params=GeoToDataFrameParams(geometry="xy", x_column="lon", y_column="lat")
    ).run(gdf=gdf)["df"]
    assert out["lon"].tolist() == [1.0, 3.0]
    assert out["lat"].tolist() == [2.0, 4.0]


def test_dataframe_to_geo_from_xy():
    df = pd.DataFrame({"lon": [1.0, 3.0], "lat": [2.0, 4.0], "name": ["a", "b"]})
    out = DataFrameToGeo(
        params=DataFrameToGeoParams(
            source="xy", x_column="lon", y_column="lat", crs="EPSG:4326"
        )
    ).run(df=df)["gdf"]
    assert isinstance(out, gpd.GeoDataFrame)
    assert out.crs.to_epsg() == 4326
    assert out.geometry.iloc[1] == Point(3.0, 4.0)


def test_dataframe_to_geo_from_wkt():
    df = pd.DataFrame({"g": ["POINT (1 2)", "POINT (3 4)"]})
    out = DataFrameToGeo(
        params=DataFrameToGeoParams(source="wkt", wkt_column="g", crs="EPSG:3857")
    ).run(df=df)["gdf"]
    assert "g" not in out.columns
    assert out.geometry.iloc[0] == Point(1, 2)


def test_reproject(gdf):
    out = Reproject(params=ReprojectParams(crs="EPSG:3857")).run(gdf=gdf)["gdf"]
    assert out.crs.to_epsg() == 3857
    assert out.geometry.iloc[0].x != gdf.geometry.iloc[0].x
