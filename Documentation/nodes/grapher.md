# Grapher nodes

Grapher nodes (purple) turn a table or a model into a figure. Every figure shows a live preview under its node, and can be sent to the [Dashboard](../panels/dashboard.md) or saved with [`export_figure`](export.md).

## The general-purpose plot: `matplotlib_plot`

**Grapher (`matplotlib_plot`).** Draws with a local
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

## Fitted curves: `regression_plot`

**`regression_plot`** (grapher). The fit, not the data: a **LOWESS**
smoother (`statsmodels.nonparametric.smoothers_lowess`, window set by
`frac`) or a **linear** least-squares line, with a confidence
interval. Drawing the observations is a `show_points` option, **off by
default**. A *discrete* `color_by` or `shape_by` column fits **one
curve per category**, in that category's colour and line style (its
points take the matching marker from the same `shape_map` series);
two different discrete columns fit the cross-product, one curve per
combination, with two legends. A *continuous* colour-by column cannot
split a fit, so it colours the points and leaves one curve (noted on
the figure). The interval is exact for the linear fit (the
confidence interval of the mean response, from `statsmodels` OLS) and
**bootstrapped** for LOWESS — statsmodels' lowess returns smoothed
values and nothing else, so `n_boot` resamples are refitted and the
band is their percentile envelope. That bootstrap is seeded
(`viz._BOOT_SEED`), so the same data always draws the same band: an
interval that flickered on every auto-run would be unreadable, and
untestable. Groups with fewer than three points, or with no spread in
x, are skipped and noted. Everything else — the colour/shape
channels, axis labels, manual limits, log scales, grid/frame, figure
size, title and legend blocks — matches `matplotlib_plot`; the
per-row `size_by` / `alpha_by` channels do not apply to a fitted
curve and are not offered.

## Tables as figures: `table_viewer`

**`table_viewer`** (grapher). Renders a *small* DataFrame as a table
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

## Single-variable plots

**Single-variable plots** (grapher). `pie_chart` — counts of a
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

## Time-series plots

**Time-series plots** (grapher). `time_series_plot` — one numeric
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

## Log scales

Any grapher axis that carries a *measured* quantity
offers a `log_x` / `log_y` tickbox: `matplotlib_plot`, `regression_plot`,
`histogram_plot`, `box_plot`, `density_2d`, the classifier curves
(`roc_curve_plot`, `precision_recall_plot`, `det_curve_plot`,
`calibration_curve_plot`), `learning_curve_plot`, and — on the value
axis only — `pca_scree_plot`, `time_series_plot`,
`multivariate_timeseries_plot` and `forecast_plot`. Axes showing
categories, dates, map coordinates, lag indices, or signed quantities
(correlations, loadings, quantiles) do not offer one, since a log scale
has nothing to say about them. `nodes/viz.py::_finalize_plot` applies
the toggle for every grapher that routes through it, so a new grapher
usually only has to declare the two fields —
`tests/nodes/test_viz.py::test_every_grapher_with_a_measured_axis_offers_a_log_toggle`
is the list that has to be updated with it.

## Density: `density_2d`

**`density_2d`** (grapher). Bivariate density of two numeric columns
— `kind` = `contour` (seaborn `kdeplot`, `fill` + `levels`) or
`hexbin` (a binned count grid, better for a lot of data), with an
optional light scatter overlay of the raw points. `log_x` / `log_y`
estimate the density *in* log space (and bin the hexagons there),
rather than drawing it and re-scaling the axis afterwards.

## PCA plots

**PCA plots** (grapher). `pca_scree_plot` — takes the `pca` node's
`variance` output; % variance explained per component (bars) with an
optional cumulative line (secondary axis) and a Kaiser reference
line. `pca_corr_circle` — takes `pca`'s `loadings` *and* `variance`
outputs; each variable as a vector scaled by √(explained variance),
so its length is the true correlation with the two chosen
components and it is bounded within the unit circle (the standard
correlation-circle convention).

## Maps

**Map plots** (grapher, geopandas + mapclassify). `geo_plot` — draw a
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

## Distribution and category plots

**More grapher nodes** (seaborn-backed, same styling / colour-by
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

## Model plots

**Model-visualization plots** (`grapher` macro type, in `nodes/viz.py`;
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

## Axis limits

**Manual axis limits.** Every grapher carries four always-visible
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
