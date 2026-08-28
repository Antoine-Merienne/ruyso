"""
The Options panel shown on the right of the Pipeline and Dashboard
tabs (never on the Table tab).

On the Pipeline tab it is the editor for the selected node:

* a read-only **macro type** line;
* a **micro type** dropdown listing the concrete node types of that
  macro type -- changing it recreates the underlying node in place
  (see ``ui.node_editing.change_node_micro_type``), which is how the
  spec's "choose the micro type after creating the node" step works;
* a parameter form built from the node's ``params_schema`` via
  ``property_forms.iter_field_specs`` and written straight back onto
  the NodeGraphQt node properties (so ``graph_bridge`` keeps seeing
  the values it expects).

Per the spec its background is a lightened, slightly translucent tint
of the macro type color of the last selected (or last existing) node;
that derivation lives in ``theme.options_panel_background``.
"""

from __future__ import annotations

from NodeGraphQt import BaseNode
from NodeGraphQt.constants import NodePropWidgetEnum
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ruyso_app.ui import theme
from ruyso_app.ui.property_forms import iter_field_specs

#: Minimum width; the panel lives in a splitter and can be widened.
MIN_PANEL_WIDTH = 240


class OptionsPanel(QWidget):
    """Right-hand settings panel for the selected node / dashboard element."""

    #: Emitted with a core node_type when the micro-type dropdown is
    #: changed by the user (not when it is repopulated programmatically).
    micro_type_change_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoOptionsPanel")
        self.setMinimumWidth(MIN_PANEL_WIDTH)

        self._category: str | None = None
        self._node: BaseNode | None = None
        self._suppress_micro_signal = False

        self._title = QLabel("Options", self)
        self._title.setStyleSheet("font-weight: bold;")

        self._macro_label = QLabel("-", self)
        self._micro_combo = QComboBox(self)
        self._micro_combo.currentTextChanged.connect(self._on_micro_combo_changed)

        self._header_form = QFormLayout()
        self._header_form.addRow("Macro type", self._macro_label)
        self._header_form.addRow("Micro type", self._micro_combo)

        self._placeholder = QLabel("No selection", self)
        self._placeholder.setWordWrap(True)

        self._params_host = QWidget(self)
        self._params_form = QFormLayout(self._params_host)
        self._params_form.setContentsMargins(0, 8, 0, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addLayout(self._header_form)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._params_host)
        layout.addStretch(1)

        self._set_editor_visible(False)
        self.apply_theme()

    # -- public API ---------------------------------------------------------

    def show_node(self, node: BaseNode, siblings: list[str]) -> None:
        """
        Populate the panel for ``node``.

        Args:
            node: The selected canvas node (built by ``node_factory``).
            siblings: Every core node_type sharing ``node``'s macro type,
                for the micro-type dropdown.
        """
        core_cls = type(node).CORE_NODE_CLASS
        core_type = type(node).CORE_NODE_TYPE
        self._node = node

        self.set_category(core_cls.category)
        self._macro_label.setText(theme.label_for_category(core_cls.category))

        self._suppress_micro_signal = True
        self._micro_combo.clear()
        self._micro_combo.addItems(siblings)
        if core_type in siblings:
            self._micro_combo.setCurrentText(core_type)
        self._micro_combo.setEnabled(len(siblings) > 1)
        self._suppress_micro_signal = False

        self._rebuild_params_form(node)
        self._set_editor_visible(True)

    def clear(self) -> None:
        """Show the empty state (nothing selected)."""
        self._node = None
        self._set_editor_visible(False)

    def current_node(self) -> BaseNode | None:
        return self._node

    def set_category(self, category: str | None) -> None:
        """Set the macro type whose color tints the panel background."""
        self._category = category
        self.apply_theme()

    def current_category(self) -> str | None:
        return self._category

    def apply_theme(self) -> None:
        """Recompute the background tint from the current theme + category."""
        background = theme.options_panel_background(self._category)
        self.setStyleSheet(
            f"QWidget#ruysoOptionsPanel {{ background-color: {background}; }}"
        )

    # -- internals --------------------------------------------------------

    def _set_editor_visible(self, visible: bool) -> None:
        self._placeholder.setVisible(not visible)
        self._params_host.setVisible(visible)
        for i in range(self._header_form.count()):
            item = self._header_form.itemAt(i).widget()
            if item is not None:
                item.setVisible(visible)

    def _on_micro_combo_changed(self, new_type: str) -> None:
        if self._suppress_micro_signal or not new_type:
            return
        if self._node is not None and type(self._node).CORE_NODE_TYPE == new_type:
            return
        self.micro_type_change_requested.emit(new_type)

    def _rebuild_params_form(self, node: BaseNode) -> None:
        while self._params_form.rowCount():
            self._params_form.removeRow(0)

        schema = type(node).CORE_NODE_CLASS.params_schema
        for spec in iter_field_specs(schema):
            widget = self._build_field_widget(node, spec)
            self._params_form.addRow(spec.name.replace("_", " "), widget)

    def _build_field_widget(self, node: BaseNode, spec) -> QWidget:
        """One editor widget bound to ``node``'s NodeGraphQt property."""
        name = spec.name
        current = node.get_property(name)
        enum = NodePropWidgetEnum

        if spec.widget == enum.QCOMBO_BOX:
            combo = QComboBox()
            combo.addItems(spec.choices or [])
            if current is not None:
                combo.setCurrentText(str(current))
            combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))
            return combo

        if spec.widget == enum.QCHECK_BOX:
            box = QCheckBox()
            box.setChecked(bool(current))
            box.toggled.connect(lambda v, n=name: node.set_property(n, bool(v)))
            return box

        if spec.widget == enum.INT:
            spin = QSpinBox()
            spin.setRange(-1_000_000, 1_000_000)
            spin.setValue(int(current or 0))
            spin.valueChanged.connect(lambda v, n=name: node.set_property(n, int(v)))
            return spin

        if spec.widget == enum.FLOAT:
            spin = QDoubleSpinBox()
            spin.setRange(-1e9, 1e9)
            spin.setDecimals(4)
            spin.setValue(float(current or 0.0))
            spin.valueChanged.connect(lambda v, n=name: node.set_property(n, float(v)))
            return spin

        # QLINE_EDIT and FILE_OPEN both edit as free text here.
        edit = QLineEdit("" if current is None else str(current))
        edit.textChanged.connect(lambda v, n=name: node.set_property(n, v))
        if spec.widget == enum.FILE_OPEN:
            edit.setPlaceholderText("path to file")
        return edit
