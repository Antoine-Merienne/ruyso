"""
Geospatial data-loading nodes: read a vector file from disk into a
geopandas ``GeoDataFrame``.

These share ``LoaderParams`` with the plain loaders but output a
``geodataframe`` port. A ``GeoDataFrame`` is a pandas ``DataFrame``
subclass, so that output can still be wired into any node expecting a
plain ``dataframe`` (see the dtype compatibility rule in
``engine.graph``).
"""

from __future__ import annotations

from typing import Any

import geopandas as gpd
from pydantic import Field

from ruyso_app.core.node import Node
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node
from ruyso_app.nodes.loaders import LoaderParams


@register_node
class GeoJSONLoader(Node):
    """Load a GeoJSON file into a GeoDataFrame."""

    node_type = "geojson_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = LoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {"gdf": gpd.read_file(self.params.filepath)}


@register_node
class ShapefileLoader(Node):
    """Load an ESRI Shapefile (``.shp``) into a GeoDataFrame."""

    node_type = "shapefile_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = LoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {"gdf": gpd.read_file(self.params.filepath)}


class GeoPackageLoaderParams(LoaderParams):
    """Parameters for :class:`GeoPackageLoader`."""

    layer: str | None = Field(
        default=None,
        description="Layer name to read. Blank = the file's first layer.",
    )


@register_node
class GeoPackageLoader(Node):
    """Load one layer of a GeoPackage (``.gpkg``) into a GeoDataFrame."""

    node_type = "geopackage_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeoPackageLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {"gdf": gpd.read_file(self.params.filepath, layer=self.params.layer or None)}
