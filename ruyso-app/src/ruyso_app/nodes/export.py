"""
Export nodes: write a pipeline's intermediate or final artifacts to
disk (figures, tables, models, ...). Kept in their own category since
they are typically the last step of a pipeline and, unlike other
nodes, have a side effect on the filesystem rather than producing a
value for further downstream processing.
"""

from typing import Any

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


class FigureExportParams(NodeParams):
    """
    Parameters for FigureExport.

    Attributes:
        filepath: Destination path for the saved image
            (extension determines the format, e.g. ".png", ".svg").
        dpi: Resolution used when saving the figure.
    """

    filepath: str
    dpi: int = 150


@register_node
class FigureExport(Node):
    """
    Save a matplotlib Figure to disk.

    This is a sink node: it has no output ports, only the side effect
    of writing a file. It returns an empty dict, matching the generic
    Node.run() contract (a dict of output port values -- here, no
    output ports are declared, so no entries are expected).
    """

    node_type = "figure_export"
    category = "export"
    inputs = [Port(name="figure", dtype="figure")]
    outputs: list[Port] = []
    params_schema = FigureExportParams
    # Writing a file is a side effect that should happen every time
    # the pipeline runs, and its "figure" input is not reliably
    # hashable by joblib (see MatplotlibPlot.cacheable) - never cache.
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Save the input figure to ``self.params.filepath``.

        Args:
            figure: A matplotlib.figure.Figure (via the "figure" input port).

        Returns:
            {} - this node produces no output port values.
        """
        self.validate_inputs(inputs)
        figure = inputs["figure"]
        figure.savefig(self.params.filepath, dpi=self.params.dpi, bbox_inches="tight")
        return {}
