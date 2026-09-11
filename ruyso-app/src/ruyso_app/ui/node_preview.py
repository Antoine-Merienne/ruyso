"""
On-canvas figure previews for nodes that produce or consume a figure
(grapher nodes, and figure sinks such as
``export_figure``).

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
from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ruyso_app.engine import settings

#: dtype used by core ``Port``s that carry a matplotlib figure.
FIGURE_DTYPE = "figure"

#: Macro types that always get a preview even if their ports are not
#: figure-typed (a statistical test renders a table/plot of results).
_ALWAYS_PREVIEW_CATEGORIES = frozenset({"grapher"})

#: Thumbnail size on screen at 1:1 zoom, in pixels.
_THUMB_W = 180
_THUMB_H = 120

#: Timer interval (ms) for re-syncing thumbnail positions to their nodes,
#: while the canvas is actually being manipulated.
_SYNC_INTERVAL_MS = 60

#: How long after the last canvas interaction the sync timer keeps
#: running. Long enough to cover a gesture's inertia and the tail of a
#: zoom animation; short enough that an idle canvas costs nothing.
_SETTLE_MS = 300

#: Events that mean the canvas is (or is about to be) moving.
_WAKING_EVENTS = frozenset(
    {
        QEvent.Type.MouseButtonPress,
        QEvent.Type.MouseMove,
        QEvent.Type.MouseButtonRelease,
        QEvent.Type.Wheel,
        QEvent.Type.NativeGesture,
        QEvent.Type.Resize,
        QEvent.Type.KeyPress,
    }
)


# --------------------------------------------------------------------------
# figure resolution
# --------------------------------------------------------------------------


def is_figure_core_class(core_cls: type | None) -> bool:
    """Whether a core ``Node`` subclass should get an on-canvas figure preview."""
    if core_cls is None:
        return False
    if core_cls.category == "export":
        # Export / sink nodes (export_figure, export_to_dashboard) carry
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
    * A node with only a figure *input* port (e.g. ``export_figure``)
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


def figure_axis_limits(figure: Figure | None) -> dict[str, str]:
    """
    The x/y limits ``figure``'s first Axes actually settled on, as text.

    Feeds the Options panel's manual axis-range boxes so they show the
    real axis rather than an empty field. A date axis is reported as ISO
    dates, matching what ``nodes.viz._limit_value`` parses back, so a
    value shown here can be edited and round-trips.

    Returns an empty dict for a figure with no axes, so the caller can
    treat "no plot yet" and "no limits" identically.
    """
    if figure is None or not figure.axes:
        return {}
    ax = figure.axes[0]
    limits: dict[str, str] = {}
    for prefix, (low, high), axis in (
        ("x", ax.get_xlim(), ax.xaxis),
        ("y", ax.get_ylim(), ax.yaxis),
    ):
        as_dates = _is_date_axis(axis)
        limits[f"{prefix}_min"] = _format_limit(low, as_dates)
        limits[f"{prefix}_max"] = _format_limit(high, as_dates)
    return limits


def _is_date_axis(axis: Any) -> bool:
    """Whether ``axis`` plots matplotlib date numbers rather than plain floats."""
    import matplotlib.dates as mdates

    getter = getattr(axis, "get_converter", None)
    converter = getter() if callable(getter) else getattr(axis, "converter", None)
    if isinstance(converter, (mdates.DateConverter, mdates.ConciseDateConverter)):
        return True
    return isinstance(axis.get_major_locator(), mdates.DateLocator)


def _format_limit(value: float, as_dates: bool) -> str:
    """One axis edge as editable text: an ISO date, or a trimmed number."""
    if as_dates:
        import matplotlib.dates as mdates

        try:
            stamp = mdates.num2date(value)
        except (ValueError, OverflowError):
            return ""
        # Midnight is the common case (a daily/monthly axis); showing the
        # time only when it is non-zero keeps the box short and editable.
        if (stamp.hour, stamp.minute, stamp.second) == (0, 0, 0):
            return stamp.strftime("%Y-%m-%d")
        return stamp.strftime("%Y-%m-%d %H:%M:%S")
    if value != value:  # NaN
        return ""
    rounded = round(float(value), 6)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:g}"


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


#: Logical pixels per inch used to size a figure window. Deliberately a
#: constant rather than ``figure.get_dpi()``: attaching a
#: ``FigureCanvasQTAgg`` *mutates* the figure's dpi to
#: ``devicePixelRatio * dpi`` (see ``FigureCanvasBase._set_device_pixel_ratio``),
#: and the ratio is only 1.0 until the widget lands on a screen. Reading
#: the live dpi therefore gave 100 on the first open and 200 on every
#: later one -- the same plot opening small, then twice as big.
_WINDOW_DPI = 100.0

#: Floor for a figure window, for a figure configured absurdly small.
_MIN_WINDOW_W = 240
_MIN_WINDOW_H = 180

#: Fraction of the available screen a figure window may take up before
#: it is scaled down (keeping its aspect).
_MAX_SCREEN_FRACTION = 0.9


def window_size_for(figure: Figure) -> QSize:
    """
    The size a figure's window always opens at: its configured
    ``fig_width`` x ``fig_height``, in inches, at :data:`_WINDOW_DPI`.

    Memoised **onto the figure**, because a canvas writes back to
    ``figure.set_size_inches`` whenever its widget is resized -- so
    without this, dragging a window bigger and reopening it would grow
    the next one too. Each run builds a fresh figure from the node's
    params, so the remembered value follows a changed ``fig_width``.
    """
    cached = getattr(figure, "_ruyso_window_size", None)
    if cached is not None:
        return QSize(cached)

    width_in, height_in = figure.get_size_inches()
    width = max(_MIN_WINDOW_W, round(width_in * _WINDOW_DPI))
    height = max(_MIN_WINDOW_H, round(height_in * _WINDOW_DPI))

    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        limit_w = available.width() * _MAX_SCREEN_FRACTION
        limit_h = available.height() * _MAX_SCREEN_FRACTION
        shrink = min(1.0, limit_w / width, limit_h / height)
        if shrink < 1.0:
            width = max(_MIN_WINDOW_W, round(width * shrink))
            height = max(_MIN_WINDOW_H, round(height * shrink))

    size = QSize(width, height)
    try:
        figure._ruyso_window_size = size
    except AttributeError:  # pragma: no cover - Figure always allows this
        pass
    return size


class FigureWindow(QWidget):
    """
    A resizable top-level window showing one figure at its own aspect ratio.

    One of these is kept per figure node and reused: it is hidden on
    close rather than destroyed, so clicking a figure again raises the
    same window instead of stacking duplicates. :meth:`set_figure` swaps
    in a re-rendered figure without rebuilding the window, which is how
    an open window follows edits made in the Options panel.
    """

    def __init__(self, figure: Figure, title: str = "Figure") -> None:
        super().__init__()
        self.setWindowFlag(Qt.Window, True)
        self.setWindowTitle(title)

        self._canvas: FigureCanvasQTAgg | None = None
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self.set_figure(figure)
        self.resize(window_size_for(figure))

    def figure(self) -> Figure | None:
        return self._canvas.figure if self._canvas is not None else None

    def set_figure(self, figure: Figure) -> None:
        """Show ``figure``, replacing whatever was displayed before."""
        if self._canvas is not None:
            if self._canvas.figure is figure:
                self._canvas.draw_idle()
                return
            self._layout.removeWidget(self._canvas)
            self._canvas.setParent(None)
            self._canvas.deleteLater()
        self._canvas = FigureCanvasQTAgg(figure)
        self._layout.addWidget(self._canvas)
        self._canvas.draw_idle()

    def show_at_configured_size(self) -> None:
        """Show (or re-show) the window at the figure's configured size."""
        figure = self.figure()
        if figure is not None:
            self.resize(window_size_for(figure))
        self.show()
        self.raise_()
        self.activateWindow()


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
        """
        Draw ``figure``, unless it is the one already drawn.

        The skip cache hands an unchanged grapher's *same* Figure object
        back rather than re-running it, so identity is exactly the right
        question here: same object, same pixels, and rasterising it
        again through an Agg canvas would be pure waste on every
        keystroke-triggered background run.
        """
        if figure is self._figure and self._pixmap is not None:
            return
        self._figure = figure
        self._pixmap = figure_to_pixmap(figure)
        self._label.setText("")
        self._rescale_pixmap()

    def resizeEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._rescale_pixmap()

    def mousePressEvent(self, event: QEvent) -> None:  # noqa: N802 - Qt override
        # Accept, and do NOT chain to QWidget.mousePressEvent: the base
        # implementation *ignores* the event, which then propagates to
        # the parent -- the NodeGraphQt viewport -- which reads it as a
        # click on empty canvas and clears the selection. Opening a
        # figure used to deselect its own node and blank the Options
        # panel because of that.
        self.clicked.emit(self.node_id)
        event.accept()

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

    Also owns the pop-out :class:`FigureWindow`s -- **one per node**,
    hidden on close and reused, so clicking a figure twice raises the
    window it already has rather than stacking copies (the old list of
    windows was only ever appended to, so every window ever opened was
    kept alive for the session).
    """

    #: Emitted with a node id when its figure thumbnail is clicked, so
    #: ``MainWindow`` can select that node and fill the Options panel --
    #: clicking a figure means "I want to work on this plot".
    node_activated = Signal(str)

    def __init__(self, graph: NodeGraph) -> None:
        super().__init__()
        self._graph = graph
        self._viewer = graph.viewer()
        self._viewport = self._viewer.viewport()
        self._thumbs: dict[str, FigureThumbnail] = {}
        self._windows: dict[str, FigureWindow] = {}
        self._outputs: dict[str, dict] = {}

        # Thumbnails are plain widgets over the QGraphicsView, so nothing
        # moves them when the canvas does -- they have to be re-placed on
        # a timer. It used to tick every 60ms for the life of the app,
        # burning a wakeup 16 times a second to re-place widgets that had
        # not moved. Now it runs only while the canvas is being
        # manipulated, and stops shortly after (see _wake).
        self._timer = QTimer(self)
        self._timer.setInterval(_SYNC_INTERVAL_MS)
        self._timer.timeout.connect(self.sync_positions)
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(_SETTLE_MS)
        self._idle.timeout.connect(self._timer.stop)

        graph.node_created.connect(self._on_node_created)
        graph.nodes_deleted.connect(self._on_nodes_deleted)
        graph.session_changed.connect(lambda *_: self.clear())
        self._viewer.horizontalScrollBar().valueChanged.connect(self.sync_positions)
        self._viewer.verticalScrollBar().valueChanged.connect(self.sync_positions)
        self._viewport.installEventFilter(self)
        self._viewer.installEventFilter(self)

        for node in graph.all_nodes():
            self._on_node_created(node)

    # -- lifecycle ----------------------------------------------------------

    def thumbnails_enabled(self) -> bool:
        return bool(settings.get("appearance.node_thumbnails"))

    def thumbnail_width(self) -> int:
        try:
            width = int(settings.get("appearance.thumbnail_width"))
        except (TypeError, ValueError):
            return _THUMB_W
        return max(60, min(width, 600))

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        """Wake the position sync while the canvas is being manipulated."""
        if event.type() in _WAKING_EVENTS:
            self._wake()
        return False  # never consume: the canvas still needs these

    def _wake(self) -> None:
        """
        Run the sync for the next :data:`_SETTLE_MS`, refreshed on each
        event -- so a continuous drag keeps it running and letting go
        stops it, without either end needing an explicit signal.
        """
        if not self.thumbnails_enabled() or not self._thumbs:
            return
        if not self._timer.isActive():
            self._timer.start()
        self._idle.start()

    def apply_preferences(self) -> None:
        """Show or hide the thumbnails, and re-apply their size."""
        visible = self.thumbnails_enabled()
        for thumb in self._thumbs.values():
            thumb.setVisible(visible)
        if visible:
            self.sync_positions()
            self._wake()
        else:
            self._timer.stop()  # nothing to keep in step
            self._idle.stop()

    def _on_node_created(self, node: BaseNode) -> None:
        if not is_figure_node(node) or node.id in self._thumbs:
            return
        core_cls = type(node).CORE_NODE_CLASS
        thumb = FigureThumbnail(
            node.id, placeholder_text_for_category(core_cls.category), self._viewport
        )
        thumb.clicked.connect(self._open_window)
        self._thumbs[node.id] = thumb
        thumb.setVisible(self.thumbnails_enabled())
        self.sync_positions()
        self._wake()

    def _on_nodes_deleted(self, node_ids: list[str]) -> None:
        for node_id in node_ids:
            thumb = self._thumbs.pop(node_id, None)
            if thumb is not None:
                thumb.deleteLater()
            self._close_window(node_id)
        if not self._thumbs:
            self._timer.stop()
            self._idle.stop()

    def _close_window(self, node_id: str) -> None:
        """Drop the pop-out window of a node that no longer exists."""
        window = self._windows.pop(node_id, None)
        if window is not None:
            window.close()
            window.deleteLater()

    def clear(self) -> None:
        for thumb in self._thumbs.values():
            thumb.deleteLater()
        self._thumbs.clear()
        for node_id in list(self._windows):
            self._close_window(node_id)
        self._timer.stop()
        self._idle.stop()

    # -- content ----------------------------------------------------------

    def set_run_outputs(self, outputs: dict[str, dict]) -> None:
        """Refresh every thumbnail -- and any open window -- from a run."""
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

            # An open pop-out follows the re-render, so editing a plot's
            # params in the Options panel updates the big figure live.
            window = self._windows.get(node_id)
            if window is not None and figure is not None:
                window.set_figure(figure)

    # -- geometry ----------------------------------------------------------

    def sync_positions(self, *_args: object) -> None:
        """Move/scale every thumbnail to sit just beneath its node."""
        if not self.thumbnails_enabled():
            return
        node_by_id = {n.id: n for n in self._graph.all_nodes()}
        preferred = self.thumbnail_width()
        for node_id, thumb in self._thumbs.items():
            node = node_by_id.get(node_id)
            if node is None:
                continue
            scene_rect = node.view.sceneBoundingRect()
            top_left = self._viewer.mapFromScene(scene_rect.bottomLeft())
            node_px = self._viewer.mapFromScene(scene_rect.topRight()).x() - top_left.x()
            # Track the node's on-screen width so the thumbnail scales
            # with zoom, but let the preference set how big it is
            # relative to the node.
            width_px = max(60, int(node_px * preferred / _THUMB_W))
            height_px = int(width_px * _THUMB_H / _THUMB_W)
            thumb.setGeometry(top_left.x(), top_left.y() + 4, int(width_px), height_px)

    # -- window ----------------------------------------------------------

    def _open_window(self, node_id: str) -> None:
        """Raise this node's figure window, creating it the first time."""
        # Selection first: a click on a figure is a click on its plot, and
        # the thumbnail no longer lets the event fall through to the
        # canvas (which used to clear the selection instead).
        self.node_activated.emit(node_id)

        thumb = self._thumbs.get(node_id)
        if thumb is None or thumb.figure() is None:
            return
        window = self._windows.get(node_id)
        if window is None:
            window = FigureWindow(thumb.figure(), title=self._window_title(node_id))
            self._windows[node_id] = window
        else:
            window.set_figure(thumb.figure())
            window.setWindowTitle(self._window_title(node_id))
        window.show_at_configured_size()

    def _window_title(self, node_id: str) -> str:
        """"Figure - <node name>"; ``node_id`` is NodeGraphQt's internal id."""
        node = next((n for n in self._graph.all_nodes() if n.id == node_id), None)
        return f"Figure - {node.name() if node is not None else node_id}"
