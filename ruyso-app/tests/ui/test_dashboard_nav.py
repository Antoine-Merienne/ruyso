"""
Tests for ``ui.dashboard_canvas.DashboardNavigation`` -- the Dashboard
canvas's trackpad / mouse pan-zoom remap (mirrors the Pipeline tab's
``ui.canvas_nav``): no scroll bars, wheel / pinch zoom, two-finger /
right-drag pan, right-click -> context menu.
"""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QMouseEvent, QWheelEvent

from ruyso_app.ui.dashboard_canvas import DashboardView


def _wheel(pixel=(0, 0), angle=(0, 0), mods=Qt.NoModifier):
    return QWheelEvent(
        QPointF(200, 150), QPointF(200, 150),
        QPoint(*pixel), QPoint(*angle),
        Qt.NoButton, mods, Qt.ScrollUpdate, False,
    )


def _mouse(kind, pos, button=Qt.LeftButton, buttons=Qt.NoButton):
    return QMouseEvent(kind, QPointF(*pos), button, buttons, Qt.NoModifier)


def _pan_offset(view):
    return (view.horizontalScrollBar().value(), view.verticalScrollBar().value())


def test_no_scrollbars(qapp):
    view = DashboardView()
    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_plain_wheel_zooms(qapp):
    view = DashboardView()
    view.resize(400, 300)
    before = view.transform().m11()
    assert view._nav.eventFilter(view.viewport(), _wheel(angle=(0, 120))) is True
    assert view.transform().m11() != before


def test_two_finger_scroll_pans_not_zooms(qapp):
    view = DashboardView()
    view.resize(400, 300)
    zoom_before = view.transform().m11()
    pan_before = _pan_offset(view)
    assert view._nav.eventFilter(view.viewport(), _wheel(pixel=(-40, -25))) is True
    assert view.transform().m11() == zoom_before  # not scaled
    assert _pan_offset(view) != pan_before  # panned


def test_right_drag_pans_then_release_opens_no_menu(qapp):
    view = DashboardView()
    view.resize(400, 300)
    nav = view._nav
    menus: list = []
    view.context_menu_requested.connect(menus.append)

    nav.eventFilter(view.viewport(), _mouse(QEvent.MouseButtonPress, (100, 100), Qt.RightButton))
    assert nav._rmb_active
    pan_before = _pan_offset(view)
    nav.eventFilter(
        view.viewport(),
        _mouse(QEvent.MouseMove, (170, 150), Qt.NoButton, Qt.RightButton),
    )
    assert nav._rmb_panning and _pan_offset(view) != pan_before
    nav.eventFilter(view.viewport(), _mouse(QEvent.MouseButtonRelease, (170, 150), Qt.RightButton))
    assert menus == []


def test_right_click_without_travel_emits_context_menu(qapp):
    view = DashboardView()
    nav = view._nav
    menus: list = []
    view.context_menu_requested.connect(menus.append)

    nav.eventFilter(view.viewport(), _mouse(QEvent.MouseButtonPress, (100, 100), Qt.RightButton))
    nav.eventFilter(
        view.viewport(),
        _mouse(QEvent.MouseMove, (101, 100), Qt.NoButton, Qt.RightButton),
    )
    nav.eventFilter(view.viewport(), _mouse(QEvent.MouseButtonRelease, (101, 100), Qt.RightButton))
    assert len(menus) == 1


def test_context_menu_event_is_swallowed(qapp):
    view = DashboardView()
    evt = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10))
    assert view._nav.eventFilter(view.viewport(), evt) is True


def test_plain_left_press_passes_through_for_rubber_band(qapp):
    view = DashboardView()
    consumed = view._nav.eventFilter(
        view.viewport(), _mouse(QEvent.MouseButtonPress, (30, 30), Qt.LeftButton)
    )
    assert consumed is False
    assert view.dragMode() == DashboardView.RubberBandDrag
