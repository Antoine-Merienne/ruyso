"""
Tests for modeling nodes (TrainTestSplit, LinearRegressionFit): known
input DataFrame -> expected split sizes / fitted model behaviour.
"""

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression

from ruyso_app.nodes.models import (
    LinearRegressionFit,
    LinearRegressionFitParams,
    TrainTestSplit,
    TrainTestSplitParams,
)


def _make_linear_dataframe(n=20):
    rng = np.random.default_rng(0)
    x = rng.uniform(0, 10, size=n)
    y = 3.0 * x + 1.0  # perfectly linear, noise-free
    return pd.DataFrame({"x": x, "target": y})


def test_train_test_split_produces_expected_sizes_and_columns():
    df = _make_linear_dataframe(n=20)
    node = TrainTestSplit(
        params=TrainTestSplitParams(target_column="target", test_size=0.25, random_state=0)
    )

    result = node.run(df=df)

    assert result["X_train"].shape == (15, 1)
    assert result["X_test"].shape == (5, 1)
    assert len(result["y_train"]) == 15
    assert len(result["y_test"]) == 5
    assert "target" not in result["X_train"].columns


def test_linear_regression_fit_recovers_known_coefficients():
    df = _make_linear_dataframe(n=50)
    split_node = TrainTestSplit(
        params=TrainTestSplitParams(target_column="target", test_size=0.2, random_state=0)
    )
    split = split_node.run(df=df)

    fit_node = LinearRegressionFit(params=LinearRegressionFitParams())
    result = fit_node.run(
        X_train=split["X_train"],
        y_train=split["y_train"],
        X_test=split["X_test"],
        y_test=split["y_test"],
    )

    model = result["model"]
    assert isinstance(model, LinearRegression)
    # y = 3*x + 1 exactly -> coefficient ~3, intercept ~1, R^2 ~1.
    assert np.isclose(model.coef_[0], 3.0, atol=1e-6)
    assert np.isclose(model.intercept_, 1.0, atol=1e-6)
    assert result["score"] > 0.999


def test_linear_regression_fit_without_test_set_has_no_score():
    df = _make_linear_dataframe(n=10)
    split_node = TrainTestSplit(
        params=TrainTestSplitParams(target_column="target", test_size=0.2, random_state=0)
    )
    split = split_node.run(df=df)

    fit_node = LinearRegressionFit(params=LinearRegressionFitParams())
    result = fit_node.run(X_train=split["X_train"], y_train=split["y_train"])

    assert "model" in result
    assert "score" not in result
