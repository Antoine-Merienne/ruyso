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

import json

from NodeGraphQt import BaseNode
from NodeGraphQt.constants import NodePropWidgetEnum
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
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

#: Label of the italic-grey "clear this field" entry at the top of a
#: column / suggestions dropdown, and the colour it is drawn in.
_CLEAR_SENTINELS = frozenset({"None", "infer"})
_SENTINEL_COLOR = QColor(150, 150, 150)


def _prepend_clear_sentinel(combo: QComboBox, label: str) -> None:
    """Insert an italic, grey '<label>' row at the top of ``combo``.

    Choosing it clears the field (handled by the combo's ``activated``
    slot); it is never itself a value.
    """
    combo.insertItem(0, label)
    font = combo.font()
    font.setItalic(True)
    combo.setItemData(0, font, Qt.FontRole)
    combo.setItemData(0, _SENTINEL_COLOR, Qt.ForegroundRole)


class OptionsPanel(QWidget):
    """Right-hand settings panel for the selected node / dashboard element."""

    #: Emitted with a core node_type when the macro or micro dropdown is
    #: changed by the user (never when repopulated programmatically).
    node_type_change_requested = Signal(str)

    #: Emitted when tickbox edits made since the last flush should now
    #: drive a downstream recompute (the panel lost focus / moved on).
    recompute_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ruysoOptionsPanel")
        self.setMinimumWidth(MIN_PANEL_WIDTH)

        self._category: str | None = None
        self._node: BaseNode | None = None
        self._suppress_type_signal = False
        self._input_columns: dict[str, str] | None = None
        # {column: [distinct values]} for the rename-categories editor
        self._column_values: dict[str, list[str]] = {}
        # True while writing a tickbox edit: MainWindow skips the
        # per-change auto-run so ticks are batched until focus-out.
        self._suppress_autorun = False
        self._pending_recompute = False
        # field name -> (warning label, accepted kinds, is_list, value getter, set_items)
        self._column_fields: dict[str, tuple] = {}
        # field name -> widget, for controller wiring
        self._field_widgets: dict[str, QWidget] = {}
        # form row index -> [(field, kind, target)]; the row is shown only
        # while *every* condition holds. kind is "eq" (field == target) or
        # "set" (field holds any non-empty value; target None).
        self._row_conditions: dict[int, list[tuple[str, str, str | None]]] = {}
        # controlling field name -> set of rows whose visibility depends on it
        self._visibility_controllers: dict[str, set[int]] = {}
        # reactive-choice field name -> (combo, generator key, depends-on field)
        self._reactive_choices: dict[str, tuple] = {}
        # checkbox-list field name (source="columns" only) -> repopulate()
        self._checkbox_lists: dict[str, object] = {}
        # category-map field name -> (repopulate(), source-column field name)
        self._category_maps: dict[str, tuple] = {}

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

        self._params_host = QWidget()
        self._params_form = QFormLayout(self._params_host)
        self._params_form.setContentsMargins(0, 8, 0, 0)
        self._params_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # The parameter form can get long (the grapher node alone has
        # ~20 rows), so it scrolls inside the panel.
        self._params_scroll = QScrollArea(self)
        self._params_scroll.setWidgetResizable(True)
        self._params_scroll.setFrameShape(QScrollArea.NoFrame)
        self._params_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._params_scroll.setWidget(self._params_host)
        self._params_scroll.viewport().setAutoFillBackground(False)
        self._params_host.setAutoFillBackground(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addLayout(self._header_form)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._params_scroll, 1)

        self._set_editor_visible(False)
        self.apply_theme()

        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)

    # -- batched-recompute plumbing --------------------------------------

    def autorun_suppressed(self) -> bool:
        """True while a tickbox edit is being written (see ``_suppress_autorun``)."""
        return self._suppress_autorun

    def flush_recompute(self) -> None:
        """Emit ``recompute_requested`` if tickbox edits are pending."""
        if self._pending_recompute:
            self._pending_recompute = False
            self.recompute_requested.emit()

    def _write_batched(self, node: BaseNode, name: str, value: str) -> None:
        """Write a param without triggering the per-change auto-run."""
        self._suppress_autorun = True
        try:
            node.set_property(name, value)
        finally:
            self._suppress_autorun = False
        self._pending_recompute = True

    def _on_app_focus_changed(self, _old: object, new: object) -> None:
        if self._pending_recompute and not self._descends_from_panel(new):
            self.flush_recompute()

    def _descends_from_panel(self, widget: object) -> bool:
        while widget is not None:
            if widget is self:
                return True
            widget = widget.parent() if hasattr(widget, "parent") else None
        return False

    # -- public API ---------------------------------------------------------

    def show_node(
        self,
        node: BaseNode,
        node_types_by_category: dict[str, list[str]],
        input_columns: dict[str, str] | None = None,
        column_values: dict[str, list[str]] | None = None,
    ) -> None:
        """
        Populate the panel for ``node``.

        Args:
            node: The selected canvas node (built by ``node_factory``).
            node_types_by_category: ``category -> [node_type, ...]`` for
                every registered node, for the two dropdowns.
            input_columns: ``{column: kind}`` of the node's input
                DataFrame from the last run, or ``None`` if unavailable.
            column_values: ``{column: [distinct values]}`` for the input
                DataFrame's categorical columns (rename-categories editor).
        """
        self.flush_recompute()  # commit the previous node's pending ticks
        core_cls = type(node).CORE_NODE_CLASS
        core_type = type(node).CORE_NODE_TYPE
        self._node = node
        self._input_columns = input_columns
        self._column_values = dict(column_values or {})

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
        self.flush_recompute()
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

    def set_input_columns(
        self,
        input_columns: dict[str, str] | None,
        column_values: dict[str, list[str]] | None = None,
    ) -> None:
        """
        Update the column pickers in place (e.g. after a background
        auto-run made the input DataFrame available) without rebuilding
        the whole form, so the user's focus and half-typed text survive.
        """
        self._input_columns = input_columns
        if column_values is not None:
            self._column_values = dict(column_values)
        columns = sorted(input_columns or {})
        for name, entry in self._column_fields.items():
            entry[4](columns)  # set_items
            self._revalidate(name)
        for repopulate in self._checkbox_lists.values():
            repopulate()
        for repopulate, _src in self._category_maps.values():
            repopulate()
        self._refresh_all_reactive_choices()

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
        self._params_scroll.setVisible(visible)
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
        self._field_widgets.clear()
        self._row_conditions.clear()
        self._visibility_controllers.clear()
        self._reactive_choices.clear()
        self._checkbox_lists.clear()
        self._category_maps.clear()

        specs = list(iter_field_specs(type(node).CORE_NODE_CLASS.params_schema))
        controllers = {
            sp.reactive_choice["depends_on"] for sp in specs if sp.reactive_choice
        }
        controllers |= {
            sp.category_map["column"] for sp in specs if sp.category_map
        }

        for spec in specs:
            widget = self._build_field_widget(node, spec)
            row = self._params_form.rowCount()
            self._params_form.addRow(spec.name.replace("_", " "), widget)
            self._field_widgets[spec.name] = widget

            conditions: list[tuple[str, str, str | None]] = []
            if spec.visible_when:
                conditions.append((spec.visible_when[0], "eq", spec.visible_when[1]))
            if spec.visible_when_set:
                conditions.append((spec.visible_when_set, "set", None))
            if spec.visible_unless:
                conditions.append((spec.visible_unless[0], "ne", spec.visible_unless[1]))
            if conditions:
                self._row_conditions[row] = conditions
                for field, _kind, _target in conditions:
                    self._visibility_controllers.setdefault(field, set()).add(row)

        controllers |= set(self._visibility_controllers)
        for cname in controllers:
            self._connect_controller(cname)
        for row in self._row_conditions:
            self._apply_row_visibility(row)
        self._refresh_all_reactive_choices()

    # -- reactive form behaviour ------------------------------------------

    def _connect_controller(self, cname: str) -> None:
        widget = self._field_widgets.get(cname)
        if widget is None:
            return
        control = getattr(widget, "_combo", widget)
        if isinstance(control, QComboBox):
            control.currentTextChanged.connect(
                lambda *_a, c=cname: self._on_controller_changed(c)
            )
        elif isinstance(control, QCheckBox):
            control.toggled.connect(
                lambda *_a, c=cname: self._on_controller_changed(c)
            )

    def _on_controller_changed(self, cname: str) -> None:
        for row in self._visibility_controllers.get(cname, ()):
            self._apply_row_visibility(row)
        for name, (_combo, _key, depends_on) in list(self._reactive_choices.items()):
            if depends_on == cname:
                self._refresh_reactive_choice(name)
        for repopulate, source in self._category_maps.values():
            if source == cname:
                repopulate()

    def _field_current_str(self, field: str) -> str:
        raw = self._node.get_property(field) if self._node is not None else ""
        return ("True" if raw else "False") if isinstance(raw, bool) else str(raw)

    def _apply_row_visibility(self, row: int) -> None:
        """Show ``row`` only while *all* of its conditions hold (AND)."""
        if self._node is None:
            return
        visible = True
        for field, kind, target in self._row_conditions.get(row, ()):
            current = self._field_current_str(field)
            if kind == "set":
                ok = bool(current.strip()) and current not in ("None", "False")
            elif kind == "ne":
                ok = current != target
            else:
                ok = current == target
            if not ok:
                visible = False
                break
        self._params_form.setRowVisible(row, visible)

    def _refresh_all_reactive_choices(self) -> None:
        for name in list(self._reactive_choices):
            self._refresh_reactive_choice(name)

    def _refresh_reactive_choice(self, name: str) -> None:
        from ruyso_app.ui.column_ops import options_for

        combo, generator, depends_on = self._reactive_choices[name]
        dep_value = (
            str(self._node.get_property(depends_on)) if self._node is not None else ""
        )
        kind = (self._input_columns or {}).get(dep_value)
        options = options_for(generator, kind)

        # Seed from the node's stored value, not the combo text: on a
        # form rebuild the combo is empty, and falling back to
        # ``options[0]`` here used to silently overwrite a valid saved
        # choice (e.g. a hand-picked colormap reverting to "tab10").
        stored = str(self._node.get_property(name)) if self._node is not None else ""
        kept = combo.currentText() or stored

        combo.blockSignals(True)
        combo.clear()
        combo.addItems(options)
        if kept in options:
            combo.setCurrentText(kept)
        elif options:
            combo.setCurrentText(options[0])
            if self._node is not None and stored not in options:
                self._node.set_property(name, options[0])
        combo.blockSignals(False)

    # -- per-field widgets ----------------------------------------------

    def _build_field_widget(self, node: BaseNode, spec) -> QWidget:
        """One editor widget bound to ``node``'s NodeGraphQt property."""
        name = spec.name
        current = node.get_property(name)
        enum = NodePropWidgetEnum

        if spec.checkbox_list is not None:
            return self._build_checkbox_list_widget(node, spec)

        if spec.category_map is not None:
            return self._build_category_map_widget(node, spec)

        if spec.reactive_choice is not None:
            return self._build_reactive_choice_widget(node, spec)

        if spec.column_dtypes is not None:
            return self._build_column_widget(node, spec, current)

        if spec.color_choices is not None:
            return self._build_color_widget(node, spec, current)

        if spec.suggestions is not None:
            return self._build_suggestions_widget(node, spec, current)

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

    # -- free-text fields with a suggestion dropdown ------------------

    def _build_suggestions_widget(self, node: BaseNode, spec, current) -> QWidget:
        """
        An editable combo (single down arrow, like the column pickers)
        pre-filled with a few suggested values. Any text is accepted;
        the italic-grey top row clears the field.
        """
        name = spec.name
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.addItems(spec.suggestions or [])
        _prepend_clear_sentinel(combo, "infer")
        combo.setCurrentText("" if current in (None, "") else str(current))

        combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))

        def _on_activated(index: int, _c=combo) -> None:
            if _c.itemText(index) in _CLEAR_SENTINELS:
                _c.setCurrentText("")

        combo.activated.connect(_on_activated)
        return combo

    # -- colour fields ------------------------------------------------

    def _build_color_widget(self, node: BaseNode, spec, current) -> QWidget:
        """
        An editable combo pre-filled with common colour names, plus a
        small "Choose..." button opening a colour dialog. Any
        matplotlib colour string (name or ``#rrggbb``) is accepted.
        """
        name = spec.name
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.addItems(spec.color_choices or [])
        combo.setCurrentText("" if current in (None, "") else str(current))
        combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))

        button = QPushButton("Choose...")
        button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        def _pick(_checked: bool = False, _combo=combo) -> None:
            initial = QColor(_combo.currentText().strip() or "#1f77b4")
            if not initial.isValid():
                initial = QColor("#1f77b4")
            chosen = QColorDialog.getColor(initial, self, "Choose colour")
            if chosen.isValid():
                _combo.setCurrentText(chosen.name())

        button.clicked.connect(_pick)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(combo, 1)
        row_layout.addWidget(button, 0)
        row._combo = combo  # for _connect_controller
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

        # Same widget as the grapher / model column fields: one editable
        # combo box with a single dropdown arrow.
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.addItems(columns)
        box.addWidget(combo)
        value_getter = combo.currentText

        if not spec.is_column_list:
            # Single value: the combo's text *is* the value.
            if spec.column_allow_none:
                _prepend_clear_sentinel(combo, "None")
            combo.setCurrentText("" if current is None else str(current))
            combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))
            combo.currentTextChanged.connect(lambda _v, n=name: self._revalidate(n))

            if spec.column_allow_none:

                def _on_activated(index: int, _c=combo) -> None:
                    if _c.itemText(index) in _CLEAR_SENTINELS:
                        _c.setCurrentText("")

                combo.activated.connect(_on_activated)

            def set_items(cols: list[str], _c=combo, _none=spec.column_allow_none) -> None:
                _c.blockSignals(True)
                kept = _c.currentText()
                _c.clear()
                _c.addItems(cols)
                if _none:
                    _prepend_clear_sentinel(_c, "None")
                _c.setCurrentText(kept)
                _c.blockSignals(False)
        else:
            # Multi value: the source of truth is ``selected``, NOT the
            # combo text (QComboBox overwrites its text with the picked
            # item on every activation, which would immediately toggle
            # that item back off if we read it here). Picking an item
            # toggles it; the italic "None" row clears; typing still
            # edits the list.
            _prepend_clear_sentinel(combo, "None")
            combo.lineEdit().setPlaceholderText("none")
            selected: list[str] = [
                c.strip() for c in str(current or "").split(",") if c.strip()
            ]

            def _show() -> None:
                combo.blockSignals(True)
                combo.setCurrentText(", ".join(selected))
                combo.blockSignals(False)

            def _commit() -> None:
                node.set_property(name, ", ".join(selected))
                self._revalidate(name)

            def _toggle_picked(index: int) -> None:
                picked = combo.itemText(index)
                if picked in _CLEAR_SENTINELS:
                    selected.clear()
                elif picked:
                    if picked in selected:
                        selected.remove(picked)
                    else:
                        selected.append(picked)
                else:
                    return
                _show()
                _commit()

            def _on_typed(text: str) -> None:
                selected[:] = [c.strip() for c in text.split(",") if c.strip()]
                node.set_property(name, text)
                self._revalidate(name)

            combo.activated.connect(_toggle_picked)
            combo.lineEdit().textEdited.connect(_on_typed)
            _show()

            def set_items(cols: list[str], _c=combo) -> None:
                _c.blockSignals(True)
                _c.clear()
                _c.addItems(cols)
                _prepend_clear_sentinel(_c, "None")
                _c.setCurrentText(", ".join(selected))
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
        container._combo = combo  # for _connect_controller
        return container

    # -- reactive-choice + checkbox-list fields ------------------------

    def _build_reactive_choice_widget(self, node: BaseNode, spec) -> QWidget:
        """
        A plain dropdown (no free text) whose options are recomputed
        from the value of another field -- see
        ``core.params.reactive_choice_field``. Populated by
        ``_refresh_reactive_choice`` once registered.
        """
        name = spec.name
        combo = QComboBox()
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))
        self._reactive_choices[name] = (
            combo,
            spec.reactive_choice["options"],
            spec.reactive_choice["depends_on"],
        )
        return combo

    def _build_checkbox_list_widget(self, node: BaseNode, spec) -> QWidget:
        """
        A scrollable column of tickboxes. ``source="columns"`` fills it
        from the input DataFrame's columns (and re-fills on
        ``set_input_columns``, in place -- no rebuild when the columns
        are unchanged); a fixed ``choices`` list is static. The checked
        labels are stored as the field's comma-separated value; a tick
        does not fire the auto-run until the panel loses focus.
        """
        name = spec.name
        fixed: list[str] | None = spec.checkbox_list.get("choices")

        inner = QWidget()
        vbox = QVBoxLayout(inner)
        vbox.setContentsMargins(4, 6, 4, 6)
        vbox.setSpacing(9)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMaximumHeight(200)
        scroll.setMinimumHeight(48)

        hint = QLabel("run the pipeline to list columns")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        boxes: dict[str, QCheckBox] = {}
        shown: list[str] | None = None  # last rendered label list (identity guard)

        def checked_set() -> set[str]:
            raw = node.get_property(name) or ""
            return {c.strip() for c in str(raw).split(",") if c.strip()}

        def on_toggle(checked: bool, label: str) -> None:
            values = checked_set() | {label} if checked else checked_set() - {label}
            self._write_batched(node, name, ", ".join(sorted(values)))

        def make_box(label: str) -> QCheckBox:
            box = QCheckBox(label)
            box.setChecked(label in checked_set())
            box.toggled.connect(lambda on, lbl=label: on_toggle(on, lbl))
            return box

        def repopulate(labels: list[str] | None = None) -> None:
            nonlocal shown
            if labels is None:
                labels = fixed if fixed is not None else sorted(self._input_columns or {})
            labels = list(labels)
            if shown == labels:
                return  # nothing changed -> no rebuild, no flicker
            shown = labels

            # Detach everything (kept checkboxes survive; the spacer /
            # hint are value items we simply drop).
            while vbox.count():
                vbox.takeAt(0)
            hint.setParent(None)
            for gone in [lbl for lbl in boxes if lbl not in labels]:
                widget = boxes.pop(gone)
                widget.setParent(None)
                widget.deleteLater()

            if not labels:
                vbox.addWidget(hint)
                vbox.addStretch(1)
                return

            current = checked_set()
            for label in labels:
                box = boxes.get(label)
                if box is None:
                    box = make_box(label)
                    boxes[label] = box
                box.blockSignals(True)
                box.setChecked(label in current)
                box.blockSignals(False)
                vbox.addWidget(box)
            vbox.addStretch(1)

        repopulate()
        if fixed is None:
            self._checkbox_lists[name] = repopulate
        return scroll

    def _build_category_map_widget(self, node: BaseNode, spec) -> QWidget:
        """
        A scrollable table: each distinct value of the source column
        (``spec.category_map["column"]``) faces a "new name" line-edit,
        blank = keep. Stored as a JSON ``{old: new}`` string. Edits are
        batched like the tickbox lists -- the auto-run waits for
        focus-out. Rebuilds when the source column changes or the input
        data arrives.
        """
        name = spec.name
        source_field = spec.category_map["column"]

        inner = QWidget()
        form = QFormLayout(inner)
        form.setContentsMargins(4, 6, 4, 6)
        form.setSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMaximumHeight(220)
        scroll.setMinimumHeight(48)

        edits: dict[str, QLineEdit] = {}
        shown: list[str] | None = None

        def stored_map() -> dict[str, str]:
            try:
                data = json.loads(node.get_property(name) or "{}")
            except (ValueError, TypeError):
                return {}
            return (
                {str(k): str(v) for k, v in data.items()}
                if isinstance(data, dict)
                else {}
            )

        def commit() -> None:
            mapping = {
                cat: e.text().strip()
                for cat, e in edits.items()
                if e.text().strip() and e.text().strip() != cat
            }
            self._write_batched(node, name, json.dumps(mapping, ensure_ascii=False))

        def repopulate() -> None:
            nonlocal shown
            source = str(node.get_property(source_field) or "")
            cats = list(self._column_values.get(source, []))
            if shown == cats:
                return
            shown = cats

            while form.rowCount():
                form.removeRow(0)
            edits.clear()

            if not cats:
                empty = QLabel("run the pipeline to list categories")
                empty.setStyleSheet("color: gray; font-size: 11px;")
                form.addRow(empty)
                return

            current = stored_map()
            for cat in cats:
                field = QLineEdit(current.get(cat, ""))
                field.setPlaceholderText(cat)
                field.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                field.textChanged.connect(lambda _t: commit())
                edits[cat] = field
                form.addRow(cat, field)

        repopulate()
        self._category_maps[name] = (repopulate, source_field)
        return scroll

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
