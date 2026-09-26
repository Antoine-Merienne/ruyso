"""
Statistics nodes (macro type ``statistics``).

One node per *family* of hypothesis test (node_type ending in
``_test``) -- each with a ``test`` dropdown and per-test parameters --
plus a handful of non-test tools: ``regression`` (statsmodels inference
models), ``pca``, and the time-series forecasters ``arima`` /
``auto_arima``. The Micro type dropdown groups the whole macro type
into these two: non-tests first, then every ``*_test`` node
(``ui.micro_type_groups``).

Every node takes a ``df`` input and produces one or more ``df``
outputs (a tidy results table), so results are browsable in the Table
tab like any other DataFrame. scipy powers the classical tests;
statsmodels powers the time-series tests, the regressions, and ARIMA;
scikit-learn powers PCA.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    checkbox_list_field,
    column_field,
    suggestions_field,
    unit_interval_field,
    visible_field,
)
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

_ALT = Literal["two-sided", "less", "greater"]

_STATS_INPUTS = [Port(name="df", dtype="dataframe")]
_STATS_OUTPUTS = [Port(name="df", dtype="dataframe")]


def _row(**fields: Any) -> pd.DataFrame:
    """A one-row results DataFrame."""
    return pd.DataFrame([fields])


def _num(df: pd.DataFrame, col: str, ctx: str) -> pd.Series:
    if col not in df.columns:
        raise ValueError(f"{ctx}: column {col!r} is not in the input data.")
    s = pd.to_numeric(df[col], errors="coerce")
    return s


def _aligned(df: pd.DataFrame, a: str, b: str, ctx: str) -> tuple[pd.Series, pd.Series]:
    sa, sb = _num(df, a, ctx), _num(df, b, ctx)
    mask = sa.notna() & sb.notna()
    if mask.sum() < 3:
        raise ValueError(f"{ctx}: fewer than 3 complete pairs of {a!r} / {b!r}.")
    return sa[mask].to_numpy("float64"), sb[mask].to_numpy("float64")


def _groups(
    df: pd.DataFrame, value_col: str, group_col: str, ctx: str
) -> list[tuple[Any, np.ndarray]]:
    if group_col not in df.columns:
        raise ValueError(f"{ctx}: column {group_col!r} is not in the input data.")
    values = _num(df, value_col, ctx)
    out: list[tuple[Any, np.ndarray]] = []
    for key, sub in df.groupby(group_col, observed=True):
        arr = pd.to_numeric(sub[value_col], errors="coerce").dropna().to_numpy("float64")
        if arr.size:
            out.append((key, arr))
    if len(out) < 2:
        raise ValueError(f"{ctx}: need at least 2 non-empty groups in {group_col!r}.")
    return out


# --------------------------------------------------------------------------
# one-sample
# --------------------------------------------------------------------------


class OneSampleTestParams(NodeParams):
    """
    Attributes:
        column: Numeric column to test.
        test: "t_test" (Student's t) or "wilcoxon" (signed-rank).
        popmean: Reference value the column is compared against.
        alternative: Direction of the alternative hypothesis.
    """

    column: str = column_field(dtypes=("numeric",))
    test: Literal["t_test", "wilcoxon"] = "t_test"
    popmean: float = 0.0
    alternative: _ALT = "two-sided"


@register_node
class OneSampleTest(Node):
    """One-sample location tests (compare a column's centre to a value)."""

    node_type = "one_sample_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = OneSampleTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        x = _num(inputs["df"], p.column, "one_sample_test").dropna().to_numpy("float64")
        if x.size < 3:
            raise ValueError("one_sample_test: need at least 3 non-missing values.")

        if p.test == "t_test":
            res = stats.ttest_1samp(x, p.popmean, alternative=p.alternative)
            ci = res.confidence_interval()
            return {
                "df": _row(
                    test="t_test", n=x.size, mean=float(np.mean(x)),
                    statistic=float(res.statistic), dof=float(res.df),
                    pvalue=float(res.pvalue),
                    ci_low=float(ci.low), ci_high=float(ci.high),
                )
            }
        res = stats.wilcoxon(x - p.popmean, alternative=p.alternative)
        return {
            "df": _row(
                test="wilcoxon", n=x.size, median=float(np.median(x)),
                statistic=float(res.statistic), pvalue=float(res.pvalue),
            )
        }


# --------------------------------------------------------------------------
# independent samples
# --------------------------------------------------------------------------


class IndependentSamplesTestParams(NodeParams):
    """
    Attributes:
        value_column: Numeric column being compared.
        group_column: Categorical column defining the groups.
        test: The comparison to run (two-group or k-group).
        alternative: Direction (two-group tests only).
    """

    value_column: str = column_field(dtypes=("numeric",))
    group_column: str = column_field(dtypes=("categorical", "boolean"))
    test: Literal[
        "t_test", "welch_t", "mann_whitney", "ranksums", "brunner_munzel",
        "ks_2samp", "kruskal", "anova", "median_test",
    ] = "t_test"
    alternative: _ALT = "two-sided"


@register_node
class IndependentSamplesTest(Node):
    """Compare a numeric column across independent groups."""

    node_type = "independent_samples_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = IndependentSamplesTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        ctx = "independent_samples_test"
        groups = _groups(inputs["df"], p.value_column, p.group_column, ctx)
        arrays = [a for _k, a in groups]
        two_group = {
            "t_test", "welch_t", "mann_whitney", "ranksums", "brunner_munzel",
            "ks_2samp",
        }
        if p.test in two_group and len(arrays) != 2:
            raise ValueError(f"{ctx}: {p.test!r} needs exactly 2 groups, got {len(arrays)}.")

        common = dict(
            test=p.test, n_groups=len(arrays), n_total=int(sum(a.size for a in arrays)),
            dof=float("nan"), ci_low=float("nan"), ci_high=float("nan"),
        )
        g0 = arrays[0]
        g1 = arrays[1] if len(arrays) > 1 else None

        if p.test in ("t_test", "welch_t"):
            res = stats.ttest_ind(
                g0, g1, equal_var=(p.test == "t_test"), alternative=p.alternative
            )
            ci = res.confidence_interval()
            common.update(dof=float(res.df), ci_low=float(ci.low), ci_high=float(ci.high))
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "mann_whitney":
            res = stats.mannwhitneyu(g0, g1, alternative=p.alternative)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "ranksums":
            res = stats.ranksums(g0, g1, alternative=p.alternative)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "brunner_munzel":
            res = stats.brunnermunzel(g0, g1, alternative=p.alternative)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "ks_2samp":
            res = stats.ks_2samp(g0, g1, alternative=p.alternative)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "kruskal":
            res = stats.kruskal(*arrays)
            common["dof"] = float(len(arrays) - 1)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "anova":
            res = stats.f_oneway(*arrays)
            common["dof"] = float(len(arrays) - 1)
            stat, pval = float(res.statistic), float(res.pvalue)
        else:  # median_test
            stat, pval, _med, _table = stats.median_test(*arrays)
            common["dof"] = float(len(arrays) - 1)
            stat, pval = float(stat), float(pval)

        return {"df": _row(statistic=stat, pvalue=pval, **common)}


# --------------------------------------------------------------------------
# paired samples
# --------------------------------------------------------------------------


class PairedTestParams(NodeParams):
    """Attributes: column_a / column_b -- the two paired numeric columns."""

    column_a: str = column_field(dtypes=("numeric",))
    column_b: str = column_field(dtypes=("numeric",))
    test: Literal["t_test", "wilcoxon"] = "t_test"
    alternative: _ALT = "two-sided"


@register_node
class PairedTest(Node):
    """Paired-sample location tests (two measurements on the same units)."""

    node_type = "paired_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = PairedTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        a, b = _aligned(inputs["df"], p.column_a, p.column_b, "paired_test")
        if p.test == "t_test":
            res = stats.ttest_rel(a, b, alternative=p.alternative)
            ci = res.confidence_interval()
            return {
                "df": _row(
                    test="t_test", n_pairs=a.size, mean_diff=float(np.mean(a - b)),
                    statistic=float(res.statistic), dof=float(res.df),
                    pvalue=float(res.pvalue),
                    ci_low=float(ci.low), ci_high=float(ci.high),
                )
            }
        res = stats.wilcoxon(a, b, alternative=p.alternative)
        return {
            "df": _row(
                test="wilcoxon", n_pairs=a.size, median_diff=float(np.median(a - b)),
                statistic=float(res.statistic), pvalue=float(res.pvalue),
            )
        }


# --------------------------------------------------------------------------
# correlation
# --------------------------------------------------------------------------


class CorrelationTestParams(NodeParams):
    column_a: str = column_field(dtypes=("numeric",))
    column_b: str = column_field(dtypes=("numeric",))
    test: Literal["pearson", "spearman", "kendall", "point_biserial"] = "pearson"
    alternative: _ALT = "two-sided"


@register_node
class CorrelationTest(Node):
    """Correlation / association between two numeric columns."""

    node_type = "correlation_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = CorrelationTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        a, b = _aligned(inputs["df"], p.column_a, p.column_b, "correlation_test")
        ci_low = ci_high = float("nan")
        if p.test == "pearson":
            res = stats.pearsonr(a, b, alternative=p.alternative)
            ci = res.confidence_interval()
            ci_low, ci_high = float(ci.low), float(ci.high)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "spearman":
            res = stats.spearmanr(a, b, alternative=p.alternative)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "kendall":
            res = stats.kendalltau(a, b, alternative=p.alternative)
            stat, pval = float(res.statistic), float(res.pvalue)
        else:  # point_biserial
            res = stats.pointbiserialr(a, b)
            stat, pval = float(res.statistic), float(res.pvalue)
        return {
            "df": _row(
                test=p.test, n=a.size, statistic=stat, pvalue=pval,
                ci_low=ci_low, ci_high=ci_high,
            )
        }


# --------------------------------------------------------------------------
# association (categorical x categorical)
# --------------------------------------------------------------------------


class AssociationTestParams(NodeParams):
    column_a: str = column_field(dtypes=("categorical", "boolean"))
    column_b: str = column_field(dtypes=("categorical", "boolean"))
    test: Literal["chi_square", "g_test", "fisher_exact"] = "chi_square"
    yates_correction: bool = visible_field(
        True, visible_when=("test", "chi_square"),
        description="Apply Yates' continuity correction (2x2 tables).",
    )


@register_node
class AssociationTest(Node):
    """Association between two categorical columns (contingency table)."""

    node_type = "association_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = AssociationTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        df = inputs["df"]
        for col in (p.column_a, p.column_b):
            if col not in df.columns:
                raise ValueError(f"association_test: column {col!r} is not in the data.")
        table = pd.crosstab(df[p.column_a], df[p.column_b])
        n = int(table.to_numpy().sum())

        if p.test == "fisher_exact":
            if table.shape != (2, 2):
                raise ValueError("association_test: fisher_exact needs a 2x2 table.")
            odds, pval = stats.fisher_exact(table.to_numpy())
            return {
                "df": _row(
                    test="fisher_exact", n=n, statistic=float(odds), dof=float("nan"),
                    pvalue=float(pval), cramers_v=float("nan"),
                )
            }

        lambda_ = "log-likelihood" if p.test == "g_test" else None
        chi2, pval, dof, _expected = stats.chi2_contingency(
            table.to_numpy(), correction=bool(p.yates_correction), lambda_=lambda_
        )
        k = min(table.shape)
        cramers_v = float(np.sqrt(chi2 / (n * (k - 1)))) if n and k > 1 else 0.0
        return {
            "df": _row(
                test=p.test, n=n, statistic=float(chi2), dof=float(dof),
                pvalue=float(pval), cramers_v=cramers_v,
            )
        }


# --------------------------------------------------------------------------
# normality
# --------------------------------------------------------------------------


class NormalityTestParams(NodeParams):
    column: str = column_field(dtypes=("numeric",))
    test: Literal[
        "shapiro", "dagostino_k2", "jarque_bera", "anderson_darling", "ks_normal"
    ] = "shapiro"


@register_node
class NormalityTest(Node):
    """Test whether a numeric column looks normally distributed."""

    node_type = "normality_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = NormalityTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        x = _num(inputs["df"], p.column, "normality_test").dropna().to_numpy("float64")
        if x.size < 8:
            raise ValueError("normality_test: need at least 8 non-missing values.")

        crit_5 = float("nan")
        reject_5 = None
        if p.test == "shapiro":
            res = stats.shapiro(x)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "dagostino_k2":
            res = stats.normaltest(x)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "jarque_bera":
            res = stats.jarque_bera(x)
            stat, pval = float(res.statistic), float(res.pvalue)
        elif p.test == "ks_normal":
            z = (x - x.mean()) / (x.std(ddof=1) or 1.0)
            res = stats.kstest(z, "norm")
            stat, pval = float(res.statistic), float(res.pvalue)
        else:  # anderson_darling
            try:
                res = stats.anderson(x, dist="norm", method="interpolate")
                stat = float(res.statistic)
                pval = float(res.pvalue)
                reject_5 = bool(pval < 0.05)
            except TypeError:  # scipy < 1.17 has no ``method`` argument
                res = stats.anderson(x, dist="norm")
                stat = float(res.statistic)
                pval = float("nan")
                levels = list(res.significance_level)
                if 5.0 in levels:
                    crit_5 = float(res.critical_values[levels.index(5.0)])
                    reject_5 = bool(stat > crit_5)

        return {
            "df": _row(
                test=p.test, n=x.size, statistic=stat, pvalue=pval,
                critical_value_5pct=crit_5, reject_5pct=reject_5,
            )
        }


# --------------------------------------------------------------------------
# variance homogeneity
# --------------------------------------------------------------------------


class VarianceTestParams(NodeParams):
    value_column: str = column_field(dtypes=("numeric",))
    group_column: str = column_field(dtypes=("categorical", "boolean"))
    test: Literal["levene", "bartlett", "fligner"] = "levene"
    center: Literal["median", "mean", "trimmed"] = visible_field(
        "median", visible_unless=("test", "bartlett"),
        description="Centre used by Levene / Fligner.",
    )


@register_node
class VarianceTest(Node):
    """Test equality of variance across groups (homoscedasticity)."""

    node_type = "variance_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = VarianceTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        arrays = [a for _k, a in _groups(
            inputs["df"], p.value_column, p.group_column, "variance_test"
        )]
        if p.test == "bartlett":
            res = stats.bartlett(*arrays)
        elif p.test == "levene":
            res = stats.levene(*arrays, center=p.center)
        else:
            res = stats.fligner(*arrays, center=p.center)
        return {
            "df": _row(
                test=p.test, n_groups=len(arrays),
                statistic=float(res.statistic), pvalue=float(res.pvalue),
            )
        }


# --------------------------------------------------------------------------
# resampling / Monte Carlo
# --------------------------------------------------------------------------


class ResamplingTestParams(NodeParams):
    test: Literal[
        "permutation_mean_diff", "bootstrap_mean_ci", "bootstrap_median_ci"
    ] = "permutation_mean_diff"
    value_column: str = column_field(dtypes=("numeric",))
    group_column: str = column_field(
        dtypes=("categorical", "boolean"),
        default="",
        allow_none=True,
        visible_when=("test", "permutation_mean_diff"),
    )
    n_resamples: int = 9999
    confidence_level: float = unit_interval_field(
        0.95, lo=0.5, hi=0.999,
        visible_unless=("test", "permutation_mean_diff"),
    )
    random_state: int = 0


@register_node
class ResamplingTest(Node):
    """Permutation / bootstrap / Monte-Carlo inference."""

    node_type = "resampling_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = ResamplingTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        df = inputs["df"]
        n_res = max(int(p.n_resamples), 99)

        if p.test == "permutation_mean_diff":
            group_col = (p.group_column or "").strip()
            if not group_col:
                raise ValueError("resampling_test: pick a group column for the permutation test.")
            arrays = [a for _k, a in _groups(df, p.value_column, group_col, "resampling_test")]
            if len(arrays) != 2:
                raise ValueError("resampling_test: permutation test needs exactly 2 groups.")
            res = stats.permutation_test(
                (arrays[0], arrays[1]),
                lambda a, b, axis=-1: np.mean(a, axis=axis) - np.mean(b, axis=axis),
                vectorized=True, n_resamples=n_res, alternative="two-sided",
                random_state=int(p.random_state),
            )
            return {
                "df": _row(
                    test="permutation_mean_diff", n=int(sum(a.size for a in arrays)),
                    statistic=float(res.statistic), pvalue=float(res.pvalue),
                    n_resamples=n_res,
                )
            }

        x = _num(df, p.value_column, "resampling_test").dropna().to_numpy("float64")
        if x.size < 3:
            raise ValueError("resampling_test: need at least 3 non-missing values.")
        fn = np.mean if p.test == "bootstrap_mean_ci" else np.median
        res = stats.bootstrap(
            (x,), fn, n_resamples=n_res, confidence_level=float(p.confidence_level),
            random_state=int(p.random_state), method="BCa",
        )
        return {
            "df": _row(
                test=p.test, n=x.size, point_estimate=float(fn(x)),
                ci_low=float(res.confidence_interval.low),
                ci_high=float(res.confidence_interval.high),
                standard_error=float(res.standard_error), n_resamples=n_res,
            )
        }


# --------------------------------------------------------------------------
# multiple testing / meta-analysis
# --------------------------------------------------------------------------


class MultipleTestingParams(NodeParams):
    pvalue_column: str = column_field(dtypes=("numeric",))
    method: Literal[
        "fdr_bh", "fdr_by", "bonferroni", "holm", "sidak",
        "combine_fisher", "combine_stouffer",
    ] = "fdr_bh"
    alpha: float = unit_interval_field(0.05, hi=0.5)


@register_node
class MultipleTesting(Node):
    """Adjust a column of p-values (FDR / FWER) or pool them (meta-analysis)."""

    node_type = "multiple_testing"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = MultipleTestingParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from scipy import stats

        p = self.params
        df = inputs["df"]
        pvals = _num(df, p.pvalue_column, "multiple_testing")
        keep = pvals.notna()
        values = pvals[keep].to_numpy("float64")
        if values.size == 0:
            raise ValueError("multiple_testing: no numeric p-values found.")

        if p.method.startswith("combine_"):
            how = p.method.split("_", 1)[1]
            res = stats.combine_pvalues(values, method=how)
            return {
                "df": _row(
                    method=p.method, k=int(values.size),
                    statistic=float(res.statistic), pvalue=float(res.pvalue),
                )
            }

        if p.method in ("fdr_bh", "fdr_by"):
            adjusted = stats.false_discovery_control(
                values, method="bh" if p.method == "fdr_bh" else "by"
            )
        else:
            from statsmodels.stats.multitest import multipletests

            _reject, adjusted, _a1, _a2 = multipletests(
                values, alpha=float(p.alpha), method=p.method
            )

        out = df.loc[keep].copy()
        out["adjusted_pvalue"] = adjusted
        out["reject"] = adjusted < float(p.alpha)
        return {"df": out.reset_index(drop=True)}


# --------------------------------------------------------------------------
# time series
# --------------------------------------------------------------------------


class TimeSeriesTestParams(NodeParams):
    column: str = column_field(dtypes=("numeric",))
    test: Literal[
        "adf", "kpss", "ljung_box", "durbin_watson", "granger"
    ] = "adf"
    column_b: str = column_field(
        dtypes=("numeric",), default="", allow_none=True,
        visible_when=("test", "granger"),
        description="Candidate 'causing' series for the Granger test.",
    )
    max_lag: int = visible_field(
        10, visible_unless=("test", "durbin_watson"),
        description="Maximum lag for ljung_box / granger; regression lag hint for adf.",
    )
    adf_regression: Literal["c", "ct", "ctt", "n"] = visible_field(
        "c", visible_when=("test", "adf"),
    )
    kpss_regression: Literal["c", "ct"] = visible_field(
        "c", visible_when=("test", "kpss"),
    )


@register_node
class TimeSeriesTest(Node):
    """Stationarity / autocorrelation / Granger-causality tests."""

    node_type = "timeseries_test"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = list(_STATS_OUTPUTS)
    params_schema = TimeSeriesTestParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import warnings

        p = self.params
        df = inputs["df"]
        x = _num(df, p.column, "timeseries_test").dropna().to_numpy("float64")
        if x.size < 12:
            raise ValueError("timeseries_test: need at least 12 non-missing values.")
        lag = max(int(p.max_lag), 1)

        if p.test == "adf":
            from statsmodels.tsa.stattools import adfuller

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                stat, pval, used_lag, nobs, crit, _icb = adfuller(
                    x, regression=p.adf_regression, autolag="AIC"
                )
            return {
                "df": _row(
                    test="adf", statistic=float(stat), pvalue=float(pval),
                    used_lag=int(used_lag), n_obs=int(nobs),
                    crit_5pct=float(crit["5%"]), stationary=bool(pval < 0.05),
                )
            }

        if p.test == "kpss":
            from statsmodels.tsa.stattools import kpss

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                stat, pval, n_lags, crit = kpss(
                    x, regression=p.kpss_regression, nlags="auto"
                )
            return {
                "df": _row(
                    test="kpss", statistic=float(stat), pvalue=float(pval),
                    n_lags=int(n_lags), crit_5pct=float(crit["5%"]),
                    stationary=bool(pval >= 0.05),
                )
            }

        if p.test == "ljung_box":
            from statsmodels.stats.diagnostic import acorr_ljungbox

            res = acorr_ljungbox(x, lags=lag, return_df=True)
            res = res.reset_index(names="lag").rename(
                columns={"lb_stat": "statistic", "lb_pvalue": "pvalue"}
            )
            return {"df": res}

        if p.test == "durbin_watson":
            from statsmodels.stats.stattools import durbin_watson

            return {
                "df": _row(
                    test="durbin_watson", statistic=float(durbin_watson(x)),
                    n=int(x.size),
                )
            }

        # granger
        from statsmodels.tsa.stattools import grangercausalitytests

        col_b = (p.column_b or "").strip()
        if not col_b or col_b not in df.columns:
            raise ValueError("timeseries_test: pick a second column for the Granger test.")
        pair = df[[p.column, col_b]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(pair) < 3 * lag:
            raise ValueError("timeseries_test: not enough rows for the requested max_lag.")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = grangercausalitytests(pair.to_numpy(), maxlag=lag)
        rows = []
        for lg, (tests, _models) in results.items():
            f_stat, f_p, _dfn, _dfd = tests["ssr_ftest"]
            rows.append({"lag": int(lg), "f_statistic": float(f_stat), "pvalue": float(f_p)})
        return {"df": pd.DataFrame(rows)}


# --------------------------------------------------------------------------
# regression (statsmodels inference models)
# --------------------------------------------------------------------------


class RegressionParams(NodeParams):
    """
    Attributes:
        model: The statsmodels model to fit.
        y_column: The dependent variable.
        x_columns: The predictor columns (tickboxes).
        add_intercept: Add a constant term.
        robust_se: Heteroskedasticity-robust covariance (OLS only).
        confidence_level: Confidence level for the coefficient intervals.
    """

    model: Literal["ols", "logit", "poisson", "probit", "rlm"] = "ols"
    y_column: str = column_field(dtypes=("any",))
    x_columns: list[str] | None = checkbox_list_field(source="columns", default=None)
    add_intercept: bool = True
    robust_se: Literal["none", "HC0", "HC1", "HC2", "HC3"] = visible_field(
        "none", visible_when=("model", "ols"),
        description="Robust standard errors (OLS).",
    )
    confidence_level: float = unit_interval_field(0.95, lo=0.5, hi=0.999)


@register_node
class Regression(Node):
    """
    Fit a statsmodels inference model (OLS / Logit / Poisson / Probit /
    RLM) and output the full coefficient table (estimate, std err,
    t/z, p-value, confidence interval) and the residuals.
    """

    node_type = "regression"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [
        Port(name="coeffs", dtype="dataframe"),
        Port(name="residuals", dtype="dataframe"),
    ]
    params_schema = RegressionParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import statsmodels.api as sm

        p = self.params
        df = inputs["df"]
        if p.y_column not in df.columns:
            raise ValueError(f"regression: y column {p.y_column!r} is not in the data.")
        x_cols = [
            c for c in (p.x_columns or [])
            if c in df.columns and c != p.y_column
        ]
        if not x_cols:
            raise ValueError("regression: tick at least one predictor column.")

        data = df[[p.y_column, *x_cols]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(data) <= len(x_cols) + 1:
            raise ValueError("regression: not enough complete rows to fit the model.")
        y = data[p.y_column].to_numpy("float64")
        X = data[x_cols].to_numpy("float64")
        if p.add_intercept:
            X = sm.add_constant(X, has_constant="add")
        term_names = (["const", *x_cols] if p.add_intercept else list(x_cols))

        if p.model == "ols":
            fit_kw = {} if p.robust_se == "none" else {"cov_type": p.robust_se}
            res = sm.OLS(y, X).fit(**fit_kw)
        elif p.model == "rlm":
            res = sm.RLM(y, X).fit()
        elif p.model == "poisson":
            res = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        elif p.model == "probit":
            res = sm.Probit(y, X).fit(disp=0)
        else:  # logit
            res = sm.Logit(y, X).fit(disp=0)

        alpha = 1.0 - float(p.confidence_level)
        ci = np.asarray(res.conf_int(alpha=alpha))
        coeffs = pd.DataFrame(
            {
                "term": term_names,
                "coef": np.asarray(res.params, dtype="float64"),
                "std_err": np.asarray(res.bse, dtype="float64"),
                "stat": np.asarray(res.tvalues, dtype="float64"),
                "pvalue": np.asarray(res.pvalues, dtype="float64"),
                "ci_low": ci[:, 0],
                "ci_high": ci[:, 1],
            }
        )

        resid = getattr(res, "resid_response", None)
        if resid is None:
            resid = res.resid
        residuals = pd.DataFrame(
            {
                "row": data.index.to_numpy(),
                "fitted": np.asarray(res.fittedvalues, dtype="float64"),
                "residual": np.asarray(resid, dtype="float64"),
            }
        )
        return {"coeffs": coeffs, "residuals": residuals}


# --------------------------------------------------------------------------
# PCA
# --------------------------------------------------------------------------


class PCAParams(NodeParams):
    """
    Attributes:
        n_components: Number of components to keep. 0 = keep every
            component (``min(n_rows, n_columns)``).
        standardize: Standardize each column (zero mean, unit variance)
            before fitting -- recommended unless the columns are
            already on comparable scales, since PCA is sensitive to it.
        random_state: Seed for the randomized SVD solver (large inputs
            only; ignored otherwise).

    Runs on every numeric column of the input -- drop the ones you
    don't want with a ``column_filter`` / ``dtype_filter`` first.
    """

    n_components: int = 0
    standardize: bool = True
    random_state: int = 0


@register_node
class PCA(Node):
    """
    Principal component analysis: reduce numeric columns to
    uncorrelated components. ``scores`` is the transformed data
    (PC1, PC2, ...); ``loadings`` is each original variable's weight in
    each component; ``variance`` is the (cumulative) share of variance
    each component explains.
    """

    node_type = "pca"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [
        Port(name="scores", dtype="dataframe"),
        Port(name="loadings", dtype="dataframe"),
        Port(name="variance", dtype="dataframe"),
    ]
    params_schema = PCAParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from sklearn.decomposition import PCA as SkPCA
        from sklearn.preprocessing import StandardScaler

        p = self.params
        df = inputs["df"]
        columns = df.select_dtypes(include="number").columns.tolist()
        if len(columns) < 2:
            raise ValueError("pca: need at least 2 numeric columns.")

        data = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
        if len(data) < 2:
            raise ValueError("pca: not enough complete rows (need at least 2).")

        X = data.to_numpy("float64")
        if p.standardize:
            X = StandardScaler().fit_transform(X)

        n_components = min(int(p.n_components), len(columns), len(data)) if p.n_components else None
        model = SkPCA(n_components=n_components, random_state=int(p.random_state))
        transformed = model.fit_transform(X)

        pc_names = [f"PC{i + 1}" for i in range(transformed.shape[1])]
        scores = pd.DataFrame(transformed, columns=pc_names, index=data.index)

        loadings = pd.DataFrame(
            model.components_.T, index=pd.Index(columns, name="variable"), columns=pc_names
        ).reset_index()

        ratio = model.explained_variance_ratio_
        variance = pd.DataFrame(
            {
                "component": pc_names,
                "explained_variance": model.explained_variance_,
                "explained_variance_ratio": ratio,
                "cumulative_variance_ratio": np.cumsum(ratio),
            }
        )
        return {"scores": scores, "loadings": loadings, "variance": variance}


# --------------------------------------------------------------------------
# ICA
# --------------------------------------------------------------------------


class ICAParams(NodeParams):
    """
    Attributes:
        n_components: Number of independent components to extract.
            0 = same as the number of input columns.
        algorithm: FastICA fitting strategy -- "parallel" (all
            components at once) or "deflation" (one at a time).
        fun: Nonlinearity used to approximate negentropy -- "logcosh"
            (general-purpose default), "exp" or "cube".
        whiten: Whitening strategy before unmixing.
        standardize: Standardize each column (zero mean, unit variance)
            before fitting.
        max_iter / tol: Fitting controls.
        random_state: Seed.

    Runs on every numeric column of the input.
    """

    n_components: int = 0
    algorithm: Literal["parallel", "deflation"] = "parallel"
    fun: Literal["logcosh", "exp", "cube"] = "logcosh"
    whiten: Literal["unit-variance", "arbitrary-variance"] = "unit-variance"
    standardize: bool = True
    max_iter: int = 200
    tol: float = 1e-4
    random_state: int = 0


@register_node
class ICA(Node):
    """
    Independent component analysis: separate numeric columns into
    statistically independent source signals. ``sources`` is the
    transformed data (IC1, IC2, ...); ``mixing`` is each original
    variable's weight in each source (the FastICA mixing matrix,
    the ICA analogue of PCA's loadings).
    """

    node_type = "ica"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [
        Port(name="sources", dtype="dataframe"),
        Port(name="mixing", dtype="dataframe"),
    ]
    params_schema = ICAParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from sklearn.decomposition import FastICA
        from sklearn.preprocessing import StandardScaler

        p = self.params
        df = inputs["df"]
        columns = df.select_dtypes(include="number").columns.tolist()
        if len(columns) < 2:
            raise ValueError("ica: need at least 2 numeric columns.")

        data = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
        if len(data) < 2:
            raise ValueError("ica: not enough complete rows (need at least 2).")

        X = data.to_numpy("float64")
        if p.standardize:
            X = StandardScaler().fit_transform(X)

        n_components = min(int(p.n_components), len(columns), len(data)) if p.n_components else None
        model = FastICA(
            n_components=n_components, algorithm=p.algorithm, fun=p.fun,
            whiten=p.whiten, max_iter=int(p.max_iter), tol=float(p.tol),
            random_state=int(p.random_state),
        )
        transformed = model.fit_transform(X)

        ic_names = [f"IC{i + 1}" for i in range(transformed.shape[1])]
        sources = pd.DataFrame(transformed, columns=ic_names, index=data.index)
        mixing = pd.DataFrame(
            model.mixing_, index=pd.Index(columns, name="variable"), columns=ic_names
        ).reset_index()
        return {"sources": sources, "mixing": mixing}


# --------------------------------------------------------------------------
# t-SNE
# --------------------------------------------------------------------------


class TSNEParams(NodeParams):
    """
    Attributes:
        n_components: Embedding dimensionality (2 or 3, typically).
        perplexity: Roughly the number of effective nearest neighbours
            considered for each point; balances local vs. global
            structure. Must be less than the number of rows.
        learning_rate: "auto" (scikit-learn's heuristic, the default)
            or a fixed positive number.
        max_iter: Maximum optimisation iterations.
        metric: Distance metric in the original space.
        init: Embedding initialisation -- "pca" (deterministic,
            default) or "random".
        standardize: Standardize each column before fitting.
        random_state: Seed.

    Runs on every numeric column of the input.
    """

    n_components: int = 2
    perplexity: float = 30.0
    learning_rate: str = suggestions_field(
        suggestions=["auto", "10", "50", "200", "500", "1000"], default="auto",
    )
    max_iter: int = 1000
    metric: Literal["euclidean", "manhattan", "cosine", "chebyshev"] = "euclidean"
    init: Literal["pca", "random"] = "pca"
    standardize: bool = True
    random_state: int = 0


@register_node
class TSNE(Node):
    """
    t-SNE: a nonlinear embedding (2D/3D, typically) for visualising
    structure/clusters in numeric columns. Direct output only (an
    embedding table) -- t-SNE has no ``transform`` for new data, so
    there is no reusable "model" the way a fit node produces one.
    """

    node_type = "tsne"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = TSNEParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        from sklearn.manifold import TSNE as SkTSNE
        from sklearn.preprocessing import StandardScaler

        p = self.params
        df = inputs["df"]
        columns = df.select_dtypes(include="number").columns.tolist()
        if len(columns) < 2:
            raise ValueError("tsne: need at least 2 numeric columns.")

        data = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
        n_components = max(int(p.n_components), 1)
        if len(data) < n_components + 1:
            raise ValueError("tsne: not enough complete rows.")

        X = data.to_numpy("float64")
        if p.standardize:
            X = StandardScaler().fit_transform(X)

        lr_text = (p.learning_rate or "auto").strip()
        learning_rate: str | float = "auto" if lr_text.lower() == "auto" else float(lr_text)

        model = SkTSNE(
            n_components=n_components, perplexity=float(p.perplexity),
            learning_rate=learning_rate, max_iter=int(p.max_iter),
            metric=p.metric, init=p.init, random_state=int(p.random_state),
        )
        embedding = model.fit_transform(X)
        names = [f"tsne_{i + 1}" for i in range(embedding.shape[1])]
        return {"df": pd.DataFrame(embedding, columns=names, index=data.index)}


# --------------------------------------------------------------------------
# ARIMA / AutoARIMA (statsmodels SARIMAX; the seasonal (P, D, Q, s) term
# is how these handle/remove seasonality -- see ``ArimaParams.seasonal``)
# --------------------------------------------------------------------------


def _fit_sarimax(
    x: np.ndarray, order: tuple[int, int, int], seasonal_order: tuple[int, int, int, int],
    trend: str,
) -> Any:
    """Fit a (seasonal) ARIMA model. Assumes ``x`` is already ordered by
    time (see the ``sort`` transform)."""
    import warnings

    from statsmodels.tsa.statespace.sarimax import SARIMAX

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return SARIMAX(
            x, order=order, seasonal_order=seasonal_order, trend=trend,
            enforce_stationarity=False, enforce_invertibility=False,
            concentrate_scale=True,  # ~25% faster, statistically equivalent
        ).fit(disp=False)


def _residuals_table(res: Any) -> pd.DataFrame:
    """One-step-ahead residuals of a fitted (SAR)IMA model."""
    resid = np.asarray(res.resid, dtype="float64")
    fitted = np.asarray(res.fittedvalues, dtype="float64")
    sd = float(np.nanstd(resid)) or 1.0
    return pd.DataFrame(
        {
            "step": np.arange(1, len(resid) + 1),
            "fitted": fitted[: len(resid)],
            "residual": resid,
            "standardized_residual": resid / sd,
        }
    )


class ArimaForecast:
    """Lightweight, picklable bundle put on an ``arima`` / ``auto_arima``
    ``model`` output port: enough for ``forecast_plot`` to draw the
    history + forecast without carrying the (non-cacheable) statsmodels
    results object. Mirrors the ``ruyso_*`` interface the ``var`` node's
    model uses, so the shared plot helper reads it the same way."""

    def __init__(
        self, res: Any, x: np.ndarray, column: str,
        forecast_periods: int, confidence_level: float,
        order: tuple, seasonal_order: tuple,
    ) -> None:
        alpha = 1.0 - float(confidence_level)
        fc = res.get_forecast(steps=max(int(forecast_periods), 1))
        mean = np.asarray(fc.predicted_mean, dtype="float64")
        ci = np.asarray(fc.conf_int(alpha=alpha), dtype="float64")
        self.ruyso_method = "arima"
        self.ruyso_names = [column]
        self.ruyso_endog = pd.DataFrame({column: np.asarray(x, dtype="float64")})
        self.ruyso_forecast_periods = int(max(int(forecast_periods), 1))
        self.ruyso_forecast = pd.DataFrame(
            {"mid": mean, "low": ci[:, 0], "high": ci[:, 1]}
        )
        self.ruyso_order = str(order)
        self.ruyso_seasonal_order = str(seasonal_order)


def _forecast_table(res: Any, forecast_periods: int, confidence_level: float) -> pd.DataFrame:
    alpha = 1.0 - float(confidence_level)
    forecast = res.get_forecast(steps=max(int(forecast_periods), 1))
    mean = np.asarray(forecast.predicted_mean, dtype="float64")
    ci = np.asarray(forecast.conf_int(alpha=alpha), dtype="float64")
    return pd.DataFrame(
        {
            "step": np.arange(1, len(mean) + 1),
            "forecast": mean,
            "ci_low": ci[:, 0],
            "ci_high": ci[:, 1],
        }
    )


def _fit_summary_table(
    res: Any, order: tuple[int, int, int], seasonal_order: tuple[int, int, int, int]
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "order": str(order),
                "seasonal_order": str(seasonal_order),
                "aic": float(res.aic),
                "bic": float(res.bic),
                "log_likelihood": float(res.llf),
                "n_obs": int(res.nobs),
            }
        ]
    )


class ArimaParams(NodeParams):
    """
    Attributes:
        column: Numeric time-series column, already ordered by time
            (see the ``sort`` transform).
        p / d / q: Non-seasonal ARIMA order -- AR terms, differencing,
            MA terms.
        seasonal: Also fit a seasonal (P, D, Q, s) component -- this is
            how a seasonal pattern is taken out of the series (a
            seasonal difference, ``D`` >= 1, removes it structurally;
            the seasonal AR/MA terms model what's left of it).
        P / D / Q: Seasonal order (used only when ``seasonal`` is on).
        seasonal_periods: s -- the season length (e.g. 12 for monthly
            data with a yearly cycle, 7 for daily with a weekly cycle).
        trend: Deterministic trend term -- "n" none, "c" constant,
            "t" linear, "ct" both.
        forecast_periods: Steps to forecast beyond the data.
        confidence_level: Confidence level for the forecast interval.
    """

    column: str = column_field(dtypes=("numeric",))
    p: int = 1
    d: int = 0
    q: int = 0
    seasonal: bool = False
    P: int = visible_field(0, visible_when=("seasonal", "True"))
    D: int = visible_field(0, visible_when=("seasonal", "True"))
    Q: int = visible_field(0, visible_when=("seasonal", "True"))
    seasonal_periods: int = visible_field(12, visible_when=("seasonal", "True"))
    trend: Literal["n", "c", "t", "ct"] = "c"
    forecast_periods: int = 10
    confidence_level: float = unit_interval_field(0.95, lo=0.5, hi=0.999)


@register_node
class Arima(Node):
    """
    ARIMA(p,d,q)(P,D,Q)s: fit a (seasonal) ARIMA model on a chosen
    order and forecast forward. ``fit`` is a one-row summary (order,
    AIC/BIC, log-likelihood); ``forecast`` has one row per step
    (forecast value + confidence interval). See ``auto_arima`` for an
    automatic order search.
    """

    node_type = "arima"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [
        Port(name="fit", dtype="dataframe"),
        Port(name="forecast", dtype="dataframe"),
        Port(name="residuals", dtype="dataframe"),
        Port(name="model", dtype="model"),
    ]
    params_schema = ArimaParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        x = _num(inputs["df"], p.column, "arima").dropna().to_numpy("float64")
        if x.size < 10:
            raise ValueError("arima: need at least 10 non-missing values.")

        order = (int(p.p), int(p.d), int(p.q))
        seasonal_order = (
            (int(p.P), int(p.D), int(p.Q), int(p.seasonal_periods))
            if p.seasonal else (0, 0, 0, 0)
        )
        res = _fit_sarimax(x, order, seasonal_order, p.trend)
        return {
            "fit": _fit_summary_table(res, order, seasonal_order),
            "forecast": _forecast_table(res, p.forecast_periods, p.confidence_level),
            "residuals": _residuals_table(res),
            "model": ArimaForecast(
                res, x, p.column, p.forecast_periods, p.confidence_level,
                order, seasonal_order,
            ),
        }


def _select_d(x: np.ndarray, max_d: int) -> int:
    """
    ADF-based differencing order: the smallest ``d`` in ``[0, max_d]``
    at which the ``d``-times-differenced series looks stationary (ADF
    p-value < 0.05); ``max_d`` if none does.
    """
    import warnings

    from statsmodels.tsa.stattools import adfuller

    series = x.astype("float64", copy=True)
    for d in range(max_d + 1):
        if len(series) < 10:
            return d
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                pval = float(adfuller(series, autolag="AIC")[1])
            except (ValueError, np.linalg.LinAlgError):
                return d
        if pval < 0.05:
            return d
        series = np.diff(series)
    return max_d


def _stepwise_search(
    x: np.ndarray, max_p: int, d: int, max_q: int, seasonal: bool,
    max_P: int, D: int, max_Q: int, seasonal_periods: int, trend: str, ic: str,
) -> tuple[tuple[int, int, int], tuple[int, int, int, int], Any]:
    """
    Hyndman-Khandakar-style stepwise search: hill-climb over (p, q)
    (and (P, Q), if ``seasonal``) from a few seed models, at each step
    moving to whichever neighbour ((p +/- 1, q), (p, q +/- 1), ...)
    improves ``ic`` (AIC or BIC) the most, until none does. This finds
    a good order in a handful of fits instead of a full grid over every
    (p, q) combination -- the same idea as the reference R
    implementation, simplified: ``d`` comes from ``_select_d`` and
    ``D`` from a fixed rule (see ``AutoArimaParams``), not a
    seasonal unit-root test.
    """
    import warnings

    from statsmodels.tsa.statespace.sarimax import SARIMAX

    def ic_of(res: Any) -> float:
        return float(res.aic if ic == "aic" else res.bic)

    #: Hard cap on model fits. A seasonal SARIMAX fit costs ~1s, so an
    #: unbounded hill-climb over (p, q, P, Q) can run for minutes; past
    #: this many fits the search stops and returns the best found so far.
    budget = 24 if seasonal else 200
    n_fits = 0

    def fit(p: int, q: int, P: int, Q: int) -> Any:
        s_order = (P, D, Q, seasonal_periods) if seasonal else (0, 0, 0, 0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return SARIMAX(
                x, order=(p, d, q), seasonal_order=s_order, trend=trend,
                enforce_stationarity=False, enforce_invertibility=False,
                concentrate_scale=True,
            ).fit(disp=False)

    # Lighter seeds when seasonal (each fit is ~1s): start small.
    if seasonal:
        seeds = [(1, 1, 1, 1), (0, 0, 1, 0), (0, 0, 0, 1), (1, 0, 0, 0)]
    else:
        seeds = [
            (min(2, max_p), min(2, max_q), 0, 0), (0, 0, 0, 0), (1, 0, 0, 0), (0, 1, 0, 0),
        ]

    best: tuple[int, int, int, int] | None = None
    best_ic = float("inf")
    best_res: Any = None
    tried: set[tuple[int, int, int, int]] = set()

    def try_point(p: int, q: int, P: int, Q: int) -> None:
        nonlocal best, best_ic, best_res, n_fits
        key = (p, q, P, Q)
        if n_fits >= budget or key in tried or not (0 <= p <= max_p and 0 <= q <= max_q):
            return
        if seasonal and not (0 <= P <= max_P and 0 <= Q <= max_Q):
            return
        tried.add(key)
        n_fits += 1
        if p == q == P == Q == 0 and d == 0 and D == 0:
            return  # a null model is not a meaningful fit
        try:
            res = fit(p, q, P, Q)
        except Exception:  # noqa: BLE001 - an unfittable order is just skipped
            return
        value = ic_of(res)
        if value < best_ic:
            best, best_ic, best_res = key, value, res

    for seed in seeds:
        try_point(*seed)
    if best is None:
        best = (0, 0, 0, 0)
        best_res = fit(*best)
        best_ic = ic_of(best_res)

    improved = True
    while improved:
        improved = False
        p, q, P, Q = best
        neighbors = [(p + 1, q, P, Q), (p - 1, q, P, Q), (p, q + 1, P, Q), (p, q - 1, P, Q)]
        if seasonal:
            neighbors += [
                (p, q, P + 1, Q), (p, q, P - 1, Q), (p, q, P, Q + 1), (p, q, P, Q - 1),
            ]
        before = best_ic
        for candidate in neighbors:
            try_point(*candidate)
        improved = best_ic < before

    p, q, P, Q = best
    order = (p, d, q)
    seasonal_order = (P, D, Q, seasonal_periods) if seasonal else (0, 0, 0, 0)
    return order, seasonal_order, best_res


class AutoArimaParams(NodeParams):
    """
    Attributes:
        column: Numeric time-series column, already ordered by time.
        max_p / max_d / max_q: Upper bound for the non-seasonal search
            (``d`` itself is chosen automatically -- see ``arima.py``
            ``_select_d`` -- up to ``max_d``).
        seasonal: Also search a seasonal (P, D, Q, s) component -- how
            this node takes seasonality out of the series (see
            ``ArimaParams.seasonal``).
        max_P / max_Q: Upper bound for the seasonal AR/MA search order
            (used only when ``seasonal`` is on). The seasonal
            differencing order ``D`` is fixed at 1 when seasonal
            (0 otherwise), the usual rule of thumb, rather than
            searched.
        seasonal_periods: s -- the season length.
        trend: Deterministic trend term.
        information_criterion: Criterion the stepwise search minimises.
        forecast_periods / confidence_level: as ``arima``.
    """

    column: str = column_field(dtypes=("numeric",))
    max_p: int = 5
    max_d: int = 2
    max_q: int = 5
    seasonal: bool = False
    max_P: int = visible_field(2, visible_when=("seasonal", "True"))
    max_Q: int = visible_field(2, visible_when=("seasonal", "True"))
    seasonal_periods: int = visible_field(12, visible_when=("seasonal", "True"))
    trend: Literal["n", "c", "t", "ct"] = "c"
    information_criterion: Literal["aic", "bic"] = "aic"
    forecast_periods: int = 10
    confidence_level: float = unit_interval_field(0.95, lo=0.5, hi=0.999)


@register_node
class AutoArima(Node):
    """
    Stepwise ARIMA order search (Hyndman-Khandakar-style, minimizing
    AIC/BIC -- see ``_stepwise_search``), then forecast forward with
    the chosen order. Same outputs as ``arima``, plus the search
    reveals its choice through the ``order`` / ``seasonal_order``
    columns of ``fit``.
    """

    node_type = "auto_arima"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [
        Port(name="fit", dtype="dataframe"),
        Port(name="forecast", dtype="dataframe"),
        Port(name="residuals", dtype="dataframe"),
        Port(name="model", dtype="model"),
    ]
    params_schema = AutoArimaParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        x = _num(inputs["df"], p.column, "auto_arima").dropna().to_numpy("float64")
        min_needed = 3 * int(p.seasonal_periods) if p.seasonal else 10
        if x.size < max(min_needed, 10):
            raise ValueError(
                "auto_arima: not enough non-missing values for the requested search."
            )

        d = _select_d(x, max(int(p.max_d), 0))
        D = 1 if p.seasonal else 0  # the usual rule of thumb, not searched

        order, seasonal_order, res = _stepwise_search(
            x, max(int(p.max_p), 0), d, max(int(p.max_q), 0), p.seasonal,
            max(int(p.max_P), 0), D, max(int(p.max_Q), 0), int(p.seasonal_periods),
            p.trend, p.information_criterion,
        )
        return {
            "fit": _fit_summary_table(res, order, seasonal_order),
            "forecast": _forecast_table(res, p.forecast_periods, p.confidence_level),
            "residuals": _residuals_table(res),
            "model": ArimaForecast(
                res, x, p.column, p.forecast_periods, p.confidence_level,
                order, seasonal_order,
            ),
        }


# --------------------------------------------------------------------------
# Seasonal decomposition: split a series into trend + seasonal +
# remainder (STL, or the classical moving-average method).
# --------------------------------------------------------------------------


class SeasonalDecomposeParams(NodeParams):
    """
    Attributes:
        column: Numeric time-series column, already ordered by time
            (see the ``sort`` transform).
        method: ``stl`` (LOESS-based, handles a changing seasonal
            shape, always additive) or ``classical`` (a centred
            moving-average decomposition; supports a multiplicative
            model).
        period: Season length -- e.g. 12 for monthly data with a
            yearly cycle, 7 for daily with a weekly one.
        model: Additive vs multiplicative (classical only).
        two_sided: Use a centred moving average (classical only);
            off = a trailing one.
        extrapolate_trend: Fill this many trend points at each end by
            linear extrapolation instead of leaving them missing
            (classical only; 0 = leave as NaN).
        stl_seasonal: Length of the seasonal LOESS smoother -- an odd
            number >= 7 (STL only). Larger = a smoother, more slowly
            changing seasonal component.
        stl_trend: Length of the trend LOESS smoother -- an odd number
            larger than ``period`` (STL only; 0 = statsmodels' default).
        robust: Down-weight outliers in the STL fit (STL only).
    """

    column: str = column_field(dtypes=("numeric",))
    method: Literal["stl", "classical"] = "stl"
    period: int = 12
    model: Literal["additive", "multiplicative"] = visible_field(
        "additive", visible_when=("method", "classical")
    )
    two_sided: bool = visible_field(True, visible_when=("method", "classical"))
    extrapolate_trend: int = visible_field(0, visible_when=("method", "classical"))
    stl_seasonal: int = visible_field(7, visible_when=("method", "stl"))
    stl_trend: int = visible_field(0, visible_when=("method", "stl"))
    robust: bool = visible_field(False, visible_when=("method", "stl"))


@register_node
class SeasonalDecompose(Node):
    """
    Split a time series into **trend**, **seasonal** and **remainder**
    components (plus the seasonally-adjusted series), by STL or the
    classical moving-average method. One row per observation.
    """

    node_type = "seasonal_decompose"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [Port(name="components", dtype="dataframe")]
    params_schema = SeasonalDecomposeParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        s = _num(inputs["df"], p.column, "seasonal_decompose").dropna().reset_index(drop=True)
        period = max(int(p.period), 2)
        if s.size < 2 * period:
            raise ValueError(
                f"seasonal_decompose: need at least {2 * period} non-missing values "
                f"for period {period}."
            )

        if p.method == "stl":
            from statsmodels.tsa.seasonal import STL

            seasonal = int(p.stl_seasonal)
            if seasonal < 7 or seasonal % 2 == 0:
                seasonal = max(7, seasonal + (1 - seasonal % 2))
            kw: dict[str, Any] = {"period": period, "seasonal": seasonal, "robust": bool(p.robust)}
            if int(p.stl_trend) > 0:
                trend = int(p.stl_trend)
                kw["trend"] = trend + (1 - trend % 2)  # force odd
            res = STL(s.to_numpy("float64"), **kw).fit()
            observed = s.to_numpy("float64")
            trend_c = np.asarray(res.trend, dtype="float64")
            seasonal_c = np.asarray(res.seasonal, dtype="float64")
            resid_c = np.asarray(res.resid, dtype="float64")
            adjusted = observed - seasonal_c
        else:
            from statsmodels.tsa.seasonal import seasonal_decompose

            res = seasonal_decompose(
                s.to_numpy("float64"), model=p.model, period=period,
                two_sided=bool(p.two_sided),
                extrapolate_trend=int(p.extrapolate_trend),
            )
            observed = np.asarray(res.observed, dtype="float64")
            trend_c = np.asarray(res.trend, dtype="float64")
            seasonal_c = np.asarray(res.seasonal, dtype="float64")
            resid_c = np.asarray(res.resid, dtype="float64")
            adjusted = (
                observed / seasonal_c if p.model == "multiplicative"
                else observed - seasonal_c
            )

        return {
            "components": pd.DataFrame(
                {
                    "step": np.arange(1, len(observed) + 1),
                    "observed": observed,
                    "trend": trend_c,
                    "seasonal": seasonal_c,
                    "resid": resid_c,
                    "seasonally_adjusted": adjusted,
                }
            )
        }


# --------------------------------------------------------------------------
# VAR / VECM (vector autoregression, statsmodels)
# --------------------------------------------------------------------------


def _var_data(df: pd.DataFrame, variables: list[str] | None, dt_col: str, ctx: str):
    """(numeric DataFrame of the chosen variables, index name) for a VAR/VECM fit."""
    cols = [c for c in (variables or []) if c in df.columns and c != dt_col]
    if len(cols) < 2:
        raise ValueError(f"{ctx}: tick at least two variables to include in the model.")
    data = df[cols].apply(pd.to_numeric, errors="coerce")
    index_name = "index"
    if dt_col and dt_col in df.columns:
        idx = pd.to_datetime(df[dt_col], errors="coerce")
        data = data.set_index(idx).sort_index()
        index_name = dt_col
    data = data.dropna()
    if len(data) < 3 * len(cols) + 5:
        raise ValueError(f"{ctx}: not enough complete rows to fit the model.")
    return data, index_name


def _var_coeff_table(res: Any) -> pd.DataFrame:
    """Long coefficient table for a fitted ``VARResults`` (one row per equation x term)."""
    params, se = res.params, res.stderr
    tvals, pvals = res.tvalues, res.pvalues
    rows = []
    for eq in params.columns:
        for term in params.index:
            rows.append(
                {
                    "equation": str(eq),
                    "term": str(term),
                    "coef": float(params.loc[term, eq]),
                    "std_err": float(se.loc[term, eq]),
                    "stat": float(tvals.loc[term, eq]),
                    "pvalue": float(pvals.loc[term, eq]),
                }
            )
    return pd.DataFrame(rows)


def _vecm_coeff_table(res: Any, names: list[str]) -> pd.DataFrame:
    """Long coefficient table for a fitted ``VECMResults`` (short-run + loadings)."""
    neqs = len(names)
    gamma = np.asarray(res.gamma, dtype="float64")
    k_ar_diff = gamma.shape[1] // neqs if neqs else 0
    se_g = np.asarray(getattr(res, "stderr_gamma", np.full_like(gamma, np.nan)))
    pv_g = np.asarray(getattr(res, "pvalues_gamma", np.full_like(gamma, np.nan)))
    alpha = np.asarray(res.alpha, dtype="float64")
    se_a = np.asarray(getattr(res, "stderr_alpha", np.full_like(alpha, np.nan)))
    pv_a = np.asarray(getattr(res, "pvalues_alpha", np.full_like(alpha, np.nan)))
    rows = []
    for i, eq in enumerate(names):
        for d in range(k_ar_diff):
            for j in range(neqs):
                col = d * neqs + j
                rows.append(
                    {
                        "equation": eq,
                        "term": f"L{d + 1}.d.{names[j]}",
                        "coef": float(gamma[i, col]),
                        "std_err": float(se_g[i, col]),
                        "stat": np.nan,
                        "pvalue": float(pv_g[i, col]),
                    }
                )
        for k in range(alpha.shape[1]):
            rows.append(
                {
                    "equation": eq,
                    "term": f"ec{k + 1}",  # loading on cointegration relation k
                    "coef": float(alpha[i, k]),
                    "std_err": float(se_a[i, k]),
                    "stat": np.nan,
                    "pvalue": float(pv_a[i, k]),
                }
            )
    return pd.DataFrame(rows)


class VarParams(NodeParams):
    """
    Parameters for Var.

    Attributes:
        method: ``var`` -- a level VAR (``statsmodels`` ``VAR``);
            ``vecm`` -- a vector error-correction model for cointegrated
            series (``statsmodels`` ``VECM``).
        datetime_column: Optional datetime column to use as the time
            index (blank = keep the row order). Rows are sorted by it.
        variables: The series to include in the system (tickboxes,
            two or more).
        lags: VAR order (number of lagged levels), or for a VECM the
            number of lagged differences ``k_ar_diff``. When
            ``optimize_lag`` is on this is the *maximum* order searched.
        optimize_lag: Search every order from 1 up to ``lags`` and keep
            the one that minimises ``ic`` (``VAR.fit(ic=...)`` /
            ``vecm.select_order``).
        ic: Information criterion for the ``optimize_lag`` search.
        trend: VAR only -- deterministic terms (``n`` none, ``c``
            constant, ``ct`` constant + trend, ``ctt`` + quadratic).
        deterministic: VECM only -- deterministic terms inside /
            outside the cointegration relation (``ci`` constant inside,
            ``co`` constant outside, ``li`` / ``lo`` linear trend,
            ``n`` none).
        coint_rank: VECM only -- number of cointegration relations.
        forecast_periods: Steps ahead for the ``forecast`` output.
        confidence_level: Confidence level for the forecast interval.
    """

    method: Literal["var", "vecm"] = "var"
    datetime_column: str = column_field(dtypes=("datetime", "any"), allow_none=True, default="")
    variables: list[str] | None = checkbox_list_field(source="columns", default=None)
    lags: int = 1
    optimize_lag: bool = False
    ic: Literal["aic", "bic", "hqic", "fpe"] = visible_field(
        "aic", visible_when=("optimize_lag", "True"),
        description="Information criterion for the lag-order search.",
    )
    trend: Literal["n", "c", "ct", "ctt"] = visible_field(
        "c", visible_when=("method", "var"),
    )
    deterministic: Literal["n", "co", "ci", "lo", "li"] = visible_field(
        "ci", visible_when=("method", "vecm"),
    )
    coint_rank: int = visible_field(1, visible_when=("method", "vecm"))
    forecast_periods: int = 10
    confidence_level: float = unit_interval_field(0.95, lo=0.5, hi=0.999)


@register_node
class Var(Node):
    """
    Fit a vector autoregression (VAR) or vector error-correction model
    (VECM) on two or more time series.

    Outputs the full coefficient table (``coeffs``), the per-equation
    residuals (``residuals``), a multi-step forecast with interval
    (``forecast``), and the fitted ``model`` object -- consumed by
    ``var_test`` and the ``var_*`` / ``irf`` grapher nodes.
    """

    node_type = "var"
    category = "statistics"
    inputs = list(_STATS_INPUTS)
    outputs = [
        Port(name="coeffs", dtype="dataframe"),
        Port(name="residuals", dtype="dataframe"),
        Port(name="forecast", dtype="dataframe"),
        Port(name="model", dtype="model"),
    ]
    params_schema = VarParams
    # statsmodels results wrappers are heavy and not reliably hashable.
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        data, index_name = _var_data(
            inputs["df"], p.variables, p.datetime_column, "var"
        )
        names = list(data.columns)
        alpha = 1.0 - float(p.confidence_level)
        lags = max(int(p.lags), 1)
        steps_ahead = max(int(p.forecast_periods), 1)

        if p.method == "var":
            from statsmodels.tsa.api import VAR

            if p.optimize_lag:
                fitted = VAR(data).fit(maxlags=lags, ic=p.ic, trend=p.trend)
            else:
                fitted = VAR(data).fit(lags, trend=p.trend)
            selected_lag = int(fitted.k_ar)
            coeffs = _var_coeff_table(fitted)
            resid = fitted.resid.copy()
            resid.index.name = index_name
            residuals = resid.reset_index()
            mid, low, high = fitted.forecast_interval(
                data.values[-fitted.k_ar:], steps_ahead, alpha=alpha,
            )
        else:
            from statsmodels.tsa.vector_ar.vecm import VECM, select_order

            if p.optimize_lag:
                k_ar_diff = int(
                    select_order(
                        data, maxlags=lags, deterministic=p.deterministic
                    ).selected_orders[p.ic]
                )
            else:
                k_ar_diff = lags
            selected_lag = k_ar_diff
            fitted = VECM(
                data, k_ar_diff=k_ar_diff, coint_rank=max(int(p.coint_rank), 1),
                deterministic=p.deterministic,
            ).fit()
            coeffs = _vecm_coeff_table(fitted, names)
            resid_arr = np.asarray(fitted.resid, dtype="float64")
            resid = pd.DataFrame(
                resid_arr, columns=names, index=data.index[-len(resid_arr):]
            )
            resid.index.name = index_name
            residuals = resid.reset_index()
            mid, low, high = fitted.predict(steps=steps_ahead, alpha=alpha)

        steps = np.arange(1, len(mid) + 1)
        forecast = pd.DataFrame(
            {
                "step": np.repeat(steps, len(names)),
                "variable": np.tile(names, len(steps)),
                "forecast": np.asarray(mid, dtype="float64").ravel(),
                "ci_low": np.asarray(low, dtype="float64").ravel(),
                "ci_high": np.asarray(high, dtype="float64").ravel(),
            }
        )

        # Stashed for the var_* grapher nodes (history + names + settings,
        # no re-derivation).
        fitted.ruyso_names = names
        fitted.ruyso_endog = data
        fitted.ruyso_method = p.method
        fitted.ruyso_forecast_periods = steps_ahead
        fitted.ruyso_selected_lag = selected_lag
        return {
            "coeffs": coeffs,
            "residuals": residuals,
            "forecast": forecast,
            "model": fitted,
        }


class VarTestParams(NodeParams):
    """
    Parameters for VarTest.

    Attributes:
        test: Which diagnostic to run on the fitted VAR/VECM:

            * ``granger_causality`` -- do the ``causing`` variables
              Granger-cause the ``caused`` ones (Wald / F test on the
              lag coefficients)?
            * ``instantaneous_causality`` -- contemporaneous
              (same-period) causality between ``causing`` and the rest.
            * ``normality`` -- Jarque-Bera on the residuals (joint,
              skew, kurtosis).
            * ``whiteness`` -- Portmanteau / Ljung-Box test for
              residual autocorrelation up to ``whiteness_lags``.
        causing / caused: Variable subsets for the causality tests
            (tickboxes).
        whiteness_lags: Number of lags for the whiteness test.
        adjusted: Use the small-sample-adjusted (Ljung-Box) statistic.
        signif: Significance level for the reported conclusion.
    """

    test: Literal[
        "granger_causality", "instantaneous_causality", "normality", "whiteness"
    ] = "granger_causality"
    causing: list[str] | None = checkbox_list_field(
        source="columns", default=None,
        visible_when_in=("test", ("granger_causality", "instantaneous_causality")),
    )
    caused: list[str] | None = checkbox_list_field(
        source="columns", default=None,
        visible_when_in=("test", ("granger_causality",)),
    )
    whiteness_lags: int = visible_field(12, visible_when=("test", "whiteness"))
    adjusted: bool = visible_field(False, visible_when=("test", "whiteness"))
    signif: float = unit_interval_field(0.05, lo=0.001, hi=0.2)


@register_node
class VarTest(Node):
    """
    Diagnostic hypothesis tests on a fitted VAR / VECM (``model`` port
    from the ``var`` node): Granger / instantaneous causality, residual
    normality, and residual whiteness (no autocorrelation).
    """

    node_type = "var_test"
    category = "statistics"
    inputs = [Port(name="model", dtype="model")]
    outputs = list(_STATS_OUTPUTS)
    params_schema = VarTestParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        model = inputs["model"]
        names = list(getattr(model, "ruyso_names", []) or getattr(model, "names", []) or [])
        signif = float(p.signif)

        def _pick(sel: list[str] | None, fallback: list[str]) -> list[str]:
            chosen = [c for c in (sel or []) if c in names]
            return chosen or fallback

        if p.test in ("granger_causality", "instantaneous_causality"):
            causing = _pick(p.causing, names[:1])
            if p.test == "granger_causality":
                caused = _pick(p.caused, [c for c in names if c not in causing] or names)
                fn = getattr(model, "test_causality", None) or getattr(
                    model, "test_granger_causality"
                )
                res = fn(caused, causing, signif=signif)
                extra = {"causing": ", ".join(causing), "caused": ", ".join(caused)}
            else:
                fn = getattr(model, "test_inst_causality")
                res = fn(causing, signif=signif)
                extra = {"causing": ", ".join(causing), "caused": ""}
        elif p.test == "normality":
            res = model.test_normality(signif=signif)
            extra = {}
        else:  # whiteness
            res = model.test_whiteness(
                nlags=max(int(p.whiteness_lags), 1), signif=signif,
                adjusted=bool(p.adjusted),
            )
            extra = {"nlags": int(p.whiteness_lags)}

        df_val = getattr(res, "df", None)
        conclusion = getattr(res, "conclusion_str", None) or getattr(res, "conclusion", "")
        return {
            "df": _row(
                test=p.test,
                statistic=float(res.test_statistic),
                pvalue=float(res.pvalue),
                df=str(df_val) if df_val is not None else "",
                crit_value=float(getattr(res, "crit_value", float("nan"))),
                signif=signif,
                conclusion=str(conclusion).replace("Conclusion: ", ""),
                **extra,
            )
        }
