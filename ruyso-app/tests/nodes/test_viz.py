"""
Tests for the visualization node (MatplotlibPlot): known input
DataFrame -> a valid matplotlib Figure with the expected labels.
"""

import matplotlib
import pandas as pd

matplotlib.use("Agg")  # ensure headless backend before importing pyplot anywhere
from matplotlib.figure import Figure

from pipeline_app.nodes.viz import MatplotlibPlot, MatplotlibPlotParams


def test_matplotlib_plot_returns_a_figure_with_correct_labels():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]})
    node = MatplotlibPlot(params=MatplotlibPlotParams(x="x", y="y", title="Test plot"))

    result = node.run(df=df)

    fig = result["figure"]
    assert isinstance(fig, Figure)
    ax = fig.axes[0]
    assert ax.get_xlabel() == "x"
    assert ax.get_ylabel() == "y"
    assert ax.get_title() == "Test plot"


def test_matplotlib_plot_supports_line_and_bar_kinds():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]})

    for kind in ("scatter", "line", "bar"):
        node = MatplotlibPlot(params=MatplotlibPlotParams(x="x", y="y", kind=kind))
        result = node.run(df=df)
        assert isinstance(result["figure"], Figure)
