"""
Tests for ``ui.preferences_dialog``.

Two properties carry the design. Every preference that exists must have
a control -- a setting nobody can reach is dead weight, and one that
appears in the dialog but writes nothing is worse. And nothing is
committed until OK or Apply, because several of these change how the
whole app looks the moment they land.
"""

import pytest

from ruyso_app.engine import settings
from ruyso_app.ui.preferences_dialog import PAGES, PreferencesDialog, human_size


@pytest.fixture
def dialog(qapp):
    """A dialog that is always closed, so its measuring thread is joined."""
    widget = PreferencesDialog()
    yield widget
    widget.close()


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    settings.reset()


def _apply_button(dialog):
    from PySide6.QtWidgets import QDialogButtonBox

    return dialog._buttons.button(QDialogButtonBox.Apply)


# -- coverage of the settings ------------------------------------------


def test_every_preference_has_a_control(dialog):
    """A setting with no way to reach it is dead weight."""
    reachable = set(dialog._loaders)
    expected = set(settings.DEFAULTS) - set(settings.INTERNAL_KEYS)
    assert expected - reachable == set()


def test_no_control_edits_something_that_is_not_a_setting(dialog):
    assert set(dialog._loaders) <= set(settings.DEFAULTS)


def test_the_apps_own_bookkeeping_is_not_shown(dialog):
    """Window geometry and the last file are written by the app, not chosen."""
    assert set(dialog._loaders).isdisjoint(settings.INTERNAL_KEYS)


def test_every_page_is_built(dialog):
    assert dialog._stack.count() == len(PAGES)
    assert dialog._categories.count() == len(PAGES)


# -- staging -----------------------------------------------------------


def test_nothing_is_committed_until_apply(dialog):
    dialog._stage("execution.debounce_ms", 900)

    assert dialog.has_pending_changes()
    assert settings.get("execution.debounce_ms") == 450  # still the old value

    dialog.apply_changes()
    assert settings.get("execution.debounce_ms") == 900
    assert not dialog.has_pending_changes()


def test_cancel_discards_the_staged_edits(dialog):
    dialog._stage("execution.debounce_ms", 900)
    dialog.reject()

    assert settings.get("execution.debounce_ms") == 450
    assert not dialog.has_pending_changes()


def test_staging_back_to_the_stored_value_is_not_a_change(dialog):
    """Toggling a checkbox twice should not leave Apply lit."""
    dialog._stage("cache.enabled", False)
    assert dialog.has_pending_changes()

    dialog._stage("cache.enabled", True)
    assert not dialog.has_pending_changes()


def test_apply_is_disabled_until_something_changes(dialog):
    assert not _apply_button(dialog).isEnabled()
    dialog._stage("cache.enabled", False)
    assert _apply_button(dialog).isEnabled()
    dialog.apply_changes()
    assert not _apply_button(dialog).isEnabled()


def test_applying_announces_itself(dialog):
    seen: list[int] = []
    dialog.applied.connect(lambda: seen.append(1))

    dialog._stage("appearance.theme", "light")
    dialog.apply_changes()

    assert seen == [1]


def test_applying_nothing_announces_nothing(dialog):
    seen: list[int] = []
    dialog.applied.connect(lambda: seen.append(1))
    dialog.apply_changes()
    assert seen == []


# -- widgets reflect the store -----------------------------------------


def test_controls_load_the_stored_values(qapp):
    settings.update({"execution.debounce_ms": 1200, "appearance.theme": "light"})
    widget = PreferencesDialog()
    try:
        # Re-reading is what reload_all does; it must not stage anything.
        widget.reload_all()
        assert not widget.has_pending_changes()
    finally:
        widget.close()


def test_reload_drops_pending_edits(dialog):
    dialog._stage("execution.debounce_ms", 900)
    dialog.reload_all()
    assert not dialog.has_pending_changes()


# -- helpers -----------------------------------------------------------


@pytest.mark.parametrize(
    "num_bytes, expected",
    [(0, "0 B"), (512, "512 B"), (1536, "2 KB"), (5 * 1024**2, "5.0 MB")],
)
def test_human_size(num_bytes, expected):
    assert human_size(num_bytes) == expected


def test_human_size_admits_when_it_does_not_know():
    assert human_size(-1) == "unknown"


# -- the Toolbox page ----------------------------------------------------

from ruyso_app.core import toolboxes  # noqa: E402


def test_every_family_gets_a_checkbox(dialog):
    assert set(dialog._toolbox_boxes) == {t.key for t in toolboxes.all_toolboxes()}


def test_the_essential_families_are_shown_on_and_not_switchable(dialog):
    for key in toolboxes.essential_keys():
        box = dialog._toolbox_boxes[key]
        assert box.isChecked() and not box.isEnabled()


def test_the_total_counts_the_enabled_nodes(dialog):
    total = sum(len(v) for v in toolboxes.node_types_by_toolbox().values())
    assert dialog._toolbox_total.text() == f"{total} of {total} nodes enabled"

    dialog._toolbox_boxes["geo"].setChecked(False)
    assert dialog._toolbox_total.text() == f"{total - 20} of {total} nodes enabled"


def test_unticking_a_family_stages_the_new_list(dialog):
    dialog._toolbox_boxes["geo"].setChecked(False)

    staged = dialog._pending[toolboxes.SETTING]
    assert "geo" not in staged
    assert "statistics" in staged
    assert toolboxes.is_enabled("geo")  # not committed yet


def test_only_essentials_leaves_export_on(dialog):
    dialog._set_toolboxes(list(toolboxes.ESSENTIAL_PRESET))

    staged = dialog._pending[toolboxes.SETTING]
    assert staged == ["export"]
    assert dialog._toolbox_boxes["export"].isChecked()
    assert not dialog._toolbox_boxes["ml"].isChecked()


def test_enable_all_turns_everything_back_on(dialog):
    dialog._set_toolboxes([])
    dialog._set_toolboxes(list(toolboxes.optional_keys()))
    assert all(
        dialog._toolbox_boxes[k].isChecked() for k in toolboxes.optional_keys()
    )


def test_a_family_in_use_cannot_be_switched_off(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    told: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: told.append(a[2])
    )
    widget = PreferencesDialog(
        nodes_in_use=lambda: {"geo_buffer": ["Buffer 1", "Buffer 2"]}
    )
    try:
        widget._toolbox_boxes["geo"].setChecked(False)

        assert widget._toolbox_boxes["geo"].isChecked()  # the refusal, visible
        assert not widget.has_pending_changes()
        assert "Buffer 1" in told[0] and "Geo / maps" in told[0]
    finally:
        widget.close()


def test_a_family_not_in_use_switches_off_normally(qapp):
    widget = PreferencesDialog(nodes_in_use=lambda: {"drop_na": ["Clean 1"]})
    try:
        widget._toolbox_boxes["geo"].setChecked(False)
        assert not widget._toolbox_boxes["geo"].isChecked()
        assert widget.has_pending_changes()
    finally:
        widget.close()


def test_a_preset_also_respects_what_is_in_use(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    widget = PreferencesDialog(nodes_in_use=lambda: {"geo_buffer": ["Buffer 1"]})
    try:
        widget._set_toolboxes(list(toolboxes.ESSENTIAL_PRESET))
        # Geo is kept because the canvas uses it; the rest went off.
        assert widget._toolbox_boxes["geo"].isChecked()
        assert not widget._toolbox_boxes["ml"].isChecked()
    finally:
        widget.close()
