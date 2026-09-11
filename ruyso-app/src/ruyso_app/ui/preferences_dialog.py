"""
The Preferences dialog: a category list beside a stack of pages.

Every control is declared as a :class:`Field` naming the setting it
edits, so a page is a list of rows rather than a pile of hand-wired
widgets, and adding a preference is one line here plus one in
``engine.settings.DEFAULTS``.

Changes are **staged**: editing a control writes into a pending dict,
and only OK or Apply commits it to the store and tells the window to
re-read. Cancel drops the lot. That costs a staging layer the two
colormap dialogs do not have, but a preference is easier to set by
accident than a colormap is, and several of them (font size, accent,
grid) change how the whole app looks the instant they land.

Two pages are unusual and are built by hand rather than from fields:
Cache, which shows live disk usage measured off the GUI thread, and
Advanced, which is mostly buttons.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ruyso_app.core import toolboxes
from ruyso_app.engine import cache as engine_cache
from ruyso_app.engine import settings


@dataclass(frozen=True)
class Field:
    """One row of a page: a label, a setting, and how to edit it."""

    setting: str
    label: str
    kind: str  # bool | int | float | text | choice | colour | folder | font
    #: For ``choice``: the values offered, or ``(value, label)`` pairs.
    choices: tuple = ()
    #: For the numeric kinds.
    minimum: float = 0.0
    maximum: float = 1_000_000.0
    step: float = 1.0
    decimals: int = 2
    #: Shown greyed inside an empty text box.
    placeholder: str = ""
    hint: str = ""


@dataclass(frozen=True)
class Page:
    """One entry in the category list."""

    key: str
    title: str
    fields: tuple[Field, ...] = ()
    note: str = ""
    #: Built by hand instead of from ``fields``.
    builder: Callable[["PreferencesDialog"], QWidget] | None = dc_field(default=None)


_THEMES = (("system", "Follow the system"), ("dark", "Dark"), ("light", "Light"))
_GRIDS = (("none", "None"), ("dots", "Dots"), ("lines", "Lines"))
_PAGE_SIZES = (("content", "Fit the content"), ("a4", "A4"), ("letter", "Letter"))
_FIG_FORMATS = ("png", "jpeg", "pdf", "svg", "tiff", "webp", "eps")
_TABLE_FORMATS = ("csv", "tsv", "xlsx", "parquet", "feather", "json")
_MPL_STYLES = (
    "seaborn-v0_8-whitegrid", "seaborn-v0_8-white", "seaborn-v0_8-darkgrid",
    "ggplot", "bmh", "fivethirtyeight", "classic", "default",
)

#: "Leave each node's own default alone" -- see engine.settings.DEFAULTS.
_UNSET_HINT = "0 = leave each node's own default alone"


PAGES: tuple[Page, ...] = (
    Page(
        "general",
        "General",
        (
            Field("general.restore_window", "Restore window size and position", "bool"),
            Field("general.restore_last_pipeline", "Reopen the last pipeline on launch", "bool"),
            Field("general.confirm_on_close", "Ask before discarding unsaved changes", "bool"),
            Field("general.default_folder", "Default folder", "folder",
                  placeholder="wherever the system last used"),
        ),
    ),
    Page(
        "appearance",
        "Appearance",
        (
            Field("appearance.theme", "Theme", "choice", choices=_THEMES),
            Field("appearance.accent_color", "Accent colour", "colour",
                  hint="blank = the theme's own accent"),
            Field("appearance.font_size", "Interface font size", "int",
                  minimum=0, maximum=24, hint="0 = the system default"),
            Field("appearance.canvas_grid", "Canvas grid", "choice", choices=_GRIDS),
            Field("appearance.grid_size", "Grid spacing", "int", minimum=2, maximum=200),
            Field("appearance.snap_to_grid", "Snap nodes to the grid", "bool"),
            Field("appearance.node_thumbnails", "Show figure previews on nodes", "bool"),
            Field("appearance.thumbnail_width", "Preview size", "int",
                  minimum=60, maximum=600),
            Field("appearance.show_run_log", "Show the run log panel", "bool"),
        ),
    ),
    Page(
        "execution",
        "Execution",
        (
            Field("execution.auto_run", "Run automatically as the pipeline changes", "bool"),
            Field("execution.debounce_ms", "Wait after an edit", "int",
                  minimum=50, maximum=10_000, step=50, hint="milliseconds"),
            Field("execution.render_figures_in_autorun", "Re-render figures during auto-run", "bool"),
            Field("execution.stop_on_first_error", "Stop at the first error", "bool"),
        ),
        note="Pressing Run always executes every node, whatever is cached.",
    ),
    Page("toolbox", "Toolbox", builder=lambda dialog: dialog._build_toolbox_page()),
    Page("cache", "Cache", builder=lambda dialog: dialog._build_cache_page()),
    Page(
        "charts",
        "Chart defaults",
        (
            Field("charts.fig_width", "Figure width", "float",
                  minimum=0.0, maximum=40.0, step=0.5, decimals=1, hint=_UNSET_HINT),
            Field("charts.fig_height", "Figure height", "float",
                  minimum=0.0, maximum=40.0, step=0.5, decimals=1, hint=_UNSET_HINT),
            Field("charts.dpi", "Figure resolution", "int",
                  minimum=0, maximum=600, step=10, hint="0 = matplotlib's own"),
            Field("charts.continuous_colormap", "Continuous colormap", "text",
                  placeholder="each node's own"),
            Field("charts.categorical_colormap", "Categorical colormap", "text",
                  placeholder="each node's own"),
            Field("charts.style", "Plot style", "choice", choices=_MPL_STYLES),
            Field("charts.font_family", "Plot font", "font", hint="blank = matplotlib's own"),
        ),
        note="These seed newly created nodes. Existing nodes and saved "
             "pipelines keep the values they already have.",
    ),
    Page(
        "export",
        "Export",
        (
            Field("export.figure_format", "Figure format", "choice", choices=_FIG_FORMATS),
            Field("export.figure_dpi", "Figure resolution", "int",
                  minimum=36, maximum=1200, step=10),
            Field("export.transparent", "Transparent background", "bool"),
            Field("export.bbox_tight", "Trim whitespace around the figure", "bool"),
            Field("export.table_format", "Table format", "choice", choices=_TABLE_FORMATS),
            Field("export.folder", "Default export folder", "folder",
                  placeholder="alongside the pipeline"),
        ),
    ),
    Page(
        "dashboard",
        "Dashboard",
        (
            Field("dashboard.show_grid", "Show the alignment grid", "bool"),
            Field("dashboard.snap", "Snap blocks to the grid", "bool"),
            Field("dashboard.grid_size", "Grid spacing", "int", minimum=2, maximum=200),
            Field("dashboard.page_size", "Exported page size", "choice", choices=_PAGE_SIZES),
            Field("dashboard.export_dpi", "Export resolution", "int",
                  minimum=36, maximum=1200, step=10),
            Field("dashboard.title_font", "Title font", "font"),
            Field("dashboard.text_font", "Text font", "font"),
        ),
    ),
    Page(
        "data",
        "Data",
        (
            Field("data.max_preview_rows", "Rows to show in the Table tab", "int",
                  minimum=100, maximum=1_000_000, step=500),
            Field("data.float_precision", "Decimal places", "int", minimum=0, maximum=12),
            Field("data.missing_display", "Show missing values as", "text",
                  placeholder="(empty)"),
            Field("data.csv_separator", "CSV separator", "text"),
            Field("data.csv_encoding", "CSV encoding", "text"),
            Field("data.csv_decimal", "CSV decimal point", "text"),
        ),
        note="The CSV settings seed new loader nodes.",
    ),
    Page("advanced", "Advanced", builder=lambda dialog: dialog._build_advanced_page()),
)


class _CacheSizeWorker(QThread):
    """Measures the cache directory off the GUI thread."""

    measured = Signal(int)

    def run(self) -> None:
        try:
            self.measured.emit(engine_cache.current_size_bytes())
        except Exception:  # noqa: BLE001 - a size readout must not crash the dialog
            self.measured.emit(-1)


def human_size(num_bytes: int) -> str:
    """``125 MB``. Negative means "could not tell"."""
    if num_bytes < 0:
        return "unknown"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit in ("B", "KB") else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class PreferencesDialog(QDialog):
    """Edit the application preferences. Emits :attr:`applied` on commit."""

    #: Emitted after values are written, so the window can re-read them.
    applied = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        nodes_in_use: Callable[[], dict[str, list[str]]] | None = None,
    ) -> None:
        """
        Args:
            nodes_in_use: Returns ``{node_type: [display name, ...]}``
                for what is on the canvas right now. The Toolbox page
                uses it to refuse switching off a family that is being
                used; without it, nothing is in use.
        """
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(720, 560)

        self._nodes_in_use = nodes_in_use or (lambda: {})
        #: Edited-but-not-yet-committed values, by setting key.
        self._pending: dict[str, Any] = {}
        #: Setting key -> a callable that re-reads the store into the widget.
        self._loaders: dict[str, Callable[[], None]] = {}
        self._size_worker: _CacheSizeWorker | None = None

        self._categories = QListWidget(self)
        self._categories.setFixedWidth(180)
        self._stack = QStackedWidget(self)
        for page in PAGES:
            self._categories.addItem(page.title)
            self._stack.addWidget(self._build_page(page))
        self._categories.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._categories.setCurrentRow(0)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply,
            parent=self,
        )
        self._buttons.accepted.connect(self._on_ok)
        self._buttons.rejected.connect(self.reject)
        self._buttons.button(QDialogButtonBox.Apply).clicked.connect(self.apply_changes)
        self._refresh_apply_state()

        columns = QHBoxLayout()
        columns.addWidget(self._categories)
        columns.addWidget(self._stack, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(columns, 1)
        layout.addWidget(self._buttons)

    # -- staging ---------------------------------------------------------

    def _stage(self, key: str, value: Any) -> None:
        """Record an edit without committing it."""
        if settings.get(key) == value:
            self._pending.pop(key, None)  # back to where it started
        else:
            self._pending[key] = value
        self._refresh_apply_state()

    def has_pending_changes(self) -> bool:
        return bool(self._pending)

    def _refresh_apply_state(self) -> None:
        self._buttons.button(QDialogButtonBox.Apply).setEnabled(bool(self._pending))

    def apply_changes(self) -> None:
        """Commit the staged edits and tell the window to re-read them."""
        if not self._pending:
            return
        pending, self._pending = self._pending, {}
        settings.update(pending)
        if "cache.max_gb" in pending or "cache.enabled" in pending:
            engine_cache.enforce_size_limit()
        self._refresh_apply_state()
        self.applied.emit()

    def _on_ok(self) -> None:
        self.apply_changes()
        self.accept()

    def reject(self) -> None:  # noqa: D102 - Qt override
        self._pending.clear()
        super().reject()

    def reload_all(self) -> None:
        """Re-read every widget from the store (after a reset)."""
        self._pending.clear()
        for load in self._loaders.values():
            load()
        self._refresh_apply_state()

    # -- page construction -----------------------------------------------

    def _build_page(self, page: Page) -> QWidget:
        if page.builder is not None:
            return page.builder(self)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        for spec in page.fields:
            form.addRow(spec.label, self._build_field(spec))
        layout.addLayout(form)
        if page.note:
            note = QLabel(page.note, container)
            note.setWordWrap(True)
            note.setEnabled(False)
            layout.addSpacing(8)
            layout.addWidget(note)
        layout.addStretch(1)
        return container

    def _build_field(self, spec: Field) -> QWidget:
        builder = getattr(self, f"_field_{spec.kind}")
        widget = builder(spec)
        if not spec.hint:
            return widget
        row = QWidget(self)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(widget, 1)
        hint = QLabel(spec.hint, row)
        hint.setEnabled(False)
        line.addWidget(hint)
        row.editor = widget  # for tests
        return row

    # -- one builder per field kind --------------------------------------

    def _field_bool(self, spec: Field) -> QWidget:
        box = QCheckBox(self)
        self._register(spec, lambda: box.setChecked(bool(settings.get(spec.setting))))
        box.toggled.connect(lambda value: self._stage(spec.setting, bool(value)))
        return box

    def _field_int(self, spec: Field) -> QWidget:
        spin = QSpinBox(self)
        spin.setRange(int(spec.minimum), int(spec.maximum))
        spin.setSingleStep(int(spec.step))
        self._register(spec, lambda: spin.setValue(int(settings.get(spec.setting))))
        spin.valueChanged.connect(lambda value: self._stage(spec.setting, int(value)))
        return spin

    def _field_float(self, spec: Field) -> QWidget:
        spin = QDoubleSpinBox(self)
        spin.setRange(spec.minimum, spec.maximum)
        spin.setSingleStep(spec.step)
        spin.setDecimals(spec.decimals)
        self._register(spec, lambda: spin.setValue(float(settings.get(spec.setting))))
        spin.valueChanged.connect(lambda value: self._stage(spec.setting, float(value)))
        return spin

    def _field_text(self, spec: Field) -> QWidget:
        edit = QLineEdit(self)
        edit.setPlaceholderText(spec.placeholder)
        self._register(spec, lambda: edit.setText(str(settings.get(spec.setting))))
        edit.textEdited.connect(lambda value: self._stage(spec.setting, value))
        return edit

    def _field_choice(self, spec: Field) -> QWidget:
        combo = QComboBox(self)
        for entry in spec.choices:
            value, label = entry if isinstance(entry, tuple) else (entry, entry)
            combo.addItem(label, value)

        def load() -> None:
            index = combo.findData(settings.get(spec.setting))
            combo.setCurrentIndex(index if index >= 0 else 0)

        self._register(spec, load)
        combo.currentIndexChanged.connect(
            lambda _i: self._stage(spec.setting, combo.currentData())
        )
        return combo

    def _field_font(self, spec: Field) -> QWidget:
        row = QWidget(self)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        combo = QFontComboBox(row)
        use_default = QCheckBox("Default", row)
        line.addWidget(combo, 1)
        line.addWidget(use_default)

        def load() -> None:
            value = str(settings.get(spec.setting))
            use_default.setChecked(not value)
            combo.setEnabled(bool(value))
            if value:
                combo.setCurrentFont(QFont(value))

        def push() -> None:
            self._stage(
                spec.setting,
                "" if use_default.isChecked() else combo.currentFont().family(),
            )

        self._register(spec, load)
        use_default.toggled.connect(lambda on: (combo.setEnabled(not on), push()))
        combo.currentFontChanged.connect(lambda _f: push())
        row.editor = combo
        return row

    def _field_colour(self, spec: Field) -> QWidget:
        row = QWidget(self)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(row)
        edit.setPlaceholderText("#1e88e5")
        pick = QPushButton("Choose...", row)
        clear = QPushButton("Default", row)
        line.addWidget(edit, 1)
        line.addWidget(pick)
        line.addWidget(clear)

        def choose() -> None:
            initial = QColor(edit.text().strip() or "#1e88e5")
            chosen = QColorDialog.getColor(initial, self, "Accent colour")
            if chosen.isValid():
                edit.setText(chosen.name())
                self._stage(spec.setting, chosen.name())

        self._register(spec, lambda: edit.setText(str(settings.get(spec.setting))))
        edit.textEdited.connect(lambda value: self._stage(spec.setting, value))
        pick.clicked.connect(choose)
        clear.clicked.connect(lambda: (edit.clear(), self._stage(spec.setting, "")))
        row.editor = edit
        return row

    def _field_folder(self, spec: Field) -> QWidget:
        row = QWidget(self)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(row)
        edit.setPlaceholderText(spec.placeholder)
        browse = QPushButton("Browse...", row)
        line.addWidget(edit, 1)
        line.addWidget(browse)

        def choose() -> None:
            chosen = QFileDialog.getExistingDirectory(self, spec.label, edit.text())
            if chosen:
                edit.setText(chosen)
                self._stage(spec.setting, chosen)

        self._register(spec, lambda: edit.setText(str(settings.get(spec.setting))))
        edit.textEdited.connect(lambda value: self._stage(spec.setting, value))
        browse.clicked.connect(choose)
        row.editor = edit
        return row

    def _register(self, spec: Field, load: Callable[[], None]) -> None:
        self._loaders[spec.setting] = load
        load()

    # -- the two hand-built pages ----------------------------------------

    def _build_toolbox_page(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)

        intro = QLabel(
            "Switch off the families you do not use, to keep the node "
            "menus to what you work with.",
            container,
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        counts = {k: len(v) for k, v in toolboxes.node_types_by_toolbox().items()}
        self._toolbox_boxes: dict[str, QCheckBox] = {}
        enabled = toolboxes.enabled_keys()

        for toolbox in toolboxes.all_toolboxes():
            box = QCheckBox(
                f"{toolbox.title}  ({counts.get(toolbox.key, 0)} nodes)", container
            )
            box.setChecked(toolbox.key in enabled)
            box.setToolTip(toolbox.description)
            if toolbox.essential:
                # Loading, transforming and plotting are what the app is;
                # a build without them is not a lighter version of it.
                box.setEnabled(False)
                box.setToolTip(
                    f"{toolbox.description} Always on."
                )
            else:
                box.toggled.connect(
                    lambda checked, key=toolbox.key: self._on_toolbox_toggled(key, checked)
                )
            self._toolbox_boxes[toolbox.key] = box
            layout.addWidget(box)

        self._toolbox_total = QLabel("", container)
        self._toolbox_total.setEnabled(False)
        layout.addSpacing(6)
        layout.addWidget(self._toolbox_total)

        buttons = QHBoxLayout()
        for label, keys in (
            ("Enable all", list(toolboxes.optional_keys())),
            ("Only essentials", list(toolboxes.ESSENTIAL_PRESET)),
        ):
            button = QPushButton(label, container)
            button.clicked.connect(lambda _c=False, k=keys: self._set_toolboxes(k))
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        note = QLabel(
            "Menus update as soon as you apply. Skipping the import of a "
            "switched-off family is what saves start-up time, and that "
            "takes effect the next time the app is launched.",
            container,
        )
        note.setWordWrap(True)
        note.setEnabled(False)
        layout.addSpacing(8)
        layout.addWidget(note)
        layout.addStretch(1)

        self._loaders[toolboxes.SETTING] = self._load_toolboxes
        self._refresh_toolbox_total()
        return container

    def _load_toolboxes(self) -> None:
        enabled = toolboxes.enabled_keys()
        for key, box in self._toolbox_boxes.items():
            box.blockSignals(True)
            box.setChecked(key in enabled)
            box.blockSignals(False)
        self._refresh_toolbox_total()

    def _checked_toolboxes(self) -> list[str]:
        return [
            key
            for key in toolboxes.optional_keys()
            if self._toolbox_boxes[key].isChecked()
        ]

    def _set_toolboxes(self, keys: list[str]) -> None:
        """Apply a preset, honouring the same in-use refusal."""
        blocked = self._families_in_use()
        for key in toolboxes.optional_keys():
            wanted = key in keys or key in blocked
            box = self._toolbox_boxes[key]
            box.blockSignals(True)
            box.setChecked(wanted)
            box.blockSignals(False)
        if any(key in blocked for key in toolboxes.optional_keys() if key not in keys):
            self._warn_in_use(blocked)
        self._stage_toolboxes()

    def _families_in_use(self) -> dict[str, list[str]]:
        """``{toolbox key: [node name, ...]}`` for what is on the canvas."""
        by_toolbox = toolboxes.node_types_by_toolbox()
        owner = {t: key for key, types in by_toolbox.items() for t in types}
        used: dict[str, list[str]] = {}
        for node_type, names in (self._nodes_in_use() or {}).items():
            toolbox = toolboxes.get(owner.get(node_type, ""))
            # An essential family is never switchable, so it can never be
            # the thing blocking a change.
            if toolbox is not None and not toolbox.essential:
                used.setdefault(toolbox.key, []).extend(names)
        return used

    def _on_toolbox_toggled(self, key: str, checked: bool) -> None:
        if not checked:
            in_use = self._families_in_use().get(key)
            if in_use:
                box = self._toolbox_boxes[key]
                box.blockSignals(True)
                box.setChecked(True)  # the refusal, made visible
                box.blockSignals(False)
                self._warn_in_use({key: in_use})
                return
        self._stage_toolboxes()

    def _warn_in_use(self, families: dict[str, list[str]]) -> None:
        lines = []
        for key, names in families.items():
            toolbox = toolboxes.get(key)
            shown = ", ".join(sorted(set(names))[:6])
            if len(set(names)) > 6:
                shown += f", and {len(set(names)) - 6} more"
            lines.append(f"{toolbox.title if toolbox else key}: {shown}")
        QMessageBox.information(
            self,
            "Toolbox in use",
            "This toolbox cannot be switched off while the canvas uses "
            "it.\n\n" + "\n".join(lines) + "\n\nDelete those nodes first.",
        )

    def _stage_toolboxes(self) -> None:
        self._stage(toolboxes.SETTING, self._checked_toolboxes())
        self._refresh_toolbox_total()

    def _refresh_toolbox_total(self) -> None:
        counts = {k: len(v) for k, v in toolboxes.node_types_by_toolbox().items()}
        total = sum(counts.values())
        enabled = sum(
            count
            for key, count in counts.items()
            if self._toolbox_boxes[key].isChecked()
        )
        self._toolbox_total.setText(f"{enabled} of {total} nodes enabled")

    def _build_cache_page(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        form = QFormLayout()

        enabled = self._build_field(
            Field("cache.enabled", "", "bool")
        )
        form.addRow("Cache results on disk", enabled)

        location = QLineEdit(str(engine_cache.cache_dir()), container)
        location.setReadOnly(True)
        form.addRow("Location", location)

        self._usage = QLabel("measuring...", container)
        form.addRow("Currently using", self._usage)

        max_size = self._build_field(
            Field("cache.max_gb", "", "float", minimum=0.1, maximum=200.0,
                  step=0.5, decimals=1, hint="GB")
        )
        form.addRow("Maximum size", max_size)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        trim = QPushButton("Trim to the limit now", container)
        trim.clicked.connect(self._on_trim_cache)
        clear = QPushButton("Clear cache", container)
        clear.clicked.connect(self._on_clear_cache)
        buttons.addWidget(trim)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        note = QLabel(
            "Cached results let an unchanged step be reused instead of "
            "recomputed. The limit is applied at startup and whenever you "
            "change it; clearing only costs the time to recompute.",
            container,
        )
        note.setWordWrap(True)
        note.setEnabled(False)
        layout.addSpacing(8)
        layout.addWidget(note)
        layout.addStretch(1)
        self._measure_cache()
        return container

    def _measure_cache(self) -> None:
        """Kick off a background measurement of the cache directory."""
        if self._size_worker is not None and self._size_worker.isRunning():
            return
        self._usage.setText("measuring...")
        self._size_worker = _CacheSizeWorker(self)
        self._size_worker.measured.connect(
            lambda total: self._usage.setText(human_size(total))
        )
        self._size_worker.start()

    def _on_trim_cache(self) -> None:
        engine_cache.enforce_size_limit()
        self._measure_cache()

    def _on_clear_cache(self) -> None:
        answer = QMessageBox.question(
            self,
            "Clear cache",
            "Delete every cached result? Nothing is lost except the time "
            "to compute them again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            engine_cache.clear()
            self._measure_cache()

    def _build_advanced_page(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        form = QFormLayout()
        form.addRow(
            "Verbose run log",
            self._build_field(Field("advanced.verbose_log", "", "bool")),
        )
        path = QLineEdit(str(settings.config_path().parent), container)
        path.setReadOnly(True)
        form.addRow("Settings folder", path)
        layout.addLayout(form)

        reset = QPushButton("Reset all preferences", container)
        reset.clicked.connect(self._on_reset_all)
        row = QHBoxLayout()
        row.addWidget(reset)
        row.addStretch(1)
        layout.addLayout(row)

        note = QLabel(
            "The verbose log prints each step's full result instead of a "
            "summary; useful when reading the output, slow on large tables.",
            container,
        )
        note.setWordWrap(True)
        note.setEnabled(False)
        layout.addSpacing(8)
        layout.addWidget(note)
        layout.addStretch(1)
        return container

    def _on_reset_all(self) -> None:
        answer = QMessageBox.question(
            self,
            "Reset preferences",
            "Put every preference back to its default?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        settings.reset()
        self.reload_all()
        self.applied.emit()

    # -- teardown ---------------------------------------------------------

    def _await_size_worker(self) -> None:
        """
        Never let the measuring thread outlive the dialog that owns it.

        A QThread destroyed while running is a hard Qt warning and, in
        this app, the shape of problem that has ended in a segfault
        during teardown before now.
        """
        worker = self._size_worker
        self._size_worker = None
        if worker is not None and worker.isRunning():
            worker.wait(2000)

    def done(self, result: int) -> None:  # noqa: D102 - Qt override
        self._await_size_worker()
        super().done(result)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._await_size_worker()
        super().closeEvent(event)
