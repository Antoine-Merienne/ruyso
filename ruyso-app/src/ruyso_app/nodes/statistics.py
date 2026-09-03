"""
Statistics nodes (macro type ``statistics``).

One node per *family* of hypothesis test -- each with a ``test``
dropdown and per-test parameters -- plus a ``regression`` node wrapping
statsmodels' inference models (OLS / Logit / Poisson / Probit / RLM).

Every node takes a ``df`` input and produces one or more ``df``
outputs (a tidy results table), so results are browsable in the Table
tab like any other DataFrame. scipy powers the classical tests;
statsmodels powers the time-series tests and the regressions.
"""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    checkbox_list_field,
    column_field,
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
