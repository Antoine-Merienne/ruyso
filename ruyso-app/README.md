# ruyso-app

Visual data science pipeline builder: a node-graph desktop application
where each box defines a step (load, clean, model, visualize) of a
Python data science pipeline.

The codebase is split into three independently testable layers:

| Layer | Package | Depends on | Status |
|---|---|---|---|
| 1. Node model | `ruyso_app.core`, `ruyso_app.nodes` | pydantic (+ the libs each node uses: pandas, geopandas, mapclassify, scikit-learn, statsmodels, scipy, matplotlib, seaborn) | done |
| 2. Execution engine | `ruyso_app.engine` | Layer 1, networkx, joblib | done |
| 3. UI | `ruyso_app.ui` | Layers 1 & 2, PySide6, NodeGraphQt | done (beta) |

Layers 1 and 2 have **no dependency on any GUI toolkit**: a pipeline
can be built, validated, and executed entirely from a script or the
command line, with nothing installed beyond `pip install -e .`.

## Setup

```bash
# Core + engine only (no GUI toolkit installed):
pip install -e ".[dev]"

# Everything, including the desktop UI:
pip install -e ".[dev,ui]"
```

## Running the test suite

```bash
pytest -q
```

The `tests/ui/` suite requires the `ui` extra (PySide6 + NodeGraphQt).
It runs fully headlessly — no display server is needed, including in
CI — via the Qt "offscreen" platform plugin:

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

## Launching the desktop app

```bash
pip install -e ".[ui]"
python -m ruyso_app.ui
```

This opens a single window with a three-tab band — **Pipeline**,
**Table**, **Dashboard** — over a global menu bar. There is no
toolbar; every action is in a menu:

- **Pipeline** menu (always available, on every tab):
  - **Open Pipeline (JSON)…** / **Save Pipeline (JSON)…** — read/write
    the exact same JSON format used by the headless CLI below, so a
    pipeline built visually runs from the command line and vice versa.
    The Dashboard's layout rides along in a separate `dashboard` section
    of the same file; the CLI ignores it, and a file that has none opens
    with an empty dashboard.
  - **Export as Script (.py)…** — write the pipeline out as a
    standalone `.py` file (see below).
  - **Run Pipeline** (shortcut **F5**) — execute the canvas on a
    background thread; results land in the run log and the on-canvas
    figure previews.
- **Edit** menu (always): **Undo** (`Cmd/Ctrl+Z`) and **Redo**
  (`Cmd/Ctrl+Shift+Z`, or `Ctrl+Y`), driven by NodeGraphQt's own
  `QUndoStack` — it already records node creation, deletion, wiring and
  every `set_property`, so a parameter edit is as undoable as a deleted
  node. Two details make it usable: selecting a node is pushed with
  `push_undo=False` (`BaseNode.set_selected` would otherwise stack a
  command per node and the first few `Ctrl+Z` presses would only undo
  selections), and the resync that rebuilds the Options form hangs off
  the undo/redo *actions*, not off the stack's `indexChanged` — the
  latter fires on every ordinary edit too and would rebuild the form out
  from under the widget being typed in. Opening a pipeline clears the
  history, so an undo can never unbuild the file you just opened.
- **Node** menu (Pipeline tab): **New Node ▸ _macro type_** (chord
  shortcuts `Cmd/Ctrl+P` then `L`/`T`/`M`/`S`/`G`/`E`), and
  **Selected Node ▸** **Delete Node** (`Ctrl/Cmd+Backspace`), **Copy** /
  **Cut** / **Paste** (`Cmd/Ctrl+C`/`X`/`V`) and **Duplicate**
  (`Cmd/Ctrl+D`).
- **Dashboard** menu (Dashboard tab): **Exporter…**.
- **Colormaps** menu (always): **Colormap Designer…** builds custom
  colormaps — a *continuous* one from draggable gradient stops or a
  *qualitative* one from an ordered swatch list, seedable from any
  built-in map and reversible; **Colormap Manager…** picks which maps
  (built-in + custom) appear in the colormap dropdowns, and in what
  order, per kind. Both persist to `~/.config/ruyso/colormaps.json`
  (`engine/colormaps.py`), which the scheduler re-registers with
  matplotlib at the top of every run. (Exported scripts do not yet
  inline a custom colormap's definition — a name-only reference will
  not resolve on a machine without the same config.)
- **View ▸ Theme**: **System** (default — follows the OS light/dark
  setting, live), **Dark**, or **Light**. The whole app is forced onto
  Qt's *Fusion* style driven by a palette from `theme.py`, so every
  widget (including combos, list widgets, spin boxes, the Table-tab
  panels…) is themed consistently rather than half of them following
  the OS appearance.

**Adding a node:** right-click the canvas → **New Node ▸ _macro type_**
— the node appears **under the cursor**. (The Node menu and the
`Cmd/Ctrl+P` chords drop it in the middle of the view instead.) A node
of that macro type appears and is selected; the Options panel on the
right then shows a **macro type** and a **micro type** dropdown
(changing either recreates the node in place — its name follows the
new type; see `ui/node_editing.py`), plus its parameter form. Wire
nodes together by dragging between ports. Grapher / figure nodes carry
a small floating preview that, after a run, shows the figure; click it
to select that plot and open (or raise) its resizable window — always
at the figure's own size, and following any edit you then make in the
Options panel.

**Canvas navigation** (`ui/canvas_nav.py`): two-finger trackpad drag
**pans** (both axes, following the OS scroll direction); **pinch**
**zooms**; **Cmd/Ctrl + wheel** zooms for a mouse. Pan by click with a
middle-button drag, or hold **Space** and left-drag. Left-drag
rubber-band select and right-click "New Node" are unchanged.

**Automatic background runs:** whenever you set a data file, wire up a
node, or edit a parameter, the app runs whatever part of the pipeline
is ready, on a background thread (`ui/auto_run.py`,
`PipelineScheduler.run_available`). Data files load without pressing
Run, so column pickers and previews populate on their own; unfinished
or broken branches are skipped silently (no error dialog). An explicit
**Run Pipeline** still runs everything and reports errors.

**Run controls:** the right of the tab band holds a **Run Pipeline**
button, a slim progress bar, and a percentage. During a run the bar
fills node-by-node with the percent to its right; it settles solid
**green** on success or **red** on failure and stays there until the
next run. The button is disabled while a run is in progress.

**Parameter form niceties:** file-path fields get a **Browse…** button
(open dialog for loaders, save dialog for exporters). Column-name
fields (marked with `core.params.column_field`) become a single
editable dropdown of the input DataFrame's columns — the same widget
for every node. For a multi-column field (e.g. `scaler.columns`,
`drop_na.columns`), picking an item from the dropdown toggles it in or
out of the comma-separated value; you can still type any name. A
warning appears below the field if a name isn't a column, or if that
column's type isn't accepted by the parameter. Acceptable types are
declared per field on the node (e.g. `scaler.columns` needs
numeric; `matplotlib_plot.x/y` accept anything).

To change how the app looks (colors, node macro-type colors, window
stylesheet, fonts), edit `src/ruyso_app/ui/theme.py` — it is the only
file that needs touching for purely visual changes.

**Popups — dropdowns and menus — need one thing QSS cannot express.**
A widget that paints an opaque window covers up its own
`border-radius`, so a rounded rule produced square corners. A
`QComboBox` popup is two nested widgets — a `QComboBoxPrivateContainer`
(a plain top-level `QFrame`) wrapping the list view — and QSS reaches
only the view, so a rounded list sat inside a square, usually wider,
frame; a `QMenu` is one widget with the same problem.
`theme.install_combo_popup_styler()` installs one application-wide event
filter that makes each of them frameless and translucent the first time
it is polished, leaving just the rounded card. It hooks `Polish`
rather than `Show` on purpose: `setWindowFlags` hides an already-visible
widget, so restyling on show would close the popup as it opened.

The same filter **clears a menu's own stylesheet**. NodeGraphQt's
`BaseMenu` sets a hard-coded dark one in its constructor, and a
widget-local stylesheet beats the application's — which is why the
canvas "New Node" menu used to look nothing like the rest of the app.

A popup — a dropdown list or a menu, they are the same kind of floating
card — is painted in `Theme.popup_background`: **white** in the light
theme, one step brighter than the panel it opened from, and the panel
colour in the dark theme, which has nowhere brighter to go. Rows take a
rounded overlay on hover rather than an edge-to-edge highlight
(`show-decoration-selected: 0`).

That filter also gives each dropdown **`ui/popup_delegate.py`**. Qt
draws combo rows with a private delegate that hands the *combo box* to
the style as the widget being painted, so under a stylesheet every row
resolved against the `QComboBox` rule and came out wearing the closed
combo's own bordered box — the white rectangle that appeared over the
list. A plain `QStyledItemDelegate` draws them as view items. It has to
draw **separators** itself (Qt marks them in
`AccessibleDescriptionRole` and leaves them to that combo delegate),
with a size hint small enough that the stylesheet's item `min-height`
cannot inflate one into a blank row. A combo that already has a
delegate of its own — the colormap and marker swatches — keeps it.

**Panes are divided by a grip, not a band.** A `QSplitter` handle paints
nothing but three dots (`assets/grip-*.svg`, a true mid-grey that reads
on both themes — a border-coloured line was invisible on the light one),
so the Log/Problems strip butts straight against the canvas and the drag
target sits on the strip's own top edge. The Table tab's description
panel scrolls, and a splitter cannot divide something that scrolls, so
its two variable tables get the same affordance from
`ui/height_grip.py`. That grip is a **cap, not a height**: a table stays
exactly as tall as its rows, and the grip only appears once there are
more rows than fit, deciding how much of the panel that table takes
before it scrolls inside itself (double-click resets it). Resizing
happens only while a drag is in progress — acting on every mouse-move
sent the table to an arbitrary height as the pointer crossed the grip,
because a hover move carries no press to measure against. The height is
set in one place for the same reason the first attempt broke: the panel
setting a fixed height while `_fill_stat_table` set a maximum left
`min > max`, and Qt's layout then stacked the sections over each other
— which is what put the second table far below its own title. The canvas itself is frameless — NodeGraphQt
wraps the viewer in a `QTabWidget` whose constructor paints its own
near-black background, which showed as a black band around the canvas on
the light theme; `PipelineCanvas.widget` clears that stylesheet on the
way out (doing it in `__init__` builds the wrapper for canvases nobody
shows, which reintroduces the exit-139 teardown crash in the tests).

**The canvas grid** is small round dots 25 scene units apart
(`ui/canvas_grid.py`), replacing NodeGraphQt's 5-px hard squares 50
units apart. It is a monkey-patch of `NodeScene._draw_dots`: the scene
is built inside NodeGraphQt's viewer with no hook to substitute a
class, and swapping the scene afterwards would orphan the live-pipe
items already parented to it. The dot colour is derived from the canvas
background, so the grid stays a hint in both themes rather than the
fixed near-black NodeGraphQt ships.

### UI restructure — status and decisions

The UI is being reworked to match the `ruyso_ui_principles` mockups in
phases. Decisions taken so far (spec section 8):

- **Macro types & palette.** The six macro types are `loading`,
  `transform`, `model`, `statistics`, `grapher`, `export` (`viz` was
  split into `grapher` + `statistics`). Each maps to one Matplotlib
  *tab10* color, identical in both themes so a node stays recognizable
  across a theme toggle; the map is in `theme._MACRO_TYPE_COLORS`.
  Every macro type now has at least one concrete node (a macro type
  with none would show its "New Node" entry **disabled** rather than
  omitted or crashing).
- **Palette hex values.** Dark and light chrome palettes are the
  `DARK_THEME` / `LIGHT_THEME` dataclasses in `theme.py` (window,
  panel, text, border, accent, canvas-background values).
- **Options panel background.** A lightened, ~92%-opaque tint of the
  selected node's macro-type color (`theme.options_panel_background`),
  falling back to an opaque panel color when nothing is selected.
- **How a node is drawn** (`ui/node_item.py`, a `NodeItem` subclass
  handed to every generated class as its `qgraphics_item`). NodeGraphQt
  fills the whole node with its colour; here the body is the **theme's
  panel colour** in both themes, so a node is a card like every other
  surface, and the **macro-type colour is a thick contour** (2.0 units,
  3.2 selected) plus the **name bar, which fills with it only while the
  node is selected**. That fill is the text item's own box, so it stops
  right below the name rather than at the port row NodeGraphQt measures
  to. Unselected, the name bar is just the top of the card — no divider,
  no tint — so the fill is unmistakable. Corners are 12, a little
  rounder than the 8 the QSS uses, which a node at this size carries
  well. The name and the port labels take the theme's text
  colour; the name flips to whatever reads on the macro colour while
  selected (`node_item.readable_on` — white on the blue loader,
  near-black on the orange transform), which is why
  `_set_text_color` is overridden rather than called once: NodeGraphQt
  re-applies its own white-on-dark default from `draw_node`.
- **Fonts.** `Helvetica, Arial, sans-serif` everywhere except the run
  console and any library/class name, which use
  `Consolas, Menlo, 'Courier New', monospace`.
- **Node creation is right-click**, not a left-click popup: the empty
  canvas shows a centered `+` and "Right-click to add a node".
- **Micro-type change after creation = recreate.** Node classes are
  fully typed at instantiation (ports/params differ per micro type),
  so changing the Options dropdown deletes the node and builds a new
  one in place, keeping its name, position, every still-valid wire,
  and any parameter whose field name is shared. See
  `ui/node_editing.py`.
- **On-canvas figure preview** is a floating thumbnail parented to the
  viewport and re-synced to its node on a light timer (Qt paints child
  widgets over the `QGraphicsScene`, so a true "behind the node" is not
  possible — it sits attached just beneath). See `ui/node_preview.py`.
  The old bottom "Figure Preview" pane is gone. Clicking a thumbnail:
  - **selects its plot node**, so the Options panel shows that figure's
    parameters while you look at it. The click is *accepted*: letting it
    fall through (`QWidget.mousePressEvent` ignores the event) reached
    the NodeGraphQt viewport, which read it as a click on empty canvas
    and cleared the selection — opening a figure used to blank its own
    options.
  - **raises one `FigureWindow` per node**, hidden on close and reused,
    rather than stacking a new window per click.
  - opens it at a **stable size**: the figure's own `fig_width` ×
    `fig_height` at a fixed 100 dpi, memoised on the figure and clamped
    to 90 % of the screen. It must not read `figure.get_dpi()`: attaching
    a `FigureCanvasQTAgg` rewrites the figure's dpi to
    `devicePixelRatio × dpi`, and the ratio is only 2.0 once the widget
    is on a Retina screen — so the same plot opened at 650×450, then at
    1300×900 ever after. (Not reproducible offscreen, where the ratio is
    always 1.0; the test applies the mutation by hand.)
  - an already-open window **follows re-renders**, so editing the plot's
    params updates the big figure live.
- **Panels are resizable** via splitter handles: canvas ↔ run log,
  canvas ↔ Options panel (Pipeline and Dashboard tabs), navigator ↔
  data grid (Table tab).
- **Path parameters get a Browse… button** (loaders open, exporters
  save; filters in `ui/file_filters.py`) and a full-width text field.
- **Table tab navigator is a flat list, not a node diagram.** Steps
  appear in execution order; a step with several output tables (e.g.
  `train_test_split`) lists each one (`step / port`). Entries are
  greyed out until the pipeline has been run and produced that table.
  Selecting one fills the **Table description** panel and shows the
  data in a grid with mouse-resizable columns. The description has a
  scalar summary (kind of table — plain / geo / time-indexed /
  geo+time — row count, variable count, missing/empty-value count)
  plus two tables: **numeric variables** (`variable | type | mean |
  std. dev | min | max`; datetime columns included here) and **string
  / categorical variables** (`variable | type | # distinct values`;
  bool columns included here). See `ui/table_description.py`.
- **The Table tab keeps showing the last successful run.** Editing the
  pipeline afterwards does not blank the tables; instead a step whose
  type, parameters or wiring changed since that run — or anything
  downstream of such a step — is tagged **· modified** (pale yellow)
  in the navigator, so a stale table is never mistaken for the current
  result. Detection lives in `ui/run_snapshot.py`; the snapshot is
  reset when a pipeline file is opened.
- **Manual axis limits.** Every grapher carries four always-visible
  edges — `x_min` / `x_max` / `y_min` / `y_max` — and no toggle. Each is
  a string, and each is independent: **blank means "fit this edge to the
  data"**, so you can pin a y-axis floor of 0 and leave the other three
  autoscaling. A number or an ISO date (`2021-03-01`, on a time axis) is
  accepted, parsed by `nodes/viz.py::_limit_value`. After a run the
  Options panel fills each empty box with the limit the plot actually
  used (`ui/node_preview.py::figure_axis_limits`), so the fields read as
  "here is your axis, adjust it" rather than starting at a meaningless
  `0.0`. That prefill is display-only — the parameter stays blank until
  someone types in the box, which is what keeps an untouched axis
  following the data; clearing a box returns that edge to autoscale.
- **Datetime display formats.** A datetime column is *always* a real
  `datetime64` column, never a formatted string — that is what keeps
  `sort` chronological, `resample_datetime` / `diff` able to do
  arithmetic, and the time-series graphers able to place points on a
  date axis. Formatting is therefore a **rendering** concern, applied at
  the edge and never to the data. `core/dtformat.py` owns the
  convention: a node that knows how its column should read (such as
  `combine_datetime` with only year + month mapped) records a
  `strftime` pattern in `DataFrame.attrs`, which pandas carries through
  copies, filters, sorts, merges and resamples, so the format survives
  the pipeline with no node forwarding it by hand. Where nothing was set
  explicitly the format is **inferred**: the coarsest ISO pattern that
  loses nothing, so a column of whole days renders `2020-02-01` rather
  than dragging a meaningless `2020-02-01 00:00:00` across every row.
  Two places honour it — the Table tab's cell renderer
  (`ui/dataframe_model.py`) and a time-series plot's x-axis ticks
  (`nodes/viz.py::_apply_time_ticks`). The axis takes only an
  *explicitly set* format, since an inferred one would override
  matplotlib's `ConciseDateFormatter`, which reads better on an
  automatic axis.
- **Data-loader family.** The `loading` macro type has one micro type
  per file format: `csv_loader`, `fixed_width_loader`, `excel_loader`,
  `json_loader`, `parquet_loader`, `feather_loader`, `stata_loader`
  (all -> `dataframe`), plus `geojson_loader`, `shapefile_loader`,
  `geopackage_loader`, `geoparquet_loader`, `geofeather_loader`
  (-> `geodataframe`; the geo Parquet / Feather loaders use
  `geopandas.read_parquet` / `read_feather`, which decode the WKB
  geometry column and the file's CRS metadata — the plain
  `parquet_loader` / `feather_loader` cannot). `csv_loader` also carries
  `encoding` and `decimal`, seeded from Preferences ▸ Data — a European
  CSV is `;`-separated with `,` as the decimal point, and setting that
  once beats setting it per node. Loaders otherwise leave
  dtypes alone, with one opt-in exception: the four text formats
  (`csv_loader`, `fixed_width_loader`, `excel_loader`, `json_loader`)
  offer **`parse_dates`** (default off) plus `datetime_columns`
  (comma-separated; blank = auto-detect) and a `datetime_format`. It
  exists because a date left as text sorts *lexically* for the rest of
  the pipeline — `01/02/2020` before `15/07/2019` — and converting at
  the source is the cheapest place to prevent that. Auto-detection is
  deliberately conservative: a column is only converted when every
  sampled value carries a date separator and a 4-digit year *and* ≥95 %
  of them parse, so version strings (`1.2.3`) and padded IDs are left
  alone. The binary formats already carry real dtypes and have no such
  option. You can still convert downstream instead with the
  `change_type` transform (target `datetime`, with an optional
  `strptime` format) or build one from parts with `combine_datetime`.
  A `geodataframe` output may be wired into any node that expects a
  plain `dataframe` (a GeoDataFrame is one); the reverse is rejected by
  `PipelineGraph.validate()`. Alongside the file loaders,
  **`example_data`** loads a bundled dataset with no file and no link —
  a `dataset` dropdown of `sklearn/…` toy sets (iris, wine, …),
  `statsmodels/…` datasets (longley, macrodata, sunspots, …) and
  `seaborn/…` datasets (tips, penguins, …). Every `seaborn/…` dataset is
  pre-seeded as a CSV under `nodes/data/seaborn/` and passed to seaborn
  as its cache dir (`data_home`), so loading one never touches the
  network. The Micro type dropdown groups `loading`'s entries with a
  separator line between general file loaders, geo-border formats, and
  the example loader (`ui.micro_type_groups`).
- **Transformer family.** `scaler` (StandardScaler / MinMaxScaler /
  MaxAbsScaler via a `method` dropdown — `with_mean`/`with_std` for
  standard, `feature_range_min`/`feature_range_max` for minmax, no
  extra options for maxabs); `drop_na` and `fill_na`
  (pick columns via a **tickbox list**; `drop_na` chooses `how` =
  any/all, `fill_na` a method — forward/backward fill, mean, median,
  most frequent, zero, or a constant value that reveals a value box;
  an empty tick list is a pass-through, and mean/median on a
  non-numeric column raises); `change_type` (cast one column; the
  target-type dropdown re-filters to the casts that make sense for the
  chosen column; casting to `datetime` reveals a `datetime_format`
  suggestions box — a `strptime` pattern, blank = infer); `column_filter` and `dtype_filter` (keep columns via
  a tickbox list); `row_filter` (a mode-aware form: filter by row
  position *or* by a column value — the operator dropdown re-filters
  to what's valid for the column's type); `sample` (count or fraction,
  seed, with-replacement), `head`, `tail`; `sort` (tickbox sort keys +
  ascending + NA position); `reset_index` (drop, or keep as a named
  column — the name box only shows when kept); `group_by` (key columns
  + one reduction from a dropdown) and `aggregate` (columns × functions
  as tickboxes + an optional group-by set → flat `column_function`
  columns); `pivot`, `unpivot` (melt) and `pivot_table` (index /
  columns / values / functions as tickboxes, plus fill_value / margins
  / dropna / observed — `pivot` & `pivot_table` flatten any MultiIndex
  result and reset the index, like `aggregate`); `concat` (two inputs, second optional; `axis` / `join`
  dropdowns + reset-index) and `merge` (SQL-style join — two required
  inputs, key columns via tickboxes, `how` = inner/left/right/outer,
  suffixes); `bin` (group a numeric column into a new categorical
  column — `method` = equal_width / quantile / explicit; explicit takes
  **cutoff points separated by semicolons** (`10; 20; 30`), open-ended
  on both sides so *n* cutoffs make *n+1* bins; `bin_count` shown unless
  explicit; `output_type` = category / bool (2 bins only) / integer /
  string with typed `labels`); `rename_categories` (relabel a
  categorical column — the Options panel shows a table of the column's
  distinct values, each facing a "new name" box; blanks keep the old
  name, two old values mapped to one name merge; stored as a JSON map,
  `core.params.category_map_field`); `one_hot_encode` (dummy columns
  `<col>_<value>`, `drop_first` + replace-vs-keep-original) and
  `ordinal_encode` (0-based integer codes, replace or add
  `<col>_ordinal`) — both act on the ticked columns (empty = every
  object/string/category column) and are fit per-DataFrame like
  `scaler`; `train_test_split` (moved here from *model* — one
  DataFrame in; outputs in wiring order `X_train` / `y_train` /
  `X_test` / `y_test` (X's are DataFrames, y's target Series), with
  `shuffle` / `stratify`); `combine_datetime` (build a real datetime64
  column from separate component columns — a **mapping table**, one row
  per time part (year … microsecond) with a column dropdown each,
  `core.params.column_map_field`; quarter → month, year+dayofyear and
  year+ISO-week are handled; a lone text column is parsed with
  `datetime_format`; a **`display_format`** sets how the result is
  *shown* (see “Datetime display formats” below); **`last_of_period`**
  lands on the last unit of each period instead of the first — with
  year+month mapped, February 2020 becomes `2020-02-29` rather than
  `2020-02-01`, at midnight, and it is a no-op once a day-level
  component is mapped; `output_column` name + a `replace` toggle to drop
  the sources), `split_datetime` (the reverse — `mode` = `components`
  (tickbox parts → `<col>_<part>` Int64 columns) or `string`
  (`strftime` → `<col>_str`), with `replace`), and `resample_datetime`
  (pick a datetime key column + a target `rule`, one downsample
  aggregator — mean/sum/…/count/ohlc — for the numeric columns, and an
  upsample `fill` — ffill / bfill / interpolate-linear / -time /
  nearest; non-numeric columns take the first value; the key comes back
  as a column; **`last_of_period`** relabels each bin with the last unit
  of its period — with `MS`, `2020-02-29` rather than `2020-02-01` —
  moving only the label, never which rows fall in which bin, and a no-op
  for rules whose bin already is one unit like `D` / `h` / `15min`);
  `diff` (row-order difference of tickbox-selected columns — a
  comma-separated `lags` list, e.g. `1, 7, 30`, each producing one
  `<column>_diff_<lag>` via `Series.diff(periods=lag)`; `first_value`
  decides what goes in the rows a diff cannot fill — `nan` (default),
  `zero`, or `keep_original` (start from the level, then changes);
  assumes the rows are already time-ordered, e.g. via `sort`);
  `custom_operation`
  (a monospace, multi-line code box — `core.params.code_field` — runs
  the typed Python against the input DataFrame bound as `df`, with `pd`
  / `np` / common `math` functions already in scope and a read-only
  hint of the input columns underneath; a reduced builtins set blocks
  `import` / `open` / `exec` / `eval` as a light guard rail, not a
  sandbox — this is a local desktop tool); `covariance_matrix` (the
  covariance matrix of the ticked numeric columns as a wide
  `variable` × columns table; `normalize` gives the correlation matrix
  instead, `ddof` for the covariance estimate); `scaler` (see the
  Transformer-family bullet above — StandardScaler / MinMaxScaler /
  MaxAbsScaler via a `method` dropdown).

  **Geo transforms** (all `geodataframe`-typed, CRS entered through a
  suggestions dropdown): `dataframe_to_geo` / `geo_to_dataframe`
  (xy / wkt), `reproject` (transform coordinates), `set_crs` (label a
  CRS without moving coordinates); `spatial_join` (`exact` predicate
  join or `nearest`, with `max_distance` / `distance_col` and a
  `project_to` metric CRS), `spatial_filter` (keep whole features by
  predicate vs a `mask` layer or a bbox, `negate` for the complement),
  `geo_clip` (cut geometries to a mask), `geo_overlay` (polygon set
  ops: intersection / union / identity / symmetric_difference /
  difference); `geo_dissolve` (spatial `group_by` — merge geometries
  per key, one `aggfunc` for the rest), `geo_explode` (multipart →
  one row per part), `geo_buffer` (grow/shrink by a distance, with
  `cap_style` / `join_style` / `segments` / `single_sided` / `dissolve`),
  `geometry_op` (replace geometry with its centroid / representative
  point / convex or concave hull / envelope / boundary / exterior ring
  / simplified / made-valid form), `geo_measures` (append area / length
  / centroid_x·y / bounds / geom_type / num_points / is_valid columns).
  For the two-layer ops the second layer is auto-reprojected onto the
  first's CRS; `geo_buffer` / `geo_measures` / `spatial_join`-nearest
  take a `project_to` CRS with an **`auto (UTM)`** option and refuse a
  geographic CRS with no projection (so distances / areas come out in
  metres).

  The Micro type dropdown groups the whole `transform` macro type with
  separator lines — base / filters / type / reshaping / datetime /
  geo (convert · relate · derive) / custom (`ui.micro_type_groups`). The reactive behaviour is
  new Options-panel machinery: `core.params` markers
  (`reactive_choice_field`, `checkbox_list_field`, `category_map_field`,
  `column_map_field`, `visible_field` / `visible_when=` /
  `visible_when_set=` / `visible_unless=`) drive per-row visibility and
  dependent dropdowns in `ui/options_panel.py`, with option lists in
  `ui/column_ops.py`. The rename-categories table is fed by
  `column_spec.input_column_values` (distinct values of the input's
  categorical columns).
- **Model family.** Every fit node has the same shape: inputs
  `X_train` (dataframe), `y_train` (array), optional `X_test`/`y_test`
  (carried alongside, unused by a plain fit); outputs `model` — the
  fitted scikit-learn estimator object — and `optim` (see below).
  Evaluation is done downstream by `model_scores` / `residuals` / the
  model plots. Supervised: `linear_regression_fit`,
  `logistic_regression_fit`, `ridge_fit`, `lasso_fit`,
  `elastic_net_fit`, `decision_tree_fit`, `random_forest_fit`,
  `gradient_boosting_fit`, `adaboost_fit`, `svm_fit`, `knn_fit`,
  `naive_bayes_fit`. Where an algorithm exists in both flavours the
  node has a **`task`** dropdown (classifier / regressor) that selects
  the estimator class; task-specific args (`class_weight`,
  `classifier_criterion` vs `regressor_criterion`, `epsilon`, …) are
  shown only for the matching task. The parameter forms expose every
  constructor argument that maps onto an existing widget (int / float /
  bool / dropdown); `nodes/models.py` `SklearnFitNode` filters the
  chosen params against the estimator's signature and maps UI sentinels
  back (`"none"` → `None`, `0` → `None` for `max_depth` / `n_jobs` /
  `max_iter` / …). Clustering (unsupervised): `kmeans_fit`,
  `minibatch_kmeans_fit`, `dbscan_fit`, `hdbscan_fit`,
  `agglomerative_clustering_fit`, `spectral_clustering_fit`,
  `gaussian_mixture_fit` — `SklearnClusterFitNode` is shaped like a
  *transform*, not a fit: input `df` → output `df` with a `cluster`
  label column appended (`-1` = noise for DBSCAN/HDBSCAN or a row with
  missing numeric values), plus the fitted estimator on a secondary
  optional `model` port. Every numeric column is used; a shared
  `standardize` (default on) and a `cluster_column` name come from
  `ClusterParams`. The `model` port's value differs: KMeans /
  MiniBatchKMeans / GaussianMixture can `predict` new rows, the others
  are transductive (their `model` just carries `labels_`, already in
  the output `df`). The Micro type dropdown groups the whole `model`
  macro type into *utilities* (the model-consuming nodes below), then
  *supervised fits*, then *unsupervised fits* (the clustering nodes) —
  separator lines between
  each (`ui.micro_type_groups`).
  - **Optimize section.** Every supervised fit node's params also
    carry a shared `optimize` toggle (`SklearnFitParams`). Ticked, its
    section reveals `optimize_bounds` — a table of that node's own
    numeric hyperparameters, each with a checkbox and a `[lo, hi]`
    range — plus `optimize_metric`, an Optuna `optimize_method` (tpe /
    random / cmaes / grid) and `optimize_n_trials`. `X_test`/`y_test`
    become required inputs only when `optimize` is on: every trial
    refits on `X_train`/`y_train` and is scored against them, and the
    `model` output becomes the best trial's estimator. The `optim`
    output (a plain dict; `None` when `optimize` is off) carries
    `method` / `metric` / `direction` / `n_trials` / `best_value` /
    `best_params` / a per-trial `trials` DataFrame (`train_score` +
    `test_score` + the sampled values), for `optim_diagnostic` /
    `optim_scores` to read.
- **Model-consuming nodes** (`model` macro type, `nodes/model_ops.py`).
  All take a fitted `model` port; the evaluation ones also take the
  `X` (dataframe) + `y` (array) that `train_test_split` produces.
  `predict` — `df` + `model` → the df with a `prediction` column
  appended (and, for a classifier, a `probabilities` toggle adds one
  `proba_<class>` column each); features are aligned to the model's
  `feature_names_in_` when present, else positionally. `model_coeffs`
  — `model` → a tidy `feature` / value DataFrame (`coef_` +
  `intercept` row, one value column per class for multiclass; falls
  back to `feature_importances_` for trees / forests). `model_scores`
  — `model` + `X` + `y` → a `metric` / `value` DataFrame; classification
  and regression metrics (tickboxes, both always editable) with an
  `average` for multiclass precision / recall / f1. Which set is
  actually computed is detected from the model itself
  (`sklearn.base.is_classifier`), not a separate toggle — the node
  produces a sensible result with its defaults as soon as it is wired
  up, whichever kind of model that is. `residuals`
  — `model` + `X` + `y` → per-row `y_true` / `y_pred` / `residual`
  (+ `std_residual`), regression only. `optim_diagnostic` — `optim` →
  a one-row summary (method, metric, trial count, best score,
  `best_<param>` per searched parameter). `optim_scores` — `optim` →
  the per-trial `trials` DataFrame. All five DataFrame outputs are
  browsable in the Table tab automatically.
- **Model-visualization plots** (`grapher` macro type, in `nodes/viz.py`;
  input `model` + `X` + `y`, output `figure`). `confusion_matrix_plot`
  (`normalize` none/true/pred/all, colormap, annotate, colorbar);
  `roc_curve_plot`, `precision_recall_plot`, `det_curve_plot` (binary
  → one curve with the model colour + a chance line; multiclass →
  one-vs-rest, a curve per class coloured from a qualitative colormap);
  `calibration_curve_plot` (binary only — `n_bins`, `strategy`,
  reference line); `learning_curve_plot` (`cv`, `n_points`, `scoring`,
  std band or error bars — re-fits the model on growing subsets);
  `qq_plot` (normal Q-Q of a regression model's residuals). Each has
  the same axis / title / (where relevant) legend styling fields as the
  other graphers and gets the on-canvas figure preview.
- **Statistics family** (`statistics` macro type, `nodes/statistics.py`;
  input `df`, output one or more result `df`s browsable in the Table
  tab). One node per test family, each with a `test` dropdown:
  `one_sample_test` (t / Wilcoxon), `independent_samples_test`
  (t / Welch / Mann-Whitney / Kruskal / ANOVA / Brunner-Munzel /
  rank-sums / median / KS), `paired_test` (t / Wilcoxon),
  `correlation_test` (Pearson / Spearman / Kendall / point-biserial,
  with CIs), `association_test` (χ² / G-test / Fisher, + Cramér's V),
  `normality_test` (Shapiro / D'Agostino / Jarque-Bera /
  Anderson-Darling / KS), `variance_test` (Levene / Bartlett /
  Fligner), `resampling_test` (permutation mean-diff, bootstrap
  mean/median CI — scipy `permutation_test` / `bootstrap`),
  `multiple_testing` (FDR-BH/BY, Bonferroni/Holm/Šidák on a p-value
  column → adjusted p + `reject`; or Fisher/Stouffer meta-combination),
  `timeseries_test` (ADF / KPSS stationarity, Ljung-Box,
  Durbin-Watson, Granger causality — statsmodels). Plus four non-test
  tools: **`regression`** — statsmodels inference: `model` = OLS /
  Logit / Poisson-GLM / Probit / RLM, a `y_column` picker + `x_columns`
  tickbox list, `add_intercept`, robust SEs (OLS), a confidence level;
  two outputs, a `coeffs` table (term, coef, std_err, t/z, p-value, CI)
  and a `residuals` DataFrame (row, fitted, residual). **`pca`** —
  scikit-learn PCA on ticked numeric columns (blank = every numeric
  column), `n_components` (0 = keep all), `standardize`; three outputs:
  `scores` (PC1, PC2, … per row), `loadings` (each variable's weight in
  each component) and `variance` (explained + cumulative variance
  ratio per component). **`arima`** — statsmodels SARIMAX on a chosen
  `(p, d, q)` order, with an optional seasonal `(P, D, Q, s)` term
  (`seasonal` toggle + `seasonal_periods`) — this is how a seasonal
  pattern is taken out of the series, via seasonal differencing; a
  `trend` term, `forecast_periods` steps ahead with a confidence
  interval; four outputs — `fit` (order, AIC/BIC, log-likelihood),
  `forecast` (step, forecast, ci_low, ci_high), `residuals` (one-step
  residuals + fitted + standardized), and `model` (a small picklable
  forecast bundle for `forecast_plot`). **`auto_arima`** — the same
  SARIMAX forecaster and outputs, but the order is found by an in-repo
  Hyndman-Khandakar-style *stepwise* search (`nodes/statistics.py`
  `_stepwise_search`): `d` from an ADF-based rule (`_select_d`), a
  hill-climb over `(p, q)` (and `(P, Q)` when `seasonal` is on) from a
  few seed models, minimizing `information_criterion` (AIC/BIC) until
  no neighbouring order improves it — a handful of fits, not a full
  grid (`concentrate_scale`, lighter seasonal seeds and a 24-fit cap
  keep a *seasonal* search to ~15 s rather than minutes); the seasonal
  differencing order `D` is fixed at 1 when
  `seasonal` is on (0 otherwise), a simplification over a true
  seasonal unit-root test. Same four outputs as `arima`.
  **`seasonal_decompose`** — split a series into `trend` + `seasonal`
  + `resid` (+ the seasonally-adjusted series), one row per
  observation, by `method` = `stl` (LOESS-based
  `statsmodels.tsa.seasonal.STL`; `stl_seasonal` / `stl_trend`
  smoother lengths, `robust`) or `classical` (a centred moving average;
  `model` additive / multiplicative, `two_sided`, `extrapolate_trend`).
  `period` sets the season length. **`ica`** —
  scikit-learn `FastICA`, same shape as `pca` (`sources` = the
  independent components per row, `mixing` = each variable's weight in
  each source). **`tsne`** — scikit-learn `TSNE`; a nonlinear 2D/3D
  embedding, output directly as a `tsne_1, tsne_2, …` table (t-SNE has
  no `transform` for new data, so there is no reusable model).
  `pca` / `ica` / `tsne` all run on **every numeric column** of the
  input — no column picker; drop the ones you don't want upstream.
  **`var`** — statsmodels vector autoregression: `method` = `var`
  (level VAR) or `vecm` (vector error-correction for cointegrated
  series); a `datetime_column`, a tickbox list of `variables`, `lags`
  (VAR order / VECM `k_ar_diff` — the *maximum* when `optimize_lag` is
  on, which then keeps whichever order 1…`lags` minimises the chosen
  `ic`), `trend` (VAR) / `deterministic` + `coint_rank` (VECM). Four
  outputs:
  `coeffs` (one row per equation × term, with std err / p-value),
  `residuals` (per-equation), `forecast` (step × variable, with
  interval) and `model` — the fitted results object consumed by
  `var_test` and the `var_*` / `irf` grapher nodes. **`var_test`** —
  diagnostic hypothesis tests on that `model`: `granger_causality` /
  `instantaneous_causality` (with `causing` / `caused` tickboxes),
  residual `normality` (Jarque-Bera), and `whiteness` (Portmanteau /
  Ljung-Box). The Micro type dropdown groups the whole
  macro type — the tools (`regression`, `pca`, `ica`, `tsne`,
  `multiple_testing`), the time-series models (`arima`, `auto_arima`,
  `var`), then every `*_test` node alphabetically
  (`ui.micro_type_groups`). Classical tests are powered
  by scipy; time-series, regressions and ARIMA by statsmodels; PCA /
  ICA / t-SNE by scikit-learn.
- **Grapher (`matplotlib_plot`).** Draws with a local
  `seaborn-v0_8-whitegrid` style context (never global), a `darkblue`
  default colour, slightly smaller markers/lines and a top/right
  despine. **Four independent visual channels**, each a fixed value
  *plus* an optional "... by `<column>`" picker (italic-grey **None**
  row), all following the same logic:
  - **colour** — `mark_color` (common-colour dropdown, each row a
    swatch drawn by `ui/swatch_combo.SwatchItemDelegate`, + a
    *Choose...* dialog; the closed box carries exactly **one** swatch,
    on the line edit, so it tracks a typed `#rrggbb` as well as a
    picked name — item *icons* are deliberately not set, since an
    editable combo would repeat them in its own box) /
    `color_by` (+ a
    `colormap` whose options adapt: qualitative for text/category/bool,
    sequential/diverging for numeric/datetime; the list comes from
    `engine/colormaps.py` via `ui/column_ops.py` and is rendered as a
    full-width gradient with the name pinned right);
  - **shape** — `marker_shape` / `line_style` / `bar_hatch` (per `kind`)
    / `shape_by`; a *discrete* shape-by column reveals a **shape map**
    picker (`assorted` / `geometric` / `bold` / `minimal` — a named
    series of markers/linestyles/hatches, with an on-figure note past
    its length); a *continuous* one keeps the fixed shape (noted);
  - **size** — `point_size` / `line_width` (per `kind`) / `size_by`
    (+ `size_min`/`size_max` for scatter, `width_min`/`width_max` for
    lines); works for discrete (stepped) and continuous (interpolated);
  - **alpha** — `alpha` / `alpha_by` (+ `alpha_min`/`alpha_max`).

  The fixed field shows while its "by" picker is empty
  (`visible_when_unset=`); the map/range fields show once it names a
  column (`visible_when_set=` / `visible_when_kind=("shape_by", kinds)`
  for the shape/size split). Shape and size are fully independent — you
  can size-by a column while picking a fixed marker, or shape-by a
  column at a fixed size. Also: a **bar mode** (dodge / stack / layer)
  for a coloured bar chart, plus a **`bar_error`** (none / SEM / std /
  a t-based 95%/99% CI) that draws an error-bar whisker per bar — when
  it's not "none" each bar becomes a *mean* of its y values (grouped
  by x, and by the colour-by group if any) rather than a sum or one
  bar per row, so per-row shape/opacity styling no longer applies
  (noted on the figure); a **`line_fill`** (area chart) and
  **`line_stack`** (stacked area — needs a discrete colour-by column,
  drawn with `ax.stackplot`) for the line kind; axis grid / frame /
  label overrides / font size / log scales / figure size; **manual
  axis limits** (see below); title font size + bold + italic; legend show
  / title / location / font size.
  Colouring by a categorical column draws a legend in a translucent
  box; by a continuous column, a colorbar; colour-by and shape-by on
  *different* columns get two legends (same column → one combined
  legend of coloured shapes). (A row may carry any mix of
  `visible_when=`, `visible_when_set=`, `visible_when_unset=`,
  `visible_when_kind=` and `visible_unless=`, and shows only while
  *all* hold. Ratio / fraction floats — `test_size`, `subsample`,
  `l1_ratio`, `alpha`, … — use `core.params.unit_interval_field`,
  rendered as a 0→1 slider.)
- **`table_viewer`** (grapher). Renders a *small* DataFrame as a table
  image (matplotlib `ax.table`, no LaTeX needed) that previews and
  exports like any figure — intended for a presentation-sized table,
  not for browsing a full DataFrame (the Table tab is for that):
  `decimals` rounding for numeric columns, `max_rows` / `max_cols`
  truncation (with a note), font size, row height, a `padding` slider
  (`ax.table(bbox=...)`) so the table doesn't touch the figure edge,
  and a `style` preset — `shaded` (the original look: header fill +
  zebra rows + bordered cells), `three_line` (the academic three-rule
  table used by APA / most journals — a rule above and below the
  header, one at the bottom, no vertical lines), `grid` (a full border
  on every cell), `striped` (zebra rows, borderless) or `minimal` (no
  lines at all but a header underline) — see `viz._apply_table_style`.
  `header_color` only applies to the `shaded` style.
- **Single-variable plots** (grapher). `pie_chart` — counts of a
  categorical column as `pie`, `doughnut` (a pie with a hole,
  `doughnut_width`), or `tile` (a waffle-style grid of unit squares,
  `tile_columns` wide — capped at ~100 tiles for a large count, each
  then standing for more than one row); `top_n` groups the smallest
  categories into "other". `heatmap_1d` — a single numeric column as a
  strip of coloured cells (`columns_per_row` wraps it into a
  calendar-style grid), `orientation` horizontal / vertical, an
  optional `label_column` whose values tick the cell axis (unwrapped
  only), an optional colourbar and printed values.
  `autocorrelogram` — ACF and/or PACF of a numeric (time-ordered)
  column via `statsmodels.graphics.tsaplots.plot_acf` / `plot_pacf`;
  `show_acf` / `show_pacf` can each be unticked (at least one must stay
  on) and `show_ci` draws the shaded confidence band.
- **Time-series plots** (grapher). `time_series_plot` — one numeric
  series over a datetime `x` (coerced, sorted); `mark` = line /
  line+markers / markers / bars; `x_tick_freq` sets the major-tick
  spacing (year / quarter / month / …, ticks only). Two grouping
  channels driven by the **same** categorical column, either settable
  on its own: `color_by` gives one series per level from `colormap`,
  `style_by` gives each level a different marker shape / line style /
  bar hatch from `shape_map` (when unset, the fixed `marker_shape` /
  `line_style` / `bar_hatch` applies). Groups combine `layer` /
  `stack` / `dodge`; plus `alpha` and the usual legend controls.
  `multivariate_timeseries_plot` — several numeric
  series on a shared datetime axis, `layout` = `overlay` (one axes,
  optional per-series `normalize`) or `grid` (one stacked panel each).
  Colouring follows `layout`, and only the field that applies is shown:
  `overlay` puts every line on one axes, so each takes its own colour
  from a qualitative **`colormap`** (default `tab10`); `grid` gives each
  series its own panel, where colour carries no information, so a single
  **`mark_color`** (default `materialblue`) is used for all of them.
  `forecast_plot` — takes a `model` from `arima` / `auto_arima` (one
  panel) or `var` / `vecm` (one panel per chosen `variable`, tickboxes
  populated from the model): the fitted history plus a multi-step
  forecast. The horizon is the model node's
  `forecast_periods`; `history_color` / `forecast_color` set the two
  lines and `ci_style` the interval — `band` (a lighter fill in the
  forecast colour), `lines`, `errorbar`, or `none`. `var_acorr_plot` —
  the residual auto- and cross-correlation grid of a fitted VAR/VECM (a
  whiteness check). `irf_plot` — impulse-response functions
  (`orthogonalized`, `cumulative`), with tickbox `responses` (rows) and
  `shocks` (columns) chosen from the model, a `line_color`, and the
  same `ci_style` options for the standard-error interval.
- **`density_2d`** (grapher). Bivariate density of two numeric columns
  — `kind` = `contour` (seaborn `kdeplot`, `fill` + `levels`) or
  `hexbin` (a binned count grid, better for a lot of data), with an
  optional light scatter overlay of the raw points.
- **PCA plots** (grapher). `pca_scree_plot` — takes the `pca` node's
  `variance` output; % variance explained per component (bars) with an
  optional cumulative line (secondary axis) and a Kaiser reference
  line. `pca_corr_circle` — takes `pca`'s `loadings` *and* `variance`
  outputs; each variable as a vector scaled by √(explained variance),
  so its length is the true correlation with the two chosen
  components and it is bounded within the unit circle (the standard
  correlation-circle convention).
- **Map plots** (grapher, geopandas + mapclassify). `geo_plot` — draw a
  GeoDataFrame's geometries. `color_by` a numeric column →
  choropleth: `classification` = `continuous` (colourbar) or a
  mapclassify scheme (`quantiles` / `equal_interval` / `natural_breaks`
  / `std_mean`) with `classes` bins; a text / boolean column → a
  categorical map. No `color_by` → a `single_color` fill with
  `edge_color` / `line_width`. `size_by` a numeric column scales point
  size between `size_min` / `size_max` (bubble map). Optional second
  `overlay` layer (auto-reprojected) with its own fill / colour /
  width; `missing_color` for NaN; `show_axes` (off by default) and
  `equal_aspect`. `geo_density` — a point-density heat-map (the geo
  `density_2d`): `kind` = `hexbin` (`gridsize`) or `kde` (`bandwidth`
  / `levels` / `fill`), optional `show_points` and a `boundary`
  outline layer. Both emit a normal `figure`, so they flow into the
  preview, `export_to_dashboard` and `export_figure`.
- **More grapher nodes** (seaborn-backed, same styling / colour-by
  controls). `box_plot` — a numeric column across a categorical one,
  `kind` = box / violin / boxen / swarm (seaborn's catplot family);
  `orientation` swaps the axes, `alpha` sets the fill opacity,
  `color_by` splits each category into hue sub-groups (categorical
  only — a continuous column raises); `show_outliers` toggles the flier
  points (box / boxen); `box_stat` changes what the box spans (box
  kind) — `iqr` (default), `std_dev` (mean ± `std_k`·σ) or `ci`
  (a `confidence_level` interval around the mean), the last two drawn
  directly rather than by seaborn; the swarm kind adds a `point_size`
  and, above `swarm_max_points` rows, draws a seeded random subsample
  (noted on the figure). `histogram_plot` — distribution of one numeric column;
  `mode` = histogram / kde / both (`bins` + `stat` hidden for pure
  KDE), `color_by` overlays one distribution per category with
  `multiple` = layer / stack / dodge. `heatmap_plot` — categorical ×
  categorical; `statistic` = count (crosstab) / row % / column % /
  aggregate of a numeric `value_column` / association (standardised
  residuals from independence, with Cramér's V in the title).

  The `grapher` Micro type dropdown is grouped with separator lines
  (`ui.micro_type_groups`): `table_viewer` on its own, then the base
  plots, then the ML plots that are classification-specific or
  task-agnostic, then the regression-only ML plots (`qq_plot`), then
  the PCA/stats plots.

- **Dashboard tab.** The `export_to_dashboard` node (`export` macro
  type) is a sink: it takes a `figure` — a grapher plot or a
  `table_viewer` table — and has no output. Every such node becomes one
  item on the Dashboard's **infinite pan/zoom canvas** (same navigation
  as the Pipeline tab: two-finger / right-drag pan, pinch / wheel zoom,
  no scroll bars), keyed to the node and re-rendered **as a vector**
  (SVG) in place on each run / auto-run, so it stays sharp at any zoom.
  A figure whose source plot changed since the last run, was
  disconnected, or errored gets the Table tab's yellow "· modified"
  tag; a figure whose export node was deleted is kept as its last
  snapshot. Click an item for a blue selection contour; left-drag
  rubber-bands a multi-selection that moves as a group. Selecting one
  figure opens the **same Options panel** as on the Pipeline tab, bound
  to the upstream plot node — so restyling a dashboard figure is the
  same act as editing its grapher (if the plot is disconnected, a
  canvas overlay says so). A **tool strip down the left edge** offers
  the four assembly tools as icon buttons — title, text box, shape ▾,
  arrange ▾ — the last two dropping the same menus as the canvas
  right-click; Arrange is disabled until something is selected, since
  every entry in it acts on a selection. "Add Title" / "Add Text Box"
  (tool strip, Dashboard menu or canvas right-click) drop free-text
  items, restyled live (bold, italic, size, colour, alignment, font).
  The "add figures using the `export_to_dashboard` node" hint stays up
  until a **figure** arrives: it is not asking for a text box, and
  clearing it when one was added left someone who had typed a heading
  with no idea how to get their plot across. **Dashboard ▸ Exporter…**
  renders the bounding box of all items to PDF (vectors preserved) or
  PNG, by file extension. The canvas is session state — only each
  node's `title` param persists (with the pipeline). Right-clicking a
  figure-bearing node on the Pipeline canvas offers **Add to
  Dashboard**, which drops a wired `export_to_dashboard` node for it.
- **Export nodes** (category `export`, all file-writing sinks). Each
  has an explicit `format` dropdown that decides the type; the
  extension is appended to `filepath` if missing. `export_figure` —
  a `figure` to PNG / JPEG / PDF / SVG / TIFF / WEBP / EPS (`dpi`,
  `transparent`, `bbox_tight`). `export_table` — a `dataframe` to CSV /
  TSV / Excel / Parquet / Feather / JSON, with an `include_index`
  toggle (and `sheet_name` for Excel). `export_geodata` — a
  `geodataframe` to GeoJSON / GeoPackage / GeoParquet / GeoFeather /
  Shapefile (`layer_name` for GPKG). `export_to_dashboard` sends a
  figure to the Dashboard tab (above).

> Packaging the app into a standalone executable (PyInstaller/Nuitka)
> is intentionally not set up yet — planned for once more features
> have been added.

## Running a pipeline headlessly (no UI)

A pipeline is described as JSON: a list of node instances and a list
of connections between their ports. See
`examples/simple_regression_pipeline.json` for a hand-written example
(CSV load -> drop missing values -> train/test split -> linear
regression fit -> scatter plot -> save the plot to disk).

```bash
python examples/run_example.py examples/simple_regression_pipeline.json
```

Node execution results are cached on disk (via `joblib.Memory`, keyed
on node type + parameters + input values), so re-running the same
pipeline — or a pipeline that only changed a downstream node — does
not recompute unchanged upstream steps. Nodes with side effects or
non-hashable outputs (e.g. `matplotlib_plot`, `export_figure`) opt out
of caching via `Node.cacheable = False` and always re-run.

## Exporting a pipeline as a standalone script

Any validated pipeline (built visually or written by hand as JSON) can
be exported to a plain `.py` file that reproduces it exactly, with
**no dependency on the engine** (no `PipelineGraph`,
`PipelineScheduler`, `networkx`, or `joblib`) and none on the UI —
only on the concrete node classes it actually uses:

```bash
python examples/export_to_script.py \
    examples/simple_regression_pipeline.json \
    examples/simple_regression_pipeline_exported.py

python examples/simple_regression_pipeline_exported.py
```

This is useful for reproducing a result without installing the app,
for auditing exactly what a pipeline does, or for handing a pipeline
off as ordinary, readable Python code.

## What a run reports

`PipelineScheduler.run()` / `run_available()` return a **`RunReport`**
with three parts, because a run has three outcomes and only two of them
used to be reported:

- `.outputs` — nodes that ran cleanly, mapped to their output dicts.
- `.errors` — nodes that raised, mapped to a **`NodeError`**
  (`engine/errors.py`).
- `.blocked` — nodes that never ran, mapped to *the node that caused
  it*, or `None` when the node simply is not wired up yet. These
  previously appeared in neither dict, so a run that stopped a third of
  the way through reported one failure and said nothing at all about
  the steps it skipped. `.unwired` is the subset with no cause.

The report unpacks as `(outputs, errors)`, so existing two-value
callers are unaffected.

A `NodeError` carries a one-line `title` (what `str()` returns), a
longer `detail`, the `kind` (`param` / `input` / `runtime` / `blocked`),
the `field` at fault when one can be identified — so the UI can point at
the right row of the Options panel — and the original traceback in
`raw`. `errors.translate()` rewrites pydantic, pandas, sklearn and OS
exceptions as sentences about settings and columns rather than about
Python: *"The "columns" setting expects a list of values, not the text
'nope'."* rather than pydantic's `[type=list_type, input_value='nope'…]`
dump. Anything it does not recognise falls through to
`TypeName: message`, exactly what was shown before, so an unmodelled
failure is never made worse.

`run_available()` also tells **`blocked`** (something upstream failed)
apart from **`unwired`** (a required input has nothing plugged in).
Both draw a grey dot; only the tooltip differs. Conflating them made a
canvas someone was still assembling look like a broken pipeline.

That dot is **drawn with the node** (`ui/node_item.py`), not set as a
pixmap on NodeGraphQt's icon slot, so it stays a circle however far you
zoom in — the 16-px bitmap it used to be went visibly blocky. It is
drawn rather than added as a child `QGraphicsEllipseItem`: a child item
is destroyed with its C++ parent while the Python wrapper is still
held, and collecting that wrapper afterwards segfaults in NodeGraphQt's
`QUndoStack` teardown. `ui/node_status.py` keeps the pixmap path as a
fallback for a node that is not ours.

## The Dashboard canvas

Beyond figures and captions, the canvas takes **shapes** — rectangle,
rounded rectangle, ellipse, line, arrow, triangle — because boxing a
region, circling a result and pointing at it is how a plot becomes an
argument. `ui/dashboard_shapes.py` carries two geometry models in one
class: an *area* is a rect resized from its bottom-right corner, a
*line* is two endpoints with a handle each, which is the only way to
aim one.

The **Add Shape** and **Arrange** menus are built once, in
`ui/dashboard_menus.py`, and filled into all three places that offer
them — the Dashboard menu, the canvas right-click and the left tool
strip — so the three cannot list different commands. The canvas menu is
built by `DashboardPage.build_context_menu()` apart from showing it,
because `exec` blocks until someone clicks: a menu only ever built
inside the handler is a menu no test can look at, which is how it came
to be raising `NameError` on every right-click.

**Arranging** (`ui/dashboard_layout.py`, pure functions over items):
z-order, align on six edges, distribute, nudge with the arrow keys
(Shift for 10px), duplicate, lock. Alignment works on each block's
`visual_rect`, **not** its `sceneBoundingRect` — the latter includes the
padding an item reserves for its selection handles, 15px for a shape
against 3px for a figure, so aligning on it would leave the two twelve
pixels out of line while both claimed to be aligned.

**Undo.** The canvas has its own `QUndoStack`, and Edit ▸ Undo routes to
whichever tab is in front — without that, editing the dashboard and
pressing `Cmd+Z` would quietly undo something on the Pipeline tab, which
is worse than a shortcut that does nothing. Rather than a command class
per operation, each one records the scene either side of itself
(`ui/dashboard_undo.py`): a dashboard holds tens of items, so a snapshot
is cheap, and one mechanism covering add / move / resize / restyle /
reorder / lock / delete is far less to get wrong than seven inverses.
Snapshots hold the item **objects**, so undoing a delete puts back the
same figure with its rendered SVG still in it, not a blank one waiting
for the next run.

**Multi-select restyles as a group** — selecting five shapes and setting
one colour changes all five, which is most of why the inspector exists.
A mixed selection of kinds has nothing in common to edit, so it falls
back to the placeholder.

**Locking** makes a block untouchable: not selectable, movable,
resizable or deletable. Since a locked block cannot be selected, it
cannot be unlocked from its own inspector either — **Dashboard ▸ Unlock
All** is the way back.

**The layout is saved with the pipeline**, in a `dashboard` section of
the same JSON file, so sending someone a pipeline sends the report with
it:

```json
{
  "nodes": [ … ],
  "connections": [ … ],
  "dashboard": {"version": 1, "items": [
    {"type": "figure", "pos": [20, 80], "z": 0,
     "state": {"export_node_id": "Board 1", "title": "Sales by region", …}},
    {"type": "shape", "pos": [300, 40], "z": 1, "state": {"kind": "arrow", …}}
  ]}
}
```

- `graph_to_dict` / `graph_from_dict` stay **pure graph** and never see
  the key, so hand-written files, `examples/*.json` and the headless CLI
  are untouched. `save_document` / `load_document` add the sections; the
  key is only written once the canvas has something on it, and a section
  a future version adds is carried in and out rather than stripped.
- **The rendered picture is not stored** — it comes back from running
  the pipeline, and a stale image on disk would be worse than none. A
  figure block is saved by its **export node's name**, which is what
  re-binds it to the same block (not a duplicate) on the next run; until
  then it wears the "· modified" tag. A block whose node is missing
  stays put and tagged, exactly as when that node is deleted live.
- **Dashboard edits count as unsaved work** — the title's `•` and the
  close prompt watch both undo stacks, because an hour of layout is as
  losable as an hour of wiring.
- **Opening a document replaces the document**: a file with no
  `dashboard` section clears the canvas, so blocks cannot bleed from one
  pipeline into the next and be saved into it.

A block describes itself through the same `capture_state` /
`apply_state` pair the undo snapshots use — saving a layout and undoing
an edit are the same question, so there is one description of a block
rather than two that could drift apart.

## When something goes wrong

Failures land in a **Problems** panel beside the run log on the Pipeline
tab, not in a modal dialog. A `QMessageBox` holding `str(exception)`
interrupted the work, said nothing actionable, and was gone the moment
it was dismissed; a panel stays until the problem does, reads as a
sentence, and leads to the node it is about.

```
Problems (1)                          [tab band: ● 1 problem]

● Load Data · There is no file at '/no/such/file.csv'.
  Check the file path setting on this node.
  Fix in Options ▸ filepath
  ▸ Show technical details          (the traceback, with Copy)
```

- **Only nodes that actually raised get a row.** Blocked nodes are left
  to the canvas's grey dots and their tooltips: one bad parameter can
  block eight steps, and eight rows saying so would bury the one row
  that matters. A graph too broken to run at all has no node to blame,
  so it gets a single pipeline-wide row.
- **Auto-run fills it live**, so a mistake shows up as you make it
  rather than waiting for a Run — silently, as auto-run always has been:
  no dialog, no log spam, just the panel and a red chip in the tab band.
  The chip is hidden when there is nothing wrong.
- **Clicking a row selects that node** and outlines the offending
  setting in the Options panel. The outline clears the moment you edit
  that field — it points at the thing to fix and must not argue with a
  value you have already changed; whether the edit *worked* is the next
  run's answer.
- **Modals survive only for file actions you invoked** — Open, Save,
  Export script, Export dashboard. You asked for a thing and it did not
  happen, and a failed Save reported only in a panel on another tab is
  a good way to lose work.

## Preferences

**Edit ▸ Preferences…** (`Cmd/Ctrl+,`; macOS files it under the
application menu) opens nine pages — General, Appearance, Execution,
Cache, Chart defaults, Export, Dashboard, Data, Advanced. Values live in
`~/.config/ruyso/settings.json` (`$RUYSO_CONFIG_DIR` overrides it),
written atomically, alongside `colormaps.json`.

`engine/settings.py` holds them because several are read with no window
open: the disk-cache budget by `engine/cache.py`, the plot style and
font by `nodes/viz.py`. A headless run honours the same preferences the
app does. `DEFAULTS` is the single source of truth for what exists and
what type it is — an unknown key is refused on write, and a stored value
of the wrong type is ignored on read, so a hand-edited or
newer-version settings file degrades to defaults instead of breaking
the app.

### Toolboxes

129 nodes is a lot to scroll past when your work is loading a CSV and
plotting it, so **Preferences ▸ Toolbox** switches families off:

| Family | Modules | Nodes |
|---|---|---|
| Loading | `loaders`, `example_data` | 8 — always on |
| Transform | `transforms` | 29 — always on |
| Charts | `viz` | 23 — always on |
| Export | `export` | 4 |
| Machine learning | `models`, `model_ops` | 26 |
| Statistics & time series | `statistics` | 19 |
| Geo / maps | `geo_loaders`, `geo_transforms`, `geo_viz` | 20 |

A family is defined by its **modules**, not by node category, because
that is the granularity an import can be skipped at — and the two do not
line up: `models.py` holds one transform node among its model nodes, and
geo spans three modules across three categories.

Switching one off does two things. It **shortens the menus** at once:
`node_factory.core_node_types_by_category` filters by the enabled set,
and the New Node menu, the canvas menu and the micro-type dropdown all
read that one function, so they narrow together. And it **skips the
import** at the next launch, via
`NodeRegistry.discover_package(only=…)` — measured, dropping geo takes
node discovery from **671 ms to 451 ms** and means geopandas and pyproj
are never imported at all. Only geo carries real weight; statistics and
ML together add ~25 ms, because pandas and numpy arrive with
`transforms` regardless. The page says so, since the menu change is
immediate and the load-time change is not.

Two edges are handled. A family the canvas is **using cannot be switched
off** — the dialog names the nodes and refuses, rather than letting you
create a pipeline you cannot reopen. And opening a pipeline whose nodes
come from a switched-off family **offers to switch it back on**, naming
the family; declining leaves both the preference and the canvas alone.

The filter lives in `node_factory`, never in `NodeRegistry`: the
registry is the truth about what the app *has*, and a preference about
what to show is not its business.

Four things are worth knowing:

- **Changes are staged.** Editing a control writes to a pending dict;
  OK or Apply commits, Cancel drops it. Unlike the colormap dialogs,
  several of these (font size, accent, grid) change how the whole app
  looks the instant they land.
- **Chart / Export / Data defaults seed *new nodes*** — applied at
  creation by `ui/node_defaults.py`, not by rewriting schema defaults.
  Existing nodes keep their values, and `pipeline_to_canvas` suspends
  seeding entirely: a file's unmentioned parameter means the node's own
  default, the same on every machine, rather than "whatever this person
  prefers".
- **Blank or 0 means "leave each node's own default alone."** The
  graphers deliberately use eight different figure sizes (one is a
  6.0×2.2 strip), so a single figure-size preference applied to all of
  them would flatten choices their authors made on purpose. Set one and
  it wins everywhere; leave it at 0 and nothing is overridden.
- **The disk-cache budget is applied at startup, on a background
  thread.** joblib 1.5 dropped `bytes_limit` from `Memory.__init__`, so
  it has to be an explicit `reduce_size` pass, and that walks the whole
  directory — not something to do on the way to seeing a result. The
  cache may drift over its budget during a long session; it is a disk
  allowance, not a hard ceiling.

The window also behaves like a document: the title names the open file
and gains a `•` while there are unsaved edits (which is exactly "the
undo stack has moved since the last save", straight off `QUndoStack`),
and closing with unsaved work prompts unless that preference is off.

## Why an auto-run is fast

Auto-run fires after every parameter edit, and 31 nodes — every grapher,
every export — opt out of the joblib disk cache, so each background run
used to re-render every figure on the canvas even when the edit was
three steps away. `engine/run_cache.py` works one level up from joblib:
instead of "have I computed this function on these arguments", it asks
**"has anything that feeds this node changed since I last ran it"**,
using the transitive signatures from `engine/signatures.py`. When the
answer is no, the node's previous outputs are handed back and it never
runs at all.

```
cold                 ran 6: load, plot0…plot4
untouched            ran 1: load
edit plot2's params  ran 2: load, plot2
delete plot4         ran 1: load        (its cache entry is pruned)
```

Design points, each load-bearing:

- **One entry per node**, keyed by node id, holding its latest
  `(signature, outputs)`. The cache is never larger than the graph and a
  deleted node's entry is pruned on the next run — entries hold
  DataFrames and figures, so a signature-keyed history could quietly
  reach hundreds of megabytes.
- **Loaders and exports always execute.** A loader because a file can
  change on disk under an unchanged path; an export because its value
  *is* the side effect, so skipping it means a deleted output file is
  never rewritten.
- **What a loader read is folded into what its dependents key on**
  (`run_cache.content_token`). Re-running the loader is not enough on its
  own: a signature is built from node types, parameters and wiring, none
  of which move when a CSV is edited under the same path — so everything
  downstream would keep serving results computed from the old file while
  the loader happily read the new one.
- **A hit is only served once the inputs are known to be available**, so
  a node whose loader has just started failing is reported blocked
  rather than showing yesterday's data under a red node.
- **The manual Run passes no cache at all**, so pressing Run stays the
  way to force genuine re-execution — rewriting exports, redrawing every
  figure.
- **The worker gets a snapshot, not the live cache.**
  `AutoRunController.interrupt()` calls `QThread.terminate()`, which
  kills the thread at an arbitrary instruction; the snapshot is adopted
  as the live cache on the GUI thread only once a run reaches
  `_on_worker_done`, so a terminated run costs one wasted pass and
  nothing else.

A reused node's outputs come back **by identity** — no node in `nodes/`
mutates its input in place — and the UI leans on exactly that to skip
the work of drawing a figure it has already drawn: `FigureThumbnail`
does not re-rasterise, and the Dashboard does not re-serialise to SVG,
when the `Figure` object is the same one as last time. Serialising a
figure to SVG is the most expensive thing the Dashboard does, and it
used to happen on every background run.

The on-canvas thumbnails are plain widgets over the `QGraphicsView`, so
nothing moves them when the canvas does and they have to be re-placed on
a timer. That timer used to tick every 60 ms for the life of the app —
16 wakeups a second to re-place widgets that had not moved. It now runs
only while the canvas is being manipulated (an event filter wakes it;
300 ms of quiet stops it), so an idle canvas costs nothing.

## Project layout

```
src/ruyso_app/
├── core/     # Node/Port/NodeParams contracts + NodeRegistry
├── nodes/    # Concrete nodes (file + geo loaders, transforms, models, viz, export)
├── engine/   # PipelineGraph, serialization, cache, scheduler, codegen, errors
└── ui/       # NodeGraphQt canvas, property forms, main window
```
