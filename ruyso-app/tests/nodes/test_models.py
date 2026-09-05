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


# -- clustering -----------------------------------------------------------

from ruyso_app.nodes.models import (  # noqa: E402
    AgglomerativeClusteringFit,
    AgglomerativeClusteringFitParams,
    DBSCANFit,
    DBSCANFitParams,
    GaussianMixtureFit,
    GaussianMixtureFitParams,
    HDBSCANFit,
    HDBSCANFitParams,
    KMeansFit,
    KMeansFitParams,
    MiniBatchKMeansFit,
    MiniBatchKMeansFitParams,
    SklearnClusterFitNode,
    SpectralClusteringFit,
    SpectralClusteringFitParams,
)


def _two_blobs(n=60):
    rng = np.random.default_rng(2)
    a = rng.normal(loc=0.0, scale=0.3, size=(n // 2, 2))
    b = rng.normal(loc=6.0, scale=0.3, size=(n // 2, 2))
    return pd.DataFrame(np.vstack([a, b]), columns=["x", "y"])


@pytest.mark.parametrize(
    "node_cls, params",
    [
        (KMeansFit, KMeansFitParams(n_clusters=2, n_init=3, random_state=0)),
        (MiniBatchKMeansFit, MiniBatchKMeansFitParams(n_clusters=2, random_state=0)),
        (DBSCANFit, DBSCANFitParams(eps=1.0, min_samples=3)),
        (HDBSCANFit, HDBSCANFitParams(min_cluster_size=3)),
        (AgglomerativeClusteringFit, AgglomerativeClusteringFitParams(n_clusters=2)),
        (SpectralClusteringFit, SpectralClusteringFitParams(n_clusters=2, random_state=0)),
        (GaussianMixtureFit, GaussianMixtureFitParams(n_components=2, random_state=0)),
    ],
)
def test_clustering_nodes_fit_on_x_alone_and_separate_two_blobs(node_cls, params):
    X = _two_blobs()
    result = node_cls(params=params).run(X_train=X)
    model = result["model"]
    labels = getattr(model, "labels_", None)
    if labels is None:  # GaussianMixture: no labels_, use predict instead
        labels = model.predict(X)
    labels = np.asarray(labels)
    # two well-separated blobs -> every real cluster label should be
    # "pure" (all its members from the same blob); DBSCAN/HDBSCAN may
    # also emit -1 (noise), which is excluded from this check.
    blob = np.array([0] * (len(X) // 2) + [1] * (len(X) - len(X) // 2))
    for label in set(labels) - {-1}:
        assert len(set(blob[labels == label])) == 1


def test_clustering_nodes_do_not_require_a_target_column():
    node_cls = KMeansFit
    assert node_cls.inputs[1].name == "y_train" and not node_cls.inputs[1].required


def test_clustering_base_ignores_y_train_even_if_wired():
    X = _two_blobs()
    y = pd.Series(np.zeros(len(X)))  # a bogus target, should simply be ignored
    result = KMeansFit(params=KMeansFitParams(n_clusters=2, random_state=0)).run(
        X_train=X, y_train=y
    )
    assert hasattr(result["model"], "labels_")


def test_clustering_nodes_are_registered_under_the_model_category():
    from ruyso_app.core.registry import NodeRegistry

    for node_type in (
        "kmeans_fit", "minibatch_kmeans_fit", "dbscan_fit", "hdbscan_fit",
        "agglomerative_clustering_fit", "spectral_clustering_fit", "gaussian_mixture_fit",
    ):
        cls = NodeRegistry.get(node_type)
        assert cls.category == "model"
        assert issubclass(cls, SklearnClusterFitNode)


# -- optimize section -------------------------------------------------

import json  # noqa: E402

from ruyso_app.nodes.models import RidgeFit, RidgeFitParams  # noqa: E402


def _regression_frame(n=150):
    rng = np.random.default_rng(3)
    X = rng.normal(size=(n, 3))
    y = 2.0 * X[:, 0] - X[:, 1] + 0.05 * rng.normal(size=n)
    return pd.DataFrame({"a": X[:, 0], "b": X[:, 1], "c": X[:, 2], "target": y})


def test_optimize_off_leaves_optim_none():
    split = _split(_regression_frame())
    out = LinearRegressionFit(params=LinearRegressionFitParams()).run(
        X_train=split["X_train"], y_train=split["y_train"]
    )
    assert out["optim"] is None


def test_optimize_searches_bounds_and_returns_the_best_model():
    split = _split(_regression_frame())
    params = RidgeFitParams(
        task="regressor",
        optimize=True,
        optimize_bounds=json.dumps({"alpha": [0.001, 10.0]}),
        optimize_metric="r2",
        optimize_method="tpe",
        optimize_n_trials=5,
    )
    out = RidgeFit(params=params).run(
        X_train=split["X_train"], y_train=split["y_train"],
        X_test=split["X_test"], y_test=split["y_test"],
    )
    optim = out["optim"]
    assert optim["metric"] == "r2" and optim["direction"] == "maximize"
    assert optim["n_trials"] == 5
    assert list(optim["best_params"]) == ["alpha"]
    assert 0.001 <= optim["best_params"]["alpha"] <= 10.0
    assert out["model"].alpha == optim["best_params"]["alpha"]  # the best trial's estimator
    assert {"trial", "alpha", "train_score", "test_score"} <= set(optim["trials"].columns)
    assert len(optim["trials"]) == 5


def test_optimize_requires_x_test_and_y_test():
    split = _split(_regression_frame())
    params = RidgeFitParams(
        task="regressor", optimize=True,
        optimize_bounds=json.dumps({"alpha": [0.1, 5.0]}),
    )
    with pytest.raises(ValueError, match="X_test/y_test"):
        RidgeFit(params=params).run(X_train=split["X_train"], y_train=split["y_train"])


def test_optimize_requires_at_least_one_bounded_parameter():
    split = _split(_regression_frame())
    params = RidgeFitParams(task="regressor", optimize=True, optimize_bounds="{}")
    with pytest.raises(ValueError, match="no parameter has bounds"):
        RidgeFit(params=params).run(
            X_train=split["X_train"], y_train=split["y_train"],
            X_test=split["X_test"], y_test=split["y_test"],
        )


def test_optimize_malformed_bounds_json_raises():
    split = _split(_regression_frame())
    params = RidgeFitParams(task="regressor", optimize=True, optimize_bounds="not json")
    with pytest.raises(ValueError, match="JSON"):
        RidgeFit(params=params).run(
            X_train=split["X_train"], y_train=split["y_train"],
            X_test=split["X_test"], y_test=split["y_test"],
        )


def test_optimize_unknown_parameter_raises():
    split = _split(_regression_frame())
    params = RidgeFitParams(
        task="regressor", optimize=True,
        optimize_bounds=json.dumps({"not_a_real_param": [0, 1]}),
    )
    with pytest.raises(ValueError, match="unknown optimize parameter"):
        RidgeFit(params=params).run(
            X_train=split["X_train"], y_train=split["y_train"],
            X_test=split["X_test"], y_test=split["y_test"],
        )


def test_optimize_grid_method_respects_int_bounds():
    split = _split(_classification_frame())
    params = RandomForestFitParams(
        task="classifier", n_estimators=20,
        optimize=True,
        optimize_bounds=json.dumps({"n_estimators": [10, 30], "max_depth": [2, 6]}),
        optimize_metric="accuracy", optimize_method="grid", optimize_n_trials=25,
    )
    out = RandomForestFit(params=params).run(
        X_train=split["X_train"], y_train=split["y_train"],
        X_test=split["X_test"], y_test=split["y_test"],
    )
    optim = out["optim"]
    assert optim["trials"]["n_estimators"].dtype.kind == "i"
    assert optim["trials"]["max_depth"].dtype.kind == "i"
    assert 10 <= optim["best_params"]["n_estimators"] <= 30


def test_optimize_falls_back_to_a_valid_metric_for_the_task():
    # "accuracy" (the default) does not apply to a regressor -- must
    # fall back to "r2" rather than silently computing NaN/garbage.
    split = _split(_regression_frame())
    params = RidgeFitParams(
        task="regressor", optimize=True,
        optimize_bounds=json.dumps({"alpha": [0.1, 5.0]}),
        optimize_metric="accuracy", optimize_n_trials=3,
    )
    out = RidgeFit(params=params).run(
        X_train=split["X_train"], y_train=split["y_train"],
        X_test=split["X_test"], y_test=split["y_test"],
    )
    assert out["optim"]["metric"] == "r2"
