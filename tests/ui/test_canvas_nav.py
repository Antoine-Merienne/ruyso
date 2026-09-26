"""
Tests for ``ui.canvas_nav.CanvasNavigation`` -- the trackpad pan/zoom
remap for the pipeline canvas.
"""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QContextMenuEvent, QKeyEvent, QMouseEvent, QWheelEvent

from ruyso_app.ui.canvas import PipelineCanvas


def _range(viewer):
    r = viewer._scene_range
    return (round(r.left(), 2), round(r.top(), 2), round(r.width(), 2), round(r.height(), 2))


def _wheel(pixel=(0, 0), angle=(0, 0), mods=Qt.NoModifier):
    return QWheelEvent(
        QPointF(200, 150),
        QPointF(200, 150),
        QPoint(*pixel),
        QPoint(*angle),
        Qt.NoButton,
        mods,
        Qt.ScrollUpdate,
        False,
    )


def _mouse(kind, pos, button=Qt.LeftButton, buttons=Qt.NoButton):
    return QMouseEvent(kind, QPointF(*pos), button, buttons, Qt.NoModifier)


def test_two_finger_scroll_pans_and_does_not_zoom(qapp):
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    nav = canvas._navigation
    before = _range(viewer)

    consumed = nav.eventFilter(viewer.viewport(), _wheel(pixel=(-40, -25)))

    after = _range(viewer)
    assert consumed is True  # NodeGraphQt's wheel-zoom never runs
    assert after[:2] != before[:2]  # translated
    assert after[2:] == before[2:]  # ... but not scaled


def test_ctrl_wheel_zooms(qapp):
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    nav = canvas._navigation
    before = _range(viewer)

    consumed = nav.eventFilter(
        viewer.viewport(), _wheel(angle=(0, 120), mods=Qt.ControlModifier)
    )

    assert consumed is True
    assert _range(viewer)[2:] != before[2:]  # scene rect resized -> zoom


def test_space_left_drag_pans(qapp):
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    vp = viewer.viewport()
    nav = canvas._navigation

    nav.eventFilter(viewer, QKeyEvent(QEvent.KeyPress, Qt.Key_Space, Qt.NoModifier))
    assert nav._space_held

    assert nav.eventFilter(vp, _mouse(QEvent.MouseButtonPress, (100, 100))) is True
    assert nav._panning
    before = _range(viewer)
    assert nav.eventFilter(vp, _mouse(QEvent.MouseMove, (170, 140), buttons=Qt.LeftButton)) is True
    assert _range(viewer)[:2] != before[:2]
    assert nav.eventFilter(vp, _mouse(QEvent.MouseButtonRelease, (170, 140))) is True
    assert not nav._panning

    nav.eventFilter(viewer, QKeyEvent(QEvent.KeyRelease, Qt.Key_Space, Qt.NoModifier))
    assert not nav._space_held


def test_plain_left_press_is_left_for_nodegraphqt(qapp):
    # Without Space held, a left press must pass through so NodeGraphQt's
    # rubber-band selection still works.
    canvas = PipelineCanvas()
    nav = canvas._navigation
    consumed = nav.eventFilter(
        canvas.graph.viewer().viewport(), _mouse(QEvent.MouseButtonPress, (100, 100))
    )
    assert consumed is False


def test_plain_mouse_wheel_zooms(qapp):
    # A real mouse wheel reports only angleDelta (no pixelDelta) and no
    # modifier -> it must zoom, not pan.
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    nav = canvas._navigation
    before = _range(viewer)

    consumed = nav.eventFilter(viewer.viewport(), _wheel(angle=(0, 120)))

    assert consumed is True
    assert _range(viewer)[2:] != before[2:]  # scaled -> zoom


def test_right_drag_pans(qapp):
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    vp = viewer.viewport()
    nav = canvas._navigation

    press = nav.eventFilter(
        vp, _mouse(QEvent.MouseButtonPress, (100, 100), button=Qt.RightButton)
    )
    assert press is True and nav._rmb_active

    before = _range(viewer)
    nav.eventFilter(
        vp, _mouse(QEvent.MouseMove, (170, 140), button=Qt.NoButton, buttons=Qt.RightButton)
    )
    after = _range(viewer)
    assert nav._rmb_panning
    assert after[:2] != before[:2]  # translated
    assert after[2:] == before[2:]  # ... not scaled

    release = nav.eventFilter(
        vp, _mouse(QEvent.MouseButtonRelease, (170, 140), button=Qt.RightButton)
    )
    assert release is True and not nav._rmb_active


def test_context_menu_event_is_swallowed(qapp):
    canvas = PipelineCanvas()
    nav = canvas._navigation
    evt = QContextMenuEvent(QContextMenuEvent.Mouse, QPoint(10, 10))
    assert nav.eventFilter(canvas.graph.viewer(), evt) is True


def test_right_click_without_drag_opens_the_context_menu(qapp):
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    vp = viewer.viewport()
    nav = canvas._navigation

    calls = []
    viewer.contextMenuEvent = lambda event: calls.append(event)

    nav.eventFilter(vp, _mouse(QEvent.MouseButtonPress, (100, 100), button=Qt.RightButton))
    # a jitter below the drag threshold does not start a pan
    nav.eventFilter(
        vp, _mouse(QEvent.MouseMove, (101, 100), button=Qt.NoButton, buttons=Qt.RightButton)
    )
    assert not nav._rmb_panning
    nav.eventFilter(vp, _mouse(QEvent.MouseButtonRelease, (101, 100), button=Qt.RightButton))

    qapp.processEvents()  # the menu is opened on the next event-loop tick
    assert len(calls) == 1


def test_right_drag_does_not_open_the_context_menu(qapp):
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    vp = viewer.viewport()
    nav = canvas._navigation

    calls = []
    viewer.contextMenuEvent = lambda event: calls.append(event)

    nav.eventFilter(vp, _mouse(QEvent.MouseButtonPress, (100, 100), button=Qt.RightButton))
    nav.eventFilter(
        vp, _mouse(QEvent.MouseMove, (170, 140), button=Qt.NoButton, buttons=Qt.RightButton)
    )
    nav.eventFilter(vp, _mouse(QEvent.MouseButtonRelease, (170, 140), button=Qt.RightButton))

    qapp.processEvents()
    assert calls == []


def test_plain_right_press_is_consumed_but_left_press_passes_through(qapp):
    canvas = PipelineCanvas()
    nav = canvas._navigation
    viewer = canvas.graph.viewer()
    vp = viewer.viewport()
    viewer.contextMenuEvent = lambda event: None  # never open the real (modal) menu

    assert (
        nav.eventFilter(vp, _mouse(QEvent.MouseButtonPress, (5, 5), button=Qt.RightButton))
        is True
    )
    # clean up the half-open right-button gesture
    nav.eventFilter(vp, _mouse(QEvent.MouseButtonRelease, (5, 5), button=Qt.RightButton))
    assert (
        nav.eventFilter(vp, _mouse(QEvent.MouseButtonPress, (5, 5), button=Qt.LeftButton))
        is False
    )


def test_pinch_gesture_zooms(qapp):
    canvas = PipelineCanvas()
    viewer = canvas.graph.viewer()
    nav = canvas._navigation
    before = _range(viewer)

    class _Pinch:
        def type(self):
            return QEvent.NativeGesture

        def gestureType(self):
            return Qt.ZoomNativeGesture

        def value(self):
            return 0.05

        def position(self):
            return QPointF(200, 150)

    assert nav.eventFilter(viewer.viewport(), _Pinch()) is True
    assert _range(viewer)[2:] != before[2:]


# -- snap to grid --------------------------------------------------------


def test_nodes_snap_to_the_grid_when_the_preference_is_on(qapp):
    """NodeGraphQt draws a grid but has no notion of snapping to it."""
    from ruyso_app.engine import settings
    from ruyso_app.ui.canvas import PipelineCanvas
    from ruyso_app.ui.node_factory import qt_type_for

    try:
        settings.update({"appearance.snap_to_grid": True, "appearance.grid_size": 20})
        canvas = PipelineCanvas()
        node = canvas.graph.create_node(qt_type_for("sort"), pos=[137.0, 214.0])
        assert node.pos() == [140.0, 220.0]

        node.set_pos(103.0, 197.0)
        canvas.snap_node(node)
        assert node.pos() == [100.0, 200.0]
    finally:
        settings.reset()


def test_nodes_are_left_alone_when_snapping_is_off(qapp):
    from ruyso_app.engine import settings
    from ruyso_app.ui.canvas import PipelineCanvas
    from ruyso_app.ui.node_factory import qt_type_for

    try:
        settings.set("appearance.snap_to_grid", False)
        canvas = PipelineCanvas()
        node = canvas.graph.create_node(qt_type_for("sort"), pos=[137.0, 214.0])
        assert node.pos() == [137.0, 214.0]
    finally:
        settings.reset()


def test_the_canvas_grid_mode_follows_the_preference(qapp):
    from NodeGraphQt.constants import ViewerEnum

    from ruyso_app.engine import settings
    from ruyso_app.ui.canvas import PipelineCanvas

    try:
        settings.set("appearance.canvas_grid", "none")
        canvas = PipelineCanvas()
        assert canvas.graph.scene().grid_mode == ViewerEnum.GRID_DISPLAY_NONE.value

        settings.set("appearance.canvas_grid", "lines")
        canvas.apply_preferences()
        assert canvas.graph.scene().grid_mode == ViewerEnum.GRID_DISPLAY_LINES.value
    finally:
        settings.reset()
