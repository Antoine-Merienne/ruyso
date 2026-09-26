"""
Geometric shapes for the Dashboard canvas, and the form that styles them.

A report is not only figures and captions: boxing a region, circling a
result and pointing an arrow at it are how a plot gets turned into an
argument. :class:`ShapeItem` covers those six shapes without becoming a
drawing program -- there is no freehand path, no bezier, no grouping.

Two geometry models share one class, because a shape is either an
*area* (rectangle, rounded rectangle, ellipse, triangle), described by a
rect and resized from its bottom-right corner like a
:class:`~ui.dashboard_items.FigureItem`; or a *line* (line, arrow),
described by two endpoints with a handle on each, which is the only way
to draw one at an arbitrary angle.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsItem,
    QGraphicsObject,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

#: The shapes on offer, in menu order.
SHAPE_KINDS: tuple[str, ...] = (
    "rectangle",
    "rounded",
    "ellipse",
    "line",
    "arrow",
    "triangle",
)

#: Menu labels for each kind.
SHAPE_LABELS: dict[str, str] = {
    "rectangle": "Rectangle",
    "rounded": "Rounded rectangle",
    "ellipse": "Ellipse",
    "line": "Line",
    "arrow": "Arrow",
    "triangle": "Triangle",
}

#: Kinds described by two endpoints rather than by a rectangle.
LINEAR_KINDS = frozenset({"line", "arrow"})

#: Stroke patterns offered, mapped to Qt's pen styles.
STROKE_STYLES: dict[str, Qt.PenStyle] = {
    "solid": Qt.SolidLine,
    "dashed": Qt.DashLine,
    "dotted": Qt.DotLine,
    "dash-dot": Qt.DashDotLine,
}

_SELECT_COLOR = QColor("#3b82f6")
_HANDLE = 13.0
_MIN_SIZE = 16.0
#: Half-width of the arrow head, and how far back it reaches.
_ARROW_HEAD = 12.0

#: A fresh shape's look: a translucent fill under a solid dark outline,
#: which reads as an annotation over a figure rather than as a block.
DEFAULT_STYLE: dict[str, Any] = {
    "fill": "#3b82f6",
    "fill_alpha": 0.18,
    "stroke": "#1f2937",
    "stroke_width": 2.0,
    "stroke_style": "solid",
    "radius": 12.0,
    "rotation": 0.0,
    "locked": False,
}


class ShapeItem(QGraphicsObject):
    """One drawn shape: an area or a line, styled through ShapeInspector."""

    def __init__(self, kind: str = "rectangle") -> None:
        super().__init__()
        self.kind = kind if kind in SHAPE_KINDS else "rectangle"
        self._style: dict[str, Any] = dict(DEFAULT_STYLE)
        self._rect = QRectF(0.0, 0.0, 180.0, 120.0)
        self._p1 = QPointF(0.0, 0.0)
        self._p2 = QPointF(180.0, 90.0)
        self._dragging: int | None = None  # which handle, if any

        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setRotation(self._style["rotation"])

    # -- style ------------------------------------------------------------

    def style(self) -> dict[str, Any]:
        return dict(self._style)

    def set_style(self, **changes: Any) -> None:
        self.prepareGeometryChange()
        self._style.update(changes)
        if "rotation" in changes:
            self.setRotation(float(self._style["rotation"]))
        if "locked" in changes:
            self._apply_lock()
        self.update()

    def is_locked(self) -> bool:
        return bool(self._style.get("locked"))

    def set_locked(self, locked: bool) -> None:
        """The name ``dashboard_layout.set_locked`` looks for; the other
        item kinds carry it too, so locking works on any selection."""
        self.set_style(locked=bool(locked))

    def _apply_lock(self) -> None:
        """
        A locked shape is untouchable: not movable, not selectable, and
        so not deletable either. ``Unlock all`` on the Dashboard menu is
        the way back, since a shape you cannot select is one you cannot
        unlock from its own inspector.
        """
        locked = self.is_locked()
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        self.setFlag(QGraphicsItem.ItemIsSelectable, not locked)
        if locked:
            self.setSelected(False)

    # -- geometry ---------------------------------------------------------

    def is_linear(self) -> bool:
        return self.kind in LINEAR_KINDS

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        pad = float(self._style["stroke_width"]) + _HANDLE
        if self.is_linear():
            rect = QRectF(self._p1, self._p2).normalized()
        else:
            rect = QRectF(self._rect)
        return rect.adjusted(-pad, -pad, pad, pad)

    def shape_rect(self) -> QRectF:
        return QRectF(self._rect)

    def visual_rect(self) -> QRectF:
        """What is drawn, without the padding boundingRect adds for handles."""
        if self.is_linear():
            return QRectF(self._p1, self._p2).normalized()
        return QRectF(self._rect)

    def endpoints(self) -> tuple[QPointF, QPointF]:
        return QPointF(self._p1), QPointF(self._p2)

    def set_geometry(self, rect: QRectF | None = None, points=None) -> None:
        self.prepareGeometryChange()
        if rect is not None:
            self._rect = QRectF(rect)
        if points is not None:
            self._p1, self._p2 = QPointF(points[0]), QPointF(points[1])
        self.update()

    # -- painting ---------------------------------------------------------

    def _pen(self) -> QPen:
        colour = QColor(self._style["stroke"])
        if not colour.isValid():
            colour = QColor(DEFAULT_STYLE["stroke"])
        pen = QPen(colour, float(self._style["stroke_width"]))
        pen.setStyle(STROKE_STYLES.get(self._style["stroke_style"], Qt.SolidLine))
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        return pen

    def _brush(self) -> QBrush:
        colour = QColor(self._style["fill"])
        if not colour.isValid():
            return QBrush(Qt.NoBrush)
        colour.setAlphaF(max(0.0, min(1.0, float(self._style["fill_alpha"]))))
        return QBrush(colour)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:  # noqa: N802
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(self._pen())
        painter.setBrush(self._brush() if not self.is_linear() else Qt.NoBrush)

        if self.kind == "rectangle":
            painter.drawRect(self._rect)
        elif self.kind == "rounded":
            radius = float(self._style["radius"])
            painter.drawRoundedRect(self._rect, radius, radius)
        elif self.kind == "ellipse":
            painter.drawEllipse(self._rect)
        elif self.kind == "triangle":
            painter.drawPolygon(self._triangle())
        elif self.kind in LINEAR_KINDS:
            painter.drawLine(self._p1, self._p2)
            if self.kind == "arrow":
                painter.setBrush(QBrush(self._pen().color()))
                painter.setPen(Qt.NoPen)
                painter.drawPolygon(self._arrow_head())

        if self.isSelected():
            self._paint_selection(painter)

    def _triangle(self) -> QPolygonF:
        rect = self._rect
        return QPolygonF(
            [
                QPointF(rect.center().x(), rect.top()),
                QPointF(rect.right(), rect.bottom()),
                QPointF(rect.left(), rect.bottom()),
            ]
        )

    def _arrow_head(self) -> QPolygonF:
        """A filled triangle at ``_p2``, pointing along the line."""
        angle = math.atan2(self._p2.y() - self._p1.y(), self._p2.x() - self._p1.x())
        spread = math.radians(26)
        back = _ARROW_HEAD + float(self._style["stroke_width"])
        return QPolygonF(
            [
                QPointF(self._p2),
                QPointF(
                    self._p2.x() - back * math.cos(angle - spread),
                    self._p2.y() - back * math.sin(angle - spread),
                ),
                QPointF(
                    self._p2.x() - back * math.cos(angle + spread),
                    self._p2.y() - back * math.sin(angle + spread),
                ),
            ]
        )

    def _paint_selection(self, painter: QPainter) -> None:
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_SELECT_COLOR, 1, Qt.DashLine))
        if not self.is_linear():
            painter.drawRect(self._rect)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_SELECT_COLOR)
        for handle in self._handles():
            painter.fillRect(handle, _SELECT_COLOR)

    def _handles(self) -> list[QRectF]:
        """One handle at the bottom-right for an area; one per endpoint
        for a line, which is the only way to aim it."""
        half = _HANDLE / 2
        if self.is_linear():
            return [
                QRectF(p.x() - half, p.y() - half, _HANDLE, _HANDLE)
                for p in (self._p1, self._p2)
            ]
        return [
            QRectF(
                self._rect.right() - _HANDLE,
                self._rect.bottom() - _HANDLE,
                _HANDLE,
                _HANDLE,
            )
        ]

    # -- resize vs. move --------------------------------------------------

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if self.isSelected() and not self.is_locked():
            for index, handle in enumerate(self._handles()):
                if handle.contains(event.pos()):
                    self._dragging = index
                    event.accept()
                    return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if self._dragging is None:
            super().mouseMoveEvent(event)
            return
        self.prepareGeometryChange()
        if self.is_linear():
            if self._dragging == 0:
                self._p1 = QPointF(event.pos())
            else:
                self._p2 = QPointF(event.pos())
        else:
            self._rect.setRight(max(self._rect.left() + _MIN_SIZE, event.pos().x()))
            self._rect.setBottom(max(self._rect.top() + _MIN_SIZE, event.pos().y()))
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        self._dragging = None
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        over = self.isSelected() and any(
            handle.contains(event.pos()) for handle in self._handles()
        )
        self.setCursor(Qt.SizeFDiagCursor if over else Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    # -- undo / persistence state -----------------------------------------

    def capture_state(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "style": dict(self._style),
            "rect": (
                self._rect.x(), self._rect.y(), self._rect.width(), self._rect.height()
            ),
            "points": (
                (self._p1.x(), self._p1.y()), (self._p2.x(), self._p2.y())
            ),
        }

    def apply_state(self, state: dict[str, Any]) -> None:
        self.prepareGeometryChange()
        self.kind = state.get("kind", self.kind)
        self._style = dict(state.get("style", self._style))
        x, y, w, h = state.get("rect", (0, 0, 180, 120))
        self._rect = QRectF(x, y, w, h)
        (x1, y1), (x2, y2) = state.get("points", ((0, 0), (180, 90)))
        self._p1, self._p2 = QPointF(x1, y1), QPointF(x2, y2)
        self.setRotation(float(self._style.get("rotation", 0.0)))
        self._apply_lock()
        self.update()


#: Shown in a field whose value differs across the selection.
MIXED = "—"


class ShapeInspector(QWidget):
    """
    Styles the selected shapes -- one, or several at once.

    Editing a whole selection is most of why a report builder has an
    inspector: making five callouts match by hand is the tedious part.
    A field the selection disagrees on shows :data:`MIXED` until it is
    set, at which point it applies to all of them.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[ShapeItem] = []
        self._loading = False

        self._fill = QPushButton("Fill colour...", self)
        self._fill_alpha = QDoubleSpinBox(self)
        self._fill_alpha.setRange(0.0, 1.0)
        self._fill_alpha.setSingleStep(0.05)
        self._stroke = QPushButton("Line colour...", self)
        self._stroke_width = QDoubleSpinBox(self)
        self._stroke_width.setRange(0.0, 40.0)
        self._stroke_width.setSingleStep(0.5)
        self._stroke_style = QComboBox(self)
        self._stroke_style.addItems(list(STROKE_STYLES))
        self._radius = QSpinBox(self)
        self._radius.setRange(0, 200)
        self._rotation = QSpinBox(self)
        self._rotation.setRange(-180, 180)
        self._locked = QCheckBox("Locked", self)
        self._locked.setToolTip(
            "A locked shape cannot be selected, moved or deleted. "
            "Use Dashboard > Unlock all to release it."
        )

        self._heading = QLabel("Shape", self)
        form = QFormLayout()
        form.addRow(self._fill)
        form.addRow("Fill opacity", self._fill_alpha)
        form.addRow(self._stroke)
        form.addRow("Line width", self._stroke_width)
        form.addRow("Line style", self._stroke_style)
        self._radius_row = self._radius
        form.addRow("Corner radius", self._radius)
        form.addRow("Rotation", self._rotation)
        form.addRow(self._locked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._heading)
        layout.addLayout(form)
        layout.addStretch(1)

        self._fill.clicked.connect(lambda: self._pick_colour("fill"))
        self._stroke.clicked.connect(lambda: self._pick_colour("stroke"))
        self._fill_alpha.valueChanged.connect(
            lambda v: self._push(fill_alpha=float(v))
        )
        self._stroke_width.valueChanged.connect(
            lambda v: self._push(stroke_width=float(v))
        )
        self._stroke_style.currentTextChanged.connect(
            lambda v: self._push(stroke_style=v)
        )
        self._radius.valueChanged.connect(lambda v: self._push(radius=float(v)))
        self._rotation.valueChanged.connect(lambda v: self._push(rotation=float(v)))
        self._locked.toggled.connect(lambda v: self._push(locked=bool(v)))

    # -- binding ----------------------------------------------------------

    def set_items(self, items: list[ShapeItem]) -> None:
        self._loading = True  # suppress the feedback loop while filling
        self._items = list(items)
        if items:
            self._heading.setText(
                "Shape" if len(items) == 1 else f"{len(items)} shapes"
            )
            self._fill_alpha.setValue(float(self._common("fill_alpha", 0.18)))
            self._stroke_width.setValue(float(self._common("stroke_width", 2.0)))
            style = self._common("stroke_style", None)
            self._stroke_style.setCurrentText(style if style else "solid")
            self._radius.setValue(int(self._common("radius", 12.0) or 0))
            self._rotation.setValue(int(self._common("rotation", 0.0) or 0))
            locked = self._common("locked", None)
            self._locked.setChecked(bool(locked))
            self._radius.setEnabled(any(i.kind == "rounded" for i in items))
        self._loading = False

    def _common(self, key: str, default: Any) -> Any:
        """The value every selected shape shares, or ``None`` if they differ."""
        values = {item.style().get(key) for item in self._items}
        if len(values) == 1:
            return values.pop()
        return default if not self._items else None

    def items(self) -> list[ShapeItem]:
        return list(self._items)

    # -- editing ----------------------------------------------------------

    def _push(self, **changes: Any) -> None:
        if self._loading or not self._items:
            return
        for item in self._items:
            item.set_style(**changes)
        self.changed()

    def _pick_colour(self, key: str) -> None:
        if not self._items:
            return
        current = QColor(self._items[0].style().get(key, "#3b82f6"))
        chosen = QColorDialog.getColor(current, self, f"{key.title()} colour")
        if chosen.isValid():
            self._push(**{key: chosen.name()})

    def changed(self) -> None:
        """Hook the page replaces, so an edit can be pushed onto undo."""
