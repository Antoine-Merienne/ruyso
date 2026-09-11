"""
Tests for the custom Pipeline / Table / Dashboard tab band.

Covers the non-visual behavior: which tab is current, that selecting a
tab emits exactly one ``tab_changed`` with the right key, that
re-selecting the current tab is a silent no-op, and that an unknown
key is rejected.
"""

import pytest

from ruyso_app.ui.tab_bar import TabBar

TABS = [("pipeline", "Pipeline"), ("table", "Table"), ("dashboard", "Dashboard")]


def test_first_tab_is_current_by_default(qapp):
    bar = TabBar(TABS)
    assert bar.current_key() == "pipeline"


def test_selecting_a_tab_emits_tab_changed_once(qapp):
    bar = TabBar(TABS)
    seen = []
    bar.tab_changed.connect(seen.append)

    bar.set_current_key("table")

    assert seen == ["table"]
    assert bar.current_key() == "table"


def test_reselecting_current_tab_is_a_noop(qapp):
    bar = TabBar(TABS)
    seen = []
    bar.tab_changed.connect(seen.append)

    bar.set_current_key("pipeline")

    assert seen == []


def test_unknown_tab_key_raises(qapp):
    bar = TabBar(TABS)
    with pytest.raises(KeyError):
        bar.set_current_key("nope")


def test_tabs_are_mutually_exclusive(qapp):
    bar = TabBar(TABS)
    bar.set_current_key("dashboard")

    checked = [k for k, b in bar._buttons.items() if b.isChecked()]
    assert checked == ["dashboard"]


def test_a_tab_is_wide_enough_for_its_label_in_bold(qapp):
    """The active tab is bold, but Qt sizes a button from the regular
    font it was built with -- so "Dashboard" was clipped the moment it
    became the active one."""
    from PySide6.QtGui import QFontMetrics

    bar = TabBar(TABS)
    button = bar._buttons["dashboard"]
    bold = button.font()
    bold.setBold(True)

    assert button.minimumWidth() > QFontMetrics(bold).horizontalAdvance("Dashboard")
    # ... and it is the bold width that is reserved, not the regular one.
    regular = QFontMetrics(button.font()).horizontalAdvance("Dashboard")
    assert button.minimumWidth() > regular
