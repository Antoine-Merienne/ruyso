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
* :class:`ImageItem` -- a picture imported from a file, embedded in the
  saved pipeline.
* :class:`TextItem` -- a free-text commentary / title, restyled live
  through :class:`TextInspector` (bold, italic, size, colour,
  alignment, font family). Resized horizontally from a handle on its
  right edge; its height follows the number of lines.

Every block has a **frame** -- contour, fill, corner radius -- styled by
the shape inspector (``dashboard_shapes.ShapeInspector``), which the
text inspector embeds and a figure reaches through its right-click
"Cosmetic Panel...". All are selectable / movable; the view's
rubber-band drag multi-selects and a multi-selection drags as a group.
Selection draws a blue contour.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
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

from ruyso_app.ui.dashboard_shapes import ShapeInspector, paint_frame

#: Blue selection contour shared by both item kinds.
_SELECT_COLOR = QColor("#3b82f6")
#: Table tab's "· modified" tag (kept in sync with ``ui.table_page``).
_MODIFIED_TAG = "· modified"
_MODIFIED_COLOR = QColor("#d8be55")

_TITLE_H = 22.0
_PAD = 8.0
_HANDLE = 13.0
_MIN_W = 140.0
#: Narrowest a text box can be dragged: about one short word.
_MIN_TEXT_W = 40.0


class _Block(QGraphicsObject):
    """
    A framed, aspect-locked block resized from its bottom-right handle:
    the shared half of :class:`FigureItem` and :class:`ImageItem`.

    Its frame (contour, fill, corner radius) is a style dict over
    ``dashboard_shapes.FRAME_KEYS``, edited by the same inspector as a
    shape.
    """

    #: What the inspector heading calls one of these.
    BLOCK_NAME = "block"
    #: A fresh block's frame.
    FRAME_DEFAULT: dict[str, Any] = {}

    def __init__(self) -> None:
        super().__init__()
        self._locked = False
        self._aspect = 0.72  # height / width of the content area
        self._rect = QRectF(0.0, 0.0, 380.0, 380.0)
        self._style: dict[str, Any] = dict(self.FRAME_DEFAULT)
        self._resizing = False
        self.setFlags(
            QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)

    def _height_for(self, width: float) -> float:
        """The block height that keeps the content at its aspect."""
        return width * self._aspect

    def _reflow(self) -> None:
        self.prepareGeometryChange()
        self._rect.setHeight(self._height_for(self._rect.width()))

    # -- frame style -------------------------------------------------

    def style(self) -> dict[str, Any]:
        return dict(self._style)

    def set_style(self, **changes: Any) -> None:
        self._style.update(changes)
        self.update()

    def _apply_saved_style(self, state: dict[str, Any]) -> None:
        # A file saved before frames existed has no style: defaults.
        self._style = {**self.FRAME_DEFAULT, **(state.get("style") or {})}

    # -- geometry ------------------------------------------------------

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        pad = 3.0 + float(self._style.get("stroke_width") or 0.0) / 2
        return self._rect.adjusted(-pad, -pad, pad, pad)

    def visual_rect(self) -> QRectF:
        """The block itself, without boundingRect's selection padding --
        what ``dashboard_layout`` aligns on."""
        return QRectF(self._rect)

    def _handle_rect(self) -> QRectF:
        return QRectF(
            self._rect.right() - _HANDLE, self._rect.bottom() - _HANDLE, _HANDLE, _HANDLE
        )

    def _paint_selection(self, painter: QPainter) -> None:
        if self.isSelected():
            painter.setPen(QPen(_SELECT_COLOR, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self._rect)
            painter.fillRect(self._handle_rect(), _SELECT_COLOR)

    # -- locking ---------------------------------------------------

    def is_locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        """A locked block cannot be selected, moved, resized or deleted.

        Dashboard > Unlock all is the way back: a block you cannot
        select is a block you cannot unlock from its own inspector."""
        self._locked = bool(locked)
        self.setFlag(QGraphicsItem.ItemIsMovable, not self._locked)
        self.setFlag(QGraphicsItem.ItemIsSelectable, not self._locked)
        if self._locked:
            self.setSelected(False)
        self.update()

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
            self._rect.setHeight(self._height_for(new_w))
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


class FigureItem(_Block):
    """A pipeline figure on the dashboard canvas, keyed to its export node."""

    BLOCK_NAME = "figure"
    #: White card with a hairline border: how a figure looked before
    #: frames were stylable.
    FRAME_DEFAULT = {
        "fill": "#ffffff", "fill_alpha": 1.0,
        "stroke": "#c4c4c4", "stroke_width": 1.0, "stroke_style": "solid",
        "radius": 0.0,
    }

    def __init__(self, export_node_id: str, title: str = "") -> None:
        super().__init__()
        self.export_node_id = export_node_id
        self._title = title
        self._stale = False
        self._renderer: QSvgRenderer | None = None
        self._reflow()

    def _height_for(self, width: float) -> float:
        return (width - 2 * _PAD) * self._aspect + _TITLE_H + _PAD

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

    # -- painting ----------------------------------------------------

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:  # noqa: N802
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_frame(painter, self._rect, self._style, lambda: self._paint_content(painter))
        self._paint_selection(painter)

    def _paint_content(self, painter: QPainter) -> None:
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

    # -- undo / persistence state ----------------------------------

    def capture_state(self) -> dict[str, Any]:
        # The export node's name is what a saved block is re-bound by
        # when the file is opened again -- everything else about a
        # figure comes back from running the pipeline.
        return {
            "export_node_id": self.export_node_id,
            "title": self._title,
            "stale": self._stale,
            "locked": self._locked,
            "width": self._rect.width(),
            "aspect": self._aspect,
            "style": dict(self._style),
        }

    def apply_state(self, state: dict[str, Any]) -> None:
        self.prepareGeometryChange()
        self.export_node_id = state.get("export_node_id", self.export_node_id)
        self._title = state.get("title", self._title)
        self._stale = state.get("stale", self._stale)
        self._aspect = state.get("aspect", self._aspect)
        self._apply_saved_style(state)
        self._rect.setWidth(state.get("width", self._rect.width()))
        self._reflow()
        self.set_locked(state.get("locked", False))
        self.update()


#: What the Import Image dialog offers: everything Qt reads on every
#: platform (the gif / jpeg / webp / svg readers are Qt plugins, which
#: the self-test checks a frozen build carries).
IMAGE_FORMATS = ("png", "jpg", "jpeg", "svg", "gif", "bmp", "webp")
IMAGE_FILTER = "Images (" + " ".join(f"*.{f}" for f in IMAGE_FORMATS) + ")"


class ImageItem(_Block):
    """
    An image imported onto the dashboard.

    The file's bytes are **embedded**, base64, in the block's state -- so
    a saved pipeline carries its images and opens complete on another
    machine. The encoded string is made once and handed out by
    reference, so every undo snapshot shares it rather than copying it.
    An SVG stays a vector (sharp in a PDF export); anything else is drawn
    from a ``QImage``.
    """

    BLOCK_NAME = "image"
    FRAME_DEFAULT = {
        "fill": "", "fill_alpha": 1.0,
        "stroke": "#1f2937", "stroke_width": 0.0, "stroke_style": "solid",
        "radius": 0.0,
    }

    def __init__(self) -> None:
        super().__init__()
        self._data = ""  # base64 of the file
        self._format = "png"
        self._svg: QSvgRenderer | None = None
        self._image: QImage | None = None

    @classmethod
    def from_file(cls, path: str) -> "ImageItem":
        """A new block holding the image at ``path``, at its natural width
        (capped, so a photo does not arrive the size of a wall)."""
        file = Path(path)
        item = cls()
        size = item._load(base64.b64encode(file.read_bytes()).decode("ascii"),
                          file.suffix.lower().lstrip("."))
        if size is None:
            raise ValueError(f"{file.name} is not an image Ruyso can read.")
        item._rect.setWidth(max(_MIN_W, min(480.0, float(size.width()))))
        item._reflow()
        return item

    def _load(self, data: str, fmt: str) -> QSize | None:
        """Decode ``data``; return its natural size, or ``None`` if unreadable."""
        raw = QByteArray(base64.b64decode(data))
        if fmt == "svg":
            renderer = QSvgRenderer(raw)
            if not renderer.isValid():
                return None
            self._svg, self._image, size = renderer, None, renderer.defaultSize()
        else:
            image = QImage()
            if not image.loadFromData(raw) or image.isNull():
                return None
            self._svg, self._image, size = None, image, image.size()
        self._data, self._format = data, fmt
        if size.width() > 0:
            self._aspect = size.height() / size.width()
        self._reflow()
        return size

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:  # noqa: N802
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        def content() -> None:
            if self._svg is not None:
                self._svg.render(painter, self._rect)
            elif self._image is not None:
                painter.drawImage(self._rect, self._image)

        paint_frame(painter, self._rect, self._style, content)
        self._paint_selection(painter)

    def capture_state(self) -> dict[str, Any]:
        return {
            "data": self._data,
            "format": self._format,
            "width": self._rect.width(),
            "locked": self._locked,
            "style": dict(self._style),
        }

    def apply_state(self, state: dict[str, Any]) -> None:
        self.prepareGeometryChange()
        data = state.get("data") or ""
        if data and data is not self._data:  # an undo snapshot shares it
            self._load(data, str(state.get("format", "png")))
        self._apply_saved_style(state)
        self._rect.setWidth(state.get("width", self._rect.width()))
        self._reflow()
        self.set_locked(state.get("locked", False))
        self.update()


#: Default style of a fresh text item, and of the "title" preset.
_TEXT_DEFAULT: dict[str, Any] = {
    "bold": False,
    "italic": False,
    "size": 12,
    "color": "#202020",
    "align": "left",
    "family": "",
    "locked": False,
    # frame: none by default -- a caption is just text
    "fill": "",
    "fill_alpha": 1.0,
    "stroke": "#1f2937",
    "stroke_width": 0.0,
    "stroke_style": "solid",
    "radius": 0.0,
}
_TITLE_DEFAULT = {**_TEXT_DEFAULT, "bold": True, "size": 24}

_ALIGN_FLAGS = {
    "left": Qt.AlignLeft,
    "center": Qt.AlignHCenter,
    "right": Qt.AlignRight,
}


class TextItem(QGraphicsTextItem):
    """A free-text commentary / title box, restyled via TextInspector.

    Its width is set by the person (the handle on the right edge); its
    height is always the text's, so a box grows a line at a time."""

    BLOCK_NAME = "text box"

    def __init__(self, text: str = "", is_title: bool = False) -> None:
        super().__init__(text or ("Title" if is_title else "Text"))
        self.is_title = is_title
        self._style: dict[str, Any] = dict(_TITLE_DEFAULT if is_title else _TEXT_DEFAULT)
        preferred = self._preferred_family()
        if preferred:
            self._style["family"] = preferred
        self.setFlags(
            QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable
        )
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setTextWidth(320)
        self.setAcceptHoverEvents(True)
        self._resizing = False
        self._over_handle = False
        self._apply_style()

    # -- style ------------------------------------------------------

    def _preferred_family(self) -> str:
        """The Dashboard font preference for this kind of item, if set."""
        from ruyso_app.engine import settings

        key = "dashboard.title_font" if self.is_title else "dashboard.text_font"
        return str(settings.get(key) or "")

    def apply_font_preference(self) -> None:
        """
        Adopt the current font preference, unless this item was restyled.

        A person who picked a font in the inspector has said what they
        want for that box; changing the default afterwards should not
        undo it. Only an item still on its inherited family follows.
        """
        preferred = self._preferred_family()
        if not preferred or self._style.get("_family_chosen"):
            return
        self.set_style(family=preferred)
        self._style["_family_chosen"] = False  # still inherited

    # -- locking ---------------------------------------------------

    def is_locked(self) -> bool:
        return bool(self._style.get("locked"))

    def set_locked(self, locked: bool) -> None:
        """See FigureItem.set_locked -- same contract."""
        self._style["locked"] = bool(locked)
        self.setFlag(QGraphicsItem.ItemIsMovable, not locked)
        self.setFlag(QGraphicsItem.ItemIsSelectable, not locked)
        if locked:
            self.setSelected(False)
        self.update()

    # -- undo / persistence state ----------------------------------

    def capture_state(self) -> dict[str, Any]:
        return {
            "text": self.toPlainText(),
            "style": dict(self._style),
            "is_title": self.is_title,
            "width": self.textWidth(),
        }

    def apply_state(self, state: dict[str, Any]) -> None:
        self.is_title = state.get("is_title", self.is_title)
        self.setPlainText(state.get("text", self.toPlainText()))
        self.setTextWidth(state.get("width", self.textWidth()))
        # Defaults first: a file saved before frames existed lacks them.
        base = _TITLE_DEFAULT if self.is_title else _TEXT_DEFAULT
        self._style = {**base, **state.get("style", self._style)}
        self._apply_style()
        self.set_locked(bool(self._style.get("locked")))

    def style(self) -> dict[str, Any]:
        return dict(self._style)

    def set_style(self, **changes: Any) -> None:
        self.prepareGeometryChange()  # a thicker contour draws further out
        self._style.update(changes)
        self._apply_style()
        self.update()

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

    # -- horizontal resize from the right-edge handle -----------

    def _handle_rect(self) -> QRectF:
        box = QGraphicsTextItem.boundingRect(self)
        return QRectF(box.right() - 7, box.center().y() - 9, 7, 18)

    def _editing(self) -> bool:
        return bool(self.textInteractionFlags() & Qt.TextEditable)

    def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if (
            self.isSelected()
            and not self._editing()
            and self._handle_rect().contains(event.pos())
        ):
            self._resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        if self._resizing:
            # The height follows: the document re-wraps to the new width.
            self.setTextWidth(max(_MIN_TEXT_W, event.pos().x()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        self._resizing = False
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
        # Only touch the cursor when crossing the handle: while editing,
        # the text item sets its own I-beam, and resetting it on every
        # move would fight that.
        over = self.isSelected() and self._handle_rect().contains(event.pos())
        if over != self._over_handle:
            self._over_handle = over
            if over:
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.unsetCursor()
        super().hoverMoveEvent(event)

    # -- frame, text, then our own blue contour instead of Qt's dashed one

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt override
        pad = float(self._style.get("stroke_width") or 0.0) / 2
        return QGraphicsTextItem.boundingRect(self).adjusted(-pad, -pad, pad, pad)

    def visual_rect(self) -> QRectF:
        """The box itself, without its contour's overhang -- what
        ``dashboard_layout`` aligns on."""
        return QGraphicsTextItem.boundingRect(self)

    def paint(self, painter: QPainter, option: Any, widget: Any = None) -> None:  # noqa: N802
        option.state &= ~QStyle.State_Selected
        box = QGraphicsTextItem.boundingRect(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        paint_frame(
            painter, box, self._style,
            lambda: QGraphicsTextItem.paint(self, painter, option, widget),
        )
        if self.isSelected():
            painter.setPen(QPen(_SELECT_COLOR, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(box.adjusted(1, 1, -1, -1))
            painter.fillRect(self._handle_rect(), _SELECT_COLOR)


class TextInspector(QWidget):
    """Right-hand form that restyles the selected :class:`TextItem` live."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[TextItem] = []

        self._bold = QCheckBox("Bold", self)
        self._italic = QCheckBox("Italic", self)
        self._size = QSpinBox(self)
        self._size.setRange(6, 96)
        self._align = QComboBox(self)
        self._align.addItems(["left", "center", "right"])
        self._family = QFontComboBox(self)
        self._color = QPushButton("Text colour...", self)

        #: Contour / fill / corners -- the same form a shape uses.
        self.frame = ShapeInspector(self)
        self.frame.layout().setContentsMargins(0, 12, 0, 0)
        self.frame.changed = lambda: self.changed()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(QLabel("Text box", self))
        for widget in (
            self._bold, self._italic, self._size,
            self._align, self._family, self._color,
        ):
            layout.addWidget(widget)
        layout.addWidget(self.frame)
        layout.addStretch(1)

        self._bold.toggled.connect(lambda v: self._push(bold=v))
        self._italic.toggled.connect(lambda v: self._push(italic=v))
        self._size.valueChanged.connect(lambda v: self._push(size=v))
        self._align.currentTextChanged.connect(lambda v: self._push(align=v))
        # ``_family_chosen`` records that this box's font was picked by
        # hand, so a later change to the Dashboard font preference
        # leaves it alone (see TextItem.apply_font_preference).
        self._family.currentFontChanged.connect(
            lambda f: self._push(family=f.family(), _family_chosen=True)
        )
        self._color.clicked.connect(self._pick_color)

    def set_items(self, items: list[TextItem]) -> None:
        """
        Bind the form to one text box or to several at once.

        Editing a whole selection is most of why the pane exists: making
        five captions match by hand is the tedious part. Where the
        selection disagrees the field simply shows the first one's
        value, and setting it applies to all.
        """
        self._items = []  # suppress feedback while loading
        if items:
            s = items[0].style()
            self._bold.setChecked(bool(s["bold"]))
            self._italic.setChecked(bool(s["italic"]))
            self._size.setValue(int(s["size"]))
            self._align.setCurrentText(s["align"])
            if s["family"]:
                self._family.setCurrentFont(QFont(s["family"]))
        self.frame.set_items(list(items), heading="Frame")
        self._items = list(items)

    def set_item(self, item: TextItem | None) -> None:
        """Bind a single item (kept for callers that have just one)."""
        self.set_items([item] if item is not None else [])

    def items(self) -> list[TextItem]:
        return list(self._items)

    def _push(self, **changes: Any) -> None:
        for item in self._items:
            item.set_style(**changes)
        self.changed()

    def changed(self) -> None:
        """Hook the page replaces, so an edit can be pushed onto undo."""

    def _pick_color(self) -> None:
        if not self._items:
            return
        chosen = QColorDialog.getColor(
            QColor(self._items[0].style()["color"]), self, "Text colour"
        )
        if chosen.isValid():
            self._push(color=chosen.name())
