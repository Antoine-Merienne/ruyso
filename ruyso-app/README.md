# ruyso-app

Visual data science pipeline builder: a node-graph desktop application
where each box defines a step (load, clean, model, visualize) of a
Python data science pipeline.

The codebase is split into three independently testable layers:

| Layer | Package | Depends on | Status |
|---|---|---|---|
| 1. Node model | `ruyso_app.core`, `ruyso_app.nodes` | pydantic (+ the libs each node uses: pandas, geopandas, scikit-learn, matplotlib, seaborn) | done |
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
  - **Export as Script (.py)…** — write the pipeline out as a
    standalone `.py` file (see below).
  - **Run Pipeline** (shortcut **F5**) — execute the canvas on a
    background thread; results land in the run log and the on-canvas
    figure previews.
- **Node** menu (Pipeline tab): **New Node ▸ _macro type_** (chord
  shortcuts `Cmd/Ctrl+P` then `L`/`T`/`M`/`S`/`G`/`E`), and
  **Selected Node ▸ Delete Node** (`Ctrl/Cmd+Backspace`).
- **Dashboard** menu (Dashboard tab): **Exporter…**.
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
to open a resizable window sized to the figure.

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
for every node. For a multi-column field (e.g. `standard_scaler.columns`,
`drop_na.columns`), picking an item from the dropdown toggles it in or
out of the comma-separated value; you can still type any name. A
warning appears below the field if a name isn't a column, or if that
column's type isn't accepted by the parameter. Acceptable types are
declared per field on the node (e.g. `standard_scaler.columns` needs
numeric; `matplotlib_plot.x/y` accept anything).

To change how the app looks (colors, node macro-type colors, window
stylesheet, fonts), edit `src/ruyso_app/ui/theme.py` — it is the only
file that needs touching for purely visual changes.

### UI restructure — status and decisions

The UI is being reworked to match the `ruyso_ui_principles` mockups in
phases. Decisions taken so far (spec section 8):

- **Macro types & palette.** The six macro types are `loading`,
  `transform`, `model`, `statistical_test`, `grapher`, `export`
  (`viz` was split into `grapher` + `statistical_test`). Each maps to
  one Matplotlib *tab10* color, identical in both themes so a node
  stays recognizable across a theme toggle; the map is in
  `theme._MACRO_TYPE_COLORS`. `statistical_test` has no concrete node
  yet — its "New Node" entry is shown **disabled** rather than
  omitted or crashing.
- **Palette hex values.** Dark and light chrome palettes are the
  `DARK_THEME` / `LIGHT_THEME` dataclasses in `theme.py` (window,
  panel, text, border, accent, canvas-background values).
- **Options panel background.** A lightened, ~92%-opaque tint of the
  selected node's macro-type color (`theme.options_panel_background`),
  falling back to an opaque panel color when nothing is selected.
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
  possible — it sits attached just beneath). Click → resizable
  `FigureWindow` sized to the figure's aspect ratio. See
  `ui/node_preview.py`. The old bottom "Figure Preview" pane is gone.
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
- **Data-loader family.** The `loading` macro type has one micro type
  per file format: `csv_loader`, `fixed_width_loader`, `excel_loader`,
  `json_loader`, `parquet_loader`, `feather_loader`, `stata_loader`
  (all -> `dataframe`), plus `geojson_loader`, `shapefile_loader`,
  `geopackage_loader` (-> `geodataframe`). Every loader shares two
  parameters, applied after load: `datetime_columns` and
  `datetime_format`. In the Options panel both are editable dropdowns
  (same widget as the model/grapher/transform column pickers):
  `datetime_columns` lists the loaded file's own columns once the file
  has been read, with an italic-grey **None** entry that clears it;
  `datetime_format` offers a few common `strptime` patterns (declared
  via `core.params.suggestions_field`) but accepts any text, with an
  italic-grey **infer** entry for "let pandas guess". A `geodataframe`
  output may be wired into any node that expects a plain `dataframe`
  (a GeoDataFrame is one); the reverse is rejected by
  `PipelineGraph.validate()`.
- **Transformer family.** `standard_scaler`; `drop_na` and `fill_na`
  (pick columns via a **tickbox list**; `drop_na` chooses `how` =
  any/all, `fill_na` a method — forward/backward fill, mean, median,
  most frequent, zero, or a constant value that reveals a value box;
  an empty tick list is a pass-through, and mean/median on a
  non-numeric column raises); `change_type` (cast one column; the
  target-type dropdown re-filters to the casts that make sense for the
  chosen column); `column_filter` and `dtype_filter` (keep columns via
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
  `core.params.category_map_field`); plus geo transforms
  `geo_to_dataframe`, `dataframe_to_geo` and `reproject` (CRS from the
  same suggestions dropdown as the datetime-format field). The reactive
  behaviour is new Options-panel machinery: `core.params` markers
  (`reactive_choice_field`, `checkbox_list_field`, `category_map_field`,
  `visible_field` / `visible_when=` / `visible_when_set=` /
  `visible_unless=`) drive per-row visibility and dependent dropdowns
  in `ui/options_panel.py`, with option lists in `ui/column_ops.py`.
  The rename-categories table is fed by `column_spec.input_column_values`
  (distinct values of the input's categorical columns).
- **Grapher (`matplotlib_plot`).** Draws with a local
  `seaborn-v0_8-whitegrid` style context (never global), a `darkblue`
  default colour, slightly smaller markers/lines and a top/right
  despine. The Options panel exposes: `x` / `y` / `kind` / `title`; an
  optional **colour by** column picker with an italic-grey **None**
  row — while it is None a colour field (a common-colour dropdown plus
  a *Choose...* colour dialog, `core.params.color_field`) is shown, and
  while it names a column a **colormap** picker is shown instead whose
  options adapt to the column type (qualitative maps for
  text/category/bool, sequential/diverging for numeric/datetime — the
  `colormaps` generator in `ui/column_ops.py`); marker size / line
  width (whichever fits `kind`); a **bar mode** (dodge / stack / layer)
  shown only for a bar chart coloured by a column; axis grid / frame /
  label overrides / font size / log scales / figure size; title font
  size + bold + italic; and legend show / title / location / font size
  (shown only while colouring by a column). Colouring by a categorical
  column draws a legend in a lightly translucent box; by a continuous
  column, a colorbar. (A row may carry any mix of `visible_when=`,
  `visible_when_set=` and `visible_unless=`, and then shows only while
  *all* of them hold.)
- **More grapher nodes** (seaborn-backed, same styling / colour-by
  controls). `box_plot` — box or violin of a numeric column across a
  categorical one, `orientation` swaps the axes, `color_by` splits each
  category into hue sub-groups (categorical only — a continuous column
  raises). `histogram_plot` — distribution of one numeric column;
  `mode` = histogram / kde / both (`bins` + `stat` hidden for pure
  KDE), `color_by` overlays one distribution per category with
  `multiple` = layer / stack / dodge. `heatmap_plot` — categorical ×
  categorical; `statistic` = count (crosstab) / row % / column % /
  aggregate of a numeric `value_column` / association (standardised
  residuals from independence, with Cramér's V in the title).

Still to come: the Dashboard tab (figure/title/text blocks, "add to
dashboard", PDF/PNG export); the statistical-test node type and its
preview.

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
non-hashable outputs (e.g. `matplotlib_plot`, `figure_export`) opt out
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

## Project layout

```
src/ruyso_app/
├── core/     # Node/Port/NodeParams contracts + NodeRegistry
├── nodes/    # Concrete nodes (file + geo loaders, transforms, models, viz, export)
├── engine/   # PipelineGraph, serialization, cache, scheduler, codegen
└── ui/       # NodeGraphQt canvas, property forms, main window
```
