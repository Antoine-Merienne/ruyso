"""
Visualization nodes: turn data into a matplotlib Figure object that
downstream nodes (or the UI canvas) can display or export.
"""

from typing import Any, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import column_field
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


class MatplotlibPlotParams(NodeParams):
    """
    Parameters for MatplotlibPlot.

    Attributes:
        x: Column name to use for the x-axis.
        y: Column name to use for the y-axis.
        kind: Type of plot to draw.
        title: Optional plot title.
    """

    x: str = column_field(dtypes=("any",), description="Column for the x-axis.")
    y: str = column_field(dtypes=("numeric",), description="Column for the y-axis.")
    kind: Literal["scatter", "line", "bar"] = "scatter"
    title: str | None = None


@register_node
class MatplotlibPlot(Node):
    """
    Create a matplotlib Figure from two columns of a DataFrame.

    The figure is returned as an output value (not displayed
    directly), so the caller (engine or UI) decides how/where to
    render or save it. This keeps the node free of any UI dependency.
    """

    node_type = "matplotlib_plot"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = MatplotlibPlotParams
    # matplotlib Figure objects can embed internal masked arrays that
    # joblib's fast hasher cannot process; the figure is cheap to
    # rebuild anyway, so this node always re-runs rather than being cached.
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Draw the configured plot.

        Args:
            df: Input pandas.DataFrame (via the "df" input port).

        Returns:
            {"figure": matplotlib.figure.Figure}
        """
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")  # non-interactive backend, safe for headless/test runs
        import matplotlib.pyplot as plt

        df = inputs["df"]
        fig, ax = plt.subplots()

        if self.params.kind == "scatter":
            ax.scatter(df[self.params.x], df[self.params.y])
        elif self.params.kind == "line":
            ax.plot(df[self.params.x], df[self.params.y])
        elif self.params.kind == "bar":
            ax.bar(df[self.params.x], df[self.params.y])

        ax.set_xlabel(self.params.x)
        ax.set_ylabel(self.params.y)
        if self.params.title:
            ax.set_title(self.params.title)

        return {"figure": fig}