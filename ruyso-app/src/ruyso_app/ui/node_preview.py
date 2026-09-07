"""
On-canvas figure previews for nodes that produce or consume a figure
(grapher nodes, and figure sinks such as
``figure_export``).

Design decision (spec section 8 -- "a window appears behind / attached
to the node"): the earlier version embedded a widget *inside* the node
via NodeGraphQt's ``add_custom_widget``. That was replaced because an
always-on embedded canvas is heavy and clutters the graph. Instead:

* Each eligible node gets a small **floating thumbnail** parented to
  the NodeGraphQt viewport, positioned just beneath the node and
  scaled with it. Its geometry is re-synced to the node on a light
  timer (plus immediately on scroll), which is simpler and steadier
  than trying to push a ``QWidget`` behind ``QGraphicsItem`` nodes
  (Qt always paints child widgets over the scene, so a true "behind"
  is not possible -- "attached beneath" is the honest version).
* Before a run the thumbnail shows a placeholder
  ("run pipeline to render graph" / "... test"); after a run it shows
  a bitmap of the resolved figure.
* Clicking a thumbnail opens a **resizable window** sized to the
  figure's own aspect ratio (:class:`FigureWindow`), which is how you
  actually read the plot when several are on the canvas.

Only this module knows how to turn a run's ``{node_id: {port: value}}``
outputs into "the figure for this node".
"""

from __future__ import annotations

from typing import Any

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from NodeGraphQt import BaseNode, NodeGraph
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

#: dtype used by core ``Port``s that carry a matplotlib figure.
FIGURE_DTYPE = "figure"

#: Macro types that always get a preview even if their ports are not
#: figure-typed (a statistical test renders a table/plot of results).
_ALWAYS_PREVIEW_CATEGORIES = frozenset({"grapher"})

#: Thumbnail size on screen at 1:1 zoom, in pixels.
_THUMB_W = 180
_THUMB_H = 120

#: Timer interval (ms) for re-syncing thumbnail positions to their nodes.
_SYNC_INTERVAL_MS = 60


# --------------------------------------------------------------------------
# figure resolution
# --------------------------------------------------------------------------


def is_figure_core_class(core_cls: type | None) -> bool:
    """Whether a core ``Node`` subclass should get an on-canvas figure preview."""
    if core_cls is None:
        return False
    if core_cls.category == "export":
        # Export / sink nodes (figure_export, export_to_dashboard) carry
        # a figure-typed *input* but are not previewed on the canvas --
        # the figure is shown by the sink they feed (a file, the
        # Dashboard tab), not next to the export node.
        return False
    if core_cls.category in _ALWAYS_PREVIEW_CATEGORIES:
        return True
    ports = list(core_cls.inputs) + list(core_cls.outputs)
    return any(getattr(p, "dtype", None) == FIGURE_DTYPE for p in ports)


def is_figure_node(node: BaseNode) -> bool:
    """Whether ``node`` should get an on-canvas figure preview."""
    return is_figure_core_class(getattr(type(node), "CORE_NODE_CLASS", None))


def placeholder_text_for_category(category: str) -> str:
    """
    Placeholder shown before the pipeline has been run, per the spec:
    "run pipeline to render graph" for grapher nodes, "run pipeline to
    render graph".
    """
    kind = "graph"
    return f"run pipeline to render {kind}"


def resolve_figure(node: BaseNode, outputs: dict[str, dict]) -> Figure | None:
    """
    Find the matplotlib figure associated with ``node`` in a run's outputs.

    * A node with a figure *output* port -> that output value.
    * A node with only a figure *input* port (e.g. ``figure_export``)
      -> the value on the upstream output port feeding it.
    * Otherwise -> ``None``.
    """
    core_cls = getattr(type(node), "CORE_NODE_CLASS", None)
    if core_cls is None:
        return None

    node_outputs = outputs.get(node.name(), {})
    for port in core_cls.outputs:
        if getattr(port, "dtype", None) == FIGURE_DTYPE and port.name in node_outputs:
            value = node_outputs[port.name]
            return value if _looks_like_figure(value) else None

    for port in core_cls.inputs:
        if getattr(port, "dtype", None) != FIGURE_DTYPE:
            continue
        canvas_port = node.inputs().get(port.name)
        connected = canvas_port.connected_ports() if canvas_port is not None else []
        if not connected:
            continue
        upstream_port = connected[0]
        value = outputs.get(upstream_port.node().name(), {}).get(upstream_port.name())
        if _looks_like_figure(value):
            return value
    return None


def resolve_source_node(node: BaseNode) -> BaseNode | None:
    """
    The node feeding ``node``'s ``figure`` input port, if any.

    Used by the Dashboard tab: an ``export_to_dashboard`` node's block
    is edited through the parameter form of the *plot* node upstream of
    it (the grapher / ``table_viewer`` that actually renders the
    figure), not the export node itself.
    """
    core_cls = getattr(type(node), "CORE_NODE_CLASS", None)
    if core_cls is None:
        return None
    for port in core_cls.inputs:
        if getattr(port, "dtype", None) != FIGURE_DTYPE:
            continue
        canvas_port = node.inputs().get(port.name)
        connected = canvas_port.connected_ports() if canvas_port is not None else []
        if connected:
            return connected[0].node()
    return None


def _looks_like_figure(value: Any) -> bool:
    return hasattr(value, "savefig") and hasattr(value, "axes")


def figure_to_pixmap(figure: Figure) -> QPixmap:
    """Rasterize ``figure`` to a QPixmap without disturbing its Qt canvas."""
    agg = FigureCanvasAgg(figure)
    agg.draw()
    width, height = agg.get_width_height()
    image = QImage(bytes(agg.buffer_rgba()), width, height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(image.copy())


def figure_to_svg_bytes(figure: Figure) -> bytes:
    """
    Serialise ``figure`` to an SVG document that Qt's SVG renderer can
    draw cleanly.

    Used by the Dashboard tab, which renders figures as vectors so they
    stay sharp at any zoom / export scale. ``svg.fonttype="none"`` keeps
    text as ``<text>`` elements (drawn with Qt fonts) instead of glyph
    outlines referenced via ``<use>`` -- QtSvg does not resolve the
    latter and would drop every label. Goes through matplotlib's own SVG
    backend rather than the figure's live Qt canvas, so it does not
    disturb an on-screen preview of the same figure.
    """
    import io

    import matplotlib.pyplot as plt

    buffer = io.BytesIO()
    with plt.rc_context({"svg.fonttype": "none"}):
        figure.savefig(buffer, format="svg", bbox_inches="tight")
    return buffer.getvalue()


# --------------------------------------------------------------------------
# widgets
# --------------------------------------------------------------------------


class FigureWindow(QWidget):
    """A resizable top-level window showing one figure at its own aspect ratio."""

    def __init__(self, figure: Figure, title: str = "Figure") -> None:
        super().__init__()
        self.setWindowFlag(Qt.Window, True)
        self.setWindowTitle(title)

        canvas = FigureCanvasQTAgg(figure)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(canvas)
        canvas.draw()

        width_in, height_in = figure.get_size_inches()
        dpi = figure.get_dpi()
        self.resize(max(240, int(width_in * dpi)), max(180, int(height_in * dpi)))


class FigureThumbnail(QWidget):
    """Small preview pinned to a node; click to open the full figure window."""

    #: Emitted (with the node id) when the thumbnail is clicked.
    clicked = Signal(str)

    def __init__(self, node_id: str, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node_id = node_id
        self._figure: Figure | None = None
        self._pixmap: QPixmap | None = None

        self._label = QLabel(placeholder, self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(True)
        self._label.setStyleSheet(
            "background: rgba(20,20,20,190); color: rgba(255,255,255,220);"
            " border: 1px solid rgba(255,255,255,60); font-size: 10px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)
        self.resize(_THUMB_W, _THUMB_H)

    def has_figure(self) -> bool:
        return self._figure is not None

    def figure(self) -> Figure | None:
        return self._figure

    def show_placeholder(self, text: str) -> None:
        self._figure = None
        self._pixmap = None
        self._label.setPixmap(QPixmap())
        self._label.setText(text)

    def show_figure(self, figure: Figure) -> None:
        self._figure = figure
        self._pixmap = figure_to_pixmap(figure)
        self._label.setText("")
        self._rescale_pixmap()

    def resizeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._rescale_pixmap()

    def mousePressEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        self.clicked.emit(self.node_id)
        super().mousePressEvent(event)

    def _rescale_pixmap(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            return
        self._label.setPixmap(
            self._pixmap.scaled(
                self._label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )


# --------------------------------------------------------------------------
# overlay manager
# --------------------------------------------------------------------------


class NodePreviewOverlay(QObject):
    """
    Owns one :class:`FigureThumbnail` per figure-bearing node on a graph
    and keeps each pinned beneath its node as the canvas pans/zooms.
    """

    def __init__(self, graph: NodeGraph) -> None:
        super().__init__()
        self._graph = graph
        self._viewer = graph.viewer()
        self._viewport = self._viewer.viewport()
        self._thumbs: dict[str, FigureThumbnail] = {}
        self._windows: list[FigureWindow] = []
        self._outputs: dict[str, dict] = {}

        self._timer = QTimer(self)
        self._timer.setInterval(_SYNC_INTERVAL_MS)
        self._timer.timeout.connect(self.sync_positions)

        graph.node_created.connect(self._on_node_created)
        graph.nodes_deleted.connect(self._on_nodes_deleted)
        graph.session_changed.connect(lambda *_: self.clear())
        self._viewer.horizontalScrollBar().valueChanged.connect(self.sync_positions)
        self._viewer.verticalScrollBar().valueChanged.connect(self.sync_positions)

        for node in graph.all_nodes():
            self._on_node_created(node)

    # -- lifecycle ----------------------------------------------------------

    def _on_node_created(self, node: BaseNode) -> None:
        if not is_figure_node(node) or node.id in self._thumbs:
            return
        core_cls = type(node).CORE_NODE_CLASS
        thumb = FigureThumbnail(
            node.id, placeholder_text_for_category(core_cls.category), self._viewport
        )
        thumb.clicked.connect(self._open_window)
        self._thumbs[node.id] = thumb
        thumb.show()
        self.sync_positions()
        if not self._timer.isActive():
            self._timer.start()

    def _on_nodes_deleted(self, node_ids: list[str]) -> None:
        for node_id in node_ids:
            thumb = self._thumbs.pop(node_id, None)
            if thumb is not None:
                thumb.deleteLater()
        if not self._thumbs:
            self._timer.stop()

    def clear(self) -> None:
        for thumb in self._thumbs.values():
            thumb.deleteLater()
        self._thumbs.clear()
        self._timer.stop()

    # -- content ----------------------------------------------------------

    def set_run_outputs(self, outputs: dict[str, dict]) -> None:
        """Refresh every thumbnail from a completed run's outputs."""
        self._outputs = outputs
        node_by_id = {n.id: n for n in self._graph.all_nodes()}
        for node_id, thumb in self._thumbs.items():
            node = node_by_id.get(node_id)
            figure = resolve_figure(node, outputs) if node is not None else None
            if figure is not None:
                thumb.show_figure(figure)
            else:
                core_cls = type(node).CORE_NODE_CLASS
                thumb.show_placeholder(placeholder_text_for_category(core_cls.category))

    # -- geometry ----------------------------------------------------------

    def sync_positions(self, *_args: object) -> None:
        """Move/scale every thumbnail to sit just beneath its node."""
        node_by_id = {n.id: n for n in self._graph.all_nodes()}
        for node_id, thumb in self._thumbs.items():
            node = node_by_id.get(node_id)
            if node is None:
                continue
            scene_rect = node.view.sceneBoundingRect()
            top_left = self._viewer.mapFromScene(scene_rect.bottomLeft())
            width_px = max(
                60, self._viewer.mapFromScene(scene_rect.topRight()).x() - top_left.x()
            )
            height_px = int(width_px * _THUMB_H / _THUMB_W)
            thumb.setGeometry(top_left.x(), top_left.y() + 4, int(width_px), height_px)

    # -- window ----------------------------------------------------------

    def _open_window(self, node_id: str) -> None:
        thumb = self._thumbs.get(node_id)
        if thumb is None or thumb.figure() is None:
            return
        window = FigureWindow(thumb.figure(), title=f"Figure - {node_id}")
        window.show()
        self._windows.append(window)
