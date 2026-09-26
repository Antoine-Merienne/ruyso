"""
Does this install actually work? ``ruyso --self-test``.

Written for the packaged builds. Everything a freezer gets wrong --
an empty node catalogue, a missing matplotlib style, absent PROJ data,
a Qt platform plugin that did not make it into the bundle -- looks
perfectly fine until something is run, and several of those failures
are *silent*: a missing seaborn dataset does not raise, it downloads.

So this runs a real pipeline inside the packaged app and checks the
things that only break there. It is also an ordinary function, covered
by ``tests/test_selftest.py``, so it cannot rot unnoticed.

Exit code 0 means the install is sound. Anything else names what failed.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

#: One name per node module, so a module that failed to make it into a
#: build is named rather than hidden by another module's node count.
_EXPECTED_NODES = {
    "example_data": "example_data",
    "export": "export_figure",
    "geo_loaders": "geojson_loader",
    "geo_transforms": "set_crs",
    "geo_viz": "geo_plot",
    "loaders": "csv_loader",
    "model_ops": "predict",
    "models": "random_forest_fit",
    "statistics": "normality_test",
    "transforms": "drop_na",
    "viz": "matplotlib_plot",
}

#: What the graphers ask for by name; absent from a bundle, *every*
#: grapher fails, fallback style included (see nodes/viz.py).
_REQUIRED_STYLE = "seaborn-v0_8-whitegrid"


@contextmanager
def _no_network() -> Iterator[None]:
    """
    Make any socket attempt raise, for the duration.

    The bundled seaborn datasets are the reason: ``sns.load_dataset``
    falls back to fetching from GitHub when the local cache is missing,
    so "the pipeline ran" proves nothing about whether the data files
    were collected. Here, a download is a failure.
    """
    real_socket = socket.socket

    def refuse(*_args, **_kwargs):
        raise AssertionError(
            "the self-test tried to reach the network -- a bundled data "
            "file is missing and something fell back to downloading it"
        )

    socket.socket = refuse  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket = real_socket  # type: ignore[assignment]


def run() -> int:
    """Check this install end to end; return a process exit code."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    # Never write the real user's settings from a smoke test.
    config_dir = tempfile.mkdtemp(prefix="ruyso-selftest-")
    os.environ["RUYSO_CONFIG_DIR"] = config_dir

    from ruyso_app import __version__
    from ruyso_app.engine import settings

    # The disk cache would answer from a previous run and hide exactly
    # what this is looking for: with it on, a build whose bundled
    # datasets are missing still "runs the pipeline", served from
    # ~/.ruyso_app/cache. Every check below has to do the real work.
    settings.set("cache.enabled", False)

    checks: list[str] = []

    try:
        # 1. every node module present, not merely a plausible count
        import ruyso_app.nodes
        from ruyso_app.core.registry import NodeRegistry

        NodeRegistry.discover_package(ruyso_app.nodes)
        registered = NodeRegistry.all()
        missing = {
            module: node_type
            for module, node_type in _EXPECTED_NODES.items()
            if node_type not in registered
        }
        if missing:
            raise AssertionError(f"node modules missing from this build: {missing}")
        checks.append(f"{len(registered)} nodes")

        # 2. matplotlib's style data
        import matplotlib.pyplot as plt

        if _REQUIRED_STYLE not in plt.style.available:
            raise AssertionError(
                f"{_REQUIRED_STYLE!r} missing -- matplotlib's stylelib was not "
                "collected, and every grapher fails without it"
            )
        checks.append("styles")

        # 3. a real pipeline, with the network closed
        from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph
        from ruyso_app.engine.scheduler import PipelineScheduler

        graph = PipelineGraph()
        graph.add_node(
            NodeSpec(
                id="data",
                node_type="example_data",
                params={"dataset": "seaborn/penguins"},
            )
        )
        graph.add_node(
            NodeSpec(id="clean", node_type="drop_na", params={}),
        )
        graph.add_node(
            NodeSpec(
                id="plot",
                node_type="matplotlib_plot",
                params={"x": "bill_length_mm", "y": "bill_depth_mm"},
            )
        )
        graph.add_connection(
            Connection(
                source_node="data", source_port="df",
                target_node="clean", target_port="df",
            )
        )
        graph.add_connection(
            Connection(
                source_node="clean", source_port="df",
                target_node="plot", target_port="df",
            )
        )
        with _no_network():
            report = PipelineScheduler().run(graph)
        if report.errors:
            raise AssertionError(
                "pipeline failed: "
                + "; ".join(f"{node}: {err}" for node, err in report.errors.items())
            )
        figure = report.outputs["plot"]["figure"]
        checks.append("pipeline")

        # 4. the figure actually rasterises and vectorises
        from ruyso_app.ui.node_preview import figure_to_png_bytes, figure_to_svg_bytes

        png = figure_to_png_bytes(figure, width_px=320)
        svg = figure_to_svg_bytes(figure)
        if len(png) < 5_000 or not svg.lstrip().startswith(b"<?xml"):
            raise AssertionError("figure rendering produced nothing usable")
        checks.append("rendering")

        # 5. PROJ / GDAL data, which the geo nodes cannot work without
        import geopandas as gpd
        import pyproj
        from shapely.geometry import Point

        if pyproj.CRS("EPSG:4326").to_epsg() != 4326:
            raise AssertionError("pyproj cannot resolve EPSG:4326 (proj.db missing)")
        frame = gpd.GeoDataFrame(
            {"name": ["a", "b"]},
            geometry=[Point(2.35, 48.85), Point(-0.13, 51.5)],
            crs="EPSG:4326",
        )
        frame.to_crs("EPSG:3857")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.geojson"
            frame.to_file(path, driver="GeoJSON")
            if len(gpd.read_file(path)) != 2:
                raise AssertionError("GeoJSON round trip lost rows")
        checks.append("geo")

        # 6. the window itself: Qt plugins, NodeGraphQt, the whole stack
        from PySide6.QtWidgets import QApplication

        from ruyso_app.ui.main_window import MainWindow

        app = QApplication.instance() or QApplication([])
        window = MainWindow()
        window.close()
        app.processEvents()
        del window
        checks.append("window")

    except Exception as exc:  # noqa: BLE001 - the whole point is to report it
        print(f"self-test FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"Ruyso {__version__} - " + ", ".join(checks) + " - OK")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via the app entry
    sys.exit(run())
