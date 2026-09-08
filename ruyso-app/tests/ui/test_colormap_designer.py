"""
Tests for ``ui.colormap_designer`` -- the custom-colormap editor.
"""

import pytest

from ruyso_app.engine import colormaps as cm
from ruyso_app.ui.colormap_designer import ColormapDesigner, GradientBar, SwatchList


@pytest.fixture(autouse=True)
def _fresh_store():
    cm.save_store({"custom": {}, "lists": {}})
    cm._last_signature = None
    yield
    cm.save_store({"custom": {}, "lists": {}})


def test_gradient_bar_stops_reverse_and_seed(qapp):
    bar = GradientBar()
    bar.set_stops([[0.0, "#000000"], [0.4, "#ff0000"], [1.0, "#ffffff"]])
    assert [round(p, 2) for p, _c in bar.stops()] == [0.0, 0.4, 1.0]

    bar.reverse()
    assert [round(p, 2) for p, _c in bar.stops()] == [0.0, 0.6, 1.0]

    bar.seed_from("viridis", n=5)
    assert len(bar.stops()) == 5


def test_swatch_list_edits(qapp):
    strip = SwatchList()
    strip.set_colours(["#111111", "#222222", "#333333"])
    assert strip.colours() == ["#111111", "#222222", "#333333"]

    strip.reverse()
    assert strip.colours() == ["#333333", "#222222", "#111111"]

    strip.seed_from("tab10")
    assert len(strip.colours()) >= 3


def test_save_writes_a_continuous_custom_map_and_emits(qapp):
    dialog = ColormapDesigner()
    seen: list[int] = []
    dialog.changed.connect(lambda: seen.append(1))

    dialog._kind_cont.setChecked(True)
    dialog._name.setText("Sunset")
    dialog._gradient.set_stops([[0.0, "#03071e"], [1.0, "#ffba08"]])
    dialog._save()

    assert seen == [1]
    definition = cm.custom_definitions()["Sunset"]
    assert definition["kind"] == "continuous"
    assert len(definition["stops"]) == 2


def test_save_rejects_a_builtin_name(qapp, monkeypatch):
    from ruyso_app.ui import colormap_designer as mod

    warned: list[str] = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))

    dialog = ColormapDesigner()
    dialog._name.setText("viridis")
    dialog._save()

    assert warned and "viridis" not in cm.custom_definitions()


def test_delete_removes_the_custom_map(qapp, monkeypatch):
    from ruyso_app.ui import colormap_designer as mod

    monkeypatch.setattr(
        mod.QMessageBox, "question",
        lambda *a, **k: mod.QMessageBox.StandardButton.Yes,
    )
    cm.upsert("Temp", {"kind": "qualitative", "colors": ["#111", "#222"]})

    dialog = ColormapDesigner()
    dialog._existing.setCurrentText("Temp")
    dialog._delete()

    assert "Temp" not in cm.custom_definitions()


def test_editing_an_existing_map_loads_its_definition(qapp):
    cm.upsert("Ocean", {"kind": "continuous", "stops": [[0.0, "#001d3d"], [1.0, "#caf0f8"]]})

    dialog = ColormapDesigner()
    dialog._existing.setCurrentText("Ocean")

    assert dialog._name.text() == "Ocean"
    assert dialog._kind_cont.isChecked()
    assert len(dialog._gradient.stops()) == 2
