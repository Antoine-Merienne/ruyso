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
            task="classification",
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
        params=ModelScoresParams(
            task="regression", regression_metrics=["r2", "mae", "rmse"]
        )
    ).run(model=model, X=split["X_test"], y=split["y_test"])["df"]
    assert out["metric"].tolist() == ["r2", "mae", "rmse"]
    assert out.loc[out["metric"] == "r2", "value"].iloc[0] > 0.9


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
