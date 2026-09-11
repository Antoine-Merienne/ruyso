"""
Tests for ``ui.height_grip`` -- the drag bar that caps the height of the
widget above it, used under the Table tab's two variable tables.
"""

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QLabel

from ruyso_app.ui.height_grip import DEFAULT_CAP, MIN_TARGET_HEIGHT, HeightGrip


def _grip(content: int, cap: int = DEFAULT_CAP):
    target = QLabel("x")
    grip = HeightGrip(target, cap=cap)
    grip.set_content_height(content)
    return grip, target


def _mouse(kind, y: float, button=Qt.LeftButton, buttons=Qt.LeftButton):
    return QMouseEvent(
        kind, QPointF(4.0, 4.0), QPointF(4.0, y), button, buttons, Qt.NoModifier
    )


# -- what the cap means --------------------------------------------------


def test_a_table_that_fits_is_left_at_its_content_height(qapp):
    _, target = _grip(content=120)

    assert target.height() == 120


def test_a_taller_table_is_capped(qapp):
    grip, target = _grip(content=900)

    assert target.height() == DEFAULT_CAP
    assert grip.is_capping()


def test_the_grip_appears_only_when_capping_does_something(qapp):
    fits, _ = _grip(content=120)
    overflows, _ = _grip(content=900)

    assert not fits.isVisible()
    assert overflows.isVisibleTo(overflows.parentWidget() or overflows)


def test_dragging_sets_the_cap(qapp):
    grip, target = _grip(content=900)

    grip.resize_target(320)
    assert target.height() == 320


def test_a_target_cannot_be_capped_away_to_nothing(qapp):
    grip, target = _grip(content=900)

    grip.resize_target(2)
    assert target.height() == MIN_TARGET_HEIGHT


def test_a_cap_past_the_content_just_follows_the_content(qapp):
    grip, target = _grip(content=140)

    grip.resize_target(600)
    assert target.height() == 140
    assert not grip.is_capping()


def test_double_click_restores_the_default_cap(qapp):
    grip, target = _grip(content=900)
    grip.resize_target(420)

    grip.mouseDoubleClickEvent(_mouse(QEvent.Type.MouseButtonDblClick, 0.0))
    assert target.height() == DEFAULT_CAP


# -- only a drag resizes -------------------------------------------------


def test_moving_over_the_grip_without_pressing_changes_nothing(qapp):
    """A hover move carries no drag to measure from, so acting on it
    sent the table to an arbitrary height as the pointer crossed."""
    grip, target = _grip(content=900)
    before = target.height()

    grip.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 780.0, Qt.NoButton, Qt.NoButton))
    assert target.height() == before


def test_press_then_drag_resizes_by_the_distance_travelled(qapp):
    grip, target = _grip(content=900)

    grip.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 500.0))
    grip.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 560.0))
    assert target.height() == DEFAULT_CAP + 60

    grip.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 560.0))


def test_a_move_after_the_release_is_ignored(qapp):
    grip, target = _grip(content=900)
    grip.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 500.0))
    grip.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 540.0))
    grip.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 540.0))
    after_drag = target.height()

    grip.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 900.0, Qt.NoButton, Qt.NoButton))
    assert target.height() == after_drag


def test_the_right_button_does_not_start_a_drag(qapp):
    grip, target = _grip(content=900)
    before = target.height()

    grip.mousePressEvent(
        _mouse(QEvent.Type.MouseButtonPress, 500.0, Qt.RightButton, Qt.RightButton)
    )
    grip.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 700.0, Qt.NoButton, Qt.NoButton))
    assert target.height() == before


def test_the_grip_paints_itself(qapp):
    """A bare QWidget ignores its stylesheet background unless told to,
    which left the grip invisible while it still resized the table."""
    grip, _ = _grip(content=900)

    assert grip.testAttribute(Qt.WA_StyledBackground)
    assert grip.objectName() == "ruysoHeightGrip"
