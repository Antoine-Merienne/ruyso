"""
The empty-state hint drawn over the canvas while it has no nodes.

The mockups show a centered "+" with a short "add a node" caption on
the blank canvas. This is a transparent-to-mouse ``QLabel`` laid over
the NodeGraphQt viewer: it never intercepts clicks (so the right-click
"New Node" menu still opens through it) and it hides itself as soon as
the graph contains at least one node, reappearing if every node is
deleted.
"""

from __future__ import annotations

from NodeGraphQt import NodeGraph
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QLabel, QWidget

#: Wording of the hint. The interaction is right-click (a left-click
#: popup menu was judged unfriendly), so the caption says so.
HINT_TEXT = "+\n\nRight-click to add a node"


class EmptyCanvasHint(QLabel):
    """A centered, click-through "add a node" hint over an empty canvas."""

    def __init__(self, viewer: QWidget, graph: NodeGraph) -> None:
        """
        Args:
            viewer: The widget to overlay (NodeGraphQt's ``graph.viewer()``).
            graph: The graph to watch for node count changes.
        """
        super().__init__(viewer)
        self._graph = graph

        self.setText(HINT_TEXT)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("color: rgba(255, 255, 255, 90); font-size: 22px;")

        viewer.installEventFilter(self)
        graph.node_created.connect(self._refresh)
        graph.nodes_deleted.connect(self._refresh)
        graph.session_changed.connect(self._refresh)
        self._refresh()

    # -- internals ------------------------------------------------------

    def _refresh(self, *_args: object) -> None:
        """Show the hint only while the graph is empty, and keep it centered."""
        self.setVisible(not self._graph.all_nodes())
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.raise_()

    def eventFilter(self, watched: object, event: QEvent) -> bool:
        if event.type() in (QEvent.Resize, QEvent.Show):
            self._refresh()
        return False
