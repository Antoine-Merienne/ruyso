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


# --------------------------------------------------------------------------
# Relate / combine, reshape, derive, CRS
# --------------------------------------------------------------------------

from shapely.geometry import Polygon  # noqa: E402

from ruyso_app.nodes.geo_transforms import (  # noqa: E402
    GeoBuffer,
    GeoBufferParams,
    GeoClip,
    GeoClipParams,
    GeoDissolve,
    GeoDissolveParams,
    GeoExplode,
    GeoExplodeParams,
    GeoMeasures,
    GeoMeasuresParams,
    GeoOverlay,
    GeoOverlayParams,
    GeometryOp,
    GeometryOpParams,
    SetCrs,
    SetCrsParams,
    SpatialFilter,
    SpatialFilterParams,
    SpatialJoin,
    SpatialJoinParams,
)


@pytest.fixture
def points():
    return gpd.GeoDataFrame(
        {"v": [1.0, 2.0, 3.0, 4.0], "cat": ["a", "a", "b", "b"]},
        geometry=[Point(2.35, 48.85), Point(2.36, 48.86), Point(2.42, 48.80), Point(2.43, 48.81)],
        crs="EPSG:4326",
    )


@pytest.fixture
def zones():
    return gpd.GeoDataFrame(
        {"zone": ["west", "east"]},
        geometry=[
            Polygon([(2.30, 48.75), (2.40, 48.75), (2.40, 48.90), (2.30, 48.90)]),
            Polygon([(2.40, 48.75), (2.50, 48.75), (2.50, 48.90), (2.40, 48.90)]),
        ],
        crs="EPSG:4326",
    )


def test_spatial_join_exact_attaches_zone(points, zones):
    out = SpatialJoin(
        params=SpatialJoinParams(mode="exact", predicate="within", how="inner")
    ).run(left=points, right=zones)["gdf"]
    assert "zone" in out.columns and len(out) == 4


def test_spatial_join_nearest_adds_distance_and_reprojects_the_right_layer(points, zones):
    out = SpatialJoin(
        params=SpatialJoinParams(mode="nearest", distance_col="dist", project_to="auto (UTM)")
    ).run(left=points, right=zones.to_crs("EPSG:3857"))["gdf"]
    assert "dist" in out.columns
    assert out.crs.to_epsg() == 4326  # projected for the calc, restored after


def test_spatial_filter_by_mask_and_by_bbox(points, zones):
    by_mask = SpatialFilter(params=SpatialFilterParams(predicate="within")).run(
        gdf=points, mask=zones.iloc[[0]]
    )["gdf"]
    assert len(by_mask) == 2
    by_bbox = SpatialFilter(
        params=SpatialFilterParams(predicate="intersects", bbox="2.30,48.75,2.40,48.90")
    ).run(gdf=points)["gdf"]
    assert len(by_bbox) == 2
    negated = SpatialFilter(
        params=SpatialFilterParams(predicate="within", negate=True)
    ).run(gdf=points, mask=zones.iloc[[0]])["gdf"]
    assert len(negated) == 2


def test_geo_clip_cuts_to_the_mask(points, zones):
    out = GeoClip(params=GeoClipParams()).run(gdf=points, mask=zones.iloc[[0]])["gdf"]
    assert len(out) == 2


def test_geo_overlay_intersection(zones):
    out = GeoOverlay(params=GeoOverlayParams(how="intersection")).run(
        left=zones, right=zones
    )["gdf"]
    assert len(out) == 2


def test_geo_dissolve_merges_by_group(points):
    out = GeoDissolve(params=GeoDissolveParams(by=["cat"], aggfunc="sum")).run(
        gdf=points
    )["gdf"]
    assert len(out) == 2
    assert "cat" in out.columns and "index" not in out.columns
    assert set(out["v"]) == {3.0, 7.0}


def test_geo_explode_splits_multipart():
    from shapely.geometry import MultiPoint

    gdf = gpd.GeoDataFrame(
        {"k": ["m"]}, geometry=[MultiPoint([(0, 0), (1, 1), (2, 2)])], crs="EPSG:3857"
    )
    out = GeoExplode(params=GeoExplodeParams(index_parts=True)).run(gdf=gdf)["gdf"]
    assert len(out) == 3 and "part" in out.columns


def test_geo_buffer_projects_for_metres_and_restores_crs(points):
    out = GeoBuffer(
        params=GeoBufferParams(distance=250.0, project_to="auto (UTM)")
    ).run(gdf=points)["gdf"]
    assert out.crs.to_epsg() == 4326
    assert (out.geometry.geom_type == "Polygon").all()


def test_geo_buffer_dissolve_merges_overlaps(points):
    out = GeoBuffer(
        params=GeoBufferParams(distance=5000.0, project_to="auto (UTM)", dissolve=True)
    ).run(gdf=points)["gdf"]
    assert len(out) == 1


def test_geo_buffer_raises_on_geographic_crs_without_projection(points):
    with pytest.raises(ValueError, match="geographic CRS"):
        GeoBuffer(params=GeoBufferParams(distance=250.0, project_to="")).run(gdf=points)


@pytest.mark.parametrize(
    "op", ["centroid", "convex_hull", "envelope", "representative_point", "make_valid"]
)
def test_geometry_op_replaces_geometry(zones, op):
    out = GeometryOp(params=GeometryOpParams(operation=op)).run(gdf=zones)["gdf"]
    assert len(out) == len(zones) and out.geometry.notna().all()


def test_geometry_op_simplify_reduces_points(zones):
    dense = zones.copy()
    dense["geometry"] = dense.geometry.segmentize(0.001)
    out = GeometryOp(
        params=GeometryOpParams(operation="simplify", tolerance=0.05)
    ).run(gdf=dense)["gdf"]
    from shapely import get_num_coordinates

    assert get_num_coordinates(out.geometry.iloc[0]) < get_num_coordinates(
        dense.geometry.iloc[0]
    )


def test_geo_measures_appends_columns(zones):
    out = GeoMeasures(
        params=GeoMeasuresParams(
            area=True, length=True, centroid_x=True, centroid_y=True,
            bounds=True, geom_type=True, num_points=True, is_valid=True,
            measure_crs="auto (UTM)",
        )
    ).run(gdf=zones)["gdf"]
    for col in ("area", "length", "centroid_x", "minx", "geom_type", "num_points", "is_valid"):
        assert col in out.columns
    assert (out["area"] > 0).all()  # metric, not degrees-squared


def test_set_crs_labels_without_moving_coordinates(points):
    out = SetCrs(params=SetCrsParams(crs="EPSG:3857", allow_override=True)).run(
        gdf=points
    )["gdf"]
    assert out.crs.to_epsg() == 3857
    assert out.geometry.iloc[0].x == points.geometry.iloc[0].x
