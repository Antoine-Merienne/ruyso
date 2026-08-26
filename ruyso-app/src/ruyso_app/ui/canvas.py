"""
The node-graph canvas: a thin wrapper around ``NodeGraphQt.NodeGraph``
that applies this app's visual theme and registers every node type
discovered in ``ruyso_app.nodes``.

Kept deliberately small: NodeGraphQt already provides panning,
zooming, selection, and connecting ports out of the box, plus a
Tab-triggered "add node" search once node classes are registered on
the graph -- this module's only job is that registration, plus
applying ``ui.theme``'s canvas colors.
"""

from __future__ import annotations

from NodeGraphQt import NodeGraph

from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import register_all_nodes


class PipelineCanvas:
    """Wraps a NodeGraphQt ``NodeGraph`` configured for this application."""

    def __init__(self) -> None:
        self.graph = NodeGraph()
        self.graph.set_background_color(*theme.CANVAS_BACKGROUND_COLOR)
        register_all_nodes(self.graph)

    @property
    def widget(self):
        """The QWidget to embed in the main window (the visible canvas area)."""
        return self.graph.widget
