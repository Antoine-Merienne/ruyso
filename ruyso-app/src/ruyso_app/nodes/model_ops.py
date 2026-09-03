"""
Nodes that *consume* a fitted model (the ``model`` port).

These turn a trained scikit-learn estimator into something inspectable:

* ``predict``       -- score a DataFrame, appending a prediction column
                       (and per-class probabilities for a classifier).
* ``model_coeffs``  -- the model's coefficients (or feature importances)
                       as a tidy DataFrame, viewable in the Table tab.
* ``model_scores``  -- a chosen set of metrics on a held-out (X, y),
                       as a ``metric`` / ``value`` DataFrame.
* ``residuals``     -- ``y_true`` / ``y_pred`` / ``residual`` per row
                       (regression only).

All four are in the ``model`` macro type. The evaluation nodes take
the same ``X`` (dataframe) + ``y`` (array) ports that ``train_test_split``
produces.
"""

from typing import Any, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import checkbox_list_field, visible_field
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


def align_features_to_model(df: Any, model: Any) -> Any:
    """
    Reorder / subset ``df``'s columns to match what ``model`` was fit on.

    Prefers the estimator's recorded ``feature_names_in_``; otherwise
    falls back to the first ``n_features_in_`` columns in their current
    order (df column order == model variable order).
    """
    names = getattr(model, "feature_names_in_", None)
    if names is not None:
        names = [str(n) for n in names]
        missing = [n for n in names if n not in df.columns]
        if missing:
            raise ValueError(
                f"input is missing feature column(s) the model was trained on: {missing}"
            )
        return df.loc[:, names]

    n_features = getattr(model, "n_features_in_", None)
    if n_features is not None and df.shape[1] != n_features:
        if df.shape[1] < n_features:
            raise ValueError(
                f"model expects {n_features} feature columns, input has {df.shape[1]}."
            )
        return df.iloc[:, :n_features]
    return df


# --------------------------------------------------------------------------
# predict
# --------------------------------------------------------------------------


class PredictParams(NodeParams):
    """
    Parameters for Predict.

    Attributes:
        prediction_column: Name of the appended prediction column.
        keep_features: Keep every input column alongside the prediction
            (off = only the prediction / probability columns).
        probabilities: For a classifier that supports it, also append
            one ``<proba_prefix><class>`` column per class.
        proba_prefix: Prefix for the probability columns.
    """

    prediction_column: str = "prediction"
    keep_features: bool = True
    probabilities: bool = False
    proba_prefix: str = "proba_"


@register_node
class Predict(Node):
    """Apply a fitted model to a DataFrame."""

    node_type = "predict"
    category = "model"
    inputs = [
        Port(name="df", dtype="dataframe"),
        Port(name="model", dtype="model"),
    ]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = PredictParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        df = inputs["df"]
        model = inputs["model"]

        features = align_features_to_model(df, model)
        predictions = model.predict(features)

        out = df.copy() if p.keep_features else df.iloc[:, :0].copy()
        out[p.prediction_column] = predictions

        if p.probabilities and hasattr(model, "predict_proba"):
            proba = model.predict_proba(features)
            classes = list(getattr(model, "classes_", range(proba.shape[1])))
            for i, cls in enumerate(classes):
                out[f"{p.proba_prefix}{cls}"] = proba[:, i]
        return {"df": out}


# --------------------------------------------------------------------------
# model_coeffs
# --------------------------------------------------------------------------


class ModelCoeffsParams(NodeParams):
    """
    Parameters for ModelCoeffs.

    Attributes:
        include_intercept: Add an ``intercept`` row (linear models only).
        sort_by_magnitude: Order rows by descending absolute value.
    """

    include_intercept: bool = True
    sort_by_magnitude: bool = False


@register_node
class ModelCoeffs(Node):
    """
    The model's coefficients as a tidy DataFrame (``feature`` +
    one value column). Linear models emit ``coef_`` / ``intercept_``
    (one value column per class for a multiclass model); tree / ensemble
    models fall back to ``feature_importances_``.
    """

    node_type = "model_coeffs"
    category = "model"
    inputs = [Port(name="model", dtype="model")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ModelCoeffsParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import numpy as np
        import pandas as pd

        p = self.params
        model = inputs["model"]
        names = [str(n) for n in getattr(model, "feature_names_in_", [])]
        coef = getattr(model, "coef_", None)

        if coef is not None:
            coef = np.atleast_2d(np.asarray(coef, dtype="float64"))  # (n_outputs, n_features)
            n_features = coef.shape[1]
            feats = names if len(names) == n_features else [f"x{i}" for i in range(n_features)]
            single = coef.shape[0] == 1
            classes = getattr(model, "classes_", range(coef.shape[0]))
            value_cols = (
                ["coefficient"] if single else [f"coef_{c}" for c in classes]
            )
            data = {"feature": list(feats)}
            for j, col in enumerate(value_cols):
                data[col] = coef[j]
            table = pd.DataFrame(data)

            if p.include_intercept:
                intercept = np.atleast_1d(
                    np.asarray(getattr(model, "intercept_", []), dtype="float64")
                )
                if intercept.size:
                    row = {"feature": "intercept"}
                    for j, col in enumerate(value_cols):
                        row[col] = intercept[j] if j < intercept.size else intercept[0]
                    table = pd.concat([pd.DataFrame([row]), table], ignore_index=True)
            sort_col = value_cols[0]
        elif hasattr(model, "feature_importances_"):
            importance = np.asarray(model.feature_importances_, dtype="float64")
            feats = (
                names if len(names) == len(importance)
                else [f"x{i}" for i in range(len(importance))]
            )
            table = pd.DataFrame({"feature": feats, "importance": importance})
            sort_col = "importance"
        else:
            raise ValueError(
                f"model_coeffs: {type(model).__name__} exposes neither 'coef_' nor "
                f"'feature_importances_'."
            )

        if p.sort_by_magnitude:
            order = table[sort_col].abs().sort_values(ascending=False).index
            table = table.loc[order].reset_index(drop=True)
        return {"df": table}


# --------------------------------------------------------------------------
# model_scores
# --------------------------------------------------------------------------

_CLASSIFICATION_METRICS = [
    "accuracy", "balanced_accuracy", "precision", "recall", "f1",
    "roc_auc", "log_loss", "matthews_corrcoef", "cohen_kappa",
]
_REGRESSION_METRICS = [
    "r2", "mae", "mse", "rmse", "mape", "median_absolute_error",
    "explained_variance", "max_error",
]


class ModelScoresParams(NodeParams):
    """
    Parameters for ModelScores.

    Attributes:
        task: Whether to compute classification or regression metrics.
        classification_metrics / regression_metrics: Which metrics to
            report (tickboxes), one per row of the output DataFrame.
        average: Averaging for multiclass precision / recall / f1 /
            roc_auc (ignored for a binary target).
    """

    task: Literal["classification", "regression"] = "classification"
    classification_metrics: list[str] = checkbox_list_field(
        choices=_CLASSIFICATION_METRICS,
        default=["accuracy", "f1"],
        visible_when=("task", "classification"),
    )
    regression_metrics: list[str] = checkbox_list_field(
        choices=_REGRESSION_METRICS,
        default=["r2", "mae", "rmse"],
        visible_when=("task", "regression"),
    )
    average: Literal["macro", "micro", "weighted"] = visible_field(
        "macro", visible_when=("task", "classification")
    )


@register_node
class ModelScores(Node):
    """A chosen set of evaluation metrics as a ``metric`` / ``value`` table."""

    node_type = "model_scores"
    category = "model"
    inputs = [
        Port(name="model", dtype="model"),
        Port(name="X", dtype="dataframe"),
        Port(name="y", dtype="array"),
    ]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ModelScoresParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import numpy as np
        import pandas as pd

        p = self.params
        model = inputs["model"]
        X = align_features_to_model(inputs["X"], model)
        y_true = np.asarray(inputs["y"])

        if p.task == "classification":
            scores = _classification_scores(
                model, X, y_true, p.classification_metrics or [], p.average
            )
        else:
            scores = _regression_scores(
                model, X, y_true, p.regression_metrics or []
            )
        return {
            "df": pd.DataFrame(
                {"metric": list(scores), "value": [scores[m] for m in scores]}
            )
        }


def _classification_scores(
    model: Any, X: Any, y_true: Any, chosen: list[str], average: str
) -> dict[str, float]:
    import numpy as np
    from sklearn import metrics as skm

    y_pred = model.predict(X)
    proba = None
    if hasattr(model, "predict_proba"):
        try:
            proba = model.predict_proba(X)
        except Exception:  # noqa: BLE001
            proba = None

    classes = list(getattr(model, "classes_", np.unique(y_true)))
    binary = len(classes) == 2
    avg = "binary" if binary else average

    out: dict[str, float] = {}
    for metric in chosen:
        try:
            if metric == "accuracy":
                value = skm.accuracy_score(y_true, y_pred)
            elif metric == "balanced_accuracy":
                value = skm.balanced_accuracy_score(y_true, y_pred)
            elif metric == "precision":
                value = skm.precision_score(y_true, y_pred, average=avg, zero_division=0)
            elif metric == "recall":
                value = skm.recall_score(y_true, y_pred, average=avg, zero_division=0)
            elif metric == "f1":
                value = skm.f1_score(y_true, y_pred, average=avg, zero_division=0)
            elif metric == "matthews_corrcoef":
                value = skm.matthews_corrcoef(y_true, y_pred)
            elif metric == "cohen_kappa":
                value = skm.cohen_kappa_score(y_true, y_pred)
            elif metric == "roc_auc":
                if proba is None:
                    value = float("nan")
                elif binary:
                    value = skm.roc_auc_score(y_true, proba[:, 1])
                else:
                    value = skm.roc_auc_score(
                        y_true, proba, multi_class="ovr", average=average
                    )
            elif metric == "log_loss":
                value = skm.log_loss(y_true, proba) if proba is not None else float("nan")
            else:
                value = float("nan")
        except Exception:  # noqa: BLE001 - a bad metric shouldn't kill the table
            value = float("nan")
        out[metric] = float(value)
    return out


def _regression_scores(
    model: Any, X: Any, y_true: Any, chosen: list[str]
) -> dict[str, float]:
    from sklearn import metrics as skm

    y_pred = model.predict(X)
    fns = {
        "r2": skm.r2_score,
        "mae": skm.mean_absolute_error,
        "mse": skm.mean_squared_error,
        "rmse": skm.root_mean_squared_error,
        "mape": skm.mean_absolute_percentage_error,
        "median_absolute_error": skm.median_absolute_error,
        "explained_variance": skm.explained_variance_score,
        "max_error": skm.max_error,
    }
    out: dict[str, float] = {}
    for metric in chosen:
        try:
            out[metric] = float(fns[metric](y_true, y_pred))
        except Exception:  # noqa: BLE001
            out[metric] = float("nan")
    return out


# --------------------------------------------------------------------------
# residuals
# --------------------------------------------------------------------------


class ResidualsParams(NodeParams):
    """
    Parameters for Residuals.

    Attributes:
        standardized: Also add a ``std_residual`` column
            (residual / residual standard deviation).
    """

    standardized: bool = True


@register_node
class Residuals(Node):
    """
    Per-row ``y_true`` / ``y_pred`` / ``residual`` for a regression
    model (residual = y_true - y_pred). Viewable in the Table tab.
    """

    node_type = "residuals"
    category = "model"
    inputs = [
        Port(name="model", dtype="model"),
        Port(name="X", dtype="dataframe"),
        Port(name="y", dtype="array"),
    ]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ResidualsParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import numpy as np
        import pandas as pd
        from sklearn.base import is_classifier

        model = inputs["model"]
        if is_classifier(model):
            raise ValueError(
                "residuals: this node is for regression models (got a classifier)."
            )

        X = align_features_to_model(inputs["X"], model)
        y_true = np.asarray(inputs["y"], dtype="float64")
        y_pred = np.asarray(model.predict(X), dtype="float64")
        residual = y_true - y_pred

        out = pd.DataFrame(
            {"y_true": y_true, "y_pred": y_pred, "residual": residual}
        )
        if self.params.standardized:
            spread = float(np.std(residual, ddof=1)) or 1.0
            out["std_residual"] = residual / spread
        return {"df": out}
