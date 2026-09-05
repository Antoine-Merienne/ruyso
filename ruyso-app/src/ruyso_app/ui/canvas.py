"""
The node-graph canvas: a thin wrapper around ``NodeGraphQt.NodeGraph``
that applies this app's visual theme and registers every node type
discovered in ``ruyso_app.nodes``.

Kept deliberately small: NodeGraphQt provides selection and port
connecting out of the box; this module registers every node type,
applies ``ui.theme``'s canvas colors, and installs
``CanvasNavigation`` to remap pan / zoom to mouse and trackpad gestures.
"""

from __future__ import annotations

from NodeGraphQt import NodeGraph

from ruyso_app.ui import theme
from ruyso_app.ui.canvas_nav import CanvasNavigation
from ruyso_app.ui.node_factory import register_all_nodes


class PipelineCanvas:
    """Wraps a NodeGraphQt ``NodeGraph`` configured for this application."""

    def __init__(self) -> None:
        self.graph = NodeGraph()
        register_all_nodes(self.graph)
        self._navigation = CanvasNavigation(self.graph.viewer())
        self.apply_theme()

    @property
    def widget(self):
        """The QWidget to embed in the main window (the visible canvas area)."""
        return self.graph.widget

    def apply_theme(self) -> None:
        """Re-read colors from the current :mod:`ui.theme` and repaint.

        Repaints the canvas background and recolors every node already
        on the canvas by its macro type, so a live theme toggle (see
        ``MainWindow._apply_theme``) takes effect immediately without
        rebuilding the graph. Node classes carry ``CORE_NODE_CLASS``
        (set by ``node_factory``); a node without it is a NodeGraphQt
        built-in and is left untouched.
        """
        active = theme.current_theme()
        self.graph.set_background_color(*active.canvas_background)
        for node in self.graph.all_nodes():
            core_cls = getattr(type(node), "CORE_NODE_CLASS", None)
            if core_cls is not None:
                node.set_color(*theme.color_for_category(core_cls.category, active))
