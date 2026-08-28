"""
The Options panel shown on the right of the Pipeline and Dashboard
tabs (never on the Table tab).

On the Pipeline tab it is the editor for the selected node:

* a **macro type** dropdown and a **micro type** dropdown -- changing
  either recreates the underlying node in place (see
  ``ui.node_editing.change_node_micro_type``); changing the macro type
  switches to the first concrete node of the new macro type;
* a parameter form built from the node's ``params_schema`` via
  ``property_forms.iter_field_specs`` and written straight back onto
  the NodeGraphQt node properties (so ``graph_bridge`` keeps seeing
  the values it expects). Path fields get a *Browse...* button; column
  fields (see ``core.params.column_field``) get a dropdown of the
  input DataFrame's columns and warn when a name is unknown or the
  column's type is not supported.

Per the spec its background is a lightened, slightly translucent tint
of the macro type color of the last selected (or last existing) node.
"""

from __future__ import annotations

from NodeGraphQt import BaseNode
from NodeGraphQt.constants import NodePropWidgetEnum
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ruyso_app.ui import theme
from ruyso_app.ui.column_spec import (
    UNKNOWN_COLUMN,
    UNSUPPORTED_TYPE,
    validate_column_value,
    warning_message,
)
from ruyso_app.ui.file_filters import filter_for
from ruyso_app.ui.property_forms import iter_field_specs

#: Minimum width; the panel lives in a splitter and can be widened.
MIN_PANEL_WIDTH = 240

_WARNING_STYLE = "color: #d9822b; font-size: 11px;"


class OptionsPanel(QWidget):
    """Right-hand settings panel for the selected node / dashboard element."""

    #: Emitted with a core node_type when the macro or micro dropdown is
    #: changed by the user (never when repopulated programmatically).
    node_type_change_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoOptionsPanel")
        self.setMinimumWidth(MIN_PANEL_WIDTH)

        self._category: str | None = None
        self._node: BaseNode | None = None
        self._suppress_type_signal = False
        self._input_columns: dict[str, str] | None = None
        # field name -> (warning label, accepted kinds, is_list, value getter)
        self._column_fields: dict[str, tuple] = {}

        self._title = QLabel("Options", self)
        self._title.setStyleSheet("font-weight: bold;")

        self._macro_combo = QComboBox(self)
        for category, label in theme.MACRO_TYPE_LABELS.items():
            self._macro_combo.addItem(label, category)
        self._macro_combo.currentIndexChanged.connect(self._on_macro_combo_changed)

        self._micro_combo = QComboBox(self)
        self._micro_combo.currentTextChanged.connect(self._on_micro_combo_changed)

        self._header_form = QFormLayout()
        self._header_form.addRow("Macro type", self._macro_combo)
        self._header_form.addRow("Micro type", self._micro_combo)

        self._placeholder = QLabel("No selection", self)
        self._placeholder.setWordWrap(True)

        self._params_host = QWidget(self)
        self._params_form = QFormLayout(self._params_host)
        self._params_form.setContentsMargins(0, 8, 0, 0)
        self._params_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

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

    def show_node(
        self,
        node: BaseNode,
        node_types_by_category: dict[str, list[str]],
        input_columns: dict[str, str] | None = None,
    ) -> None:
        """
        Populate the panel for ``node``.

        Args:
            node: The selected canvas node (built by ``node_factory``).
            node_types_by_category: ``category -> [node_type, ...]`` for
                every registered node, for the two dropdowns.
            input_columns: ``{column: kind}`` of the node's input
                DataFrame from the last run, or ``None`` if unavailable.
        """
        core_cls = type(node).CORE_NODE_CLASS
        core_type = type(node).CORE_NODE_TYPE
        self._node = node
        self._input_columns = input_columns

        self.set_category(core_cls.category)

        self._suppress_type_signal = True
        self._populate_macro_combo(core_cls.category, node_types_by_category)
        siblings = node_types_by_category.get(core_cls.category, [])
        self._micro_combo.clear()
        self._micro_combo.addItems(siblings)
        if core_type in siblings:
            self._micro_combo.setCurrentText(core_type)
        self._micro_combo.setEnabled(len(siblings) > 1)
        self._suppress_type_signal = False

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

    def set_input_columns(self, input_columns: dict[str, str] | None) -> None:
        """
        Update the column pickers in place (e.g. after a background
        auto-run made the input DataFrame available) without rebuilding
        the whole form, so the user's focus and half-typed text survive.
        """
        self._input_columns = input_columns
        columns = sorted(input_columns or {})
        for name, entry in self._column_fields.items():
            entry[4](columns)  # set_items
            self._revalidate(name)

    def apply_theme(self) -> None:
        """Recompute the background tint from the current theme + category."""
        background = theme.options_panel_background(self._category)
        self.setStyleSheet(
            f"QWidget#ruysoOptionsPanel {{ background-color: {background}; }}"
        )

    # -- internals --------------------------------------------------------

    def _populate_macro_combo(
        self, category: str, node_types_by_category: dict[str, list[str]]
    ) -> None:
        model = self._macro_combo.model()
        for i in range(self._macro_combo.count()):
            item_category = self._macro_combo.itemData(i)
            has_nodes = bool(node_types_by_category.get(item_category))
            model.item(i).setEnabled(has_nodes)
            if item_category == category:
                self._macro_combo.setCurrentIndex(i)

    def _set_editor_visible(self, visible: bool) -> None:
        self._placeholder.setVisible(not visible)
        self._params_host.setVisible(visible)
        for i in range(self._header_form.count()):
            item = self._header_form.itemAt(i).widget()
            if item is not None:
                item.setVisible(visible)

    def _on_macro_combo_changed(self, index: int) -> None:
        if self._suppress_type_signal or self._node is None or index < 0:
            return
        category = self._macro_combo.itemData(index)
        if category == type(self._node).CORE_NODE_CLASS.category:
            return
        # Ask the owner to switch to the first concrete node of this macro.
        from ruyso_app.ui.node_factory import core_node_types_by_category

        node_types = core_node_types_by_category().get(category, [])
        if node_types:
            self.node_type_change_requested.emit(node_types[0])

    def _on_micro_combo_changed(self, new_type: str) -> None:
        if self._suppress_type_signal or not new_type:
            return
        if self._node is not None and type(self._node).CORE_NODE_TYPE == new_type:
            return
        self.node_type_change_requested.emit(new_type)

    def _rebuild_params_form(self, node: BaseNode) -> None:
        while self._params_form.rowCount():
            self._params_form.removeRow(0)
        self._column_fields.clear()

        schema = type(node).CORE_NODE_CLASS.params_schema
        for spec in iter_field_specs(schema):
            widget = self._build_field_widget(node, spec)
            self._params_form.addRow(spec.name.replace("_", " "), widget)

    def _build_field_widget(self, node: BaseNode, spec) -> QWidget:
        """One editor widget bound to ``node``'s NodeGraphQt property."""
        name = spec.name
        current = node.get_property(name)
        enum = NodePropWidgetEnum

        if spec.column_dtypes is not None:
            return self._build_column_widget(node, spec, current)

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

        edit = QLineEdit("" if current is None else str(current))
        edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        edit.textChanged.connect(lambda v, n=name: node.set_property(n, v))

        if spec.widget != enum.FILE_OPEN:
            return edit

        edit.setPlaceholderText("path to file")
        browse = QPushButton("Browse...")
        browse.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        browse.clicked.connect(lambda _c=False, n=node, e=edit: self._browse_for_path(n, e))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(edit, 1)
        row_layout.addWidget(browse, 0)
        return row

    # -- column-reference fields ---------------------------------------

    def _build_column_widget(self, node: BaseNode, spec, current) -> QWidget:
        name = spec.name
        columns = sorted(self._input_columns or {})
        warning = QLabel()
        warning.setStyleSheet(_WARNING_STYLE)
        warning.setWordWrap(True)
        warning.setVisible(False)

        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)

        # Both single- and multi-column fields use the same widget as the
        # grapher / model column fields: one editable combo box with a
        # single dropdown arrow. For a list-valued field, picking an item
        # from the dropdown toggles it in/out of the comma-separated
        # value instead of replacing it; free text is always allowed.
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.addItems(columns)
        combo.setCurrentText("" if current is None else str(current))
        combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))
        combo.currentTextChanged.connect(lambda _v, n=name: self._revalidate(n))
        box.addWidget(combo)
        value_getter = combo.currentText

        if spec.is_column_list:
            combo.lineEdit().setPlaceholderText("comma-separated column names")

            def _toggle_picked(index: int, _c=combo) -> None:
                picked = _c.itemText(index)
                if not picked:
                    return
                items = [c.strip() for c in _c.currentText().split(",") if c.strip()]
                if picked in items:
                    items.remove(picked)
                else:
                    items.append(picked)
                _c.setCurrentText(", ".join(items))

            combo.activated.connect(_toggle_picked)

        def set_items(cols: list[str], _c=combo) -> None:
            _c.blockSignals(True)
            kept = _c.currentText()
            _c.clear()
            _c.addItems(cols)
            _c.setCurrentText(kept)
            _c.blockSignals(False)

        box.addWidget(warning)
        self._column_fields[name] = (
            warning,
            spec.column_dtypes,
            spec.is_column_list,
            value_getter,
            set_items,
        )
        self._revalidate(name)
        return container

    def _revalidate(self, field_name: str) -> None:
        entry = self._column_fields.get(field_name)
        if entry is None:
            return
        warning, accepted, is_list, value_getter, _set_items = entry
        raw = value_getter() or ""
        values = (
            [v.strip() for v in raw.split(",") if v.strip()] if is_list else [raw.strip()]
        )

        messages: list[str] = []
        for value in values:
            code = validate_column_value(value, accepted, self._input_columns)
            if code in (UNKNOWN_COLUMN, UNSUPPORTED_TYPE):
                messages.append(warning_message(code, value, accepted, self._input_columns))

        warning.setText("\n".join(messages))
        warning.setVisible(bool(messages))

    # -- file path fields --------------------------------------------

    def _browse_for_path(self, node: BaseNode, edit: QLineEdit) -> None:
        """Open a native file dialog and write the chosen path into ``edit``."""
        node_type = getattr(type(node), "CORE_NODE_TYPE", None)
        category = getattr(type(node).CORE_NODE_CLASS, "category", "")
        file_filter = filter_for(node_type)
        start_dir = edit.text().strip()

        if category == "export":
            path, _ = QFileDialog.getSaveFileName(
                self, "Select output file", start_dir, file_filter
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select data file", start_dir, file_filter
            )
        if path:
            edit.setText(path)  # fires textChanged -> node.set_property
