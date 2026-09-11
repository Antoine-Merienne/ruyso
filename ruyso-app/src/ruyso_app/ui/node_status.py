"""
Per-node status dots on the pipeline canvas.

Every node draws a small dot left of its title. This module colours it
by the node's state in the most recent (auto-)run, so the canvas
doubles as a debugging view:

* **grey**  -- not run: an unconnected required input, or blocked by a
  failure upstream ("blocked" / "pending");
* **blue**  -- currently executing ("running");
* **green** -- ran cleanly ("ok");
* **red**   -- raised ("error"); the message goes on the node's tooltip.

On our own nodes the dot is a **vector ellipse** owned by
``ui/node_item.RuysoNodeItem`` (:meth:`set_status_colour`), so it stays
crisp however far you zoom in; the bitmap below is the fallback for a
NodeGraphQt built-in node, whose icon slot only takes a pixmap.

``MainWindow`` drives this from the scheduler's per-node callback,
streamed to the GUI thread over a Qt signal from the worker. Only the
existing icon pixmap is mutated (on the GUI thread) -- no QGraphicsItem
is ever added or removed, which keeps well clear of the NodeGraphQt
QUndoStack-teardown crash.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap

from ruyso_app.ui import theme

_DOT_PX = 16

#: scheduler phase -> the STATUS_COLORS key used for the dot.
_PHASE_TO_COLOUR = {
    "running": "running",
    "ok": "ok",
    "error": "error",
    "blocked": "idle",
    "unwired": "idle",
    "pending": "idle",
}

_TOOLTIPS = {
    "running": "Running…",
    "ok": "Ran successfully",
    "error": "Failed",
    # "blocked" and "unwired" are both grey -- neither node ran -- but
    # they mean different things: one is downstream of a real failure,
    # the other is simply not finished being wired up, which is the
    # ordinary state of a canvas someone is still assembling.
    "blocked": "Not run — waiting on an upstream node that failed",
    "unwired": "Not run — one of its inputs is not connected",
    "pending": "Not run yet",
}


class NodeStatusController:
    """Colours each canvas node's status dot by its last-known run status."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph
        self._status: dict[str, str] = {}  # node.name() -> phase
        self._dots: dict[str, QPixmap] = {}  # colour key -> pixmap

    # -- pixmap cache -------------------------------------------------

    def _dot(self, colour_key: str) -> QPixmap:
        cached = self._dots.get(colour_key)
        if cached is not None:
            return cached
        colour = QColor(theme.STATUS_COLORS.get(colour_key, theme.STATUS_COLORS["idle"]))
        pm = QPixmap(_DOT_PX, _DOT_PX)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        painter.drawEllipse(3, 3, _DOT_PX - 6, _DOT_PX - 6)
        painter.end()
        self._dots[colour_key] = pm
        return pm

    # -- public API ------------------------------------------------

    def set_status(self, node_id: str, phase: str, message: str = "") -> None:
        """Record and paint one node's status (``node_id`` is its display name)."""
        self._status[node_id] = phase
        self._paint(node_id, phase, message)

    def reset(self, phase: str = "pending") -> None:
        """Set every current canvas node to ``phase`` (grey by default).

        Used at the start of a manual run so stale dots clear before the
        fresh statuses stream in.
        """
        for node in self._graph.all_nodes():
            name = node.name()
            self._status[name] = phase
            self._paint(name, phase)

    def mark_new(self, node: Any) -> None:
        """A node was just created -- show it grey until the next run."""
        try:
            self.set_status(node.name(), "pending")
        except Exception:  # noqa: BLE001 - never break node creation
            pass

    def refresh_theme(self) -> None:
        """Re-render the dots (call on a dark/light toggle) and repaint."""
        self._dots.clear()
        for name, phase in list(self._status.items()):
            self._paint(name, phase)

    def status_of(self, node_id: str) -> str | None:
        """The last recorded phase for a node, for tests / callers."""
        return self._status.get(node_id)

    # -- internals ------------------------------------------------

    def _paint(self, node_id: str, phase: str, message: str = "") -> None:
        node = next(
            (n for n in self._graph.all_nodes() if n.name() == node_id), None
        )
        if node is None:
            return
        view = getattr(node, "view", None)
        colour_key = _PHASE_TO_COLOUR.get(phase, "idle")
        colour = QColor(
            theme.STATUS_COLORS.get(colour_key, theme.STATUS_COLORS["idle"])
        )
        # Our node item draws the dot as a vector ellipse, which stays
        # crisp at any zoom; the pixmap path is the fallback for a
        # NodeGraphQt built-in node, whose icon slot takes a bitmap.
        paint = getattr(view, "set_status_colour", None)
        try:
            if paint is not None:
                paint(colour)
            else:
                icon = getattr(view, "icon_item", None) or getattr(
                    view, "_icon_item", None
                )
                if icon is None:
                    return
                icon.setPixmap(self._dot(colour_key))
        except Exception:  # noqa: BLE001 - NodeGraphQt internals drift
            return
        tip = _TOOLTIPS.get(phase, "")
        if phase == "error" and message:
            tip = f"Failed: {message}"
        try:
            view.setToolTip(tip)
        except Exception:  # noqa: BLE001
            pass
