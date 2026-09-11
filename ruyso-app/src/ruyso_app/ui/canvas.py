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
from NodeGraphQt.constants import ViewerEnum
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame

from ruyso_app.engine import settings
from ruyso_app.ui import theme
from ruyso_app.ui.canvas_grid import install_dot_grid
from ruyso_app.ui.canvas_nav import CanvasNavigation
from ruyso_app.ui.node_factory import register_all_nodes

#: ``appearance.canvas_grid`` -> the NodeGraphQt grid mode it means.
_GRID_MODES = {
    "none": ViewerEnum.GRID_DISPLAY_NONE.value,
    "dots": ViewerEnum.GRID_DISPLAY_DOTS.value,
    "lines": ViewerEnum.GRID_DISPLAY_LINES.value,
}


def _grid_color(background: tuple[int, int, int]) -> tuple[int, int, int]:
    """
    A dot colour one step away from the canvas background.

    NodeGraphQt's own grid colour is a fixed near-black, which reads as
    heavy charcoal dots on the light theme's warm white. Deriving it
    from the background instead keeps the grid a hint in both themes.
    """
    colour = QColor(*background)
    colour = colour.lighter(260) if colour.value() < 128 else colour.darker(115)
    return colour.red(), colour.green(), colour.blue()


class PipelineCanvas:
    """Wraps a NodeGraphQt ``NodeGraph`` configured for this application."""

    def __init__(self) -> None:
        install_dot_grid()  # small round dots instead of NodeGraphQt's squares
        self.graph = NodeGraph()
        register_all_nodes(self.graph)
        self._navigation = CanvasNavigation(self.graph.viewer())
        self.graph.node_created.connect(self.snap_node)
        # The viewer reports a finished drag; NodeGraphQt uses the same
        # signal to push the undo command, so snapping here lands after
        # the move rather than fighting the pointer during it.
        self.graph.viewer().moved_nodes.connect(lambda _data: self.snap_selection())
        self.graph.viewer().setFrameShape(QFrame.NoFrame)
        self.apply_theme()
        self.apply_preferences()

    def apply_preferences(self) -> None:
        """Re-read the Appearance preferences that shape the canvas."""
        mode = str(settings.get("appearance.canvas_grid"))
        self.graph.set_grid_mode(_GRID_MODES.get(mode, ViewerEnum.GRID_DISPLAY_DOTS.value))

    def grid_size(self) -> int:
        """Spacing, in scene units, that snapping rounds to."""
        try:
            size = int(settings.get("appearance.grid_size"))
        except (TypeError, ValueError):
            return 0
        return size if size > 1 else 0

    def snapping_enabled(self) -> bool:
        return bool(settings.get("appearance.snap_to_grid")) and self.grid_size() > 0

    def snap_node(self, node) -> None:
        """
        Round one node's position to the grid.

        NodeGraphQt draws a grid but has no notion of snapping to it, so
        this is ours: nodes are rounded on creation and after a drag
        (see :meth:`snap_selection`), rather than continuously during
        the drag, which would fight the pointer.
        """
        size = self.grid_size()
        if not self.snapping_enabled():
            return
        try:
            x, y = node.pos()
            node.set_pos(round(x / size) * size, round(y / size) * size)
        except Exception:  # noqa: BLE001 - never let a snap break a drag
            return

    def snap_selection(self) -> None:
        """Snap every selected node -- called when a drag finishes."""
        if not self.snapping_enabled():
            return
        for node in self.graph.selected_nodes():
            self.snap_node(node)

    @property
    def widget(self):
        """
        The QWidget to embed in the main window (the visible canvas area).

        ``graph.widget`` is a ``QTabWidget`` NodeGraphQt builds lazily
        around the viewer, and its constructor sets a stylesheet
        painting NodeGraphQt's own near-black background -- which read
        as a black band around the canvas on the light theme. It is
        cleared here, on the way out, rather than in ``__init__``:
        building that wrapper for a canvas nobody shows (every canvas
        in the test suite) changes the teardown order enough to
        reintroduce the QUndoStack exit-139 crash.
        """
        widget = self.graph.widget
        if widget.styleSheet():
            widget.setStyleSheet("")
        return widget

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
        self.graph.set_grid_color(*_grid_color(active.canvas_background))
        for node in self.graph.all_nodes():
            core_cls = getattr(type(node), "CORE_NODE_CLASS", None)
            if core_cls is not None:
                node.set_color(*theme.color_for_category(core_cls.category, active))
            # The node's body and its labels are the *theme's* colours,
            # not the macro type's, so they need re-reading too.
            refresh = getattr(node.view, "apply_theme", None)
            if refresh is not None:
                refresh()
