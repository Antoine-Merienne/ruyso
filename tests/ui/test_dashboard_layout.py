"""
Tests for ``ui.dashboard_layout`` -- arranging blocks on the canvas.

Pure functions over graphics items, so these use plain shapes with no
page, no scene wiring and no undo stack. The property that matters
throughout: alignment works on what you can *see* -- each item's
``visual_rect``, not its ``sceneBoundingRect``, which includes the
padding reserved for selection handles -- and a locked block is never
moved by an arrangement.
"""

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsScene

from ruyso_app.ui import dashboard_layout as layout
from ruyso_app.ui.dashboard_shapes import ShapeItem


@pytest.fixture
def scene(qapp):
    return QGraphicsScene()


def _shape(scene, x, y, w=100.0, h=60.0):
    item = ShapeItem("rectangle")
    item.set_geometry(rect=QRectF(0, 0, w, h))
    item.setPos(x, y)
    scene.addItem(item)
    return item


def _visual(item):
    """What the block draws, which is what alignment lines up -- not
    sceneBoundingRect, which includes the selection-handle padding."""
    return item.mapRectToScene(item.visual_rect())


def _lefts(items):
    return [round(_visual(i).left(), 3) for i in items]


def _tops(items):
    return [round(_visual(i).top(), 3) for i in items]


# -- z-order -------------------------------------------------------------


def test_bring_to_front_puts_items_above_everything(scene):
    a, b, c = _shape(scene, 0, 0), _shape(scene, 10, 0), _shape(scene, 20, 0)
    b.setZValue(5)

    layout.bring_to_front([a], [a, b, c])

    assert a.zValue() > b.zValue()


def test_send_to_back_puts_items_below_everything(scene):
    a, b = _shape(scene, 0, 0), _shape(scene, 10, 0)
    b.setZValue(-3)

    layout.send_to_back([a], [a, b])

    assert a.zValue() < b.zValue()


def test_bringing_several_forward_keeps_their_relative_order(scene):
    a, b = _shape(scene, 0, 0), _shape(scene, 10, 0)
    a.setZValue(1)
    b.setZValue(2)

    layout.bring_to_front([a, b], [a, b])

    assert a.zValue() < b.zValue()


def test_forward_and_backward_step_by_one(scene):
    a = _shape(scene, 0, 0)
    layout.bring_forward([a])
    assert a.zValue() == 1
    layout.send_backward([a])
    layout.send_backward([a])
    assert a.zValue() == -1


# -- alignment -----------------------------------------------------------


def test_aligning_left_moves_the_others_to_the_leftmost(scene):
    """The leftmost block stays put, so aligning twice changes nothing."""
    a, b, c = _shape(scene, 10, 0), _shape(scene, 90, 40), _shape(scene, 50, 80)

    layout.align([a, b, c], "left")

    assert _lefts([a, b, c]) == [10.0, 10.0, 10.0]
    layout.align([a, b, c], "left")
    assert _lefts([a, b, c]) == [10.0, 10.0, 10.0]  # idempotent


def test_aligning_right_uses_the_rightmost_edge(scene):
    a, b = _shape(scene, 0, 0, w=100), _shape(scene, 50, 40, w=40)

    layout.align([a, b], "right")

    rights = [round(_visual(i).right(), 3) for i in (a, b)]
    assert rights[0] == rights[1] == 100.0


def test_aligning_top_lines_up_what_you_can_see(scene):
    a, b = _shape(scene, 0, 10), _shape(scene, 30, 70)

    layout.align([a, b], "top")

    assert _tops([a, b]) == [10.0, 10.0]


def test_aligning_centres_on_the_selection_s_own_middle(scene):
    a, b = _shape(scene, 0, 0, w=100), _shape(scene, 100, 0, w=100)

    layout.align([a, b], "hcenter")

    centres = [round(_visual(i).center().x(), 3) for i in (a, b)]
    assert centres[0] == centres[1]


def test_aligning_one_block_does_nothing(scene):
    a = _shape(scene, 33, 44)
    layout.align([a], "left")
    assert (a.pos().x(), a.pos().y()) == (33, 44)


def test_an_unknown_edge_is_ignored(scene):
    a, b = _shape(scene, 0, 0), _shape(scene, 50, 0)
    layout.align([a, b], "sideways")
    assert _lefts([a, b]) == [0.0, 50.0]


# -- distribution --------------------------------------------------------


def test_distributing_spaces_the_middle_evenly(scene):
    a = _shape(scene, 0, 0, w=20)
    b = _shape(scene, 30, 0, w=20)
    c = _shape(scene, 200, 0, w=20)

    layout.distribute([a, b, c], "h")

    centres = sorted(round(_visual(i).center().x(), 3) for i in (a, b, c))
    assert centres[1] - centres[0] == pytest.approx(centres[2] - centres[1])


def test_distributing_leaves_the_outermost_blocks_alone(scene):
    a, b, c = _shape(scene, 0, 0), _shape(scene, 30, 0), _shape(scene, 400, 0)
    ends = (a.pos().x(), c.pos().x())

    layout.distribute([a, b, c], "h")

    assert (a.pos().x(), c.pos().x()) == ends


def test_distributing_needs_three(scene):
    a, b = _shape(scene, 0, 0), _shape(scene, 100, 0)
    layout.distribute([a, b], "h")
    assert (a.pos().x(), b.pos().x()) == (0, 100)


# -- nudging -------------------------------------------------------------


def test_nudging_moves_by_the_given_amount(scene):
    a = _shape(scene, 10, 10)
    layout.nudge([a], 1.0, -1.0)
    assert (a.pos().x(), a.pos().y()) == (11.0, 9.0)


# -- locking -------------------------------------------------------------


def test_a_locked_block_is_never_moved_by_an_arrangement(scene):
    a, b = _shape(scene, 10, 0), _shape(scene, 90, 0)
    b.set_locked(True)

    layout.align([a, b], "left")
    layout.nudge([a, b], 5.0, 5.0)
    layout.distribute([a, b, _shape(scene, 200, 0)], "h")

    assert b.pos().x() == 90  # untouched throughout


def test_locking_reports_which_blocks_are_locked(scene):
    a, b = _shape(scene, 0, 0), _shape(scene, 10, 0)
    layout.set_locked([a], True)

    assert layout.locked_items([a, b]) == [a]

    layout.set_locked([a], False)
    assert layout.locked_items([a, b]) == []


def test_locking_ignores_items_that_do_not_support_it(scene):
    class Plain:
        pass

    layout.set_locked([Plain()], True)  # must not raise
