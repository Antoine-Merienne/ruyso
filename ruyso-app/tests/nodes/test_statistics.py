"""
Tests for the statistics family nodes + the regression node.

One representative check per family: the node runs on a known frame,
outputs a DataFrame with the expected columns, and the p-value / stat
land in a sane range.
"""

import numpy as np
import pandas as pd
import pytest

from ruyso_app.nodes import statistics as S


@pytest.fixture
def frame():
    rng = np.random.default_rng(0)
    n = 200
    return pd.DataFrame(
        {
            "a": rng.normal(5.0, 2.0, n),
            "b": rng.normal(5.4, 2.0, n),
            "g2": rng.choice(["x", "y"], n),
            "g3": rng.choice(["p", "q", "r"], n),
            "cat1": rng.choice(["lo", "hi"], n),
            "cat2": rng.choice(["n", "s", "e"], n),
            "ts": np.cumsum(rng.normal(0.0, 1.0, n)),
            "ts2": np.cumsum(rng.normal(0.0, 1.0, n)),
            "pvals": rng.uniform(0.0, 1.0, n),
        }
    )


def test_one_sample_test_t_and_wilcoxon(frame):
    t = S.OneSampleTest(
        params=S.OneSampleTestParams(column="a", popmean=5.0)
    ).run(df=frame)["df"]
    assert list(t.columns) == [
        "test", "n", "mean", "statistic", "dof", "pvalue", "ci_low", "ci_high"
    ]
    assert 0.0 <= t.loc[0, "pvalue"] <= 1.0

    w = S.OneSampleTest(
        params=S.OneSampleTestParams(column="a", test="wilcoxon")
    ).run(df=frame)["df"]
    assert w.loc[0, "test"] == "wilcoxon"


@pytest.mark.parametrize(
    "test", ["t_test", "welch_t", "mann_whitney", "kruskal", "anova", "median_test"]
)
def test_independent_samples_tests(frame, test):
    group = "g2" if test in ("t_test", "welch_t", "mann_whitney") else "g3"
    out = S.IndependentSamplesTest(
        params=S.IndependentSamplesTestParams(
            value_column="a", group_column=group, test=test
        )
    ).run(df=frame)["df"]
    assert {"statistic", "pvalue"} <= set(out.columns)
    assert 0.0 <= out.loc[0, "pvalue"] <= 1.0


def test_independent_test_rejects_wrong_group_count(frame):
    with pytest.raises(ValueError, match="needs exactly 2 groups"):
        S.IndependentSamplesTest(
            params=S.IndependentSamplesTestParams(
                value_column="a", group_column="g3", test="t_test"
            )
        ).run(df=frame)


def test_paired_and_correlation(frame):
    p = S.PairedTest(
        params=S.PairedTestParams(column_a="a", column_b="b")
    ).run(df=frame)["df"]
    assert {"mean_diff", "ci_low", "ci_high"} <= set(p.columns)

    c = S.CorrelationTest(
        params=S.CorrelationTestParams(column_a="a", column_b="b", test="pearson")
    ).run(df=frame)["df"]
    assert -1.0 <= c.loc[0, "statistic"] <= 1.0
    assert np.isfinite(c.loc[0, "ci_low"])


def test_association_chi_square_and_fisher(frame):
    chi = S.AssociationTest(
        params=S.AssociationTestParams(column_a="cat1", column_b="cat2")
    ).run(df=frame)["df"]
    assert {"statistic", "dof", "pvalue", "cramers_v"} <= set(chi.columns)

    fisher = S.AssociationTest(
        params=S.AssociationTestParams(
            column_a="cat1", column_b="g2", test="fisher_exact"
        )
    ).run(df=frame)["df"]
    assert fisher.loc[0, "test"] == "fisher_exact"

    with pytest.raises(ValueError, match="2x2"):
        S.AssociationTest(
            params=S.AssociationTestParams(
                column_a="cat1", column_b="cat2", test="fisher_exact"
            )
        ).run(df=frame)


@pytest.mark.parametrize(
    "test", ["shapiro", "dagostino_k2", "jarque_bera", "anderson_darling", "ks_normal"]
)
def test_normality_tests(frame, test):
    out = S.NormalityTest(
        params=S.NormalityTestParams(column="a", test=test)
    ).run(df=frame)["df"]
    assert np.isfinite(out.loc[0, "statistic"])
    if test == "anderson_darling":
        assert out.loc[0, "reject_5pct"] in (True, False)
    else:
        assert 0.0 <= out.loc[0, "pvalue"] <= 1.0


@pytest.mark.parametrize("test", ["levene", "bartlett", "fligner"])
def test_variance_tests(frame, test):
    out = S.VarianceTest(
        params=S.VarianceTestParams(value_column="a", group_column="g3", test=test)
    ).run(df=frame)["df"]
    assert 0.0 <= out.loc[0, "pvalue"] <= 1.0


def test_resampling_permutation_and_bootstrap(frame):
    perm = S.ResamplingTest(
        params=S.ResamplingTestParams(
            test="permutation_mean_diff", value_column="a", group_column="g2",
            n_resamples=499,
        )
    ).run(df=frame)["df"]
    assert 0.0 <= perm.loc[0, "pvalue"] <= 1.0

    boot = S.ResamplingTest(
        params=S.ResamplingTestParams(
            test="bootstrap_mean_ci", value_column="a", n_resamples=499
        )
    ).run(df=frame)["df"]
    assert boot.loc[0, "ci_low"] < boot.loc[0, "point_estimate"] < boot.loc[0, "ci_high"]


def test_multiple_testing_adjust_and_combine(frame):
    adj = S.MultipleTesting(
        params=S.MultipleTestingParams(pvalue_column="pvals", method="fdr_bh")
    ).run(df=frame)["df"]
    assert {"adjusted_pvalue", "reject"} <= set(adj.columns)
    assert len(adj) == len(frame)
    assert (adj["adjusted_pvalue"] >= adj["pvals"] - 1e-9).all()

    comb = S.MultipleTesting(
        params=S.MultipleTestingParams(pvalue_column="pvals", method="combine_fisher")
    ).run(df=frame)["df"]
    assert list(comb.columns) == ["method", "k", "statistic", "pvalue"]


@pytest.mark.parametrize("test", ["adf", "kpss", "ljung_box", "durbin_watson"])
def test_timeseries_tests(frame, test):
    out = S.TimeSeriesTest(
        params=S.TimeSeriesTestParams(column="ts", test=test, max_lag=5)
    ).run(df=frame)["df"]
    if test == "ljung_box":
        assert list(out.columns) == ["lag", "statistic", "pvalue"] and len(out) == 5
    elif test == "durbin_watson":
        assert 0.0 <= out.loc[0, "statistic"] <= 4.0
    else:
        assert out.loc[0, "stationary"] in (True, False)


def test_timeseries_granger(frame):
    out = S.TimeSeriesTest(
        params=S.TimeSeriesTestParams(
            column="ts", column_b="ts2", test="granger", max_lag=3
        )
    ).run(df=frame)["df"]
    assert list(out.columns) == ["lag", "f_statistic", "pvalue"] and len(out) == 3


@pytest.mark.parametrize("model", ["ols", "logit", "poisson", "probit", "rlm"])
def test_regression_outputs_coeffs_and_residuals(frame, model):
    df = frame.copy()
    if model in ("logit", "probit"):
        df["y"] = (df["a"] > 5).astype(int)
    elif model == "poisson":
        df["y"] = (df["a"].clip(lower=0) * 2).round()
    else:
        df["y"] = 2.0 * df["a"] - df["b"]

    out = S.Regression(
        params=S.RegressionParams(model=model, y_column="y", x_columns=["a", "b"])
    ).run(df=df)
    coeffs, residuals = out["coeffs"], out["residuals"]
    assert list(coeffs.columns) == [
        "term", "coef", "std_err", "stat", "pvalue", "ci_low", "ci_high"
    ]
    assert list(coeffs["term"]) == ["const", "a", "b"]
    assert (coeffs["ci_low"] <= coeffs["ci_high"]).all()
    assert list(residuals.columns) == ["row", "fitted", "residual"]
    assert len(residuals) == len(df)


def test_regression_needs_predictors(frame):
    with pytest.raises(ValueError, match="at least one predictor"):
        S.Regression(
            params=S.RegressionParams(model="ols", y_column="a", x_columns=None)
        ).run(df=frame)


# -- PCA -------------------------------------------------------------


def test_pca_scores_loadings_and_variance(frame):
    out = S.PCA(params=S.PCAParams(columns=["a", "b"])).run(df=frame)
    assert list(out["scores"].columns) == ["PC1", "PC2"]
    assert len(out["scores"]) == len(frame)
    assert set(out["loadings"]["variable"]) == {"a", "b"}
    assert list(out["variance"]["component"]) == ["PC1", "PC2"]
    assert abs(out["variance"]["cumulative_variance_ratio"].iloc[-1] - 1.0) < 1e-9


def test_pca_n_components_limits_the_output():
    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {"a": rng.normal(size=50), "b": rng.normal(size=50), "c": rng.normal(size=50)}
    )
    out = S.PCA(params=S.PCAParams(n_components=1)).run(df=df)
    assert list(out["scores"].columns) == ["PC1"]


def test_pca_needs_at_least_two_numeric_columns(frame):
    with pytest.raises(ValueError, match="at least 2"):
        S.PCA(params=S.PCAParams(columns=["a"])).run(df=frame)


def test_pca_unknown_column_raises(frame):
    with pytest.raises(ValueError, match="not found"):
        S.PCA(params=S.PCAParams(columns=["a", "nope"])).run(df=frame)


# -- ARIMA / AutoARIMA ------------------------------------------------


def _ar_series(n=80, seed=0):
    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.6 * x[i - 1] + rng.normal(scale=1.0)
    return pd.DataFrame({"y": x + np.linspace(0, 5, n)})


def test_arima_fit_and_forecast_shape():
    out = S.Arima(
        params=S.ArimaParams(column="y", p=1, d=1, q=0, forecast_periods=5)
    ).run(df=_ar_series())
    assert list(out["fit"].columns) == [
        "order", "seasonal_order", "aic", "bic", "log_likelihood", "n_obs"
    ]
    assert out["fit"]["order"].iloc[0] == "(1, 1, 0)"
    assert len(out["forecast"]) == 5
    assert list(out["forecast"].columns) == ["step", "forecast", "ci_low", "ci_high"]
    assert (out["forecast"]["ci_low"] <= out["forecast"]["forecast"]).all()
    assert (out["forecast"]["forecast"] <= out["forecast"]["ci_high"]).all()


def test_arima_needs_enough_data():
    with pytest.raises(ValueError, match="at least 10"):
        S.Arima(params=S.ArimaParams(column="y")).run(df=pd.DataFrame({"y": [1.0, 2.0, 3.0]}))


def test_arima_unknown_column_raises():
    with pytest.raises(ValueError, match="not in the input data"):
        S.Arima(params=S.ArimaParams(column="nope")).run(df=_ar_series())


def test_auto_arima_finds_an_order_and_forecasts():
    out = S.AutoArima(
        params=S.AutoArimaParams(column="y", max_p=2, max_d=2, max_q=2, forecast_periods=4)
    ).run(df=_ar_series())
    assert len(out["fit"]) == 1
    assert out["fit"]["seasonal_order"].iloc[0] == "(0, 0, 0, 0)"
    assert len(out["forecast"]) == 4


def test_auto_arima_seasonal_search_picks_a_seasonal_order():
    n = 72
    t = np.arange(n)
    seasonal = 3 * np.sin(2 * np.pi * t / 12)
    x = 0.05 * t + seasonal + np.random.default_rng(1).normal(scale=0.3, size=n)
    df = pd.DataFrame({"y": x})
    out = S.AutoArima(
        params=S.AutoArimaParams(
            column="y", max_p=1, max_d=1, max_q=1,
            seasonal=True, max_P=1, max_Q=1, seasonal_periods=12, forecast_periods=3,
        )
    ).run(df=df)
    seasonal_order = out["fit"]["seasonal_order"].iloc[0]
    assert seasonal_order != "(0, 0, 0, 0)"
    assert ", 1, " in seasonal_order  # D fixed at 1 when seasonal is on


def test_auto_arima_needs_enough_data():
    with pytest.raises(ValueError, match="not enough"):
        S.AutoArima(params=S.AutoArimaParams(column="y")).run(
            df=pd.DataFrame({"y": [1.0] * 5})
        )


def test_all_statistics_nodes_are_in_the_statistics_category():
    from ruyso_app.core.registry import NodeRegistry
    import ruyso_app.nodes  # noqa: F401

    NodeRegistry.discover_package(ruyso_app.nodes)
    stat_nodes = {
        nt for nt, cls in NodeRegistry.all().items() if cls.category == "statistics"
    }
    assert "regression" in stat_nodes
    assert {"pca", "arima", "auto_arima"} <= stat_nodes
    assert len(stat_nodes) >= 14
