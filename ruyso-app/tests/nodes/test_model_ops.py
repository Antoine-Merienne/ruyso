"""
Tests for the model-consuming nodes: predict / model_coeffs /
model_scores / residuals.
"""

import numpy as np
import pandas as pd
import pytest

from ruyso_app.nodes.model_ops import (
    ModelCoeffs,
    ModelCoeffsParams,
    ModelScores,
    ModelScoresParams,
    Predict,
    PredictParams,
    Residuals,
    ResidualsParams,
    align_features_to_model,
)
from ruyso_app.nodes.models import (
    LinearRegressionFit,
    LinearRegressionFitParams,
    RandomForestFit,
    RandomForestFitParams,
    TrainTestSplit,
    TrainTestSplitParams,
)


def _frame(n=150, classification=True):
    rng = np.random.default_rng(0)
    X = rng.normal(size=(n, 3))
    if classification:
        target = (X[:, 0] + X[:, 1] > 0).astype(int)
    else:
        target = 2.0 * X[:, 0] - X[:, 1] + 0.1 * rng.normal(size=n)
    return pd.DataFrame({"a": X[:, 0], "b": X[:, 1], "c": X[:, 2], "target": target})


def _split(df):
    return TrainTestSplit(
        params=TrainTestSplitParams(target_column="target", test_size=0.3, random_state=0)
    ).run(df=df)


def _clf(split):
    return RandomForestFit(
        params=RandomForestFitParams(task="classifier", n_estimators=25)
    ).run(X_train=split["X_train"], y_train=split["y_train"])["model"]


def _reg(split):
    return LinearRegressionFit(params=LinearRegressionFitParams()).run(
        X_train=split["X_train"], y_train=split["y_train"]
    )["model"]


# -- align_features_to_model ----------------------------------------------


def test_align_reorders_columns_to_the_models_feature_names():
    split = _split(_frame())
    model = _clf(split)
    shuffled = split["X_test"][["c", "a", "b"]]
    aligned = align_features_to_model(shuffled, model)
    assert list(aligned.columns) == list(model.feature_names_in_)


def test_align_raises_on_a_missing_feature_column():
    split = _split(_frame())
    model = _clf(split)
    with pytest.raises(ValueError, match="missing feature column"):
        align_features_to_model(split["X_test"].drop(columns=["b"]), model)


# -- predict ------------------------------------------------------------


def test_predict_appends_a_prediction_column_keeping_features():
    split = _split(_frame())
    model = _clf(split)
    out = Predict(params=PredictParams()).run(df=split["X_test"], model=model)["df"]
    assert list(out.columns) == ["a", "b", "c", "prediction"]
    assert len(out) == len(split["X_test"])


def test_predict_probabilities_add_one_column_per_class():
    split = _split(_frame())
    model = _clf(split)
    out = Predict(params=PredictParams(probabilities=True)).run(
        df=split["X_test"], model=model
    )["df"]
    assert {"proba_0", "proba_1"} <= set(out.columns)
    np.testing.assert_allclose(out["proba_0"] + out["proba_1"], 1.0, atol=1e-9)


def test_predict_slim_output_drops_the_features():
    split = _split(_frame())
    model = _clf(split)
    out = Predict(params=PredictParams(keep_features=False)).run(
        df=split["X_test"], model=model
    )["df"]
    assert list(out.columns) == ["prediction"]


# -- model_coeffs -----------------------------------------------------


def test_model_coeffs_linear_has_an_intercept_row():
    split = _split(_frame(classification=False))
    model = _reg(split)
    table = ModelCoeffs(params=ModelCoeffsParams()).run(model=model)["df"]
    assert list(table.columns) == ["feature", "coefficient"]
    assert table.iloc[0]["feature"] == "intercept"
    assert set(table["feature"]) == {"intercept", "a", "b", "c"}


def test_model_coeffs_falls_back_to_feature_importances_for_a_forest():
    split = _split(_frame())
    model = _clf(split)
    table = ModelCoeffs(params=ModelCoeffsParams(sort_by_magnitude=True)).run(
        model=model
    )["df"]
    assert list(table.columns) == ["feature", "importance"]
    assert (table["importance"].values == np.sort(table["importance"].values)[::-1]).all()


# -- model_scores ---------------------------------------------------


def test_model_scores_classification_table():
    split = _split(_frame())
    model = _clf(split)
    out = ModelScores(
        params=ModelScoresParams(
            classification_metrics=["accuracy", "precision", "recall", "f1"],
        )
    ).run(model=model, X=split["X_test"], y=split["y_test"])["df"]
    assert list(out.columns) == ["metric", "value"]
    assert out["metric"].tolist() == ["accuracy", "precision", "recall", "f1"]
    assert out["value"].between(0.0, 1.0).all()


def test_model_scores_regression_table():
    split = _split(_frame(classification=False))
    model = _reg(split)
    out = ModelScores(
        params=ModelScoresParams(regression_metrics=["r2", "mae", "rmse"])
    ).run(model=model, X=split["X_test"], y=split["y_test"])["df"]
    assert out["metric"].tolist() == ["r2", "mae", "rmse"]
    assert out.loc[out["metric"] == "r2", "value"].iloc[0] > 0.9


def test_model_scores_detects_task_from_the_model_not_a_default():
    # Regression bug: the node used to default to "classification"
    # regardless of the wired-in model, silently producing NaN scores
    # for a regressor unless the user manually flipped a "task" toggle.
    # There is no such toggle any more -- the model itself decides.
    reg_split = _split(_frame(classification=False))
    model = _reg(reg_split)  # a regressor, with every default left untouched
    out = ModelScores(params=ModelScoresParams()).run(
        model=model, X=reg_split["X_test"], y=reg_split["y_test"]
    )["df"]
    assert out["metric"].tolist() == ["r2", "mae", "rmse"]  # regression defaults
    assert not out["value"].isna().any()

    clf_split = _split(_frame(classification=True))
    model = _clf(clf_split)  # ... and the reverse, a classifier
    out = ModelScores(params=ModelScoresParams()).run(
        model=model, X=clf_split["X_test"], y=clf_split["y_test"]
    )["df"]
    assert out["metric"].tolist() == ["accuracy", "f1"]  # classification defaults
    assert not out["value"].isna().any()


# -- residuals ----------------------------------------------------


def test_residuals_columns_and_relationship():
    split = _split(_frame(classification=False))
    model = _reg(split)
    out = Residuals(params=ResidualsParams()).run(
        model=model, X=split["X_test"], y=split["y_test"]
    )["df"]
    assert list(out.columns) == ["y_true", "y_pred", "residual", "std_residual"]
    np.testing.assert_allclose(
        out["residual"], out["y_true"] - out["y_pred"], atol=1e-9
    )


def test_residuals_rejects_a_classifier():
    split = _split(_frame())
    model = _clf(split)
    with pytest.raises(ValueError, match="regression model"):
        Residuals(params=ResidualsParams()).run(
            model=model, X=split["X_test"], y=split["y_test"]
        )


# -- optim_diagnostic / optim_scores -------------------------------------

from ruyso_app.nodes.model_ops import (  # noqa: E402
    OptimDiagnostic,
    OptimDiagnosticParams,
    OptimScores,
    OptimScoresParams,
)


def _fake_optim():
    return {
        "method": "tpe",
        "metric": "r2",
        "direction": "maximize",
        "n_trials": 3,
        "best_value": 0.987,
        "best_params": {"alpha": 2.5},
        "trials": pd.DataFrame(
            {
                "trial": [0, 1, 2],
                "alpha": [1.0, 2.5, 4.0],
                "train_score": [0.98, 0.99, 0.97],
                "test_score": [0.95, 0.987, 0.93],
            }
        ),
    }


def test_optim_diagnostic_summarizes_the_run():
    out = OptimDiagnostic(params=OptimDiagnosticParams()).run(optim=_fake_optim())["df"]
    assert len(out) == 1
    row = out.iloc[0]
    assert row["method"] == "tpe" and row["metric"] == "r2"
    assert row["n_trials"] == 3 and row["best_value"] == 0.987
    assert row["best_alpha"] == 2.5


def test_optim_diagnostic_requires_an_actual_optim_run():
    with pytest.raises(ValueError, match="optimize"):
        OptimDiagnostic(params=OptimDiagnosticParams()).run(optim=None)


def test_optim_scores_returns_the_trials_table():
    out = OptimScores(params=OptimScoresParams()).run(optim=_fake_optim())["df"]
    assert list(out.columns) == ["trial", "alpha", "train_score", "test_score"]
    assert len(out) == 3


def test_optim_scores_requires_an_actual_optim_run():
    with pytest.raises(ValueError, match="optimize"):
        OptimScores(params=OptimScoresParams()).run(optim=None)
