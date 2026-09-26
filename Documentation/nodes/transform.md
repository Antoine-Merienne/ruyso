# Transform nodes

Transform nodes (orange) take a table and return a reshaped, filtered, cleaned or derived one. The geo transforms work on map data (GeoDataFrames).

## General transforms

**Transformer family.** `scaler` (StandardScaler / MinMaxScaler /
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
*shown* (see [Datetime display formats](../features.md#datetime-display-formats)); **`last_of_period`**
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

## Geo transforms

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

## How the Options panel groups them

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
