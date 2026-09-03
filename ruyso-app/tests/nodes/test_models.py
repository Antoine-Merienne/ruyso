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
    # y = 3*x + 1 exactly -> coefficient ~3, intercept ~1.
    assert np.isclose(model.coef_[0], 3.0, atol=1e-6)
    assert np.isclose(model.intercept_, 1.0, atol=1e-6)
    assert "score" not in result  # fit nodes output only the model


def test_linear_regression_fit_never_outputs_a_score():
    df = _make_linear_dataframe(n=10)
    split_node = TrainTestSplit(
        params=TrainTestSplitParams(target_column="target", test_size=0.2, random_state=0)
    )
    split = split_node.run(df=df)

    fit_node = LinearRegressionFit(params=LinearRegressionFitParams())
    result = fit_node.run(X_train=split["X_train"], y_train=split["y_train"])

    assert "model" in result
    assert "score" not in result


# -- the shared SklearnFitNode framework -----------------------------------

import pytest  # noqa: E402

from ruyso_app.nodes.models import (  # noqa: E402
    AdaBoostFit,
    AdaBoostFitParams,
    KNNFit,
    KNNFitParams,
    NaiveBayesFit,
    NaiveBayesFitParams,
    RandomForestFit,
    RandomForestFitParams,
    RidgeFit,
    RidgeFitParams,
    SVMFit,
    SVMFitParams,
)


def _classification_frame(n=120):
    rng = np.random.default_rng(1)
    X = rng.normal(size=(n, 3))
    y = (X[:, 0] + X[:, 1] > 0).astype(int)
    return pd.DataFrame({"a": X[:, 0], "b": X[:, 1], "c": X[:, 2], "target": y})


def _split(df):
    node = TrainTestSplit(
        params=TrainTestSplitParams(target_column="target", test_size=0.25, random_state=0)
    )
    return node.run(df=df)


def test_train_test_split_is_now_a_transform():
    assert TrainTestSplit.category == "transform"


def test_train_test_split_output_port_order():
    assert [p.name for p in TrainTestSplit.outputs] == [
        "X_train", "y_train", "X_test", "y_test"
    ]


def test_train_test_split_can_stratify_on_the_target():
    df = _classification_frame(n=80)
    out = TrainTestSplit(
        params=TrainTestSplitParams(
            target_column="target", test_size=0.25, random_state=0, stratify=True
        )
    ).run(df=df)
    whole = df["target"].mean()
    # stratified -> the test split keeps roughly the same class balance
    assert abs(out["y_test"].mean() - whole) < 0.15


def test_task_toggle_selects_the_classifier_or_regressor_estimator():
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

    clf = RandomForestFit(params=RandomForestFitParams(task="classifier"))._make_estimator()
    reg = RandomForestFit(params=RandomForestFitParams(task="regressor"))._make_estimator()
    assert isinstance(clf, RandomForestClassifier)
    assert isinstance(reg, RandomForestRegressor)


def test_hyperparameters_and_none_sentinels_reach_the_estimator():
    est = RandomForestFit(
        params=RandomForestFitParams(
            task="regressor",
            n_estimators=17,
            max_depth=0,  # 0 -> None
            max_features="none",  # "none" -> None
            regressor_criterion="absolute_error",
            n_jobs=0,  # 0 -> None
        )
    )._make_estimator()
    assert est.n_estimators == 17
    assert est.max_depth is None
    assert est.max_features is None
    assert est.criterion == "absolute_error"  # renamed from regressor_criterion
    assert est.n_jobs is None


def test_classifier_only_arg_is_dropped_for_the_regressor():
    # class_weight exists only on RandomForestClassifier
    reg = RandomForestFit(params=RandomForestFitParams(task="regressor"))._make_estimator()
    assert "class_weight" not in reg.get_params()


def test_svm_regressor_only_arg_is_dropped_for_the_classifier():
    svr = SVMFit(params=SVMFitParams(task="regressor", epsilon=0.3))._make_estimator()
    svc = SVMFit(params=SVMFitParams(task="classifier"))._make_estimator()
    assert type(svr).__name__ == "SVR" and svr.epsilon == 0.3
    assert type(svc).__name__ == "SVC" and "epsilon" not in svc.get_params()


@pytest.mark.parametrize(
    "node_cls, params",
    [
        (RandomForestFit, {"task": "classifier", "n_estimators": 15}),
        (RidgeFit, {"task": "classifier"}),
        (SVMFit, {"task": "classifier"}),
        (KNNFit, {"task": "classifier"}),
        (AdaBoostFit, {"task": "classifier", "n_estimators": 15}),
        (NaiveBayesFit, {}),
    ],
)
def test_classifier_nodes_fit_and_produce_a_usable_model(node_cls, params):
    split = _split(_classification_frame())
    result = node_cls(params=node_cls.params_schema(**params)).run(
        X_train=split["X_train"],
        y_train=split["y_train"],
        X_test=split["X_test"],
        y_test=split["y_test"],
    )
    assert hasattr(result["model"], "predict")
    assert "score" not in result
