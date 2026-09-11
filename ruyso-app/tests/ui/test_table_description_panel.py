"""
Tests for the Table tab's "Table description" panel: each variable
table is as tall as its rows, and the grip under it caps one that does
not fit (``ui.height_grip``).
"""

import pandas as pd

from ruyso_app.ui.height_grip import DEFAULT_CAP
from ruyso_app.ui.table_page import TableDescriptionWidget


def _description(frame):
    widget = TableDescriptionWidget()
    widget.show_description(frame)
    return widget


def _wide_frame(n_numeric=12):
    data = {f"n{i}": [float(i), float(i) + 1] for i in range(n_numeric)}
    data["kind"] = ["x", "y"]
    return pd.DataFrame(data)


def test_a_table_that_fits_keeps_its_content_height_and_has_no_grip(qapp):
    """The tables were always as tall as their rows; the grip is only
    there to cap one that does not fit."""
    widget = _description(pd.DataFrame({"a": [1.0, 2.0], "kind": ["x", "y"]}))

    assert not widget._numeric_grip.is_capping()
    assert not widget._numeric_grip.isVisible()
    assert widget._numeric_table.height() < 200


def test_a_long_table_is_capped_and_gets_a_grip(qapp):
    widget = _description(_wide_frame())

    assert widget._numeric_table.height() == DEFAULT_CAP
    assert widget._numeric_grip.is_capping()
    assert widget._numeric_grip.isVisibleTo(widget)


def test_dragging_the_grip_changes_how_much_of_the_panel_a_table_takes(qapp):
    widget = _description(_wide_frame())

    widget._numeric_grip.resize_target(340)
    assert widget._numeric_table.height() == 340


def test_a_variable_table_is_never_given_a_minimum_above_its_maximum(qapp):
    """Setting the height in one place and the cap in another left
    min > max, and the layout then stacked the sections on top of each
    other -- the gap under "String / categorical variables"."""
    widget = _description(_wide_frame())

    for table in (widget._numeric_table, widget._categorical_table):
        assert table.minimumHeight() <= table.maximumHeight()


def test_each_section_sits_directly_under_its_own_title(qapp):
    widget = _description(_wide_frame())
    widget.resize(460, 700)
    widget.show()
    layout = widget._content.layout()
    spacing = layout.spacing()

    def bottom(w):
        return w.y() + w.height()

    assert widget._numeric_table.y() == bottom(widget._numeric_label) + spacing
    assert widget._categorical_table.y() == bottom(widget._categorical_label) + spacing
    # ... and nothing overlaps what comes after it.
    assert widget._numeric_grip.y() >= bottom(widget._numeric_table)


def test_a_grip_is_hidden_with_the_table_it_caps(qapp):
    widget = _description(pd.DataFrame({"only_text": ["x", "y"]}))

    assert not widget._numeric_table.isVisible()
    assert not widget._numeric_grip.isVisible()
