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
from PySide6.QtGui import QColor, QFont
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
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
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
from ruyso_app.ui.micro_type_groups import grouped_micro_types
from ruyso_app.ui.property_forms import iter_field_specs
from ruyso_app.ui.swatch_combo import SwatchComboBox

#: Minimum width; the panel lives in a splitter and can be widened.
MIN_PANEL_WIDTH = 340

_WARNING_STYLE = "color: #d9822b; font-size: 11px;"

#: Label of the italic-grey "clear this field" entry at the top of a
#: column / suggestions dropdown, and the colour it is drawn in.
_CLEAR_SENTINELS = frozenset({"None", "infer"})
_SENTINEL_COLOR = QColor(150, 150, 150)

#: "no column" row in a column-map table dropdown.
_BLANK = "—"

#: Param-field names whose plain dropdown should render a small preview
#: of each choice (see ``ui.swatches``) rather than just its text. The
#: ``colormap`` field (reactive and fixed-``Literal`` alike) and the
#: editable colour-name fields are handled separately by name / kind.
_SWATCH_FIELDS: dict[str, str] = {
    "marker_shape": "marker",
    "line_style": "linestyle",
    "bar_hatch": "hatch",
    "shape_map": "shapemap",
}


#: Floor / ceiling for a float spin box's decimal places.
_MIN_SPIN_DECIMALS = 2
_MAX_SPIN_DECIMALS = 10


def _decimals_for(*values: object) -> int:
    """
    How many decimal places a float spin box needs so it never rounds
    away any of ``values`` -- at least ``_MIN_SPIN_DECIMALS`` (so a
    whole number still shows "6.00", not "6.0000"), at most
    ``_MAX_SPIN_DECIMALS``.
    """
    needed = _MIN_SPIN_DECIMALS
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number != number or number in (float("inf"), float("-inf")):
            continue
        text = f"{abs(number):.{_MAX_SPIN_DECIMALS}f}".rstrip("0")
        frac = text.split(".", 1)[1] if "." in text else ""
        needed = max(needed, len(frac))
    return min(needed, _MAX_SPIN_DECIMALS)


def _node_tagline(core_cls: type) -> str:
    """Short "what this node does" text for the Options pane.

    Uses the core node's ``tagline`` class attribute; when that is
    blank, falls back to the first non-empty line of its docstring.
    """
    text = (getattr(core_cls, "tagline", "") or "").strip()
    if text:
        return " ".join(text.split())
    doc = (core_cls.__doc__ or "").strip()
    if not doc:
        return ""
    # First paragraph of the docstring, whitespace collapsed, trimmed to
    # its first one or two full sentences so a wrapped opening line is
    # not cut mid-clause.
    paragraph = " ".join(doc.split("\n\n", 1)[0].split()).replace("``", "")
    sentences = paragraph.replace(". ", ".\x00").split("\x00")
    return " ".join(sentences[:2]).strip()


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
        self._row_conditions: dict[int, list[tuple[str, str, str | tuple[str, ...] | None]]] = {}
        # controlling field name -> set of rows whose visibility depends on it
        self._visibility_controllers: dict[str, set[int]] = {}
        # reactive-choice field name -> (combo, generator key, depends-on field)
        self._reactive_choices: dict[str, tuple] = {}
        # fixed-kind colormap field name -> (SwatchComboBox, "continuous"/"qualitative")
        self._colormap_fields: dict[str, tuple] = {}
        # checkbox-list field name (source="columns" only) -> repopulate()
        self._checkbox_lists: dict[str, object] = {}
        # category-map field name -> (repopulate(), source-column field name)
        self._category_maps: dict[str, tuple] = {}
        # column-map field name -> repopulate()  (key -> input-column table)
        self._column_maps: dict[str, object] = {}
        # code field name -> refresh_hint()  (updates the column-name hint)
        self._code_hints: dict[str, object] = {}

        self._title = QLabel("Options", self)
        self._title.setStyleSheet("font-weight: bold;")
        self._title.setAlignment(Qt.AlignCenter)

        # Read-only "what this node does" blurb, shown just under the
        # Micro type dropdown. Filled from the core node's ``tagline``
        # (falling back to the first docstring line) by ``show_node``.
        self._node_help = QLabel("", self)
        self._node_help.setObjectName("ruysoNodeHelp")
        self._node_help.setWordWrap(True)
        self._node_help.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._node_help.setStyleSheet(
            "QLabel#ruysoNodeHelp { color: palette(mid); font-size: 11px; "
            "padding: 10px 0 8px 0; line-height: 140%; }"
        )
        self._node_help.setVisible(False)

        self._macro_combo = QComboBox(self)
        for category, label in theme.MACRO_TYPE_LABELS.items():
            self._macro_combo.addItem(label, category)
        self._macro_combo.currentIndexChanged.connect(self._on_macro_combo_changed)

        self._micro_combo = QComboBox(self)
        self._micro_combo.currentTextChanged.connect(self._on_micro_combo_changed)

        self._header_form = QFormLayout()
        self._header_form.setVerticalSpacing(10)
        self._header_form.setHorizontalSpacing(10)
        self._header_form.setContentsMargins(0, 4, 0, 4)
        self._header_form.addRow("Macro type", self._macro_combo)
        self._header_form.addRow("Micro type", self._micro_combo)

        self._placeholder = QLabel("No selection", self)
        self._placeholder.setWordWrap(True)

        self._params_host = QWidget()
        # A trailing stretch keeps the rows packed against the top so a
        # short form (or one with many hidden rows) never spreads its
        # widgets out with gaps between them.
        host_box = QVBoxLayout(self._params_host)
        host_box.setContentsMargins(0, 0, 0, 0)
        host_box.setSpacing(0)
        self._params_form = QFormLayout()
        self._params_form.setContentsMargins(0, 8, 0, 0)
        self._params_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        # Breathing room between parameter rows -- the auto-generated
        # forms were otherwise cramped enough to be hard to scan.
        self._params_form.setVerticalSpacing(12)
        self._params_form.setHorizontalSpacing(10)
        host_box.addLayout(self._params_form)
        host_box.addStretch(1)

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
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        layout.addWidget(self._title)
        layout.addSpacing(2)
        layout.addLayout(self._header_form)
        layout.addWidget(self._node_help)
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
        for index, group in enumerate(grouped_micro_types(core_cls.category, siblings)):
            if index:
                self._micro_combo.insertSeparator(self._micro_combo.count())
            self._micro_combo.addItems(group)
        if core_type in siblings:
            self._micro_combo.setCurrentText(core_type)
        self._micro_combo.setEnabled(len(siblings) > 1)
        self._suppress_type_signal = False

        self._node_help.setText(_node_tagline(core_cls))
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
        for repopulate in self._column_maps.values():
            repopulate()
        for refresh_hint in self._code_hints.values():
            refresh_hint()
        self._refresh_all_reactive_choices()
        # kind-conditioned rows depend on the freshly-learnt column kinds
        for row in self._row_conditions:
            self._apply_row_visibility(row)

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
        self._node_help.setVisible(visible and bool(self._node_help.text()))
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
        self._colormap_fields.clear()
        self._checkbox_lists.clear()
        self._category_maps.clear()
        self._column_maps.clear()
        self._code_hints.clear()

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
            if spec.visible_when_unset:
                conditions.append((spec.visible_when_unset, "unset", None))
            if spec.visible_when_kind:
                conditions.append(
                    (spec.visible_when_kind[0], "colkind", spec.visible_when_kind[1])
                )
            if spec.visible_unless:
                conditions.append((spec.visible_unless[0], "ne", spec.visible_unless[1]))
            if spec.visible_when_in:
                conditions.append((spec.visible_when_in[0], "in", spec.visible_when_in[1]))
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
            is_set = bool(current.strip()) and current not in ("None", "False")
            if kind == "set":
                ok = is_set
            elif kind == "unset":
                ok = not is_set
            elif kind == "colkind":
                col_kind = (self._input_columns or {}).get(current)
                # permissive while the run output (and hence the kind) is
                # not available yet
                ok = is_set and (col_kind is None or col_kind in target)
            elif kind == "ne":
                ok = current != target
            elif kind == "in":
                ok = current in target
            else:
                ok = current == target
            if not ok:
                visible = False
                break
        self._params_form.setRowVisible(row, visible)

    def _refresh_all_reactive_choices(self) -> None:
        for name in list(self._reactive_choices):
            self._refresh_reactive_choice(name)
        self._refresh_colormap_fields()

    def _refresh_colormap_fields(self) -> None:
        """Repopulate the fixed-kind colormap dropdowns from the current
        continuous / qualitative lists (they change when the Colormap
        Manager / Designer is used)."""
        from ruyso_app.ui.column_ops import colormap_choices

        for name, (combo, kind) in self._colormap_fields.items():
            options = colormap_choices(kind)
            stored = str(self._node.get_property(name)) if self._node is not None else ""
            kept = combo.currentText() or stored
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(options)
            if kept in options:
                combo.setCurrentText(kept)
            elif options:
                combo.setCurrentText(options[0])
            combo.blockSignals(False)

    def refresh_colormap_choices(self) -> None:
        """Public entry point (MainWindow calls this after the Colormap
        Designer / Manager changes the available maps)."""
        self._refresh_all_reactive_choices()

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

        # colormap combos are SwatchComboBox -- the delegate renders the
        # gradient from the item text, no per-item icons needed.

    @staticmethod
    def _decorate_combo(combo: QComboBox, kind: str) -> None:
        """Give each row of ``combo`` a rendered preview of its value.

        ``kind`` is a :mod:`ui.swatches` swatch kind ("colormap" /
        "marker" / "linestyle" / "hatch" / "shapemap" / "color"). The
        icon shows on the row *and* on the collapsed combo. Safe to
        re-run after the combo is repopulated.
        """
        from ruyso_app.ui import swatches

        combo.setIconSize(swatches.icon_size(kind))
        for i in range(combo.count()):
            combo.setItemIcon(i, swatches.icon_for(kind, combo.itemText(i)))

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

        if spec.column_map is not None:
            return self._build_column_map_widget(node, spec)

        if spec.reactive_choice is not None:
            return self._build_reactive_choice_widget(node, spec)

        if spec.colormap_kind is not None:
            return self._build_colormap_field_widget(node, spec)

        if spec.column_dtypes is not None:
            return self._build_column_widget(node, spec, current)

        if spec.color_choices is not None:
            return self._build_color_widget(node, spec, current)

        if spec.suggestions is not None:
            return self._build_suggestions_widget(node, spec, current)

        if spec.unit_interval is not None:
            return self._build_slider_widget(node, spec, current)

        if spec.is_code:
            return self._build_code_widget(node, spec, current)

        if spec.is_optimize_bounds:
            return self._build_optimize_bounds_widget(node, spec)

        if spec.widget == enum.QCOMBO_BOX:
            is_colormap = name == "colormap"
            combo = SwatchComboBox() if is_colormap else QComboBox()
            combo.addItems(spec.choices or [])
            if current is not None:
                combo.setCurrentText(str(current))
            combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))
            swatch_kind = _SWATCH_FIELDS.get(name)
            if swatch_kind:
                self._decorate_combo(combo, swatch_kind)
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
            spin.setDecimals(_decimals_for(spec.default, current))
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

    # -- bounded-float slider ----------------------------------------

    def _build_slider_widget(self, node: BaseNode, spec, current) -> QWidget:
        """
        A horizontal slider over ``[lo, hi]`` (``core.params.unit_interval_field``)
        plus a small read-out label. Replaces the free-text spin box for
        ratio / fraction parameters.
        """
        name = spec.name
        lo = float(spec.unit_interval["lo"])
        hi = float(spec.unit_interval["hi"])
        step = float(spec.unit_interval["step"]) or 0.01
        steps = max(int(round((hi - lo) / step)), 1)
        decimals = max(len(f"{step:.10f}".rstrip("0").split(".")[-1]), 1)

        def to_slider(value: float) -> int:
            return int(round((max(lo, min(hi, value)) - lo) / step))

        def to_value(pos: int) -> float:
            return round(lo + pos * step, decimals)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, steps)
        slider.setValue(to_slider(float(current if current is not None else lo)))

        readout = QLabel(f"{to_value(slider.value()):.{decimals}f}")
        readout.setMinimumWidth(44)
        readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def _on_change(pos: int) -> None:
            value = to_value(pos)
            readout.setText(f"{value:.{decimals}f}")
            node.set_property(name, value)

        slider.valueChanged.connect(_on_change)

        row = QWidget()
        layout = QHBoxLayout(row)
        # A little vertical room: the styled handle overhangs the groove
        # (QSS ``margin: -6px``) and QSlider.sizeHint() doesn't account
        # for it, so without this the handle's top is clipped in the form.
        layout.setContentsMargins(0, 4, 0, 4)
        layout.addWidget(slider, 1, Qt.AlignVCenter)
        layout.addWidget(readout, 0, Qt.AlignVCenter)
        row.setMinimumHeight(28)
        row._slider = slider  # noqa: SLF001 - for controller wiring / tests
        return row

    # -- Python-source fields ------------------------------------------

    #: Names bound alongside ``df`` in a ``custom_operation`` node's code
    #: (kept in sync with ``nodes.transforms._CUSTOM_OPERATION_GLOBALS``
    #: purely for this hint -- the node itself is the source of truth).
    _CODE_HINT_GLOBALS = "pd, np, exp, log, log2, log10, sqrt, sin, cos, tan, floor, ceil, pi, e"

    def _build_code_widget(self, node: BaseNode, spec, current) -> QWidget:
        """
        A multi-line, monospace Python source editor
        (``core.params.code_field``) plus a read-only hint of the input
        DataFrame's column names, so writing an expression against the
        data doesn't require leaving the panel. Edits are batched like
        the tickbox lists -- the auto-run waits for focus-out.
        """
        name = spec.name
        container = QWidget()
        box = QVBoxLayout(container)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)

        editor = QPlainTextEdit("" if current is None else str(current))
        editor.setTabChangesFocus(True)
        editor.setMinimumHeight(110)
        editor.setPlaceholderText("df['b'] = df['a'] * 2")
        mono = QFont("Menlo")
        mono.setStyleHint(QFont.Monospace)
        mono.setFamilies(["Menlo", "Consolas", "monospace"])
        editor.setFont(mono)

        hint = QLabel()
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")

        def refresh_hint() -> None:
            columns = sorted(self._input_columns or {})
            cols_text = ", ".join(columns) if columns else "(run the pipeline to list columns)"
            hint.setText(f"columns: {cols_text}\nalso available: {self._CODE_HINT_GLOBALS}")

        def commit() -> None:
            self._write_batched(node, name, editor.toPlainText())

        editor.textChanged.connect(commit)

        box.addWidget(editor)
        box.addWidget(hint)
        refresh_hint()
        self._code_hints[name] = refresh_hint
        return container

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
        self._decorate_combo(combo, "color")  # swatch on each suggested colour

        # A live swatch of the current colour (updates as the user types
        # or picks); an unparseable value shows nothing.
        from ruyso_app.ui import swatches

        preview = QLabel()
        preview.setFixedWidth(18)
        preview.setAlignment(Qt.AlignCenter)

        def _refresh_preview(text: str) -> None:
            preview.setPixmap(swatches.color_pixmap(text))

        _refresh_preview(combo.currentText())
        combo.currentTextChanged.connect(_refresh_preview)

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
        row_layout.addWidget(preview, 0)
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
        options = spec.reactive_choice["options"]
        combo = SwatchComboBox() if options == "colormaps" else QComboBox()
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))
        self._reactive_choices[name] = (
            combo,
            options,
            spec.reactive_choice["depends_on"],
        )
        return combo

    def _build_colormap_field_widget(self, node: BaseNode, spec) -> QWidget:
        """A fixed-kind colormap dropdown (``core.params.colormap_field``)
        -- a full-width gradient ``SwatchComboBox`` populated from the
        user's continuous / qualitative list."""
        from ruyso_app.ui.column_ops import colormap_choices

        name = spec.name
        kind = spec.colormap_kind
        combo = SwatchComboBox()
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        options = colormap_choices(kind)
        combo.addItems(options)
        current = node.get_property(name)
        if current is not None and str(current) in options:
            combo.setCurrentText(str(current))
        elif options:
            combo.setCurrentText(options[0])
        combo.currentTextChanged.connect(lambda v, n=name: node.set_property(n, v))
        self._colormap_fields[name] = (combo, kind)
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

    def _build_column_map_widget(self, node: BaseNode, spec) -> QWidget:
        """
        A scrollable table: each fixed key in ``spec.column_map["keys"]``
        faces a dropdown of the input DataFrame's columns (blank =
        unmapped). Stored as a JSON ``{key: column}`` string; refreshed
        in place when the input columns arrive.
        """
        name = spec.name
        keys: list[str] = list(spec.column_map["keys"])

        inner = QWidget()
        form = QFormLayout(inner)
        form.setContentsMargins(4, 6, 4, 6)
        form.setSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setMaximumHeight(240)
        scroll.setMinimumHeight(48)

        combos: dict[str, QComboBox] = {}

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
                key: c.currentText()
                for key, c in combos.items()
                if c.currentText() and c.currentText() != _BLANK
            }
            node.set_property(name, json.dumps(mapping, ensure_ascii=False))

        def repopulate() -> None:
            columns = sorted(self._input_columns or {})
            current = stored_map()
            if not combos:  # first build
                for key in keys:
                    combo = QComboBox()
                    combo.currentTextChanged.connect(lambda _t: commit())
                    combos[key] = combo
                    form.addRow(key, combo)
            for key, combo in combos.items():
                combo.blockSignals(True)
                kept = current.get(key, combo.currentText())
                combo.clear()
                combo.addItems([_BLANK, *columns])
                combo.setCurrentText(kept if kept in columns else _BLANK)
                combo.blockSignals(False)

        repopulate()
        self._column_maps[name] = repopulate
        return scroll

    #: Fields of a fit node's own params schema that belong to the
    #: "optimize" section itself (not a hyperparameter someone would
    #: search over), so they never appear as a row in the bounds table.
    _OPTIMIZE_META_FIELDS = frozenset(
        {"optimize", "optimize_bounds", "optimize_metric", "optimize_method", "optimize_n_trials"}
    )

    def _build_optimize_bounds_widget(self, node: BaseNode, spec) -> QWidget:
        """
        A fit node's "optimize" section parameter table
        (``core.params.optimize_bounds_field``): one row per *numeric*
        field of the node's own params schema (excluding the optimize
        fields themselves and ``random_state``), each a checkbox
        (include it in the search) plus a lo/hi bound pair. Stored as
        JSON ``{param: [lo, hi]}`` for the checked rows only.
        """
        name = spec.name
        core_cls = type(node).CORE_NODE_CLASS
        param_names = [
            field_name
            for field_name, info in core_cls.params_schema.model_fields.items()
            if info.annotation in (int, float)
            and field_name not in self._OPTIMIZE_META_FIELDS
            and field_name != "random_state"
        ]

        # No inner QScrollArea here (unlike the tickbox / category-map
        # tables): the row count is bounded by the node's own numeric
        # params (a handful), so the table is shown in full and the user
        # scrolls the outer Options panel rather than a nested box.
        inner = QWidget()
        form = QFormLayout(inner)
        form.setContentsMargins(4, 6, 4, 6)
        form.setSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        if not param_names:
            empty = QLabel("no numeric parameters to optimize")
            empty.setStyleSheet("color: gray; font-size: 11px;")
            form.addRow(empty)
            return inner

        def stored_map() -> dict[str, list]:
            try:
                data = json.loads(node.get_property(name) or "{}")
            except (ValueError, TypeError):
                return {}
            return data if isinstance(data, dict) else {}

        rows: dict[str, tuple[QCheckBox, QDoubleSpinBox, QDoubleSpinBox]] = {}

        def commit() -> None:
            mapping = {
                pname: [lo.value(), hi.value()]
                for pname, (box, lo, hi) in rows.items()
                if box.isChecked()
            }
            self._write_batched(node, name, json.dumps(mapping, ensure_ascii=False))

        current = stored_map()
        for pname in param_names:
            box = QCheckBox()
            lo = QDoubleSpinBox()
            hi = QDoubleSpinBox()
            bounds = current.get(pname)
            spin_decimals = _decimals_for(
                node.get_property(pname), *(bounds or ())
            )
            for spin in (lo, hi):
                spin.setRange(-1_000_000_000, 1_000_000_000)
                spin.setDecimals(spin_decimals)

            if bounds and len(bounds) == 2:
                box.setChecked(True)
                lo.setValue(float(bounds[0]))
                hi.setValue(float(bounds[1]))
            else:
                try:
                    seed = float(node.get_property(pname))
                except (TypeError, ValueError):
                    seed = 0.0
                lo.setValue(seed)
                hi.setValue(seed)
            lo.setEnabled(box.isChecked())
            hi.setEnabled(box.isChecked())

            def _on_toggled(checked: bool, _lo=lo, _hi=hi) -> None:
                _lo.setEnabled(checked)
                _hi.setEnabled(checked)
                commit()

            box.toggled.connect(_on_toggled)
            lo.valueChanged.connect(lambda _v: commit())
            hi.valueChanged.connect(lambda _v: commit())

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(box)
            row_layout.addWidget(lo)
            row_layout.addWidget(QLabel("to"))
            row_layout.addWidget(hi)
            rows[pname] = (box, lo, hi)
            form.addRow(pname, row)

        return inner

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
