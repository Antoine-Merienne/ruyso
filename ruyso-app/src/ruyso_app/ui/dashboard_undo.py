"""
Undo for the Dashboard canvas, by snapshotting the scene.

The pipeline gets undo free from NodeGraphQt's ``QUndoStack``; the
dashboard is a plain ``QGraphicsScene`` and had none, so a mis-click
that deleted a figure block meant rebuilding it -- and the dashboard is
session state, so there was nothing to reopen.

Rather than a command class per operation -- add, move, resize, restyle,
reorder, lock, delete -- each operation records the state of the scene
before and after, and undo restores it. A dashboard holds tens of items,
not thousands, so a snapshot is cheap; and one mechanism covering every
operation is far less to get wrong than seven that each have to
implement their own inverse.

Snapshots hold the item **objects**, not copies of them. Deleting takes
an item out of the scene but the snapshot keeps it alive, so undoing a
delete puts back the very same block -- a figure with its rendered SVG
still in it, rather than a blank one waiting for the next run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtGui import QUndoCommand


@dataclass
class SceneSnapshot:
    """Which items were on the canvas, where, and in what state."""

    #: Items in the scene, in the order they were found.
    items: list[Any] = field(default_factory=list)
    #: ``id(item) -> restorable state``, from each item's capture_state.
    states: dict[int, dict] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.items)


def capture(scene: Any, items: list[Any]) -> SceneSnapshot:
    """Record ``items``' membership and state on ``scene``."""
    snapshot = SceneSnapshot()
    for item in items:
        snapshot.items.append(item)
        snapshot.states[id(item)] = _capture_item(item)
    return snapshot


def _capture_item(item: Any) -> dict:
    state: dict[str, Any] = {
        "pos": (item.pos().x(), item.pos().y()),
        "z": item.zValue(),
    }
    capture_own = getattr(item, "capture_state", None)
    if callable(capture_own):
        state["own"] = capture_own()
    return state


def restore(scene: Any, snapshot: SceneSnapshot) -> None:
    """
    Put ``scene`` back to what ``snapshot`` recorded.

    Membership first (items removed since are added back, items added
    since are taken out), then each item's own state. Both directions
    matter: this same function serves undo and redo.
    """
    wanted = list(snapshot.items)
    present = [i for i in scene.items() if id(i) in snapshot.states or i in wanted]

    for item in scene.items():
        if item not in wanted and _is_ours(item):
            scene.removeItem(item)
    for item in wanted:
        if item.scene() is not scene:
            scene.addItem(item)

    for item in wanted:
        state = snapshot.states.get(id(item))
        if state is None:
            continue
        item.setPos(*state["pos"])
        item.setZValue(state["z"])
        apply_own = getattr(item, "apply_state", None)
        if callable(apply_own) and "own" in state:
            apply_own(state["own"])
    del present  # only computed for clarity above


def _is_ours(item: Any) -> bool:
    """
    Whether an item is one of the canvas's blocks.

    Anything without ``capture_state`` was put on the scene by something
    else (a rubber band, a transient overlay) and is not ours to remove.
    """
    return callable(getattr(item, "capture_state", None))


class SceneEdit(QUndoCommand):
    """One dashboard operation, as the states either side of it."""

    def __init__(
        self, scene: Any, before: SceneSnapshot, after: SceneSnapshot, text: str
    ) -> None:
        super().__init__(text)
        self._scene = scene
        self._before = before
        self._after = after
        #: Qt pushes a command by *running* it; this one has already
        #: happened, so the first redo must do nothing.
        self._first_redo = True

    def undo(self) -> None:  # noqa: D102 - Qt override
        restore(self._scene, self._before)

    def redo(self) -> None:  # noqa: D102 - Qt override
        if self._first_redo:
            self._first_redo = False
            return
        restore(self._scene, self._after)
