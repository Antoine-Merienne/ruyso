"""
Arranging blocks on the Dashboard canvas: order, alignment, spacing.

Pure functions over a list of ``QGraphicsItem``. They read and write
positions and z-values and nothing else, so they can be tested against
plain items with no page, no scene wiring and no undo stack -- the page
wraps each call in one undo step.

Alignment works on the items' **scene bounding rectangles**, not on
their positions: a figure block and a text box with the same ``y`` do
not look aligned, because their contents start at different offsets
inside them. What someone means by "align the tops" is that the tops
they can see line up.
"""

from __future__ import annotations

from typing import Any, Iterable

#: Nudge distances, in scene units, for a bare and a shifted arrow key.
NUDGE = 1.0
NUDGE_LARGE = 10.0


def _rect(item: Any):
    """
    The block's *visible* extent, in scene coordinates.

    Not ``sceneBoundingRect``: that includes whatever padding an item
    reserves for its selection handles -- 15px for a shape, 3px for a
    figure -- so aligning on it would leave a shape and a figure twelve
    pixels out of line while both claimed to be aligned. Items that know
    the difference expose ``visual_rect``; the rest have none to speak of.
    """
    visual = getattr(item, "visual_rect", None)
    if callable(visual):
        return item.mapRectToScene(visual())
    return item.sceneBoundingRect()


def _movable(items: Iterable[Any]) -> list[Any]:
    """Only the items an arrangement may touch: locked ones are not."""
    return [item for item in items if not _is_locked(item)]


def _is_locked(item: Any) -> bool:
    checker = getattr(item, "is_locked", None)
    return bool(checker()) if callable(checker) else False


# -- z-order --------------------------------------------------------------


def bring_to_front(items: Iterable[Any], all_items: Iterable[Any]) -> None:
    """Put ``items`` above everything else, keeping their order."""
    top = max((i.zValue() for i in all_items), default=0.0)
    for offset, item in enumerate(sorted(items, key=lambda i: i.zValue()), start=1):
        item.setZValue(top + offset)


def send_to_back(items: Iterable[Any], all_items: Iterable[Any]) -> None:
    bottom = min((i.zValue() for i in all_items), default=0.0)
    ordered = sorted(items, key=lambda i: i.zValue(), reverse=True)
    for offset, item in enumerate(ordered, start=1):
        item.setZValue(bottom - offset)


def bring_forward(items: Iterable[Any], _all_items: Iterable[Any] = ()) -> None:
    for item in items:
        item.setZValue(item.zValue() + 1)


def send_backward(items: Iterable[Any], _all_items: Iterable[Any] = ()) -> None:
    for item in items:
        item.setZValue(item.zValue() - 1)


# -- alignment ------------------------------------------------------------

#: edge -> (which scene-rect value to line up, which axis to move on).
_EDGES = {
    "left": (lambda r: r.left(), "x"),
    "hcenter": (lambda r: r.center().x(), "x"),
    "right": (lambda r: r.right(), "x"),
    "top": (lambda r: r.top(), "y"),
    "vcenter": (lambda r: r.center().y(), "y"),
    "bottom": (lambda r: r.bottom(), "y"),
}


def align(items: Iterable[Any], edge: str) -> None:
    """
    Line the selection up on one edge of its own bounding box.

    The target is taken from the *selection*, not from the canvas: the
    leftmost block stays where it is and the others come to it, which is
    what people expect and means aligning twice changes nothing.
    """
    movable = _movable(items)
    if len(movable) < 2 or edge not in _EDGES:
        return
    measure, axis = _EDGES[edge]
    values = [measure(_rect(item)) for item in movable]
    target = {
        "left": min, "top": min,
        "right": max, "bottom": max,
    }.get(edge, lambda vs: sum(vs) / len(vs))(values)

    for item, value in zip(movable, values):
        delta = target - value
        if axis == "x":
            item.setPos(item.pos().x() + delta, item.pos().y())
        else:
            item.setPos(item.pos().x(), item.pos().y() + delta)


# -- distribution ---------------------------------------------------------


def distribute(items: Iterable[Any], axis: str = "h") -> None:
    """
    Space the selection evenly between its outermost two blocks.

    Needs three: with two there is nothing to distribute, and the ends
    stay put so the overall extent does not drift.
    """
    movable = _movable(items)
    if len(movable) < 3 or axis not in ("h", "v"):
        return

    horizontal = axis == "h"
    key = (lambda i: _rect(i).center().x()) if horizontal else (lambda i: _rect(i).center().y())
    ordered = sorted(movable, key=key)
    first, last = key(ordered[0]), key(ordered[-1])
    step = (last - first) / (len(ordered) - 1)

    for index, item in enumerate(ordered[1:-1], start=1):
        delta = (first + step * index) - key(item)
        if horizontal:
            item.setPos(item.pos().x() + delta, item.pos().y())
        else:
            item.setPos(item.pos().x(), item.pos().y() + delta)


# -- nudging --------------------------------------------------------------


def nudge(items: Iterable[Any], dx: float, dy: float) -> None:
    for item in _movable(items):
        item.setPos(item.pos().x() + dx, item.pos().y() + dy)


# -- locking --------------------------------------------------------------


def set_locked(items: Iterable[Any], locked: bool) -> None:
    """Lock or unlock whatever supports it, ignoring what does not."""
    for item in items:
        setter = getattr(item, "set_locked", None)
        if callable(setter):
            setter(locked)


def locked_items(items: Iterable[Any]) -> list[Any]:
    return [item for item in items if _is_locked(item)]
