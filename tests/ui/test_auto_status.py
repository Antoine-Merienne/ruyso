"""
Tests for ``ui.auto_status.AutoStatusPill`` -- the "auto" chip in the
tab band. Only the state <-> dynamic-property mapping is checked
(colours come from the theme QSS).
"""

import pytest
from PySide6.QtCore import QPoint

from ruyso_app.ui.auto_status import AutoStatusPill


def test_starts_idle(qapp):
    pill = AutoStatusPill()
    assert pill.state() == "idle"
    assert pill._dot.property("state") == "idle"


@pytest.mark.parametrize("state", ["running", "ok", "error", "idle"])
def test_set_state_updates_the_dot_property(qapp, state):
    pill = AutoStatusPill()
    pill.set_state(state)
    assert pill.state() == state
    assert pill._dot.property("state") == state


def test_unknown_state_raises(qapp):
    pill = AutoStatusPill()
    with pytest.raises(ValueError):
        pill.set_state("purple")


def test_left_click_emits_clicked(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    pill = AutoStatusPill()
    pill.resize(70, 22)
    seen: list[int] = []
    pill.clicked.connect(lambda: seen.append(1))

    QTest.mouseClick(pill, Qt.LeftButton)
    assert seen == [1]

    # a press that drifts off the chip before release does not fire
    QTest.mousePress(pill, Qt.LeftButton)
    QTest.mouseRelease(pill, Qt.LeftButton, pos=pill.rect().bottomRight() + QPoint(50, 50))
    assert seen == [1]
