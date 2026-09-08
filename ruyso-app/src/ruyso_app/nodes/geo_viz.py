"""
Grapher nodes that render a GeoDataFrame as a map.

* :class:`GeoPlot` -- plot the geometries, optionally as a choropleth
  (continuous or a mapclassify scheme), a categorical map, or a bubble
  map, with an optional second overlay layer.
* :class:`GeoDensity` -- a point-density heat-map (hexbin or KDE), the
  map analogue of the ``density_2d`` grapher.

Both output a plain matplotlib ``figure`` port, so they flow into the
on-canvas preview, ``export_to_dashboard`` and ``export_figure`` like
every other grapher. Figures are built with the object-oriented
``Figure`` API (``viz._new_figure``) so nothing leaks into pyplot's
global figure manager.
"""

from __future__ import annotations

from typing import Any, Literal

import geopandas as gpd

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    color_field,
    column_field,
    reactive_choice_field,
    unit_interval_field,
    visible_field,
)
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node
from ruyso_app.nodes.geo_transforms import _align_crs
from ruyso_app.nodes.viz import (
    _BASE_STYLE,
    _COMMON_COLORS,
    _LEGEND_LOCATIONS,
    _new_figure,
)

#: mapclassify scheme names accepted by ``GeoDataFrame.plot(scheme=...)``.
_SCHEMES = Literal[
    "continuous", "quantiles", "equal_interval", "natural_breaks", "std_mean"
]


def _map_finalize(fig: Any, ax: Any, p: Any) -> None:
    """Title / aspect / axis visibility / layout for a map axes."""
    if getattr(p, "equal_aspect", True):
        ax.set_aspect("equal")
    if not getattr(p, "show_axes", False):
        ax.set_axis_off()
    else:
        ax.set_xlabel(getattr(p, "x_label", "") or "", fontsize=p.axis_font_size)
        ax.set_ylabel(getattr(p, "y_label", "") or "", fontsize=p.axis_font_size)
        ax.tick_params(axis="both", labelsize=p.axis_font_size)
    if p.title:
        ax.set_title(
            p.title,
            fontsize=p.title_font_size,
            fontweight="bold" if p.title_bold else "normal",
            fontstyle="italic" if p.title_italic else "normal",
        )
    fig.tight_layout()


class GeoPlotParams(NodeParams):
    """
    Parameters for GeoPlot.

    Attributes:
        color_by: Column to colour by (blank = one ``single_color``). A
            numeric column gives a choroplet; a text / boolean one a
            categorical map.
        classification: For a numeric ``color_by`` -- ``continuous`` (a
            colourbar) or a mapclassify scheme with ``classes`` bins.
        colormap / missing_color: Palette / colour for NaN values.
        single_color / edge_color / line_width: Fill (no ``color_by``),
            outline colour, outline width.
        size_by: Numeric column scaling point size between ``size_min``
            and ``size_max`` (bubble map); blank = fixed ``markersize``.
        alpha: Fill opacity.
        legend / legend_label / legend_location: Legend controls.
        overlay_fill / overlay_color / overlay_line_width: Style for the
            optional second ``overlay`` layer.
        show_axes / equal_aspect: Show the coordinate frame / lock the
            aspect ratio.
    """

    color_by: str = column_field(dtypes=("any",), default="", allow_none=True)
    classification: _SCHEMES = visible_field(
        "continuous", visible_when_set="color_by"
    )
    classes: int = visible_field(5, visible_when_set="color_by")
    colormap: str = reactive_choice_field(
        options="colormaps", depends_on="color_by", default="viridis",
        visible_when_set="color_by",
    )
    missing_color: str = visible_field("lightgrey", visible_when_set="color_by")
    single_color: str = color_field(
        suggestions=_COMMON_COLORS, default="#4c78a8", visible_when=("color_by", "")
    )
    edge_color: str = color_field(suggestions=_COMMON_COLORS, default="white")
    line_width: float = 0.4
    size_by: str = column_field(dtypes=("numeric",), default="", allow_none=True)
    markersize: float = visible_field(12.0, visible_when=("size_by", ""))
    size_min: float = visible_field(5.0, visible_when_set="size_by")
    size_max: float = visible_field(120.0, visible_when_set="size_by")
    alpha: float = unit_interval_field(0.9)
    legend: bool = True
    legend_label: str = ""
    legend_location: _LEGEND_LOCATIONS = "best"
    overlay_fill: bool = False
    overlay_color: str = color_field(suggestions=_COMMON_COLORS, default="black")
    overlay_line_width: float = 0.8
    show_axes: bool = False
    equal_aspect: bool = True

    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    fig_width: float = 6.0
    fig_height: float = 6.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class GeoPlot(Node):
    """Map a GeoDataFrame: plain, choropleth, categorical or bubble, with an overlay."""

    node_type = "geo_plot"
    category = "grapher"
    inputs = [
        Port(name="gdf", dtype="geodataframe"),
        Port(name="overlay", dtype="geodataframe", required=False),
    ]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = GeoPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        p = self.params
        gdf = inputs["gdf"]
        overlay = inputs.get("overlay")
        col = (p.color_by or "").strip()
        size_col = (p.size_by or "").strip()

        with plt.style.context(_BASE_STYLE):
            fig, ax = _new_figure(p)
            kw: dict[str, Any] = {
                "ax": ax,
                "alpha": float(p.alpha),
                "edgecolor": p.edge_color,
                "linewidth": float(p.line_width),
            }

            if col and col in gdf.columns:
                series = gdf[col]
                numeric = pd.api.types.is_numeric_dtype(
                    series
                ) and not pd.api.types.is_bool_dtype(series)
                kw["column"] = col
                kw["legend"] = bool(p.legend)
                legend_kwds = {"title": p.legend_label or col}
                if numeric:
                    kw["cmap"] = p.colormap or "viridis"
                    kw["missing_kwds"] = {"color": p.missing_color, "label": "missing"}
                    if p.classification != "continuous":
                        kw["scheme"] = p.classification
                        if p.classification != "std_mean":
                            kw["k"] = max(int(p.classes), 2)
                        legend_kwds["loc"] = p.legend_location
                        kw["legend_kwds"] = legend_kwds
                else:
                    kw["categorical"] = True
                    kw["cmap"] = p.colormap or "tab10"
                    legend_kwds["loc"] = p.legend_location
                    kw["legend_kwds"] = legend_kwds
            else:
                kw["color"] = p.single_color

            has_points = bool((gdf.geom_type == "Point").any())
            if has_points and size_col and size_col in gdf.columns:
                v = pd.to_numeric(gdf[size_col], errors="coerce")
                lo = float(np.nanmin(v))
                span = (float(np.nanmax(v)) - lo) or 1.0
                scaled = p.size_min + (v - lo) / span * (p.size_max - p.size_min)
                kw["markersize"] = scaled.fillna(p.size_min).to_numpy()
            elif has_points:
                kw["markersize"] = float(p.markersize)

            gdf.plot(**kw)

            if overlay is not None:
                layer = _align_crs(gdf, overlay)
                layer.plot(
                    ax=ax,
                    facecolor=p.overlay_color if p.overlay_fill else "none",
                    edgecolor=p.overlay_color,
                    linewidth=float(p.overlay_line_width),
                )

            _map_finalize(fig, ax, p)
        return {"figure": fig}


class GeoDensityParams(NodeParams):
    """
    Parameters for GeoDensity.

    Attributes:
        kind: ``hexbin`` (binned counts) or ``kde`` (smooth density).
        gridsize: Hexagon resolution (``hexbin``).
        bandwidth: KDE bandwidth, 0 = automatic (``kde``).
        levels / fill: KDE contour count / whether to fill them.
        colormap / alpha: Palette / opacity.
        show_points: Overlay the raw points, lightly.
        boundary_color / boundary_line_width: Style for the optional
            ``boundary`` outline layer.
        show_axes / equal_aspect: Coordinate frame / aspect ratio.
    """

    kind: Literal["hexbin", "kde"] = "hexbin"
    gridsize: int = visible_field(30, visible_when=("kind", "hexbin"))
    bandwidth: float = visible_field(0.0, visible_when=("kind", "kde"))
    levels: int = visible_field(10, visible_when=("kind", "kde"))
    fill: bool = visible_field(True, visible_when=("kind", "kde"))
    colormap: str = reactive_choice_field(
        options="colormaps", depends_on="kind", default="viridis"
    )
    alpha: float = unit_interval_field(0.85)
    show_points: bool = False
    boundary_color: str = color_field(suggestions=_COMMON_COLORS, default="black")
    boundary_line_width: float = 0.8
    show_axes: bool = False
    equal_aspect: bool = True

    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    fig_width: float = 6.0
    fig_height: float = 6.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class GeoDensity(Node):
    """Point-density heat-map on a map (hexbin or KDE) -- the geo ``density_2d``."""

    node_type = "geo_density"
    category = "grapher"
    inputs = [
        Port(name="gdf", dtype="geodataframe"),
        Port(name="boundary", dtype="geodataframe", required=False),
    ]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = GeoDensityParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        p = self.params
        gdf = inputs["gdf"]
        boundary = inputs.get("boundary")
        if not (gdf.geom_type == "Point").all():
            raise ValueError("geo_density: needs an all-Point geometry.")
        x = gdf.geometry.x.to_numpy()
        y = gdf.geometry.y.to_numpy()

        with plt.style.context(_BASE_STYLE):
            fig, ax = _new_figure(p)
            if p.kind == "hexbin":
                ax.hexbin(
                    x, y, gridsize=max(int(p.gridsize), 1),
                    cmap=p.colormap or "viridis", alpha=float(p.alpha), mincnt=1,
                )
            else:
                import seaborn as sns

                sns.kdeplot(
                    x=x, y=y, ax=ax, cmap=p.colormap or "viridis",
                    fill=bool(p.fill), levels=max(int(p.levels), 1),
                    bw_adjust=(float(p.bandwidth) or 1.0), alpha=float(p.alpha),
                )
            if p.show_points:
                ax.scatter(x, y, s=4, color="0.25", alpha=0.35, linewidths=0)
            if boundary is not None:
                _align_crs(gdf, boundary).plot(
                    ax=ax, facecolor="none", edgecolor=p.boundary_color,
                    linewidth=float(p.boundary_line_width),
                )
            _map_finalize(fig, ax, p)
        return {"figure": fig}
