"""
Tests for ``ui.popup_delegate`` -- the delegate every dropdown list
gets, and the artefact it exists to remove.
"""

from PySide6.QtWidgets import QComboBox, QStyledItemDelegate

from ruyso_app.ui import popup_delegate, theme
from ruyso_app.ui.popup_delegate import SEPARATOR_HEIGHT, PopupItemDelegate


def _combo_with_separator(qapp) -> QComboBox:
    theme.apply_to_app(qapp)
    combo = QComboBox()
    combo.addItem("table_viewer")
    combo.insertSeparator(1)
    combo.addItems(["box_plot", "histogram_plot"])
    combo.show()  # the popup container is polished with its combo
    return combo


def test_a_dropdown_gets_the_plain_item_delegate(qapp):
    """Qt's own combo delegate paints each row with the *combo* as the
    styled widget, so every row wore the closed combo's bordered box."""
    combo = _combo_with_separator(qapp)
    combo.showPopup()

    assert isinstance(combo.view().itemDelegate(), PopupItemDelegate)
    combo.hidePopup()


def test_a_separator_stays_a_hairline(qapp):
    """The stylesheet gives items a min-height; without a size hint of
    its own a separator inflates into a blank row."""
    combo = _combo_with_separator(qapp)
    combo.showPopup()
    view = combo.view()
    model = combo.model()

    heights = [view.visualRect(model.index(r, 0)).height() for r in range(4)]
    assert heights[1] == SEPARATOR_HEIGHT
    assert heights[0] > SEPARATOR_HEIGHT * 2  # a real row is much taller
    combo.hidePopup()


def test_a_combo_that_paints_its_own_rows_keeps_its_delegate(qapp):
    """The colormap and marker combos draw the preview being chosen."""

    class MyDelegate(QStyledItemDelegate):
        pass

    combo = QComboBox()
    combo.addItems(["a", "b"])
    mine = MyDelegate(combo)
    combo.view().setItemDelegate(mine)

    assert popup_delegate.install_on(combo.view()) is False
    assert combo.view().itemDelegate() is mine


def test_the_separator_role_is_what_identifies_one(qapp):
    combo = _combo_with_separator(qapp)
    model = combo.model()

    assert popup_delegate.is_separator(model.index(1, 0))
    assert not popup_delegate.is_separator(model.index(0, 0))
