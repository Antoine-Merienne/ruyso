"""
Colormap Manager -- choose which colormaps appear in the Options-panel
dropdowns, and in what order.

Two lists, one per kind (continuous / qualitative). Each row is a
checkable, drag-reorderable entry showing the map's gradient and name.
Checked = visible in the dropdowns. "Reset to defaults" clears the
customisation. On OK the selection is persisted via
``engine.colormaps.set_lists`` and :attr:`ColormapManager.changed` is
emitted.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ruyso_app.engine import colormaps as cmaps
from ruyso_app.ui import swatches


def _make_list() -> QListWidget:
    widget = QListWidget()
    widget.setDragDropMode(QAbstractItemView.InternalMove)
    widget.setSelectionMode(QAbstractItemView.SingleSelection)
    widget.setMinimumHeight(220)
    widget.setIconSize(swatches.icon_size("colormap"))
    return widget


class ColormapManager(QDialog):
    """Curate the colormap dropdown lists."""

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Colormap Manager")
        self.setMinimumWidth(420)

        self._lists: dict[str, QListWidget] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Tick to show in the dropdowns; drag to reorder.")
        )
        for kind in cmaps.KINDS:
            layout.addWidget(QLabel(kind.capitalize()))
            widget = _make_list()
            self._lists[kind] = widget
            layout.addWidget(widget)

        buttons = QHBoxLayout()
        reset = QPushButton("Reset to defaults")
        reset.clicked.connect(self._reset)
        ok = QPushButton("OK")
        ok.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(reset)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        self._populate()

    # -- population ------------------------------------------------

    def _populate(self) -> None:
        visible = cmaps.resolved_lists()
        for kind, widget in self._lists.items():
            widget.clear()
            shown = visible.get(kind, [])
            everything = cmaps.all_manageable(kind)
            ordered = shown + [n for n in everything if n not in shown]
            for name in ordered:
                item = QListWidgetItem(name)
                item.setIcon(swatches.icon_for("colormap", name))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked if name in shown else Qt.Unchecked
                )
                widget.addItem(item)

    def _reset(self) -> None:
        cmaps.reset_lists()
        swatches.clear_cache()
        self._populate()

    # -- read back -----------------------------------------------

    def selection(self) -> dict[str, list[str]]:
        """The current ticked-in-order names for each kind."""
        out: dict[str, list[str]] = {}
        for kind, widget in self._lists.items():
            names = [
                widget.item(i).text()
                for i in range(widget.count())
                if widget.item(i).checkState() == Qt.Checked
            ]
            if not names:  # safety net -- never an empty dropdown
                names = [cmaps.all_manageable(kind)[0]]
            out[kind] = names
        return out

    def _accept(self) -> None:
        cmaps.set_lists(self.selection())
        swatches.clear_cache()
        self.changed.emit()
        self.accept()
