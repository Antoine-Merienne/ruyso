"""
Tests for ``ui.canvas_nav.CanvasNavigation`` -- the trackpad pan/zoom
remap for the pipeline canvas.
"""

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent

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
