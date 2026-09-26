# Statistics nodes

Statistics nodes (grey) run hypothesis tests, regressions, dimensionality reduction and time-series models. Each returns one or more result tables, browsable in the [Table tab](../panels/table.md).

**Statistics family** (`statistics` macro type, `nodes/statistics.py`;
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
