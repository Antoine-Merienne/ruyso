"""
Transformer nodes that convert between a plain pandas DataFrame and a
geopandas GeoDataFrame, and reproject a GeoDataFrame.

CRS values are entered through a suggestions dropdown (same widget as
the loaders' datetime-format field): a handful of common EPSG codes,
but any CRS string geopandas accepts is allowed.
"""

from __future__ import annotations

from typing import Any, Literal

import geopandas as gpd
import pandas as pd

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import column_field, suggestions_field, visible_field
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

#: A handful of widely used coordinate reference systems.
COMMON_CRS = [
    "EPSG:4326",   # WGS 84 (lon/lat degrees)
    "EPSG:3857",   # Web Mercator
    "EPSG:2154",   # RGF93 / Lambert-93 (France)
    "EPSG:27700",  # OSGB36 / British National Grid
    "EPSG:4269",   # NAD83
    "EPSG:32633",  # WGS 84 / UTM zone 33N
]


class GeoToDataFrameParams(NodeParams):
    """
    Parameters for GeoToDataFrame.

    Attributes:
        geometry: What to do with the geometry column --
            ``drop`` it, keep it as a ``wkt`` text column, or explode
            points into ``xy`` columns.
        wkt_column / x_column / y_column: names of the columns to
            create (used by the matching ``geometry`` mode).
    """

    geometry: Literal["drop", "wkt", "xy"] = "drop"
    wkt_column: str = visible_field("geometry_wkt", visible_when=("geometry", "wkt"))
    x_column: str = visible_field("x", visible_when=("geometry", "xy"))
    y_column: str = visible_field("y", visible_when=("geometry", "xy"))


@register_node
class GeoToDataFrame(Node):
    """Convert a GeoDataFrame to a plain DataFrame."""

    node_type = "geo_to_dataframe"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = GeoToDataFrameParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        gdf = inputs["gdf"]
        p = self.params
        geom = gdf.geometry
        plain = gdf.drop(columns=[gdf.geometry.name])

        if p.geometry == "wkt":
            plain[p.wkt_column] = geom.to_wkt().to_numpy()
        elif p.geometry == "xy":
            if not (geom.geom_type == "Point").all():
                raise ValueError(
                    "geo_to_dataframe: the 'xy' mode needs an all-Point geometry"
                )
            plain[p.x_column] = geom.x.to_numpy()
            plain[p.y_column] = geom.y.to_numpy()

        return {"df": pd.DataFrame(plain)}


class DataFrameToGeoParams(NodeParams):
    """
    Parameters for DataFrameToGeo.

    Attributes:
        source: Build geometry from two ``xy`` (lon/lat) columns or
            from a single ``wkt`` text column.
        x_column / y_column / wkt_column: the source column(s).
        crs: Coordinate reference system for the result.
    """

    source: Literal["xy", "wkt"] = "xy"
    x_column: str = column_field(
        dtypes=("numeric",), default="", visible_when=("source", "xy")
    )
    y_column: str = column_field(
        dtypes=("numeric",), default="", visible_when=("source", "xy")
    )
    wkt_column: str = column_field(
        dtypes=("any",), default="", visible_when=("source", "wkt")
    )
    crs: str = suggestions_field(suggestions=COMMON_CRS, default="EPSG:4326")


@register_node
class DataFrameToGeo(Node):
    """Convert a DataFrame to a GeoDataFrame."""

    node_type = "dataframe_to_geo"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = DataFrameToGeoParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = inputs["df"].copy()
        p = self.params
        crs = p.crs or None

        if p.source == "wkt":
            geometry = gpd.GeoSeries.from_wkt(df[p.wkt_column])
            df = df.drop(columns=[p.wkt_column])
        else:
            geometry = gpd.points_from_xy(df[p.x_column], df[p.y_column])

        return {"gdf": gpd.GeoDataFrame(df, geometry=geometry, crs=crs)}


class ReprojectParams(NodeParams):
    """Parameters for Reproject.

    Attributes:
        crs: Target coordinate reference system.
    """

    crs: str = suggestions_field(suggestions=COMMON_CRS, default="EPSG:3857")


@register_node
class Reproject(Node):
    """Reproject a GeoDataFrame to another CRS."""

    node_type = "reproject"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = ReprojectParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {"gdf": inputs["gdf"].to_crs(self.params.crs)}
