"""
Tests for the map grapher nodes (``nodes.geo_viz``): a GeoDataFrame in,
a matplotlib Figure out -- plain map, choropleth (continuous + schemes),
categorical map, bubble map, an overlay layer, and the density map.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as _plt
import geopandas as gpd
import numpy as np
import pytest
from matplotlib.figure import Figure
from shapely.geometry import Point, Polygon

from ruyso_app.nodes.geo_viz import (
    GeoDensity,
    GeoDensityParams,
    GeoPlot,
    GeoPlotParams,
)


@pytest.fixture
def points():
    rng = np.random.default_rng(0)
    n = 80
    return gpd.GeoDataFrame(
        {"val": rng.gamma(2.0, 2.0, n), "cat": rng.choice(["x", "y", "z"], n)},
        geometry=[
            Point(rng.normal(2.35, 0.04), rng.normal(48.85, 0.04)) for _ in range(n)
        ],
        crs="EPSG:4326",
    )


@pytest.fixture
def zones():
    g = gpd.GeoDataFrame(
        {"pop": [1000.0, 4200.0, 800.0]},
        geometry=[
            Polygon([(2.2, 48.7), (2.35, 48.7), (2.35, 49.0), (2.2, 49.0)]),
            Polygon([(2.35, 48.7), (2.5, 48.7), (2.5, 49.0), (2.35, 49.0)]),
            Polygon([(2.5, 48.7), (2.65, 48.7), (2.65, 49.0), (2.5, 49.0)]),
        ],
        crs="EPSG:4326",
    )
    return g


def _oo(fig):
    assert isinstance(fig, Figure)
    assert fig not in [_plt.figure(k) for k in _plt.get_fignums()] if _plt.get_fignums() else True
    return fig


def test_geo_plot_plain(points):
    _oo(GeoPlot(params=GeoPlotParams()).run(gdf=points)["figure"])


def test_geo_plot_continuous_choropleth_adds_a_colourbar(zones):
    fig = _oo(
        GeoPlot(
            params=GeoPlotParams(color_by="pop", classification="continuous")
        ).run(gdf=zones)["figure"]
    )
    assert len(fig.axes) == 2  # map + colourbar


@pytest.mark.parametrize(
    "scheme", ["quantiles", "equal_interval", "natural_breaks", "std_mean"]
)
def test_geo_plot_classification_schemes(zones, scheme):
    fig = _oo(
        GeoPlot(
            params=GeoPlotParams(color_by="pop", classification=scheme, classes=3)
        ).run(gdf=zones)["figure"]
    )
    assert fig.axes[0].get_legend() is not None


def test_geo_plot_categorical_map(points):
    fig = GeoPlot(params=GeoPlotParams(color_by="cat")).run(gdf=points)["figure"]
    assert fig.axes[0].get_legend() is not None


def test_geo_plot_bubble_map_scales_marker_size(points):
    ax = GeoPlot(
        params=GeoPlotParams(size_by="val", size_min=5.0, size_max=90.0)
    ).run(gdf=points)["figure"].axes[0]
    assert len(np.unique(ax.collections[0].get_sizes())) > 1


def test_geo_plot_overlay_layer_is_reprojected_and_drawn(points, zones):
    fig = GeoPlot(params=GeoPlotParams(color_by="val")).run(
        gdf=points, overlay=zones.to_crs("EPSG:3857")
    )["figure"]
    _oo(fig)


def test_geo_plot_axes_hidden_by_default_shown_on_request(points):
    off = GeoPlot(params=GeoPlotParams()).run(gdf=points)["figure"].axes[0]
    assert off.axison is False
    on = GeoPlot(params=GeoPlotParams(show_axes=True)).run(gdf=points)["figure"].axes[0]
    assert on.axison is True


@pytest.mark.parametrize("kind", ["hexbin", "kde"])
def test_geo_density(points, zones, kind):
    fig = GeoDensity(
        params=GeoDensityParams(kind=kind, show_points=True)
    ).run(gdf=points, boundary=zones)["figure"]
    _oo(fig)


def test_geo_density_rejects_non_point_geometry(zones):
    with pytest.raises(ValueError, match="Point"):
        GeoDensity(params=GeoDensityParams()).run(gdf=zones)
