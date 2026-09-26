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
from ruyso_app.core.params import (
    checkbox_list_field,
    column_field,
    suggestions_field,
    unit_interval_field,
    visible_field,
)
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

#: Sentinel in a CRS dropdown: pick the best UTM zone for the data's extent.
AUTO_UTM = "auto (UTM)"
#: CRS choices for the "project to a metric CRS" fields (buffer / measures /
#: nearest join).
METRIC_CRS_CHOICES = [AUTO_UTM, *COMMON_CRS]


def _resolve_target_crs(gdf: "gpd.GeoDataFrame", value: str) -> Any:
    """A CRS string / estimated-UTM CRS / ``None`` from a metric-CRS field."""
    text = (value or "").strip()
    if not text:
        return None
    if text == AUTO_UTM:
        return gdf.estimate_utm_crs()
    return text


def _project_for_metric(
    gdf: "gpd.GeoDataFrame", project_to: str, ctx: str
) -> tuple["gpd.GeoDataFrame", Any]:
    """
    ``(gdf in a projected CRS, original CRS to restore or None)``.

    Raises when the input is in a geographic CRS and no target CRS was
    given -- distances / areas would otherwise be in degrees.
    """
    target = _resolve_target_crs(gdf, project_to)
    if target is None:
        if gdf.crs is not None and gdf.crs.is_geographic:
            raise ValueError(
                f"{ctx}: the input is in a geographic CRS ({gdf.crs.to_string()}); "
                f"choose a projected CRS (or '{AUTO_UTM}') so the result is in metres."
            )
        return gdf, None
    return gdf.to_crs(target), gdf.crs


def _align_crs(
    primary: "gpd.GeoDataFrame", secondary: "gpd.GeoDataFrame"
) -> "gpd.GeoDataFrame":
    """Reproject ``secondary`` onto ``primary``'s CRS when they differ."""
    if (
        primary.crs is not None
        and secondary.crs is not None
        and secondary.crs != primary.crs
    ):
        return secondary.to_crs(primary.crs)
    return secondary


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


# ==========================================================================
# Relate / combine two layers
# ==========================================================================


class SpatialJoinParams(NodeParams):
    """
    Parameters for SpatialJoin.

    Attributes:
        mode: ``exact`` -- match by a topological ``predicate``;
            ``nearest`` -- match each left feature to its closest right
            feature (``geopandas.sjoin_nearest``).
        predicate: Spatial relationship for ``exact`` mode.
        how: Which side's rows / geometry to keep.
        max_distance: ``nearest`` -- ignore right features farther than
            this (in the working CRS's units; 0 = no limit).
        distance_col: ``nearest`` -- write the match distance to this
            column (blank = don't).
        project_to: ``nearest`` -- project to this CRS for the distance
            computation (blank + a geographic input raises).
    """

    mode: Literal["exact", "nearest"] = "exact"
    predicate: Literal[
        "intersects", "within", "contains", "covers", "covered_by",
        "crosses", "touches", "overlaps",
    ] = visible_field("intersects", visible_when=("mode", "exact"))
    how: Literal["inner", "left", "right"] = "inner"
    max_distance: float = visible_field(0.0, visible_when=("mode", "nearest"))
    distance_col: str = visible_field("", visible_when=("mode", "nearest"))
    project_to: str = suggestions_field(
        suggestions=METRIC_CRS_CHOICES, default=AUTO_UTM,
        visible_when=("mode", "nearest"),
    )


@register_node
class SpatialJoin(Node):
    """Attach a second layer's attributes onto the first by spatial relationship."""

    node_type = "spatial_join"
    category = "transform"
    inputs = [
        Port(name="left", dtype="geodataframe"),
        Port(name="right", dtype="geodataframe"),
    ]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = SpatialJoinParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        left = inputs["left"]
        right = _align_crs(left, inputs["right"])

        if p.mode == "nearest":
            proj_left, original = _project_for_metric(left, p.project_to, "spatial_join")
            proj_right = right.to_crs(proj_left.crs)
            kwargs: dict[str, Any] = {"how": p.how}
            if p.max_distance > 0:
                kwargs["max_distance"] = float(p.max_distance)
            if p.distance_col.strip():
                kwargs["distance_col"] = p.distance_col.strip()
            joined = gpd.sjoin_nearest(proj_left, proj_right, **kwargs)
            if original is not None:
                joined = joined.to_crs(original)
        else:
            joined = gpd.sjoin(left, right, predicate=p.predicate, how=p.how)
        return {"gdf": joined}


class SpatialFilterParams(NodeParams):
    """
    Parameters for SpatialFilter.

    Attributes:
        predicate: Keep a feature when its geometry has this
            relationship to the mask.
        bbox: ``minx,miny,maxx,maxy`` used when no ``mask`` port is
            wired.
        negate: Keep the complement instead.
    """

    predicate: Literal[
        "intersects", "within", "contains", "crosses", "disjoint"
    ] = "intersects"
    bbox: str = ""
    negate: bool = False


@register_node
class SpatialFilter(Node):
    """Keep whole rows whose geometry relates to a mask layer (or a bounding box)."""

    node_type = "spatial_filter"
    category = "transform"
    inputs = [
        Port(name="gdf", dtype="geodataframe"),
        Port(name="mask", dtype="geodataframe", required=False),
    ]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = SpatialFilterParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        gdf = inputs["gdf"]
        mask = inputs.get("mask")

        if mask is not None:
            reference = _align_crs(gdf, mask).union_all()
        else:
            parts = [x.strip() for x in p.bbox.split(",") if x.strip()]
            if len(parts) != 4:
                raise ValueError(
                    "spatial_filter: wire a 'mask' layer or set bbox to "
                    "'minx,miny,maxx,maxy'."
                )
            from shapely.geometry import box

            reference = box(*(float(v) for v in parts))

        keep = getattr(gdf.geometry, p.predicate)(reference)
        if p.negate:
            keep = ~keep
        return {"gdf": gdf[keep].reset_index(drop=True)}


class GeoClipParams(NodeParams):
    """
    Parameters for GeoClip.

    Attributes:
        keep_geom_type: Drop parts whose geometry type changed under the
            clip (e.g. a polygon reduced to a line at the mask edge).
    """

    keep_geom_type: bool = False


@register_node
class GeoClip(Node):
    """Cut every geometry to the boundary of a mask layer (``GeoDataFrame.clip``)."""

    node_type = "geo_clip"
    category = "transform"
    inputs = [
        Port(name="gdf", dtype="geodataframe"),
        Port(name="mask", dtype="geodataframe"),
    ]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeoClipParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        gdf = inputs["gdf"]
        mask = _align_crs(gdf, inputs["mask"])
        return {
            "gdf": gdf.clip(mask, keep_geom_type=self.params.keep_geom_type).reset_index(
                drop=True
            )
        }


class GeoOverlayParams(NodeParams):
    """
    Parameters for GeoOverlay.

    Attributes:
        how: Set operation between the two polygon layers.
        keep_geom_type: Keep only pieces of the original geometry type.
    """

    how: Literal[
        "intersection", "union", "identity", "symmetric_difference", "difference"
    ] = "intersection"
    keep_geom_type: bool = True


@register_node
class GeoOverlay(Node):
    """Polygon set operations between two layers (``geopandas.overlay``)."""

    node_type = "geo_overlay"
    category = "transform"
    inputs = [
        Port(name="left", dtype="geodataframe"),
        Port(name="right", dtype="geodataframe"),
    ]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeoOverlayParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        left = inputs["left"]
        right = _align_crs(left, inputs["right"])
        out = gpd.overlay(left, right, how=p.how, keep_geom_type=p.keep_geom_type)
        return {"gdf": out.reset_index(drop=True)}


# ==========================================================================
# Reshape
# ==========================================================================


class GeoDissolveParams(NodeParams):
    """
    Parameters for GeoDissolve.

    Attributes:
        by: Group key column(s) (tickboxes). Blank = merge every row
            into a single geometry.
        aggfunc: How the non-geometry columns are aggregated per group.
        as_index: Keep the group key as the index instead of a column.
    """

    by: list[str] | None = checkbox_list_field(source="columns", default=None)
    aggfunc: Literal[
        "first", "last", "sum", "mean", "min", "max", "count"
    ] = "first"
    as_index: bool = False


@register_node
class GeoDissolve(Node):
    """Merge the geometries of rows that share a group key (a spatial ``group_by``)."""

    node_type = "geo_dissolve"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeoDissolveParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        gdf = inputs["gdf"]
        by = [c for c in (p.by or []) if c in gdf.columns] or None
        out = gdf.dissolve(by=by, aggfunc=p.aggfunc, as_index=p.as_index)
        if not p.as_index:
            out = out.reset_index(drop=True)
        return {"gdf": out}


class GeoExplodeParams(NodeParams):
    """
    Parameters for GeoExplode.

    Attributes:
        index_parts: Add a ``part`` column numbering the pieces each
            original row was split into.
    """

    index_parts: bool = False


@register_node
class GeoExplode(Node):
    """Split multi-part geometries into one row per part (``GeoDataFrame.explode``)."""

    node_type = "geo_explode"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeoExplodeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        out = inputs["gdf"].explode(index_parts=self.params.index_parts)
        if self.params.index_parts:
            out = out.reset_index(level=-1).rename(columns={"level_1": "part"})
        return {"gdf": out.reset_index(drop=True)}


# ==========================================================================
# Derive geometry / features
# ==========================================================================


class GeoBufferParams(NodeParams):
    """
    Parameters for GeoBuffer.

    Attributes:
        distance: Buffer distance in the working CRS's units (negative
            shrinks polygons).
        project_to: Project to this CRS before buffering, then back
            (blank + a geographic input raises).
        cap_style / join_style: End-cap and corner styles.
        segments: Segments used to approximate a quarter circle.
        single_sided: Buffer only one side of a line.
        dissolve: Merge all the buffers into a single geometry.
    """

    distance: float = 1000.0
    project_to: str = suggestions_field(
        suggestions=METRIC_CRS_CHOICES, default=AUTO_UTM
    )
    cap_style: Literal["round", "flat", "square"] = "round"
    join_style: Literal["round", "mitre", "bevel"] = "round"
    segments: int = 8
    single_sided: bool = False
    dissolve: bool = False


@register_node
class GeoBuffer(Node):
    """Grow or shrink every geometry by a distance (``GeoSeries.buffer``)."""

    node_type = "geo_buffer"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeoBufferParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        projected, original = _project_for_metric(
            inputs["gdf"], p.project_to, "geo_buffer"
        )
        out = projected.copy()
        out["geometry"] = projected.geometry.buffer(
            float(p.distance),
            resolution=max(int(p.segments), 1),
            cap_style=p.cap_style,
            join_style=p.join_style,
            single_sided=bool(p.single_sided),
        )
        if p.dissolve:
            out = gpd.GeoDataFrame(geometry=[out.geometry.union_all()], crs=out.crs)
        if original is not None:
            out = out.to_crs(original)
        return {"gdf": out}


class GeometryOpParams(NodeParams):
    """
    Parameters for GeometryOp.

    Attributes:
        operation: The geometry to put in place of each row's geometry.
        tolerance: Simplification tolerance (``simplify`` only).
        preserve_topology: Keep the result valid / connected
            (``simplify`` only).
        ratio: Concaveness, 0 (very concave) .. 1 (convex hull)
            (``concave_hull`` only).
    """

    operation: Literal[
        "centroid", "representative_point", "convex_hull", "concave_hull",
        "envelope", "boundary", "exterior_ring", "simplify", "make_valid",
    ] = "centroid"
    tolerance: float = visible_field(0.0, visible_when=("operation", "simplify"))
    preserve_topology: bool = visible_field(
        True, visible_when=("operation", "simplify")
    )
    ratio: float = unit_interval_field(
        0.3, visible_when=("operation", "concave_hull")
    )


@register_node
class GeometryOp(Node):
    """Replace each geometry with one derived from it (centroid, hull, simplified, ...)."""

    node_type = "geometry_op"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeometryOpParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        gdf = inputs["gdf"].copy()
        geom = gdf.geometry

        if p.operation == "exterior_ring" and not geom.geom_type.isin(
            ("Polygon",)
        ).all():
            raise ValueError(
                "geometry_op: 'exterior_ring' needs an all-Polygon geometry "
                "(explode MultiPolygons first)."
            )

        op = p.operation
        if op == "centroid":
            new_geom = geom.centroid
        elif op == "representative_point":
            new_geom = geom.representative_point()
        elif op == "convex_hull":
            new_geom = geom.convex_hull
        elif op == "concave_hull":
            new_geom = geom.concave_hull(ratio=float(p.ratio))
        elif op == "envelope":
            new_geom = geom.envelope
        elif op == "boundary":
            new_geom = geom.boundary
        elif op == "exterior_ring":
            new_geom = geom.exterior
        elif op == "simplify":
            new_geom = geom.simplify(
                float(p.tolerance), preserve_topology=bool(p.preserve_topology)
            )
        else:  # make_valid
            new_geom = geom.make_valid()

        gdf["geometry"] = new_geom
        return {"gdf": gdf}


class GeoMeasuresParams(NodeParams):
    """
    Parameters for GeoMeasures.

    Attributes:
        area / length / centroid_x / centroid_y / bounds / geom_type /
        num_points / is_valid: Columns to append (geometry is kept).
        measure_crs: CRS to project to before measuring ``area`` /
            ``length`` (blank + a geographic input raises). Other
            measures use the input CRS.
    """

    area: bool = True
    length: bool = False
    centroid_x: bool = False
    centroid_y: bool = False
    bounds: bool = False
    geom_type: bool = False
    num_points: bool = False
    is_valid: bool = False
    measure_crs: str = suggestions_field(
        suggestions=METRIC_CRS_CHOICES, default=AUTO_UTM
    )


@register_node
class GeoMeasures(Node):
    """Append geometry measurements (area, length, centroid, bounds, ...) as columns."""

    node_type = "geo_measures"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = GeoMeasuresParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        gdf = inputs["gdf"].copy()

        if p.area or p.length:
            metric_geom = _project_for_metric(
                gdf, p.measure_crs, "geo_measures"
            )[0].geometry
            if p.area:
                gdf["area"] = metric_geom.area.to_numpy()
            if p.length:
                gdf["length"] = metric_geom.length.to_numpy()

        if p.centroid_x or p.centroid_y:
            centroid = gdf.geometry.centroid
            if p.centroid_x:
                gdf["centroid_x"] = centroid.x.to_numpy()
            if p.centroid_y:
                gdf["centroid_y"] = centroid.y.to_numpy()
        if p.bounds:
            b = gdf.geometry.bounds
            for col in ("minx", "miny", "maxx", "maxy"):
                gdf[col] = b[col].to_numpy()
        if p.geom_type:
            gdf["geom_type"] = gdf.geometry.geom_type.to_numpy()
        if p.num_points:
            from shapely import get_num_coordinates

            gdf["num_points"] = get_num_coordinates(gdf.geometry.to_numpy())
        if p.is_valid:
            gdf["is_valid"] = gdf.geometry.is_valid.to_numpy()
        return {"gdf": gdf}


# ==========================================================================
# CRS
# ==========================================================================


class SetCrsParams(NodeParams):
    """
    Parameters for SetCrs.

    Attributes:
        crs: The CRS to *assign* (coordinates are left untouched -- use
            ``reproject`` to actually transform them).
        allow_override: Replace an already-set CRS.
    """

    crs: str = suggestions_field(suggestions=COMMON_CRS, default="EPSG:4326")
    allow_override: bool = True


@register_node
class SetCrs(Node):
    """Label a GeoDataFrame's CRS without moving its coordinates (``set_crs``)."""

    node_type = "set_crs"
    category = "transform"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs = [Port(name="gdf", dtype="geodataframe")]
    params_schema = SetCrsParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        return {
            "gdf": inputs["gdf"].set_crs(p.crs, allow_override=bool(p.allow_override))
        }
