"""
Colormap Designer -- a dialog for building custom colormaps.

* **Continuous**: a gradient bar with draggable colour stops (click an
  empty spot to add one, drag to move, double-click to recolour, Delete
  to remove -- minimum two).
* **Qualitative**: an ordered list of colour swatches (add / recolour /
  remove / reorder).

Either kind can be seeded from an existing colormap and reversed. Save
writes the definition to ``engine.colormaps`` (which re-registers it
with matplotlib) and emits :attr:`ColormapDesigner.changed`.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ruyso_app.engine import colormaps as cmaps
from ruyso_app.ui import swatches

_NEW = "(new colormap)"


# -- continuous: draggable-stop gradient bar --------------------------


class GradientBar(QWidget):
    """A gradient with draggable colour stops. ``stops`` is a list of
    ``[position 0..1, "#rrggbb"]`` pairs."""

    changed = Signal()

    _BAR_H = 30
    _HANDLE_H = 18

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(self._BAR_H + self._HANDLE_H + 6)
        self.setFocusPolicy(Qt.StrongFocus)
        self._stops: list[list] = [[0.0, "#3b4cc0"], [1.0, "#b40426"]]
        self._selected = 0
        self._dragging = False

    # -- data --------------------------------------------------------

    def stops(self) -> list[list]:
        return [[float(p), str(c)] for p, c in self._stops]

    def set_stops(self, stops: list[list]) -> None:
        clean = sorted(
            ([max(0.0, min(1.0, float(p))), str(c)] for p, c in stops),
            key=lambda s: s[0],
        )
        self._stops = clean or [[0.0, "#000000"], [1.0, "#ffffff"]]
        self._selected = min(self._selected, len(self._stops) - 1)
        self.update()
        self.changed.emit()

    def reverse(self) -> None:
        self.set_stops([[1.0 - p, c] for p, c in self._stops])

    def seed_from(self, name: str, n: int = 7) -> None:
        try:
            import matplotlib
            import numpy as np

            cmap = matplotlib.colormaps[name]
            xs = np.linspace(0.0, 1.0, n)
            self.set_stops(
                [[float(x), QColor.fromRgbF(*cmap(float(x))[:3]).name()] for x in xs]
            )
        except Exception:  # noqa: BLE001
            pass

    # -- geometry helpers ------------------------------------------

    def _bar_rect(self) -> QRectF:
        return QRectF(8, 2, self.width() - 16, self._BAR_H)

    def _x_for(self, pos: float) -> float:
        r = self._bar_rect()
        return r.left() + pos * r.width()

    def _pos_for(self, x: float) -> float:
        r = self._bar_rect()
        return max(0.0, min(1.0, (x - r.left()) / max(r.width(), 1.0)))

    def _colour_at(self, pos: float) -> QColor:
        stops = self._stops
        if pos <= stops[0][0]:
            return QColor(stops[0][1])
        if pos >= stops[-1][0]:
            return QColor(stops[-1][1])
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= pos <= p1:
                t = (pos - p0) / (p1 - p0 or 1.0)
                a, b = QColor(c0), QColor(c1)
                return QColor(
                    round(a.red() + t * (b.red() - a.red())),
                    round(a.green() + t * (b.green() - a.green())),
                    round(a.blue() + t * (b.blue() - a.blue())),
                )
        return QColor(stops[-1][1])

    def _handle_at(self, x: float, y: float) -> int | None:
        if y < self._bar_rect().bottom():
            return None
        for i, (pos, _c) in enumerate(self._stops):
            if abs(self._x_for(pos) - x) <= 7:
                return i
        return None

    # -- painting ------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self._bar_rect()

        grad = QLinearGradient(rect.topLeft(), rect.topRight())
        for pos, colour in self._stops:
            grad.setColorAt(max(0.0, min(1.0, pos)), QColor(colour))
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.setBrush(grad)
        painter.drawRoundedRect(rect, 4, 4)

        for i, (pos, colour) in enumerate(self._stops):
            cx = self._x_for(pos)
            top = rect.bottom() + 3
            tri = [
                QPointF(cx, top),
                QPointF(cx - 6, top + 7),
                QPointF(cx + 6, top + 7),
            ]
            painter.setBrush(QColor(colour))
            painter.setPen(
                QPen(QColor("#1e88e5") if i == self._selected else QColor(0, 0, 0, 120),
                     2 if i == self._selected else 1)
            )
            painter.drawPolygon(tri)
            painter.drawRect(QRectF(cx - 6, top + 7, 12, self._HANDLE_H - 9))

    # -- interaction -------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        hit = self._handle_at(x, y)
        if hit is not None:
            self._selected = hit
            self._dragging = True
        elif self._bar_rect().adjusted(-2, -2, 2, 2).contains(event.position()):
            pos = self._pos_for(x)
            self._stops.append([pos, self._colour_at(pos).name()])
            self._stops.sort(key=lambda s: s[0])
            self._selected = next(i for i, s in enumerate(self._stops) if s[0] == pos)
            self._dragging = True
            self.changed.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._dragging:
            return
        self._stops[self._selected][0] = self._pos_for(event.position().x())
        sel_id = id(self._stops[self._selected])
        self._stops.sort(key=lambda s: s[0])
        self._selected = next(i for i, s in enumerate(self._stops) if id(s) == sel_id)
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._dragging = False

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        hit = self._handle_at(event.position().x(), event.position().y())
        if hit is None:
            return
        chosen = QColorDialog.getColor(QColor(self._stops[hit][1]), self, "Stop colour")
        if chosen.isValid():
            self._stops[hit][1] = chosen.name()
            self.update()
            self.changed.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and len(self._stops) > 2:
            del self._stops[self._selected]
            self._selected = max(0, self._selected - 1)
            self.update()
            self.changed.emit()
        else:
            super().keyPressEvent(event)


# -- qualitative: ordered swatch list -------------------------------


class SwatchList(QWidget):
    """An ordered, editable list of colour swatches."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colours: list[str] = ["#4c72b0", "#dd8452", "#55a868", "#c44e52"]

        self._list = QListWidget()
        self._list.setMaximumHeight(160)
        self._list.itemDoubleClicked.connect(lambda _i: self._recolour())

        row = QHBoxLayout()
        for label, slot in (
            ("Add", self._add), ("Recolour", self._recolour), ("Remove", self._remove),
            ("Up", lambda: self._move(-1)), ("Down", lambda: self._move(1)),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self._list)
        box.addLayout(row)
        self._rebuild()

    def colours(self) -> list[str]:
        return list(self._colours)

    def set_colours(self, colours: list[str]) -> None:
        self._colours = [str(c) for c in colours] or ["#000000"]
        self._rebuild()
        self.changed.emit()

    def reverse(self) -> None:
        self.set_colours(list(reversed(self._colours)))

    def seed_from(self, name: str, n: int = 8) -> None:
        try:
            import matplotlib
            import numpy as np

            cmap = matplotlib.colormaps[name]
            existing = getattr(cmap, "colors", None)
            if existing is not None:
                cols = [QColor.fromRgbF(*c[:3]).name() for c in existing][:12]
            else:
                cols = [
                    QColor.fromRgbF(*cmap(float(x))[:3]).name()
                    for x in np.linspace(0.0, 1.0, n)
                ]
            self.set_colours(cols)
        except Exception:  # noqa: BLE001
            pass

    # -- internals -----------------------------------------------

    def _rebuild(self) -> None:
        self._list.clear()
        for colour in self._colours:
            item = QListWidgetItem(colour)
            item.setIcon(swatches.icon_for("color", colour))
            self._list.addItem(item)

    def _row(self) -> int:
        return self._list.currentRow()

    def _add(self) -> None:
        chosen = QColorDialog.getColor(QColor("#888888"), self, "New colour")
        if chosen.isValid():
            self._colours.append(chosen.name())
            self._rebuild()
            self._list.setCurrentRow(len(self._colours) - 1)
            self.changed.emit()

    def _recolour(self) -> None:
        i = self._row()
        if i < 0:
            return
        chosen = QColorDialog.getColor(QColor(self._colours[i]), self, "Colour")
        if chosen.isValid():
            self._colours[i] = chosen.name()
            self._rebuild()
            self._list.setCurrentRow(i)
            self.changed.emit()

    def _remove(self) -> None:
        i = self._row()
        if i >= 0 and len(self._colours) > 1:
            del self._colours[i]
            self._rebuild()
            self._list.setCurrentRow(min(i, len(self._colours) - 1))
            self.changed.emit()

    def _move(self, delta: int) -> None:
        i = self._row()
        j = i + delta
        if 0 <= i < len(self._colours) and 0 <= j < len(self._colours):
            self._colours[i], self._colours[j] = self._colours[j], self._colours[i]
            self._rebuild()
            self._list.setCurrentRow(j)
            self.changed.emit()


# -- preview ------------------------------------------------------


class _PreviewStrip(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(22)
        self._definition: dict | None = None

    def show_definition(self, definition: dict) -> None:
        self._definition = definition
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = QRectF(0, 0, self.width(), self.height())
        d = self._definition or {}
        if d.get("kind") == cmaps.QUALITATIVE:
            colours = d.get("colors") or ["#000000"]
            w = rect.width() / len(colours)
            for i, colour in enumerate(colours):
                painter.fillRect(QRectF(i * w, 0, w + 1, rect.height()), QColor(colour))
        else:
            grad = QLinearGradient(rect.topLeft(), rect.topRight())
            for pos, colour in d.get("stops", [[0.0, "#000"], [1.0, "#fff"]]):
                grad.setColorAt(max(0.0, min(1.0, float(pos))), QColor(colour))
            painter.fillRect(rect, grad)
        painter.setPen(QPen(QColor(0, 0, 0, 90), 1))
        painter.drawRect(rect.adjusted(0, 0, -1, -1))


# -- the dialog --------------------------------------------------


class ColormapDesigner(QDialog):
    """Create / edit custom colormaps."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Colormap Designer")
        self.setMinimumWidth(460)

        self._existing = QComboBox()
        self._existing.currentTextChanged.connect(self._load_existing)

        self._name = QLineEdit()
        self._name.setPlaceholderText("colormap name")

        self._kind_cont = QRadioButton("Continuous")
        self._kind_qual = QRadioButton("Qualitative")
        self._kind_cont.setChecked(True)
        self._kind_cont.toggled.connect(self._on_kind_changed)

        self._seed = QComboBox()
        seed_apply = QPushButton("Seed")
        seed_apply.clicked.connect(self._apply_seed)
        reverse_btn = QPushButton("Reverse")
        reverse_btn.clicked.connect(self._reverse)

        self._gradient = GradientBar()
        self._gradient.setMaximumHeight(72)
        self._swatches = SwatchList()
        self._gradient.changed.connect(self._refresh_preview)
        self._swatches.changed.connect(self._refresh_preview)

        self._preview = _PreviewStrip()
        self._status = QLabel("")
        self._status.setStyleSheet("color: gray; font-size: 11px;")

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.clicked.connect(self._delete)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        form = QVBoxLayout(self)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Edit:"))
        row1.addWidget(self._existing, 1)
        form.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Name:"))
        row2.addWidget(self._name, 1)
        row2.addWidget(self._kind_cont)
        row2.addWidget(self._kind_qual)
        form.addLayout(row2)
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Seed from:"))
        row3.addWidget(self._seed, 1)
        row3.addWidget(seed_apply)
        row3.addWidget(reverse_btn)
        form.addLayout(row3)
        form.addWidget(self._gradient)
        form.addWidget(self._swatches)
        form.addWidget(QLabel("Preview:"))
        form.addWidget(self._preview)
        form.addWidget(self._status)
        buttons = QHBoxLayout()
        buttons.addWidget(save_btn)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        form.addLayout(buttons)

        self._reload_existing()
        self._on_kind_changed()
        self._refresh_preview()

    # -- state --------------------------------------------------

    def _current_kind(self) -> str:
        return cmaps.CONTINUOUS if self._kind_cont.isChecked() else cmaps.QUALITATIVE

    def _definition(self) -> dict:
        if self._current_kind() == cmaps.QUALITATIVE:
            return {"kind": cmaps.QUALITATIVE, "colors": self._swatches.colours()}
        return {"kind": cmaps.CONTINUOUS, "stops": self._gradient.stops()}

    def _reload_existing(self) -> None:
        self._existing.blockSignals(True)
        self._existing.clear()
        self._existing.addItem(_NEW)
        self._existing.addItems(sorted(cmaps.custom_definitions()))
        self._existing.blockSignals(False)
        self._delete_btn.setEnabled(False)

    def _on_kind_changed(self, *_a) -> None:
        qual = self._current_kind() == cmaps.QUALITATIVE
        self._gradient.setVisible(not qual)
        self._swatches.setVisible(qual)
        self._seed.blockSignals(True)
        self._seed.clear()
        self._seed.addItems(cmaps.BUILTIN[self._current_kind()])
        self._seed.blockSignals(False)
        self._refresh_preview()

    def _load_existing(self, name: str) -> None:
        if not name or name == _NEW:
            self._delete_btn.setEnabled(False)
            return
        definition = cmaps.custom_definitions().get(name)
        if not definition:
            return
        self._name.setText(name)
        if definition.get("kind") == cmaps.QUALITATIVE:
            self._kind_qual.setChecked(True)
            self._swatches.set_colours(definition.get("colors", []))
        else:
            self._kind_cont.setChecked(True)
            self._gradient.set_stops(definition.get("stops", []))
        self._delete_btn.setEnabled(True)
        self._refresh_preview()

    def _apply_seed(self) -> None:
        name = self._seed.currentText()
        if self._current_kind() == cmaps.QUALITATIVE:
            self._swatches.seed_from(name)
        else:
            self._gradient.seed_from(name)

    def _reverse(self) -> None:
        if self._current_kind() == cmaps.QUALITATIVE:
            self._swatches.reverse()
        else:
            self._gradient.reverse()

    def _refresh_preview(self) -> None:
        self._preview.show_definition(self._definition())

    # -- persistence ------------------------------------------

    def _save(self) -> None:
        name = self._name.text().strip()
        if not name:
            self._status.setText("Give the colormap a name.")
            return
        if name.endswith("_r"):
            self._status.setText("Names cannot end in '_r' (matplotlib reverses those).")
            return
        try:
            import matplotlib

            builtin = name in matplotlib.colormaps and name not in cmaps.custom_definitions()
        except Exception:  # noqa: BLE001
            builtin = False
        if builtin:
            QMessageBox.warning(
                self, "Name in use",
                f"'{name}' is a built-in matplotlib colormap. Choose another name.",
            )
            return

        cmaps.upsert(name, self._definition())
        swatches.clear_cache()
        self._reload_existing()
        self._existing.setCurrentText(name)
        self._status.setText(f"Saved '{name}'.")
        self.changed.emit()

    def _delete(self) -> None:
        name = self._name.text().strip()
        if name not in cmaps.custom_definitions():
            return
        if QMessageBox.question(self, "Delete colormap", f"Delete '{name}'?") != (
            QMessageBox.StandardButton.Yes
        ):
            return
        cmaps.forget(name)
        swatches.clear_cache()
        self._name.clear()
        self._reload_existing()
        self._existing.setCurrentText(_NEW)
        self._status.setText(f"Deleted '{name}'.")
        self.changed.emit()
