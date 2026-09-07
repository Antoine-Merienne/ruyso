"""
The graphics-scene items that live on the Dashboard canvas, plus the
small inspector used to restyle a text item.

* :class:`FigureItem` -- a pipeline figure (a grapher plot or a
  ``table_viewer`` table) rendered from **SVG**, so it stays sharp at
  any zoom or export scale. It is keyed to the ``export_to_dashboard``
  node that produced it (:attr:`FigureItem.export_node_id`) and is
  re-rendered in place by :meth:`FigureItem.set_svg` on every run. When
  its source plot changed since the last run, was disconnected, or
  errored, :meth:`FigureItem.set_stale` draws the Table tab's yellow
  "· modified" tag. It is *edited* through the source plot's own
  parameter form (the Pipeline-tab Options panel), so it carries no
  style state beyond an editable heading.
* :class:`TextItem` -- a free-text commentary / title, restyled live
  through :class:`TextInspector` (bold, italic, size, colour,
  alignment, font family).

Both are selectable / movable; the view's rubber-band drag multi-selects
and a multi-selection drags as a group. Selection draws a blue contour.
The dashboard is session state and is not serialised (each
``export_to_dashboard`` node's ``title`` param, which seeds a figure
item's heading, is the one piece that persists, with the pipeline).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QTextCursor,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFontComboBox,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsTextItem,
    QLabel,
    QPushButton,
    QSpinBox,
    QStyle,
    QVBoxLayout,
    QWidget,
)

#: Blue selection contour shared by both item kinds.
_SELECT_COLOR = QColor("#3b82f6")
#: Table tab's "· modified" tag (kept in sync with ``ui.table_page``).
_MODIFIED_TAG = "· modified"
_MODIFIED_COLOR = QColor("#d8be55")

_TITLE_H = 22.0
_PAD = 8.0
_HANDLE = 13.0
_MIN_W = 140.0


class FigureItem(QGraphicsObject):
    """A pipeline figure on the dashboard canvas, keyed to its export node."""

    def __init__(self, export_node_id: str, title: str = "") -> None:
        super().__init__()
        self.export_node_id = export_node_id
        self._title = title
        self._stale = False
        self._renderer: QSvgRenderer | None = None
        self._aspect = 0.72  # height / width of the image area
        self._rect = QRectF(0.0, 0.0, 380.0, 380.0 * self._aspect + _TITLE_H + _PAD)
        self._resizing = False
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

    # -- content ------------------------------------------------------

    def set_svg(self, data: bytes) -> None:
        renderer = QSvgRenderer(QByteArray(data))
        if renderer.isValid():
            size = renderer.defaultSize()
            if size.width() > 0:
                self._aspect = size.height() / size.width()
            self._renderer = renderer
            self._reflow()
        self.update()

    def set_stale(self, value: bool) -> None:
        if value != self._stale:
            self._stale = value
            self.update()

    def is_stale(self) -> bool:
        return self._stale

    def title(self) -> str:
        return self._title

    def set_title(self, text: str) -> None:
        self._title = text
        self.update()

    def _reflow(self) -> None:
        """Recompute the box height so the image keeps the SVG's aspect."""
        self.prepareGeometryChange()
        image_w = self._rect.width() - 2 * _PAD
        self._rect.setHeight(image_w * self._aspect + _TITLE_H + _PAD)

    # -- geometry / painting ---------------------------------------

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        return self._rect.adjusted(-3, -3, 3, 3)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:  # noqa: N802
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self._rect, Qt.white)
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawRect(self._rect)

        # -- title strip --------------------------------------------
        title_rect = QRectF(_PAD, 2.0, self._rect.width() - 2 * _PAD, _TITLE_H)
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#202020"))
        text = painter.fontMetrics().elidedText(
            self._title or "", Qt.ElideRight, int(title_rect.width())
        )
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        if self._stale:
            painter.setPen(_MODIFIED_COLOR)
            painter.drawText(title_rect, Qt.AlignRight | Qt.AlignVCenter, _MODIFIED_TAG)

        # -- image area --------------------------------------------
        image_rect = QRectF(
            _PAD,
            _TITLE_H,
            self._rect.width() - 2 * _PAD,
            self._rect.height() - _TITLE_H - _PAD,
        )
        if self._renderer is not None and self._renderer.isValid():
            self._renderer.render(painter, self._fit(image_rect))
        else:
            painter.setPen(QColor("#8a8a8a"))
            painter.setFont(QFont(painter.font().family(), 9))
            painter.drawText(
                image_rect, Qt.AlignCenter | Qt.TextWordWrap,
                "run the pipeline to render this figure",
            )

        if self.isSelected():
            painter.setPen(QPen(_SELECT_COLOR, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._rect)
            painter.fillRect(self._handle_rect(), _SELECT_COLOR)

    def _fit(self, area: QRectF) -> QRectF:
        """Aspect-fit rect for the SVG inside ``area``."""
        if area.width() * self._aspect <= area.height():
            w, h = area.width(), area.width() * self._aspect
        else:
            w, h = area.height() / self._aspect, area.height()
        return QRectF(
            area.left() + (area.width() - w) / 2,
            area.top() + (area.height() - h) / 2,
            w,
            h,
        )

    def _handle_rect(self) -> QRectF:
        return QRectF(
            self._rect.right() - _HANDLE, self._rect.bottom() - _HANDLE, _HANDLE, _HANDLE
        )

    # -- resize (bottom-right handle) vs. move --------------------

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if self.isSelected() and self._handle_rect().contains(event.pos()):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if self._resizing:
            new_w = max(_MIN_W, event.pos().x())
            self.prepareGeometryChange()
            self._rect.setWidth(new_w)
            self._rect.setHeight((new_w - 2 * _PAD) * self._aspect + _TITLE_H + _PAD)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        self._resizing = False
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        in_handle = self.isSelected() and self._handle_rect().contains(event.pos())
        self.setCursor(Qt.SizeFDiagCursor if in_handle else Qt.ArrowCursor)
        super().hoverMoveEvent(event)


#: Default style of a fresh text item, and of the "title" preset.
_TEXT_DEFAULT: dict[str, Any] = {
    "bold": False,
    "italic": False,
    "size": 12,
    "color": "#202020",
    "align": "left",
    "family": "",
}
_TITLE_DEFAULT = {**_TEXT_DEFAULT, "bold": True, "size": 24}

_ALIGN_FLAGS = {
    "left": Qt.AlignLeft,
    "center": Qt.AlignHCenter,
    "right": Qt.AlignRight,
}


class TextItem(QGraphicsTextItem):
    """A free-text commentary / title box, restyled via TextInspector."""

    def __init__(self, text: str = "", is_title: bool = False) -> None:
        super().__init__(text or ("Title" if is_title else "Text"))
        self.is_title = is_title
        self._style: dict[str, Any] = dict(_TITLE_DEFAULT if is_title else _TEXT_DEFAULT)
        self.setFlags(
            QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable
        )
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setTextWidth(320)
        self._apply_style()

    # -- style ------------------------------------------------------

    def style(self) -> dict[str, Any]:
        return dict(self._style)

    def set_style(self, **changes: Any) -> None:
        self._style.update(changes)
        self._apply_style()

    def _apply_style(self) -> None:
        s = self._style
        font = QFont()
        if s["family"]:
            font.setFamily(s["family"])
        font.setPointSize(int(s["size"]))
        font.setBold(bool(s["bold"]))
        font.setItalic(bool(s["italic"]))
        self.setFont(font)
        self.setDefaultTextColor(QColor(s["color"]))
        cursor = self.textCursor()
        cursor.select(QTextCursor.Document)
        block_format = cursor.blockFormat()
        block_format.setAlignment(_ALIGN_FLAGS.get(s["align"], Qt.AlignLeft))
        cursor.mergeBlockFormat(block_format)
        cursor.clearSelection()
        self.setTextCursor(cursor)

    # -- edit on double-click, commit on focus-out ---------------

    def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus(Qt.MouseFocusReason)
        super().mouseDoubleClickEvent(event)

    def focusOutEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        super().focusOutEvent(event)

    # -- paint our own blue contour instead of Qt's dashed one ---

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:  # noqa: N802
        option.state &= ~QStyle.State_Selected
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(_SELECT_COLOR, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect().adjusted(1, 1, -1, -1))


class TextInspector(QWidget):
    """Right-hand form that restyles the selected :class:`TextItem` live."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item: TextItem | None = None

        self._bold = QCheckBox("Bold", self)
        self._italic = QCheckBox("Italic", self)
        self._size = QSpinBox(self)
        self._size.setRange(6, 96)
        self._align = QComboBox(self)
        self._align.addItems(["left", "center", "right"])
        self._family = QFontComboBox(self)
        self._color = QPushButton("Text colour...", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel("Text box", self))
        for widget in (
            self._bold, self._italic, self._size,
            self._align, self._family, self._color,
        ):
            layout.addWidget(widget)
        layout.addStretch(1)

        self._bold.toggled.connect(lambda v: self._push(bold=v))
        self._italic.toggled.connect(lambda v: self._push(italic=v))
        self._size.valueChanged.connect(lambda v: self._push(size=v))
        self._align.currentTextChanged.connect(lambda v: self._push(align=v))
        self._family.currentFontChanged.connect(lambda f: self._push(family=f.family()))
        self._color.clicked.connect(self._pick_color)

    def set_item(self, item: TextItem | None) -> None:
        self._item = None  # suppress feedback while loading
        if item is not None:
            s = item.style()
            self._bold.setChecked(bool(s["bold"]))
            self._italic.setChecked(bool(s["italic"]))
            self._size.setValue(int(s["size"]))
            self._align.setCurrentText(s["align"])
            if s["family"]:
                self._family.setCurrentFont(QFont(s["family"]))
        self._item = item

    def _push(self, **changes: Any) -> None:
        if self._item is not None:
            self._item.set_style(**changes)

    def _pick_color(self) -> None:
        if self._item is None:
            return
        chosen = QColorDialog.getColor(
            QColor(self._item.style()["color"]), self, "Text colour"
        )
        if chosen.isValid():
            self._item.set_style(color=chosen.name())
