"""
Tests for the export nodes: ``figure_export`` writes an image file,
``export_to_dashboard`` passes its figure through unchanged for the
Dashboard tab to pick up.
"""

import matplotlib

matplotlib.use("Agg")  # headless backend before any pyplot import
import matplotlib.pyplot as plt

from ruyso_app.nodes.export import (
    ExportToDashboard,
    ExportToDashboardParams,
    FigureExport,
    FigureExportParams,
)


def test_figure_export_writes_a_file(tmp_path):
    path = tmp_path / "out.png"
    node = FigureExport(params=FigureExportParams(filepath=str(path)))

    result = node.run(figure=plt.figure())

    assert result == {}
    assert path.exists() and path.stat().st_size > 0


def test_export_to_dashboard_is_a_sink():
    node = ExportToDashboard(params=ExportToDashboardParams(title="My chart"))

    result = node.run(figure=plt.figure())

    assert result == {}  # no output ports


def test_export_to_dashboard_ports_and_defaults():
    assert ExportToDashboard.category == "export"
    assert [p.name for p in ExportToDashboard.inputs] == ["figure"]
    assert ExportToDashboard.outputs == []
    assert ExportToDashboard.cacheable is False
    assert ExportToDashboardParams().title == ""
