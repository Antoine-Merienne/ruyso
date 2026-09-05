# ruyso-app

Visual data science pipeline builder: a node-graph desktop application
where each box defines a step (load, clean, model, visualize) of a
Python data science pipeline.

The codebase is split into three independently testable layers:

| Layer | Package | Depends on | Status |
|---|---|---|---|
| 1. Node model | `ruyso_app.core`, `ruyso_app.nodes` | pydantic (+ the libs each node uses: pandas, geopandas, scikit-learn, statsmodels, scipy, matplotlib, seaborn) | done |
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
  `geopackage_loader` (-> `geodataframe`). Loaders only read the file —
  they do not coerce dtypes; parse a column as datetime downstream with
  the `change_type` transform (target `datetime`, with an optional
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
- **Transformer family.** `standard_scaler`; `drop_na` and `fill_na`
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
  `standard_scaler`; `train_test_split` (moved here from *model* — one
  DataFrame in; outputs in wiring order `X_train` / `y_train` /
  `X_test` / `y_test` (X's are DataFrames, y's target Series), with
  `shuffle` / `stratify`); `combine_datetime` (build a real datetime64
  column from separate component columns — a **mapping table**, one row
  per time part (year … microsecond) with a column dropdown each,
  `core.params.column_map_field`; quarter → month, year+dayofyear and
  year+ISO-week are handled; a lone text column is parsed with a
  `datetime_format`; `output_column` name + a `replace` toggle to drop
  the sources), `split_datetime` (the reverse — `mode` = `components`
  (tickbox parts → `<col>_<part>` Int64 columns) or `string`
  (`strftime` → `<col>_str`), with `replace`), and `resample_datetime`
  (pick a datetime key column + a target `rule`, one downsample
  aggregator — mean/sum/…/count/ohlc — for the numeric columns, and an
  upsample `fill` — ffill / bfill / interpolate-linear / -time /
  nearest; non-numeric columns take the first value; the key comes back
  as a column); `diff` (row-order difference of numeric columns — a
  comma-separated `lags` list, e.g. `1, 7, 30`, each producing one
  `<column>_diff_<lag>` via `Series.diff(periods=lag)`; assumes the
  rows are already time-ordered, e.g. via `sort`); `custom_operation`
  (a monospace, multi-line code box — `core.params.code_field` — runs
  the typed Python against the input DataFrame bound as `df`, with `pd`
  / `np` / common `math` functions already in scope and a read-only
  hint of the input columns underneath; a reduced builtins set blocks
  `import` / `open` / `exec` / `eval` as a light guard rail, not a
  sandbox — this is a local desktop tool); plus geo transforms
  `geo_to_dataframe`, `dataframe_to_geo` and `reproject` (CRS from the
  same suggestions dropdown as the datetime-format field). The
  Micro type dropdown groups the whole `transform` macro type with
  separator lines — base / filters / type / reshaping / datetime / geo
  / custom (`ui.micro_type_groups`). The reactive behaviour is
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
  `max_iter` / …). Clustering (unsupervised, no target column):
  `kmeans_fit`, `minibatch_kmeans_fit`, `dbscan_fit`, `hdbscan_fit`,
  `agglomerative_clustering_fit`, `spectral_clustering_fit`,
  `gaussian_mixture_fit` — `SklearnClusterFitNode` fits on `X_train`
  alone (`y_train` stays wireable but is always ignored); DBSCAN /
  HDBSCAN / agglomerative / spectral have no `predict` on new data
  (read `labels_` off the fitted `model` instead). The Micro type
  dropdown groups the whole `model` macro type into *utilities* (the
  model-consuming nodes below) then an alphabetical *fits* group
  (`ui.micro_type_groups`).
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
  interval; two outputs, `fit` (order, AIC/BIC, log-likelihood) and
  `forecast` (step, forecast, ci_low, ci_high). **`auto_arima`** — the
  same SARIMAX forecaster, but the order is found by an in-repo
  Hyndman-Khandakar-style *stepwise* search (`nodes/statistics.py`
  `_stepwise_search`): `d` from an ADF-based rule (`_select_d`), a
  hill-climb over `(p, q)` (and `(P, Q)` when `seasonal` is on) from a
  few seed models, minimizing `information_criterion` (AIC/BIC) until
  no neighbouring order improves it — a handful of fits, not a full
  grid; the seasonal differencing order `D` is fixed at 1 when
  `seasonal` is on (0 otherwise), a simplification over a true
  seasonal unit-root test. Same two outputs as `arima`. The Micro type
  dropdown groups the whole macro type — these four non-test tools,
  then every `*_test` node alphabetically (`ui.micro_type_groups`).
  Classical tests are powered by scipy; time-series, regressions and
  ARIMA by statsmodels; PCA by scikit-learn.
- **Grapher (`matplotlib_plot`).** Draws with a local
  `seaborn-v0_8-whitegrid` style context (never global), a `darkblue`
  default colour, slightly smaller markers/lines and a top/right
  despine. **Four independent visual channels**, each a fixed value
  *plus* an optional "... by `<column>`" picker (italic-grey **None**
  row), all following the same logic:
  - **colour** — `mark_color` (common-colour dropdown + *Choose...*
    dialog) / `color_by` (+ a `colormap` whose options adapt: qualitative
    for text/category/bool, sequential/diverging for numeric/datetime,
    the `colormaps` generator in `ui/column_ops.py`);
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
  label overrides / font size / log scales / figure size; title font
  size + bold + italic; legend show / title / location / font size.
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
  calendar-style grid), with an optional colourbar and printed values.
  `autocorrelogram` — ACF and/or PACF of a numeric (time-ordered)
  column via `statsmodels.graphics.tsaplots.plot_acf` / `plot_pacf`;
  `show_acf` / `show_pacf` can each be unticked (at least one must stay
  on) and `show_ci` draws the shaded confidence band.
- **`density_2d`** (grapher). Bivariate density of two numeric columns
  — `kind` = `contour` (seaborn `kdeplot`, `fill` + `levels`) or
  `hexbin` (a binned count grid, better for a lot of data), with an
  optional light scatter overlay of the raw points.
- **More grapher nodes** (seaborn-backed, same styling / colour-by
  controls). `box_plot` — a numeric column across a categorical one,
  `kind` = box / violin / boxen / swarm (seaborn's catplot family);
  `orientation` swaps the axes, `color_by` splits each category into
  hue sub-groups (categorical only — a continuous column raises); the
  swarm kind adds a `point_size` and, above `swarm_max_points` rows,
  draws a seeded random subsample (noted on the figure). `histogram_plot` — distribution of one numeric column;
  `mode` = histogram / kde / both (`bins` + `stat` hidden for pure
  KDE), `color_by` overlays one distribution per category with
  `multiple` = layer / stack / dodge. `heatmap_plot` — categorical ×
  categorical; `statistic` = count (crosstab) / row % / column % /
  aggregate of a numeric `value_column` / association (standardised
  residuals from independence, with Cramér's V in the title).

Still to come: the Dashboard tab (figure/title/text blocks, "add to
dashboard", PDF/PNG export).

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
