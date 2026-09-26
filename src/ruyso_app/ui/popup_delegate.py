"""
The item delegate every dropdown list is given.

Qt draws a combo popup's rows with its own private ``QComboBoxDelegate``,
which hands the **combo box** to the style as the widget being painted.
Under a stylesheet that means each row is resolved against the
``QComboBox`` rule -- so a row came out wearing the closed combo's own
bordered, rounded box, and on the light theme that read as a white
rectangle sitting in the list.

A plain :class:`QStyledItemDelegate` draws rows as what they are, view
items, so the ``QComboBox QAbstractItemView::item`` rules in
:mod:`ui.theme` apply -- including the rounded hover overlay.

Separators are the one thing that delegate does not know about: Qt marks
them with ``"separator"`` in ``AccessibleDescriptionRole`` and relies on
the combo delegate to draw them. They are drawn here instead, as a
hairline, with a size hint small enough that the stylesheet's item
``min-height`` cannot inflate them into a blank row.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QStyledItemDelegate

from ruyso_app.ui import theme

#: Row height reserved for a separator, in pixels.
SEPARATOR_HEIGHT = 7
#: Left/right inset of the separator line inside that row.
SEPARATOR_MARGIN = 8


def is_separator(index: QModelIndex) -> bool:
    """Whether a model row is one of ``QComboBox.insertSeparator``'s."""
    return index.data(Qt.AccessibleDescriptionRole) == "separator"


class PopupItemDelegate(QStyledItemDelegate):
    """Draws dropdown rows as view items, and separators as a hairline."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt override
        if is_separator(index):
            return QSize(option.rect.width(), SEPARATOR_HEIGHT)
        return super().sizeHint(option, index)

    def paint(self, painter, option, index) -> None:
        if not is_separator(index):
            super().paint(painter, option, index)
            return
        rect = option.rect
        y = rect.center().y()
        painter.save()
        painter.setPen(QColor(theme.current_theme().border_color))
        painter.drawLine(
            rect.left() + SEPARATOR_MARGIN, y, rect.right() - SEPARATOR_MARGIN, y
        )
        painter.restore()


def install_on(view: QAbstractItemView) -> bool:
    """
    Give ``view`` the delegate, unless it already has one of its own.

    Returns whether it was installed. A combo that paints its own rows
    (the colormap and marker swatches, ``ui/swatch_combo.py``) keeps its
    delegate: those draw the preview the person is choosing by.
    """
    current = view.itemDelegate()
    # QComboBoxDelegate is Qt's own (a QStyledItemDelegate subclass).
    if isinstance(current, QStyledItemDelegate) and not current.inherits("QComboBoxDelegate"):
        return False  # someone set a real delegate; leave it alone
    view.setItemDelegate(PopupItemDelegate(view))
    return True
