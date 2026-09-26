"""
Tests for ``ui.colormap_manager`` -- curating the dropdown colormap
lists.
"""

import pytest
from PySide6.QtCore import Qt

from ruyso_app.engine import colormaps as cm
from ruyso_app.ui.colormap_manager import ColormapManager


@pytest.fixture(autouse=True)
def _fresh_store():
    cm.save_store({"custom": {}, "lists": {}})
    cm._last_signature = None
    yield
    cm.save_store({"custom": {}, "lists": {}})


def _item(widget, name):
    return next(
        widget.item(i) for i in range(widget.count()) if widget.item(i).text() == name
    )


def test_populates_both_kinds_all_checked_by_default(qapp):
    dialog = ColormapManager()
    cont = dialog._lists["continuous"]
    assert cont.count() == len(cm.BUILTIN["continuous"])
    assert all(
        cont.item(i).checkState() == Qt.Checked for i in range(cont.count())
    )


def test_unchecking_hides_a_map_on_accept(qapp):
    dialog = ColormapManager()
    _item(dialog._lists["continuous"], "viridis").setCheckState(Qt.Unchecked)
    seen: list[int] = []
    dialog.changed.connect(lambda: seen.append(1))

    dialog._accept()

    assert seen == [1]
    assert "viridis" not in cm.resolved_lists()["continuous"]
    assert "plasma" in cm.resolved_lists()["continuous"]


def test_selection_safety_net_keeps_one_when_all_unchecked(qapp):
    dialog = ColormapManager()
    widget = dialog._lists["qualitative"]
    for i in range(widget.count()):
        widget.item(i).setCheckState(Qt.Unchecked)

    picked = dialog.selection()["qualitative"]
    assert len(picked) == 1


def test_reset_restores_defaults(qapp):
    cm.set_lists({"continuous": ["coolwarm"], "qualitative": ["Set2"]})
    dialog = ColormapManager()
    dialog._reset()

    cont = dialog._lists["continuous"]
    assert all(cont.item(i).checkState() == Qt.Checked for i in range(cont.count()))
    assert cm.resolved_lists()["continuous"] == cm.BUILTIN["continuous"]


def test_custom_maps_appear_in_the_manager(qapp):
    cm.upsert("Ocean", {"kind": "continuous", "stops": [[0.0, "#012"], [1.0, "#9ef"]]})
    dialog = ColormapManager()
    names = [
        dialog._lists["continuous"].item(i).text()
        for i in range(dialog._lists["continuous"].count())
    ]
    assert "Ocean" in names
