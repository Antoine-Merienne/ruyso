"""
Export nodes: write a pipeline's intermediate or final artifacts to
disk (figures, tables, geodata), or hand a figure to the Dashboard
tab. Kept in their own category since they are typically the last step
of a pipeline and, unlike other nodes, have a side effect on the
filesystem rather than producing a value for further downstream
processing.

Each export node has an explicit ``format`` dropdown -- that is what
decides the file type; the extension is appended to ``filepath`` if it
is missing or wrong.
"""

from pathlib import Path
from typing import Any, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import visible_field
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

#: format -> the file extension it should carry.
_FIGURE_EXT = {
    "png": ".png", "jpeg": ".jpg", "pdf": ".pdf", "svg": ".svg",
    "tiff": ".tiff", "webp": ".webp", "eps": ".eps",
}
_TABLE_EXT = {
    "csv": ".csv", "tsv": ".tsv", "xlsx": ".xlsx",
    "parquet": ".parquet", "feather": ".feather", "json": ".json",
}
_GEO_EXT = {
    "geojson": ".geojson", "gpkg": ".gpkg", "geoparquet": ".parquet",
    "geofeather": ".feather", "shapefile": ".shp",
}


def _resolve_path(filepath: str, ext: str) -> str:
    """Return ``filepath`` with ``ext`` appended unless it already ends in it."""
    path = Path(filepath)
    if path.suffix.lower() != ext:
        path = path.with_name(path.name + ext)
    return str(path)


# ==========================================================================
# figure
# ==========================================================================


class ExportFigureParams(NodeParams):
    """
    Attributes:
        filepath: Destination path (the extension is fixed up from
            ``format`` if missing).
        format: Image format to write.
        dpi: Resolution for the raster formats.
        transparent: Save with a transparent background.
        bbox_tight: Trim surrounding whitespace to the drawn content.
    """

    filepath: str
    format: Literal["png", "jpeg", "pdf", "svg", "tiff", "webp", "eps"] = "png"
    dpi: int = 150
    transparent: bool = False
    bbox_tight: bool = True


@register_node
class ExportFigure(Node):
    """Save a matplotlib Figure to disk in a chosen image format."""

    node_type = "export_figure"
    category = "export"
    inputs = [Port(name="figure", dtype="figure")]
    outputs: list[Port] = []
    params_schema = ExportFigureParams
    tagline = "Write a figure to PNG / JPEG / PDF / SVG / TIFF / WEBP / EPS."
    # Writing a file is a side effect that must run every time; the
    # "figure" input is not reliably hashable by joblib. Never cache.
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        path = _resolve_path(p.filepath, _FIGURE_EXT[p.format])
        inputs["figure"].savefig(
            path,
            format=p.format,
            dpi=int(p.dpi),
            transparent=bool(p.transparent),
            bbox_inches="tight" if p.bbox_tight else None,
        )
        return {}


# ==========================================================================
# table
# ==========================================================================


class ExportTableParams(NodeParams):
    """
    Attributes:
        filepath: Destination path (extension fixed up from ``format``).
        format: Table format to write.
        include_index: Write the DataFrame index as a column.
        sheet_name: Worksheet name (Excel only).
    """

    filepath: str
    format: Literal["csv", "tsv", "xlsx", "parquet", "feather", "json"] = "csv"
    include_index: bool = False
    sheet_name: str = visible_field("Sheet1", visible_when=("format", "xlsx"))


@register_node
class ExportTable(Node):
    """Write a DataFrame to disk as CSV / TSV / Excel / Parquet / Feather / JSON."""

    node_type = "export_table"
    category = "export"
    inputs = [Port(name="table", dtype="dataframe")]
    outputs: list[Port] = []
    params_schema = ExportTableParams
    tagline = "Write a table to CSV / TSV / Excel / Parquet / Feather / JSON."
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        df = inputs["table"]
        path = _resolve_path(p.filepath, _TABLE_EXT[p.format])
        idx = bool(p.include_index)

        if p.format == "csv":
            df.to_csv(path, index=idx)
        elif p.format == "tsv":
            df.to_csv(path, sep="\t", index=idx)
        elif p.format == "xlsx":
            df.to_excel(path, index=idx, sheet_name=p.sheet_name or "Sheet1")
        elif p.format == "parquet":
            df.to_parquet(path, index=idx)
        elif p.format == "feather":
            (df.reset_index() if idx else df).to_feather(path)
        else:  # json
            df.to_json(path, orient="records", indent=2)
        return {}


# ==========================================================================
# geodata
# ==========================================================================


class ExportGeodataParams(NodeParams):
    """
    Attributes:
        filepath: Destination path (extension fixed up from ``format``;
            a Shapefile also writes .shx/.dbf/.prj beside it).
        format: Vector format to write.
        layer_name: Layer name (GeoPackage only).
    """

    filepath: str
    format: Literal[
        "geojson", "gpkg", "geoparquet", "geofeather", "shapefile"
    ] = "geojson"
    layer_name: str = visible_field("", visible_when=("format", "gpkg"))


@register_node
class ExportGeodata(Node):
    """Write a GeoDataFrame to disk as GeoJSON / GeoPackage / GeoParquet / GeoFeather / Shapefile."""

    node_type = "export_geodata"
    category = "export"
    inputs = [Port(name="gdf", dtype="geodataframe")]
    outputs: list[Port] = []
    params_schema = ExportGeodataParams
    tagline = "Write geodata to GeoJSON / GPKG / GeoParquet / GeoFeather / Shapefile."
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        gdf = inputs["gdf"]
        path = _resolve_path(p.filepath, _GEO_EXT[p.format])

        if p.format == "geojson":
            gdf.to_file(path, driver="GeoJSON")
        elif p.format == "gpkg":
            gdf.to_file(path, driver="GPKG", layer=p.layer_name or None)
        elif p.format == "geoparquet":
            gdf.to_parquet(path)
        elif p.format == "geofeather":
            gdf.to_feather(path)
        else:  # shapefile
            gdf.to_file(path, driver="ESRI Shapefile")
        return {}


# ==========================================================================
# dashboard sink
# ==========================================================================


class ExportToDashboardParams(NodeParams):
    """
    Attributes:
        title: Heading shown above the figure on the Dashboard tab. It
            seeds the dashboard block's editable title; leave blank for
            no heading.
    """

    title: str = ""


@register_node
class ExportToDashboard(Node):
    """
    Send a figure (a grapher plot or a ``table_viewer`` table) to the
    Dashboard tab.

    Wiring a grapher's ``figure`` output into this node makes a
    matching, movable/resizable figure block appear on the Dashboard,
    where it is arranged next to other figures and free-text
    commentary and exported to PDF / PNG. The block stays keyed to
    this node and re-renders in place on every run.

    This is a sink node: it has no output ports. The Dashboard reads
    the figure from the upstream node's own run output, following this
    node's ``figure`` input wire.
    """

    node_type = "export_to_dashboard"
    category = "export"
    inputs = [Port(name="figure", dtype="figure")]
    outputs: list[Port] = []
    params_schema = ExportToDashboardParams
    tagline = "Send a figure or table to the Dashboard tab."
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {}
