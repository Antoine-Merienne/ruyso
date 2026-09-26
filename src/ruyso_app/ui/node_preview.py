"""
On-canvas figure previews for nodes that produce or consume a figure
(grapher nodes, and figure sinks such as ``export_figure``).

Each eligible node gets a **preview card** beneath it
(:class:`~ui.preview_card.PreviewCard`): an item in the canvas scene,
placed from the node's own ``itemChange`` so it moves in the same frame
as the node, stacked above the wires and below every node, and drawn as
a rounded card around the figure's white plate. It replaced a floating
``QWidget`` over the viewport that a timer re-placed every 60 ms -- the
preview trailed a dragged node by up to four frames, painted over
neighbouring nodes, and was rasterised at logical size, so it was blurry
on a 2x screen.

* Before a run a card shows a placeholder line; after a run, a bitmap of
  the resolved figure at the resolution it is shown at.
* Clicking a card selects its node and opens a **resizable window** sized
  to the figure's own aspect ratio (:class:`FigureWindow`), which is how
  you actually read the plot when several are on the canvas.
* The chevron on a figure node's name bar collapses its card; the flag is
  kept on the node item and saved with the pipeline (``canvas`` section,
  see ``ui/graph_bridge.canvas_layout``).

Clicks on a card or a chevron are taken in a viewport event filter, before
NodeGraphQt sees them: its viewer treats anything that is not a node or a
wire as empty canvas and starts a rubber band without ever handing the
press to the scene.

Only this module knows how to turn a run's ``{node_id: {port: value}}``
outputs into "the figure for this node".
"""

from __future__ import annotations

from typing import Any

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from NodeGraphQt import BaseNode, NodeGraph
from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ruyso_app.core.figure_lock import figure_guard
from ruyso_app.engine import settings
from ruyso_app.ui import render_queue
from ruyso_app.ui.node_item import RuysoNodeItem
from ruyso_app.ui.preview_card import BASE_WIDTH, GAP, PreviewCard

#: dtype used by core ``Port``s that carry a matplotlib figure.
FIGURE_DTYPE = "figure"

#: Macro types that always get a preview even if their ports are not
#: figure-typed (a statistical test renders a table/plot of results).
_ALWAYS_PREVIEW_CATEGORIES = frozenset({"grapher"})

#: How long after the last zoom-driven repaint a card is re-rasterised
#: for its new size. Rendering a figure is far too slow to do on every
#: frame of a pinch; the card shows its current bitmap scaled meanwhile.
_UPGRADE_DELAY_MS = 150


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
    with figure_guard():
        bounds = (("x", ax.get_xlim(), ax.xaxis), ("y", ax.get_ylim(), ax.yaxis))
    for prefix, (low, high), axis in bounds:
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


def figure_to_png_bytes(figure: Figure, width_px: int | None = None) -> bytes:
    """
    Render ``figure`` to PNG data ``width_px`` pixels wide (default: its
    own size at its own dpi).

    Through ``savefig`` with an explicit dpi rather than by constructing
    a ``FigureCanvasAgg`` around the figure: that replaces
    ``figure.canvas`` for good, while ``savefig`` swaps a canvas in only
    for the call -- so a figure that is also open in a window keeps its
    own canvas.

    Bytes rather than a QPixmap because this is what runs on the render
    thread (``ui/render_queue.py``): a QPixmap may only be built on the
    GUI thread, and building one from ready PNG data costs nothing.
    """
    import io

    with figure_guard():
        width_in, _height_in = figure.get_size_inches()
        if width_px:
            dpi = max(float(width_px) / max(float(width_in), 0.1), 10.0)
        else:
            dpi = figure.get_dpi()
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", dpi=dpi)
        return buffer.getvalue()


def png_bytes_to_pixmap(data: bytes) -> QPixmap:
    """The GUI-thread half of a render: PNG data to a QPixmap."""
    return QPixmap.fromImage(QImage.fromData(data, "PNG"))


def figure_to_pixmap(figure: Figure, width_px: int | None = None) -> QPixmap:
    """Render ``figure`` straight to a QPixmap, on the calling thread."""
    return png_bytes_to_pixmap(figure_to_png_bytes(figure, width_px=width_px))


#: Points on one artist past which it is embedded in the SVG as a
#: bitmap instead of one vector shape per point. A 400k-point scatter
#: is a 42 MB file that matplotlib needs 1.8 s to write and Qt 2.7 s to
#: parse -- and then redraws slowly for ever after; the same plot with
#: its dots flattened is 50 KB.
_SVG_RASTER_MIN = 10_000

#: Resolution of those embedded bitmaps. Twice the default, so a block
#: exported to PDF at twice its on-screen size still looks sharp.
_SVG_RASTER_DPI = 200


def _artist_point_count(artist: Any) -> int:
    """How many points an artist draws, or 0 when it will not say."""
    try:
        offsets = artist.get_offsets()
        if offsets is not None and len(offsets) > 1:
            return len(offsets)
    except (AttributeError, TypeError):
        pass
    for accessor in ("get_paths", "get_xdata"):
        try:
            return len(getattr(artist, accessor)())
        except (AttributeError, TypeError):
            continue
    return 0


def _dense_artists(figure: Figure) -> list:
    """The artists in ``figure`` that carry too many points to vectorise."""
    dense = []
    for axes in figure.get_axes():
        for artist in list(axes.collections) + list(axes.lines):
            if artist.get_rasterized():
                continue  # already flattened by whoever drew it
            if _artist_point_count(artist) > _SVG_RASTER_MIN:
                dense.append(artist)
    return dense


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
    # A dense point cloud becomes one embedded bitmap; the axes, the
    # text and everything else stay vector. The flags go back on
    # afterwards, because the figure is also shown elsewhere -- and the
    # dpi is only passed when something was flattened, so an ordinary
    # plot's file is exactly what it was before.
    with figure_guard():
        dense = _dense_artists(figure)
        for artist in dense:
            artist.set_rasterized(True)
        try:
            with plt.rc_context({"svg.fonttype": "none"}):
                figure.savefig(
                    buffer,
                    format="svg",
                    bbox_inches="tight",
                    **({"dpi": _SVG_RASTER_DPI} if dense else {}),
                )
        finally:
            for artist in dense:
                artist.set_rasterized(False)
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

    # Under the guard, and memoised only from a reading taken there:
    # mid-save a 6.0 x 4.0 figure reads as 5.953 x 3.917, and that is
    # the size the window would then keep for good.
    with figure_guard():
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


class _GuardedCanvas(FigureCanvasQTAgg):
    """
    A live canvas that paints under the figure guard.

    A window draws its figure on the GUI thread whenever Qt asks, which
    can land in the middle of the run thread building the *next*
    figure -- and matplotlib's rcParams are global, so the window then
    paints with half of somebody else's style.
    """

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        with figure_guard():
            super().paintEvent(event)


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
        self._canvas = _GuardedCanvas(figure)
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


def _screen_ratio() -> float:
    """The primary screen's device pixel ratio (1.0 when there is none)."""
    screen = QGuiApplication.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


#: Which half of the shared render queue a job belongs to (the Dashboard
#: tab puts its SVG jobs on the same thread).
_CARD_JOB = "card"


# --------------------------------------------------------------------------
# preview manager
# --------------------------------------------------------------------------


class NodePreviewOverlay(QObject):
    """
    Owns one :class:`~ui.preview_card.PreviewCard` per figure-bearing node
    on a graph, and the pop-out :class:`FigureWindow`s.

    Windows are **one per node**, hidden on close and reused, so clicking a
    figure twice raises the window it already has rather than stacking
    copies.
    """

    #: Emitted with a node id when its preview is clicked, so ``MainWindow``
    #: can select that node and fill the Options panel -- clicking a figure
    #: means "I want to work on this plot".
    node_activated = Signal(str)
    #: Emitted when a preview is collapsed or expanded from its chevron.
    #: That flag is saved with the pipeline, so it is an edit to the document.
    layout_changed = Signal()

    def __init__(self, graph: NodeGraph) -> None:
        super().__init__()
        self._graph = graph
        self._viewer = graph.viewer()
        self._viewport = self._viewer.viewport()
        self._cards: dict[str, PreviewCard] = {}
        #: node id -> its node item, so a deleted node's listener can be
        #: detached without the node itself.
        self._views: dict[str, Any] = {}
        self._windows: dict[str, FigureWindow] = {}
        self._outputs: dict[str, dict] = {}
        #: ``(kind, node id)`` of a press this filter took, awaiting release.
        self._pressed: tuple[str, str] | None = None

        render_queue.queue().rendered.connect(self._on_rendered)

        self._upgrades: set[str] = set()
        self._upgrade_timer = QTimer(self)
        self._upgrade_timer.setSingleShot(True)
        self._upgrade_timer.setInterval(_UPGRADE_DELAY_MS)
        self._upgrade_timer.timeout.connect(self._run_upgrades)

        graph.node_created.connect(self._on_node_created)
        graph.nodes_deleted.connect(self._on_nodes_deleted)
        graph.session_changed.connect(lambda *_: self.clear())
        self._viewport.installEventFilter(self)

        for node in graph.all_nodes():
            self._on_node_created(node)

    # -- preferences -----------------------------------------------------

    def thumbnails_enabled(self) -> bool:
        return bool(settings.get("appearance.node_thumbnails"))

    def thumbnail_width(self) -> int:
        try:
            width = int(settings.get("appearance.thumbnail_width"))
        except (TypeError, ValueError):
            return int(BASE_WIDTH)
        return max(60, min(width, 600))

    def apply_preferences(self) -> None:
        """Show or hide the cards, and re-apply their size."""
        for view in list(self._views.values()):
            self._place(view)

    def apply_theme(self) -> None:
        """Repaint every card in the active theme's colours."""
        for card in self._cards.values():
            card.update()

    # -- lifecycle ---------------------------------------------------------

    def cards(self) -> dict[str, PreviewCard]:
        """node id -> card, for callers and tests."""
        return dict(self._cards)

    def _on_node_created(self, node: BaseNode) -> None:
        if not is_figure_node(node) or node.id in self._cards:
            return
        view = node.view
        core_cls = type(node).CORE_NODE_CLASS
        card = PreviewCard(
            node.id,
            placeholder_text_for_category(core_cls.category),
            self._request_render,
        )
        card.request_upgrade = self._request_upgrade
        self._viewer.scene().addItem(card)
        self._cards[node.id] = card
        self._views[node.id] = view
        if isinstance(view, RuysoNodeItem):
            view.has_preview = True
            view.geometry_listener = self._place
            view.update()
        # A node brought back by undo gets its picture back straight away.
        figure = resolve_figure(node, self._outputs) if self._outputs else None
        if figure is not None:
            card.set_figure(figure, _screen_ratio())
        self._place(view)

    def _on_nodes_deleted(self, node_ids: list[str]) -> None:
        for node_id in node_ids:
            self._drop_card(node_id)
            self._close_window(node_id)

    def _drop_card(self, node_id: str) -> None:
        card = self._cards.pop(node_id, None)
        view = self._views.pop(node_id, None)
        self._upgrades.discard(node_id)
        if view is not None and getattr(view, "geometry_listener", None) == self._place:
            view.geometry_listener = None
        if card is None:
            return
        try:
            scene = card.scene()
            if scene is not None:
                scene.removeItem(card)
        except RuntimeError:  # the scene is already being torn down
            pass

    def _close_window(self, node_id: str) -> None:
        """Drop the pop-out window of a node that no longer exists."""
        window = self._windows.pop(node_id, None)
        if window is not None:
            window.close()
            window.deleteLater()

    def clear(self) -> None:
        for node_id in list(self._cards):
            self._drop_card(node_id)
        for node_id in list(self._windows):
            self._close_window(node_id)
        self._upgrade_timer.stop()

    # -- placement -------------------------------------------------------

    def _place(self, view: Any) -> None:
        """
        Put a node's card just beneath it.

        Called from the node item's ``itemChange`` / ``draw_node`` -- in the
        same frame the node moves or changes size -- which is what keeps a
        dragged node and its preview together.
        """
        card = self._cards.get(getattr(view, "id", None))
        if card is None:
            return
        try:
            rect = view.sceneBoundingRect()
        except RuntimeError:  # the node item is already gone
            return
        card.set_width(rect.width() * self.thumbnail_width() / BASE_WIDTH)
        card.setPos(rect.left(), rect.bottom() + GAP)
        card.setVisible(
            self.thumbnails_enabled() and not getattr(view, "preview_collapsed", False)
        )

    # -- content ---------------------------------------------------------

    def set_run_outputs(self, outputs: dict[str, dict]) -> None:
        """Refresh every card -- and any open window -- from a run."""
        self._outputs = outputs
        ratio = _screen_ratio()
        node_by_id = {n.id: n for n in self._graph.all_nodes()}
        for node_id, card in self._cards.items():
            node = node_by_id.get(node_id)
            figure = resolve_figure(node, outputs) if node is not None else None
            if figure is not None:
                card.set_figure(figure, ratio)
            elif node is not None:
                core_cls = type(node).CORE_NODE_CLASS
                card.show_placeholder(placeholder_text_for_category(core_cls.category))

            # An open pop-out follows the re-render, so editing a plot's
            # params in the Options panel updates the big figure live.
            window = self._windows.get(node_id)
            if window is not None and figure is not None:
                window.set_figure(figure)

    # -- rendering -------------------------------------------------------

    def _request_render(self, node_id: str, figure: Figure, pixels: int) -> None:
        """A card wants a bitmap: queue it for the render thread."""
        render_queue.queue().submit(
            (_CARD_JOB, node_id),
            figure,
            lambda fig: (pixels, figure_to_png_bytes(fig, width_px=pixels)),
        )

    def _on_rendered(self, key: Any, figure: Figure, result: Any) -> None:
        """A finished render, back on the GUI thread."""
        kind, node_id = key
        if kind != _CARD_JOB:
            return  # the dashboard's own jobs share this queue
        card = self._cards.get(node_id)
        if card is None:
            return
        if result is None:  # the render failed; let the card ask again
            card.render_failed(figure)
            return
        pixels, data = result
        card.apply_render(figure, pixels, png_bytes_to_pixmap(data))

    def _request_upgrade(self, node_id: str) -> None:
        """A card's bitmap no longer suits the zoom: re-render once it settles."""
        self._upgrades.add(node_id)
        self._upgrade_timer.start()  # restarted by every request: a debounce

    def _run_upgrades(self) -> None:
        pending, self._upgrades = self._upgrades, set()
        for node_id in pending:
            card = self._cards.get(node_id)
            if card is not None and card.wanted_px:
                card.rasterise_at(card.wanted_px)

    # -- collapsing ------------------------------------------------------

    def is_collapsed(self, node_id: str) -> bool:
        return bool(getattr(self._views.get(node_id), "preview_collapsed", False))

    def toggle_collapsed(self, node_id: str) -> None:
        """Collapse or expand one node's preview, from its chevron."""
        view = self._views.get(node_id)
        if not isinstance(view, RuysoNodeItem):
            return
        view.set_preview_collapsed(not view.preview_collapsed)  # re-places the card
        self.layout_changed.emit()

    # -- clicks ------------------------------------------------------------

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        """
        Take left clicks on a card or a chevron before NodeGraphQt does.

        Acts on release, over the same target as the press, like a button:
        pressing on a card and dragging off it does nothing. The matching
        release is consumed too, so the viewer never sees half a click.
        """
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress:
            if event.button() != Qt.LeftButton or event.modifiers() != Qt.NoModifier:
                return False
            target = self.target_at(event.position().toPoint())
            if target is None:
                return False
            self._pressed = target
            return True
        if etype == QEvent.Type.MouseButtonRelease and self._pressed is not None:
            if event.button() != Qt.LeftButton:
                return False
            pressed, self._pressed = self._pressed, None
            if self.target_at(event.position().toPoint()) == pressed:
                self._activate(*pressed)
            return True
        if etype == QEvent.Type.MouseButtonDblClick and event.button() == Qt.LeftButton:
            # The first click already acted; a double-click must not also
            # reach NodeGraphQt, which would open its name editor.
            return self.target_at(event.position().toPoint()) is not None
        return False

    def target_at(self, viewport_pos: QPoint) -> tuple[str, str] | None:
        """
        What a click at ``viewport_pos`` would hit: ``("card", node_id)``,
        ``("chevron", node_id)``, or ``None`` for anything else.

        Walks the scene's items topmost first, so a node lying over a card
        wins -- a click on a node's body is the node's, whatever is behind.
        """
        scene_pos = self._viewer.mapToScene(viewport_pos)
        for item in self._viewer.scene().items(scene_pos):
            if isinstance(item, PreviewCard):
                if item.isVisible() and item.node_id in self._cards:
                    return ("card", item.node_id)
                continue
            top = item.topLevelItem()
            if isinstance(top, RuysoNodeItem):
                if top.id in self._cards and top.chevron_hit(scene_pos):
                    return ("chevron", top.id)
                return None
        return None

    def _activate(self, kind: str, node_id: str) -> None:
        if kind == "chevron":
            self.toggle_collapsed(node_id)
        else:
            self._open_window(node_id)

    # -- window ----------------------------------------------------------

    def _open_window(self, node_id: str) -> None:
        """Raise this node's figure window, creating it the first time."""
        # Selection first: a click on a figure is a click on its plot.
        self.node_activated.emit(node_id)

        card = self._cards.get(node_id)
        if card is None or card.figure() is None:
            return
        window = self._windows.get(node_id)
        if window is None:
            window = FigureWindow(card.figure(), title=self._window_title(node_id))
            self._windows[node_id] = window
        else:
            window.set_figure(card.figure())
            window.setWindowTitle(self._window_title(node_id))
        window.show_at_configured_size()

    def _window_title(self, node_id: str) -> str:
        """"Figure - <node name>"; ``node_id`` is NodeGraphQt's internal id."""
        node = next((n for n in self._graph.all_nodes() if n.id == node_id), None)
        return f"Figure - {node.name() if node is not None else node_id}"
