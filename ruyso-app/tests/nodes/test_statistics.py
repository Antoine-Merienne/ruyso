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


def _two_numeric_df(n=50, seed=0):
    rng = np.random.default_rng(seed)
    a = rng.normal(size=n)
    return pd.DataFrame({"a": a, "b": a * 0.8 + rng.normal(scale=0.3, size=n),
                         "label": ["x"] * n})  # a non-numeric column is ignored


def test_pca_runs_on_every_numeric_column():
    df = _two_numeric_df()
    out = S.PCA(params=S.PCAParams()).run(df=df)
    assert list(out["scores"].columns) == ["PC1", "PC2"]  # 2 numeric cols
    assert len(out["scores"]) == len(df)
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


def test_pca_needs_at_least_two_numeric_columns():
    with pytest.raises(ValueError, match="at least 2"):
        S.PCA(params=S.PCAParams()).run(df=pd.DataFrame({"a": [1.0, 2, 3], "lbl": list("xyz")}))


# -- ICA ---------------------------------------------------------------


def _mixed_sources_df(n=300, seed=0):
    rng = np.random.default_rng(seed)
    s1 = np.sin(np.linspace(0, 20, n))
    s2 = rng.uniform(-1, 1, n)
    mix = np.c_[s1 + 0.3 * s2, 0.5 * s1 - s2, 0.2 * s1 + 0.8 * s2]
    return pd.DataFrame(mix, columns=["a", "b", "c"])


def test_ica_sources_and_mixing_shapes():
    out = S.ICA(params=S.ICAParams(n_components=2, random_state=0)).run(
        df=_mixed_sources_df()
    )
    assert list(out["sources"].columns) == ["IC1", "IC2"]
    assert len(out["sources"]) == 300
    assert list(out["mixing"].columns) == ["variable", "IC1", "IC2"]
    assert list(out["mixing"]["variable"]) == ["a", "b", "c"]


def test_ica_needs_at_least_two_numeric_columns():
    with pytest.raises(ValueError, match="at least 2"):
        S.ICA(params=S.ICAParams()).run(df=pd.DataFrame({"a": [1.0, 2, 3], "lbl": list("xyz")}))


# -- t-SNE ---------------------------------------------------------------


def test_tsne_embedding_shape_and_columns():
    out = S.TSNE(
        params=S.TSNEParams(n_components=2, perplexity=10, random_state=0)
    ).run(df=_mixed_sources_df(n=100))["df"]
    assert list(out.columns) == ["tsne_1", "tsne_2"]
    assert len(out) == 100


def test_tsne_learning_rate_auto_and_numeric_both_work():
    df = _mixed_sources_df(n=60)
    out_auto = S.TSNE(
        params=S.TSNEParams(perplexity=10, learning_rate="auto", random_state=0)
    ).run(df=df)["df"]
    out_fixed = S.TSNE(
        params=S.TSNEParams(perplexity=10, learning_rate="200", random_state=0)
    ).run(df=df)["df"]
    assert len(out_auto) == len(out_fixed) == 60


def test_tsne_needs_at_least_two_numeric_columns():
    with pytest.raises(ValueError, match="at least 2"):
        S.TSNE(params=S.TSNEParams()).run(df=pd.DataFrame({"a": [1.0, 2, 3], "lbl": list("xyz")}))


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
    assert {"pca", "ica", "tsne", "arima", "auto_arima", "var", "var_test"} <= stat_nodes
    assert len(stat_nodes) >= 16


# --------------------------------------------------------------------------
# VAR / VECM + var_test
# --------------------------------------------------------------------------


def _var_frame(n: int = 160, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    e = rng.normal(size=(n, 3))
    y = np.zeros((n, 3))
    for t in range(1, n):
        y[t, 0] = 0.4 * y[t - 1, 0] + 0.25 * y[t - 1, 1] + e[t, 0]
        y[t, 1] = -0.3 * y[t - 1, 0] + 0.35 * y[t - 1, 1] + e[t, 1]
        y[t, 2] = 0.2 * y[t - 1, 1] + 0.5 * y[t - 1, 2] + e[t, 2]
    return pd.DataFrame(
        {
            "gdp": y[:, 0], "cpi": y[:, 1], "rate": y[:, 2],
            "t": pd.date_range("2000-01-01", periods=n, freq="MS"),
        }
    )


@pytest.mark.parametrize("method", ["var", "vecm"])
def test_var_outputs_coeffs_residuals_forecast_and_model(method):
    df = _var_frame()
    out = S.Var(
        params=S.VarParams(
            method=method, datetime_column="t",
            variables=["gdp", "cpi", "rate"], lags=2, forecast_periods=6,
        )
    ).run(df=df)

    assert set(out) == {"coeffs", "residuals", "forecast", "model"}
    assert {"equation", "term", "coef", "pvalue"} <= set(out["coeffs"].columns)
    assert list(out["residuals"].columns[1:]) == ["gdp", "cpi", "rate"]
    assert set(out["forecast"]["variable"]) == {"gdp", "cpi", "rate"}
    assert out["forecast"]["step"].max() == 6
    assert out["model"].ruyso_names == ["gdp", "cpi", "rate"]
    assert out["model"].ruyso_method == method


def test_var_needs_at_least_two_variables():
    with pytest.raises(ValueError, match="at least two"):
        S.Var(params=S.VarParams(variables=["gdp"])).run(df=_var_frame())


@pytest.mark.parametrize("method", ["var", "vecm"])
def test_var_optimize_lag_picks_an_order_within_the_max(method):
    df = _var_frame()
    fixed = S.Var(
        params=S.VarParams(method=method, variables=["gdp", "cpi", "rate"], lags=6)
    ).run(df=df)["model"]
    assert fixed.ruyso_selected_lag == 6

    opt = S.Var(
        params=S.VarParams(
            method=method, variables=["gdp", "cpi", "rate"],
            lags=6, optimize_lag=True, ic="bic",
        )
    ).run(df=df)["model"]
    assert 0 <= opt.ruyso_selected_lag <= 6
    assert opt.ruyso_selected_lag < 6  # the DGP is order 1, bic should trim it


def test_var_forecast_periods_are_stashed_on_the_model():
    model = S.Var(
        params=S.VarParams(variables=["gdp", "cpi"], lags=1, forecast_periods=13)
    ).run(df=_var_frame())["model"]
    assert model.ruyso_forecast_periods == 13


@pytest.mark.parametrize(
    "test", ["granger_causality", "instantaneous_causality", "normality", "whiteness"]
)
def test_var_test_runs_every_diagnostic(test):
    df = _var_frame()
    model = S.Var(
        params=S.VarParams(variables=["gdp", "cpi", "rate"], lags=2)
    ).run(df=df)["model"]

    res = S.VarTest(
        params=S.VarTestParams(test=test, causing=["cpi"], caused=["gdp"])
    ).run(model=model)["df"]

    assert res["test"].iloc[0] == test
    assert 0.0 <= res["pvalue"].iloc[0] <= 1.0
    assert res["conclusion"].iloc[0] in ("reject H_0", "fail to reject H_0")


def test_var_test_works_on_a_vecm_model():
    df = _var_frame()
    model = S.Var(
        params=S.VarParams(method="vecm", variables=["gdp", "cpi", "rate"], lags=1)
    ).run(df=df)["model"]
    res = S.VarTest(params=S.VarTestParams(test="whiteness")).run(model=model)["df"]
    assert 0.0 <= res["pvalue"].iloc[0] <= 1.0
