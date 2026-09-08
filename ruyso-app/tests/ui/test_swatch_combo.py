"""
Tests for ``ui.swatch_combo.SwatchComboBox`` -- the floating-width
colormap selector (gradient fills the combo, name pinned right).
"""

import pytest
from PySide6.QtCore import QRect
from PySide6.QtGui import QPainter, QPixmap

from ruyso_app.ui import theme
from ruyso_app.ui.swatch_combo import (
    ColormapItemDelegate,
    SwatchComboBox,
    paint_colormap_field,
)


@pytest.fixture(autouse=True)
def _reset_theme():
    theme.set_current_theme("dark")
    yield
    theme.set_theme_mode("system")


def test_combo_paints_at_several_widths_without_error(qapp):
    combo = SwatchComboBox()
    combo.addItems(["viridis", "Blues", "coolwarm", "tab10"])
    combo.setCurrentText("coolwarm")
    for w in (140, 260, 420):
        combo.setFixedWidth(w)
        combo.resize(w, 26)
        pm = combo.grab()  # forces paintEvent
        assert not pm.isNull() and pm.width() == w


def test_paint_colormap_field_is_a_noop_on_a_tiny_rect(qapp):
    pm = QPixmap(4, 4)
    pm.fill()
    painter = QPainter(pm)
    # too small to draw into -- must not raise
    paint_colormap_field(painter, QRect(0, 0, 1, 1), "viridis")
    paint_colormap_field(painter, QRect(0, 0, 40, 16), "")  # empty name
    painter.end()


def test_delegate_size_hint_gives_a_row_tall_enough_for_a_strip(qapp):
    combo = SwatchComboBox()
    combo.addItems(["viridis"])
    delegate = combo.view().itemDelegate()
    assert isinstance(delegate, ColormapItemDelegate)
    from PySide6.QtWidgets import QStyleOptionViewItem

    opt = QStyleOptionViewItem()
    hint = delegate.sizeHint(opt, combo.model().index(0, 0))
    assert hint.height() >= 20
