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


class ExportToDashboardParams(NodeParams):
    """
    Parameters for ExportToDashboard.

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
    # A sink node: the "figure" value is not reliably hashable by joblib
    # (see MatplotlibPlot.cacheable / FigureExport) - never cache.
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Consume the input figure; the Dashboard tab reads it from the
        upstream node's run output (via the ``figure`` input wire), so
        this node itself produces no output port values.

        Args:
            figure: A matplotlib.figure.Figure (via the "figure" input port).

        Returns:
            ``{}`` - this node has no output ports.
        """
        self.validate_inputs(inputs)
        return {}
