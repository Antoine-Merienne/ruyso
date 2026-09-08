"""
``SwatchComboBox`` -- a non-editable combo whose choices are colormaps,
drawn as a full-width gradient with the map's name pinned to the right.

The gradient fills whatever width the combo currently has (it follows
the Options panel as it is resized) in *both* the open dropdown list
(``ColormapItemDelegate``) and the closed combo
(``SwatchComboBox.paintEvent``), so the selector looks the same open or
shut. The name sits in a translucent rounded pill so it stays readable
over the light and the dark end of any map.

Used by the Options panel for every ``colormap`` field; the colormap
designer / manager (a later batch) can reuse it as-is.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QComboBox,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QStyledItemDelegate,
)

from ruyso_app.ui import swatches, theme

_ROW_HEIGHT = 22
_PILL_PAD_X = 6
_PILL_PAD_Y = 2


def paint_colormap_field(
    painter: QPainter, rect: QRect, name: str, *, radius: float = 0.0
) -> None:
    """Fill ``rect`` with colormap ``name`` and draw the name, right-aligned,
    in a translucent pill. ``radius`` rounds the gradient's corners to sit
    inside a rounded frame."""
    if rect.width() <= 2 or rect.height() <= 2 or not name:
        return

    pm = swatches.colormap_pixmap(name, rect.size())
    painter.save()
    if radius:
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(rect), radius, radius)
        painter.setClipPath(clip)
    painter.drawPixmap(rect.topLeft(), pm)
    painter.restore()

    th = theme.current_theme()
    fm = painter.fontMetrics()
    tw = fm.horizontalAdvance(name)
    pill_w = tw + 2 * _PILL_PAD_X
    pill_h = fm.height() + 2 * _PILL_PAD_Y
    pill = QRect(
        rect.right() - pill_w - 4,
        rect.center().y() - pill_h // 2 + 1,
        pill_w,
        pill_h,
    )
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    bg = QColor(th.panel_background)
    bg.setAlpha(220)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(pill, pill_h / 2, pill_h / 2)
    painter.setPen(QColor(th.text_color))
    painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, name)
    painter.restore()


class ColormapItemDelegate(QStyledItemDelegate):
    """Paints one dropdown row as a full-width colormap strip."""

    def paint(self, painter, option, index):  # noqa: N802 - Qt override
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        strip = option.rect.adjusted(3, 2, -3, -2)
        paint_colormap_field(painter, strip, index.data() or "")
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802 - Qt override
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), _ROW_HEIGHT + 4))
        return size


class SwatchComboBox(QComboBox):
    """A non-editable combo that renders its value as a colormap strip."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._delegate = ColormapItemDelegate(self)
        self.view().setItemDelegate(self._delegate)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QStylePainter(self)
        opt = QStyleOptionComboBox()
        self.initStyleOption(opt)
        # Frame + drop-down arrow from the style/QSS, but NOT the
        # built-in current-text label (drawControl(CE_ComboBoxLabel));
        # we paint the strip over the edit field instead.
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, opt)
        field = self.style().subControlRect(
            QStyle.ComplexControl.CC_ComboBox,
            opt,
            QStyle.SubControl.SC_ComboBoxEditField,
            self,
        )
        paint_colormap_field(
            painter, field.adjusted(1, 1, -1, -1), self.currentText(), radius=6.0
        )
