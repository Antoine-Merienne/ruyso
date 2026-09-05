"""
Modeling nodes: fit scikit-learn estimators on a train/test split.

``TrainTestSplit`` (a *transform*) turns one DataFrame into
``X_train`` / ``X_test`` (DataFrames) and ``y_train`` / ``y_test``
(the target column, as a pandas Series carried on an ``array`` port).

Every *model* node follows the same shape as ``LinearRegressionFit``:

    inputs  : X_train (dataframe), y_train (array),
              X_test (dataframe, optional), y_test (array, optional)
    outputs : model  (the fitted scikit-learn estimator object)

Evaluation (metrics, residuals, plots) is done downstream by the
``model_scores`` / ``residuals`` / model-plot nodes, which take the
fitted ``model`` plus an ``X`` / ``y``.

The concrete model nodes are thin: they declare a parameter schema
(the estimator's constructor arguments that map cleanly onto a widget)
and an ``ESTIMATORS`` table; :class:`SklearnFitNode` does the fit /
score. A node whose algorithm exists in both flavours exposes a
``task`` dropdown ("classifier" / "regressor") that selects the
estimator class.

Every supervised fit node's params schema also carries the shared
"optimize" section (:class:`SklearnFitParams`): tick ``optimize``,
check off which of the node's own numeric hyperparameters to search
over and give each a ``[lo, hi]`` range, pick an Optuna sampler, and
the node searches for the values that maximise (or, for an
error-style metric, minimise) the chosen score on ``X_test``/``y_test``
-- which become required inputs only in that case. The additional
``optim`` output carries the full run (best params, best score, and a
per-trial train/test score table) for the ``optim_diagnostic`` /
``optim_scores`` nodes in ``model_ops.py`` to consume. Clustering nodes
(unsupervised, no target/test score) do not get this section.
"""

from typing import Any, ClassVar, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    column_field,
    optimize_bounds_field,
    unit_interval_field,
    visible_field,
)
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


class TrainTestSplitParams(NodeParams):
    """
    Parameters for TrainTestSplit.

    Attributes:
        target_column: Name of the column to use as the target (y).
            All other columns are used as features (X).
        test_size: Fraction of rows held out for the test set.
        random_state: Seed for the split, for reproducibility.
        shuffle: Whether to shuffle before splitting.
        stratify: Stratify the split on the target column's values
            (classification only -- fails for a continuous target).
    """

    target_column: str = column_field(
        dtypes=("any",), description="Column to use as the target (y)."
    )
    test_size: float = unit_interval_field(0.2, lo=0.05, hi=0.95)
    random_state: int = 42
    shuffle: bool = True
    stratify: bool = False


@register_node
class TrainTestSplit(Node):
    """
    Split a DataFrame into train/test feature and target sets.

    Splits the input DataFrame into features (every column except
    ``target_column``) and target (``target_column``), then performs
    a train/test split on both.
    """

    node_type = "train_test_split"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [
        Port(name="X_train", dtype="dataframe"),
        Port(name="y_train", dtype="array"),
        Port(name="X_test", dtype="dataframe"),
        Port(name="y_test", dtype="array"),
    ]
    params_schema = TrainTestSplitParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Perform the train/test split.

        Args:
            df: Input pandas.DataFrame (via the "df" input port).

        Returns:
            Dict with "X_train", "X_test", "y_train", "y_test".
        """
        self.validate_inputs(inputs)
        from sklearn.model_selection import train_test_split

        df = inputs["df"]
        target = self.params.target_column
        if target not in df.columns:
            raise ValueError(
                f"train_test_split: target column {target!r} is not in the data."
            )
        X = df.drop(columns=[target])
        y = df[target]

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=self.params.test_size,
            random_state=self.params.random_state,
            shuffle=self.params.shuffle,
            stratify=y if self.params.stratify else None,
        )
        return {
            "X_train": X_train,
            "X_test": X_test,
            "y_train": y_train,
            "y_test": y_test,
        }


# --------------------------------------------------------------------------
# Shared scikit-learn "fit + score" machinery
# --------------------------------------------------------------------------

#: Real estimator arg -> (classifier-only field, regressor-only field).
#: A node that offers a ``task`` toggle declares whichever of these
#: differ between the two estimator classes; the base renames the
#: active one back to the real arg and drops the other.
_TASK_ARG_FIELDS: dict[str, tuple[str, str]] = {
    "criterion": ("classifier_criterion", "regressor_criterion"),
    "loss": ("classifier_loss", "regressor_loss"),
}

#: field name -> real estimator arg name, for a field whose pydantic name
#: had to differ from the arg it maps to (e.g. ``copy`` shadows
#: ``pydantic.BaseModel.copy()``, so ``HDBSCANFitParams`` calls it
#: ``copy_input`` instead).
_RENAMED_FIELDS: dict[str, str] = {
    "copy_input": "copy",
}

#: Integer params whose "0" means "use the estimator's default (None)".
#: ``max_iter`` is included so a solver's own default kicks in at 0
#: (SVM keeps its own "-1 = no limit", which is not 0 and passes through).
_ZERO_MEANS_NONE = frozenset(
    {"max_depth", "max_leaf_nodes", "n_jobs", "n_iter_no_change", "max_iter"}
)


def _clean_model_value(arg: str, value: Any) -> Any:
    """Map the UI-friendly sentinels back to what scikit-learn expects."""
    if isinstance(value, str) and value == "none":
        return None
    if arg in _ZERO_MEANS_NONE and isinstance(value, int) and value == 0:
        return None
    return value


#: Metrics (from ``model_ops._CLASSIFICATION_METRICS`` /
#: ``_REGRESSION_METRICS``) where a LOWER value is better; every other
#: one there is "higher is better". Kept as a separate literal set (not
#: computed from those lists) since the direction is a property of the
#: metric's meaning, not of which module happens to define it.
_LOWER_IS_BETTER_METRICS = frozenset(
    {"mae", "mse", "rmse", "mape", "median_absolute_error", "max_error", "log_loss"}
)


def _optuna_sampler(method: str, bounds: dict[str, list[float]], int_params: set[str]) -> Any:
    """Build the Optuna sampler for ``optimize_method``."""
    import optuna

    if method == "random":
        return optuna.samplers.RandomSampler(seed=0)
    if method == "cmaes":
        return optuna.samplers.CmaEsSampler(seed=0)
    if method == "grid":
        import numpy as np

        resolution = 5
        search_space: dict[str, list[Any]] = {}
        for name, (lo, hi) in bounds.items():
            if name in int_params:
                lo_i, hi_i = int(lo), int(hi)
                n = min(resolution, max(hi_i - lo_i + 1, 1))
                search_space[name] = sorted({int(v) for v in np.linspace(lo_i, hi_i, n)})
            else:
                search_space[name] = [float(v) for v in np.linspace(float(lo), float(hi), resolution)]
        return optuna.samplers.GridSampler(search_space)
    return optuna.samplers.TPESampler(seed=0)


class SklearnFitParams(NodeParams):
    """
    "optimize" section shared by every supervised fit node's parameters.

    Attributes:
        optimize: Search for the hyperparameter values that maximise
            (or, for an error-style metric, minimise) the test score,
            instead of fitting once with the values above directly.
            ``X_test`` / ``y_test`` become required inputs only when
            this is on -- every trial is scored against them.
        optimize_bounds: JSON ``{param: [lo, hi]}`` -- which of this
            node's own numeric hyperparameters to search over, and the
            inclusive range for each (edited as a table; see
            ``core.params.optimize_bounds_field``).
        optimize_metric: Score to optimize. Whichever of classification
            / regression actually applies to this node (a classifier or
            a regressor, detected from the fitted estimator) is used;
            if this choice does not belong to that set, it silently
            falls back to accuracy / r2 (recorded either way in the
            ``optim`` output, so it is never ambiguous which metric was
            actually used).
        optimize_method: Optuna sampler driving the search -- "tpe"
            (default, a good general-purpose Bayesian sampler),
            "random", "cmaes" (Covariance-Matrix-Adaptation, for a
            larger continuous search), or "grid" (an evenly spaced grid
            over each bound).
        optimize_n_trials: Number of parameter combinations to try.
    """

    optimize: bool = False
    optimize_bounds: str = optimize_bounds_field(
        default="{}", visible_when=("optimize", "True")
    )
    optimize_metric: Literal[
        "accuracy", "balanced_accuracy", "precision", "recall", "f1",
        "roc_auc", "log_loss", "matthews_corrcoef", "cohen_kappa",
        "r2", "mae", "mse", "rmse", "mape", "median_absolute_error",
        "explained_variance", "max_error",
    ] = visible_field("accuracy", visible_when=("optimize", "True"))
    optimize_method: Literal["tpe", "random", "cmaes", "grid"] = visible_field(
        "tpe", visible_when=("optimize", "True")
    )
    optimize_n_trials: int = visible_field(30, visible_when=("optimize", "True"))


class SklearnFitNode(Node):
    """
    Base for the model nodes: fit ``ESTIMATORS[task]`` on
    (X_train, y_train) and output the fitted estimator.

    ``X_test`` / ``y_test`` are still accepted as (optional) inputs so a
    held-out set can be carried alongside a pipeline, but evaluation is
    done by the ``model_scores`` / ``residuals`` / model-plot nodes --
    unless ``params.optimize`` is on (see :class:`SklearnFitParams`), in
    which case they are required: every trial is scored against them,
    and the best trial's estimator (not a plain single fit) is what
    comes out of the ``model`` port.
    """

    category = "model"
    inputs = [
        Port(name="X_train", dtype="dataframe"),
        Port(name="y_train", dtype="array"),
        Port(name="X_test", dtype="dataframe", required=False),
        Port(name="y_test", dtype="array", required=False),
    ]
    outputs = [
        Port(name="model", dtype="model"),
        Port(name="optim", dtype="optim", required=False),
    ]

    #: task name -> ("import.path", "ClassName"). One entry when the
    #: algorithm has a single flavour; two ("classifier"/"regressor")
    #: when it has a ``task`` field.
    ESTIMATORS: ClassVar[dict[str, tuple[str, str]]] = {}

    def _resolve_field(self, field: str, task: str) -> tuple[str | None, bool]:
        """(real estimator arg, drop?) for one schema field."""
        for real, (clf_field, reg_field) in _TASK_ARG_FIELDS.items():
            if field == clf_field:
                return real, task != "classifier"
            if field == reg_field:
                return real, task != "regressor"
        return _RENAMED_FIELDS.get(field, field), False

    def _make_estimator(self, params: Any = None) -> Any:
        import importlib
        import inspect

        p = params if params is not None else self.params
        task = getattr(p, "task", None) or next(iter(type(self).ESTIMATORS))
        module_name, class_name = type(self).ESTIMATORS[task]
        estimator_cls = getattr(importlib.import_module(module_name), class_name)
        valid = set(inspect.signature(estimator_cls.__init__).parameters) - {"self"}

        kwargs: dict[str, Any] = {}
        for field in type(p).model_fields:
            if field == "task":
                continue
            arg, drop = self._resolve_field(field, task)
            if drop or arg is None or arg not in valid:
                continue
            kwargs[arg] = _clean_model_value(arg, getattr(p, field))
        return estimator_cls(**kwargs)

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        if getattr(self.params, "optimize", False):
            return self._run_optimize(inputs)
        estimator = self._make_estimator()
        estimator.fit(inputs["X_train"], inputs["y_train"])
        return {"model": estimator, "optim": None}

    # -- optimize section --------------------------------------------

    def _run_optimize(self, inputs: dict[str, Any]) -> dict[str, Any]:
        import json

        import numpy as np
        import optuna
        import pandas as pd
        from sklearn.base import is_classifier

        from ruyso_app.nodes.model_ops import (
            _CLASSIFICATION_METRICS,
            _REGRESSION_METRICS,
            _classification_scores,
            _regression_scores,
        )

        optuna.logging.set_verbosity(optuna.logging.WARNING)

        p = self.params
        X_train, y_train = inputs["X_train"], inputs["y_train"]
        X_test, y_test = inputs.get("X_test"), inputs.get("y_test")
        if X_test is None or y_test is None:
            raise ValueError(
                f"{self.node_type}: 'optimize' is on, which needs X_test/y_test "
                f"wired in -- every trial is scored against them."
            )

        try:
            bounds: dict[str, list[float]] = json.loads(p.optimize_bounds or "{}")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{self.node_type}: could not read optimize_bounds as JSON."
            ) from exc
        if not bounds:
            raise ValueError(
                f"{self.node_type}: 'optimize' is on but no parameter has bounds "
                f"checked in the optimize section."
            )

        schema = type(p).model_fields
        unknown = [name for name in bounds if name not in schema]
        if unknown:
            raise ValueError(f"{self.node_type}: unknown optimize parameter(s): {unknown}")
        int_params = {name for name in bounds if schema[name].annotation is int}

        # Task is a property of the estimator, not of ``optimize_metric``
        # -- a probe instance (default hyperparameters) is enough to
        # know which of classification / regression applies.
        is_clf = is_classifier(self._make_estimator())
        valid_metrics = _CLASSIFICATION_METRICS if is_clf else _REGRESSION_METRICS
        metric = p.optimize_metric if p.optimize_metric in valid_metrics else (
            "accuracy" if is_clf else "r2"
        )
        direction = "minimize" if metric in _LOWER_IS_BETTER_METRICS else "maximize"
        score_fn = _classification_scores if is_clf else _regression_scores
        y_train_arr, y_test_arr = np.asarray(y_train), np.asarray(y_test)

        trial_rows: list[dict[str, Any]] = []
        best: dict[str, Any] = {}

        def objective(trial: "optuna.Trial") -> float:
            sampled: dict[str, Any] = {}
            for pname, (lo, hi) in bounds.items():
                if pname in int_params:
                    sampled[pname] = trial.suggest_int(pname, int(lo), int(hi))
                else:
                    sampled[pname] = trial.suggest_float(pname, float(lo), float(hi))

            trial_params = type(p)(**{**p.model_dump(), **sampled})
            estimator = self._make_estimator(trial_params)
            estimator.fit(X_train, y_train)

            def _score(X: Any, y: Any) -> float:
                if is_clf:
                    return score_fn(estimator, X, y, [metric], "macro")[metric]
                return score_fn(estimator, X, y, [metric])[metric]

            train_value = _score(X_train, y_train_arr)
            test_value = _score(X_test, y_test_arr)
            trial_rows.append(
                {"trial": trial.number, **sampled, "train_score": train_value, "test_score": test_value}
            )
            if not best or (
                test_value > best["value"] if direction == "maximize" else test_value < best["value"]
            ):
                best["value"] = test_value
                best["estimator"] = estimator
                best["params"] = dict(sampled)
            return test_value

        sampler = _optuna_sampler(p.optimize_method, bounds, int_params)
        study = optuna.create_study(direction=direction, sampler=sampler)
        study.optimize(objective, n_trials=max(int(p.optimize_n_trials), 1))

        optim = {
            "method": p.optimize_method,
            "metric": metric,
            "direction": direction,
            "n_trials": len(trial_rows),
            "best_value": float(best["value"]),
            "best_params": best["params"],
            "trials": pd.DataFrame(trial_rows),
        }
        return {"model": best["estimator"], "optim": optim}


# --------------------------------------------------------------------------
# Concrete model nodes
# --------------------------------------------------------------------------


class LinearRegressionFitParams(SklearnFitParams):
    """Parameters for LinearRegressionFit (scikit-learn LinearRegression)."""

    fit_intercept: bool = True
    copy_X: bool = True
    positive: bool = False
    n_jobs: int = 0  # 0 -> None


@register_node
class LinearRegressionFit(SklearnFitNode):
    """Ordinary least-squares linear regression."""

    node_type = "linear_regression_fit"
    params_schema = LinearRegressionFitParams
    ESTIMATORS = {"regressor": ("sklearn.linear_model", "LinearRegression")}


class LogisticRegressionFitParams(SklearnFitParams):
    """Parameters for LogisticRegressionFit (scikit-learn LogisticRegression)."""

    C: float = 1.0
    l1_ratio: float = unit_interval_field(
        0.0, description="0 = ridge (L2), 1 = lasso (L1), between = elastic-net."
    )
    fit_intercept: bool = True
    class_weight: Literal["none", "balanced"] = "none"
    solver: Literal[
        "lbfgs", "liblinear", "newton-cg", "newton-cholesky", "sag", "saga"
    ] = "lbfgs"
    max_iter: int = 100
    tol: float = 1e-4
    random_state: int = 0
    n_jobs: int = 0


@register_node
class LogisticRegressionFit(SklearnFitNode):
    """Logistic-regression classifier."""

    node_type = "logistic_regression_fit"
    params_schema = LogisticRegressionFitParams
    ESTIMATORS = {"classifier": ("sklearn.linear_model", "LogisticRegression")}


class RidgeFitParams(SklearnFitParams):
    """Parameters for RidgeFit (Ridge / RidgeClassifier)."""

    task: Literal["classifier", "regressor"] = "regressor"
    alpha: float = 1.0
    fit_intercept: bool = True
    copy_X: bool = True
    max_iter: int = 0  # 0 -> solver default
    tol: float = 1e-4
    solver: Literal[
        "auto", "svd", "cholesky", "lsqr", "sparse_cg", "sag", "saga", "lbfgs"
    ] = "auto"
    positive: bool = False
    random_state: int = 0
    class_weight: Literal["none", "balanced"] = visible_field(
        "none", visible_when=("task", "classifier")
    )


@register_node
class RidgeFit(SklearnFitNode):
    """L2-penalised linear model (regression or classification)."""

    node_type = "ridge_fit"
    params_schema = RidgeFitParams
    ESTIMATORS = {
        "classifier": ("sklearn.linear_model", "RidgeClassifier"),
        "regressor": ("sklearn.linear_model", "Ridge"),
    }


class LassoFitParams(SklearnFitParams):
    """Parameters for LassoFit (scikit-learn Lasso)."""

    alpha: float = 1.0
    fit_intercept: bool = True
    precompute: bool = False
    copy_X: bool = True
    max_iter: int = 1000
    tol: float = 1e-4
    warm_start: bool = False
    positive: bool = False
    random_state: int = 0
    selection: Literal["cyclic", "random"] = "cyclic"


@register_node
class LassoFit(SklearnFitNode):
    """L1-penalised linear regression."""

    node_type = "lasso_fit"
    params_schema = LassoFitParams
    ESTIMATORS = {"regressor": ("sklearn.linear_model", "Lasso")}


class ElasticNetFitParams(SklearnFitParams):
    """Parameters for ElasticNetFit (scikit-learn ElasticNet)."""

    alpha: float = 1.0
    l1_ratio: float = unit_interval_field(0.5)
    fit_intercept: bool = True
    precompute: bool = False
    max_iter: int = 1000
    copy_X: bool = True
    tol: float = 1e-4
    warm_start: bool = False
    positive: bool = False
    random_state: int = 0
    selection: Literal["cyclic", "random"] = "cyclic"


@register_node
class ElasticNetFit(SklearnFitNode):
    """L1 + L2 penalised linear regression."""

    node_type = "elastic_net_fit"
    params_schema = ElasticNetFitParams
    ESTIMATORS = {"regressor": ("sklearn.linear_model", "ElasticNet")}


class DecisionTreeFitParams(SklearnFitParams):
    """Parameters for DecisionTreeFit (DecisionTreeClassifier / Regressor)."""

    task: Literal["classifier", "regressor"] = "classifier"
    classifier_criterion: Literal["gini", "entropy", "log_loss"] = visible_field(
        "gini", visible_when=("task", "classifier")
    )
    regressor_criterion: Literal[
        "squared_error", "friedman_mse", "absolute_error", "poisson"
    ] = visible_field("squared_error", visible_when=("task", "regressor"))
    splitter: Literal["best", "random"] = "best"
    max_depth: int = 0  # 0 -> None (grow fully)
    min_samples_split: int = 2
    min_samples_leaf: int = 1
    min_weight_fraction_leaf: float = unit_interval_field(0.0, hi=0.5)
    max_features: Literal["none", "sqrt", "log2"] = "none"
    max_leaf_nodes: int = 0  # 0 -> None
    min_impurity_decrease: float = 0.0
    ccp_alpha: float = 0.0
    random_state: int = 0
    class_weight: Literal["none", "balanced"] = visible_field(
        "none", visible_when=("task", "classifier")
    )


@register_node
class DecisionTreeFit(SklearnFitNode):
    """A single decision tree (classification or regression)."""

    node_type = "decision_tree_fit"
    params_schema = DecisionTreeFitParams
    ESTIMATORS = {
        "classifier": ("sklearn.tree", "DecisionTreeClassifier"),
        "regressor": ("sklearn.tree", "DecisionTreeRegressor"),
    }


class RandomForestFitParams(SklearnFitParams):
    """Parameters for RandomForestFit (RandomForestClassifier / Regressor)."""

    task: Literal["classifier", "regressor"] = "classifier"
    n_estimators: int = 100
    classifier_criterion: Literal["gini", "entropy", "log_loss"] = visible_field(
        "gini", visible_when=("task", "classifier")
    )
    regressor_criterion: Literal[
        "squared_error", "absolute_error", "friedman_mse", "poisson"
    ] = visible_field("squared_error", visible_when=("task", "regressor"))
    max_depth: int = 0  # 0 -> None
    min_samples_split: int = 2
    min_samples_leaf: int = 1
    max_features: Literal["sqrt", "log2", "none"] = "sqrt"
    max_leaf_nodes: int = 0  # 0 -> None
    min_impurity_decrease: float = 0.0
    bootstrap: bool = True
    oob_score: bool = False
    ccp_alpha: float = 0.0
    n_jobs: int = 0  # 0 -> None
    random_state: int = 0
    warm_start: bool = False
    class_weight: Literal[
        "none", "balanced", "balanced_subsample"
    ] = visible_field("none", visible_when=("task", "classifier"))


@register_node
class RandomForestFit(SklearnFitNode):
    """A random forest of decision trees (classification or regression)."""

    node_type = "random_forest_fit"
    params_schema = RandomForestFitParams
    ESTIMATORS = {
        "classifier": ("sklearn.ensemble", "RandomForestClassifier"),
        "regressor": ("sklearn.ensemble", "RandomForestRegressor"),
    }


class GradientBoostingFitParams(SklearnFitParams):
    """Parameters for GradientBoostingFit (GradientBoosting* estimators)."""

    task: Literal["classifier", "regressor"] = "classifier"
    classifier_loss: Literal["log_loss", "exponential"] = visible_field(
        "log_loss", visible_when=("task", "classifier")
    )
    regressor_loss: Literal[
        "squared_error", "absolute_error", "huber", "quantile"
    ] = visible_field("squared_error", visible_when=("task", "regressor"))
    learning_rate: float = 0.1
    n_estimators: int = 100
    subsample: float = unit_interval_field(1.0, lo=0.1)
    criterion: Literal["friedman_mse", "squared_error"] = "friedman_mse"
    min_samples_split: int = 2
    min_samples_leaf: int = 1
    max_depth: int = 3
    max_features: Literal["none", "sqrt", "log2"] = "none"
    min_impurity_decrease: float = 0.0
    validation_fraction: float = unit_interval_field(0.1, lo=0.01, hi=0.5)
    n_iter_no_change: int = 0  # 0 -> None (no early stopping)
    tol: float = 1e-4
    ccp_alpha: float = 0.0
    random_state: int = 0


@register_node
class GradientBoostingFit(SklearnFitNode):
    """Gradient-boosted decision trees (classification or regression)."""

    node_type = "gradient_boosting_fit"
    params_schema = GradientBoostingFitParams
    ESTIMATORS = {
        "classifier": ("sklearn.ensemble", "GradientBoostingClassifier"),
        "regressor": ("sklearn.ensemble", "GradientBoostingRegressor"),
    }


class AdaBoostFitParams(SklearnFitParams):
    """Parameters for AdaBoostFit (AdaBoostClassifier / Regressor)."""

    task: Literal["classifier", "regressor"] = "classifier"
    n_estimators: int = 50
    learning_rate: float = 1.0
    regressor_loss: Literal["linear", "square", "exponential"] = visible_field(
        "linear", visible_when=("task", "regressor")
    )
    random_state: int = 0


@register_node
class AdaBoostFit(SklearnFitNode):
    """AdaBoost ensemble (classification or regression)."""

    node_type = "adaboost_fit"
    params_schema = AdaBoostFitParams
    ESTIMATORS = {
        "classifier": ("sklearn.ensemble", "AdaBoostClassifier"),
        "regressor": ("sklearn.ensemble", "AdaBoostRegressor"),
    }


class SVMFitParams(SklearnFitParams):
    """Parameters for SVMFit (SVC / SVR)."""

    task: Literal["classifier", "regressor"] = "classifier"
    C: float = 1.0
    kernel: Literal["rbf", "linear", "poly", "sigmoid"] = "rbf"
    degree: int = 3
    gamma: Literal["scale", "auto"] = "scale"
    coef0: float = 0.0
    shrinking: bool = True
    tol: float = 1e-3
    max_iter: int = -1  # -1 = no limit
    epsilon: float = visible_field(0.1, visible_when=("task", "regressor"))
    class_weight: Literal["none", "balanced"] = visible_field(
        "none", visible_when=("task", "classifier")
    )
    random_state: int = 0


@register_node
class SVMFit(SklearnFitNode):
    """Support-vector machine (classification or regression)."""

    node_type = "svm_fit"
    params_schema = SVMFitParams
    ESTIMATORS = {
        "classifier": ("sklearn.svm", "SVC"),
        "regressor": ("sklearn.svm", "SVR"),
    }


class KNNFitParams(SklearnFitParams):
    """Parameters for KNNFit (KNeighbors Classifier / Regressor)."""

    task: Literal["classifier", "regressor"] = "classifier"
    n_neighbors: int = 5
    weights: Literal["uniform", "distance"] = "uniform"
    algorithm: Literal["auto", "ball_tree", "kd_tree", "brute"] = "auto"
    leaf_size: int = 30
    p: int = 2
    metric: Literal[
        "minkowski", "euclidean", "manhattan", "chebyshev", "cosine"
    ] = "minkowski"
    n_jobs: int = 0  # 0 -> None


@register_node
class KNNFit(SklearnFitNode):
    """k-nearest-neighbours (classification or regression)."""

    node_type = "knn_fit"
    params_schema = KNNFitParams
    ESTIMATORS = {
        "classifier": ("sklearn.neighbors", "KNeighborsClassifier"),
        "regressor": ("sklearn.neighbors", "KNeighborsRegressor"),
    }


class NaiveBayesFitParams(SklearnFitParams):
    """Parameters for NaiveBayesFit (scikit-learn GaussianNB)."""

    var_smoothing: float = 1e-9


@register_node
class NaiveBayesFit(SklearnFitNode):
    """Gaussian naive-Bayes classifier."""

    node_type = "naive_bayes_fit"
    params_schema = NaiveBayesFitParams
    ESTIMATORS = {"classifier": ("sklearn.naive_bayes", "GaussianNB")}


# --------------------------------------------------------------------------
# Clustering (unsupervised -- no target column)
# --------------------------------------------------------------------------


class SklearnClusterFitNode(SklearnFitNode):
    """
    Base for clustering model nodes: fit ``ESTIMATORS["cluster"]`` on
    ``X_train`` alone. Clustering is unsupervised, so unlike
    :class:`SklearnFitNode` this never requires (or passes) a target --
    ``y_train`` stays a wireable but optional input purely so a
    ``train_test_split`` output can still be plugged in directly
    without rewiring, and is otherwise ignored.
    """

    inputs = [
        Port(name="X_train", dtype="dataframe"),
        Port(name="y_train", dtype="array", required=False),
        Port(name="X_test", dtype="dataframe", required=False),
        Port(name="y_test", dtype="array", required=False),
    ]

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        estimator = self._make_estimator()
        estimator.fit(inputs["X_train"])
        return {"model": estimator}


class KMeansFitParams(NodeParams):
    """Parameters for KMeansFit (scikit-learn KMeans)."""

    n_clusters: int = 8
    init: Literal["k-means++", "random"] = "k-means++"
    n_init: int = 10
    max_iter: int = 300
    tol: float = 1e-4
    algorithm: Literal["lloyd", "elkan"] = "lloyd"
    random_state: int = 0


@register_node
class KMeansFit(SklearnClusterFitNode):
    """K-means clustering: partition rows into ``n_clusters`` groups by nearest centroid."""

    node_type = "kmeans_fit"
    params_schema = KMeansFitParams
    ESTIMATORS = {"cluster": ("sklearn.cluster", "KMeans")}


class MiniBatchKMeansFitParams(NodeParams):
    """Parameters for MiniBatchKMeansFit (scikit-learn MiniBatchKMeans)."""

    n_clusters: int = 8
    init: Literal["k-means++", "random"] = "k-means++"
    n_init: int = 3
    max_iter: int = 100
    batch_size: int = 1024
    tol: float = 0.0
    max_no_improvement: int = 10
    random_state: int = 0


@register_node
class MiniBatchKMeansFit(SklearnClusterFitNode):
    """K-means clustering fit in small batches -- faster, approximate, for large data."""

    node_type = "minibatch_kmeans_fit"
    params_schema = MiniBatchKMeansFitParams
    ESTIMATORS = {"cluster": ("sklearn.cluster", "MiniBatchKMeans")}


class DBSCANFitParams(NodeParams):
    """Parameters for DBSCANFit (scikit-learn DBSCAN)."""

    eps: float = 0.5
    min_samples: int = 5
    metric: Literal["euclidean", "manhattan", "cosine", "l1", "l2"] = "euclidean"
    algorithm: Literal["auto", "ball_tree", "kd_tree", "brute"] = "auto"
    leaf_size: int = 30
    n_jobs: int = 0  # 0 -> None


@register_node
class DBSCANFit(SklearnClusterFitNode):
    """
    Density-based clustering (DBSCAN): groups dense regions, marks
    sparse points as noise (cluster label -1). No ``n_clusters`` to
    pick, and no ``predict`` on new data (transductive: rewire the
    fitted ``model`` -- ``labels_`` -- rather than calling ``predict``).
    """

    node_type = "dbscan_fit"
    params_schema = DBSCANFitParams
    ESTIMATORS = {"cluster": ("sklearn.cluster", "DBSCAN")}


class HDBSCANFitParams(NodeParams):
    """Parameters for HDBSCANFit (scikit-learn HDBSCAN)."""

    min_cluster_size: int = 5
    min_samples: int = 5
    cluster_selection_epsilon: float = 0.0
    metric: Literal["euclidean", "manhattan", "cosine", "l1", "l2"] = "euclidean"
    alpha: float = 1.0
    cluster_selection_method: Literal["eom", "leaf"] = "eom"
    # named "copy_input" (not "copy") -- that name would shadow
    # pydantic.BaseModel.copy(); mapped back to HDBSCAN's real "copy"
    # arg via models._RENAMED_FIELDS.
    copy_input: bool = True


@register_node
class HDBSCANFit(SklearnClusterFitNode):
    """
    Hierarchical DBSCAN: like ``dbscan_fit`` but varies density across
    the data and does not need an ``eps`` radius. No ``predict`` on new
    data (transductive).
    """

    node_type = "hdbscan_fit"
    params_schema = HDBSCANFitParams
    ESTIMATORS = {"cluster": ("sklearn.cluster", "HDBSCAN")}


class AgglomerativeClusteringFitParams(NodeParams):
    """Parameters for AgglomerativeClusteringFit (scikit-learn AgglomerativeClustering)."""

    n_clusters: int = 2
    metric: Literal["euclidean", "manhattan", "cosine", "l1", "l2"] = "euclidean"
    linkage: Literal["ward", "complete", "average", "single"] = "ward"


@register_node
class AgglomerativeClusteringFit(SklearnClusterFitNode):
    """
    Hierarchical (bottom-up) clustering. ``linkage='ward'`` (the
    default) requires ``metric='euclidean'``. No ``predict`` on new
    data (transductive).
    """

    node_type = "agglomerative_clustering_fit"
    params_schema = AgglomerativeClusteringFitParams
    ESTIMATORS = {"cluster": ("sklearn.cluster", "AgglomerativeClustering")}


class SpectralClusteringFitParams(NodeParams):
    """Parameters for SpectralClusteringFit (scikit-learn SpectralClustering)."""

    n_clusters: int = 8
    affinity: Literal["rbf", "nearest_neighbors"] = "rbf"
    n_neighbors: int = 10
    gamma: float = 1.0
    assign_labels: Literal["kmeans", "discretize", "cluster_qr"] = "kmeans"
    random_state: int = 0


@register_node
class SpectralClusteringFit(SklearnClusterFitNode):
    """
    Graph-based clustering on an affinity matrix (good for non-convex
    clusters). No ``predict`` on new data (transductive).
    """

    node_type = "spectral_clustering_fit"
    params_schema = SpectralClusteringFitParams
    ESTIMATORS = {"cluster": ("sklearn.cluster", "SpectralClustering")}


class GaussianMixtureFitParams(NodeParams):
    """Parameters for GaussianMixtureFit (scikit-learn GaussianMixture)."""

    n_components: int = 1
    covariance_type: Literal["full", "tied", "diag", "spherical"] = "full"
    tol: float = 1e-3
    reg_covar: float = 1e-6
    max_iter: int = 100
    n_init: int = 1
    init_params: Literal["kmeans", "k-means++", "random", "random_from_data"] = "kmeans"
    random_state: int = 0


@register_node
class GaussianMixtureFit(SklearnClusterFitNode):
    """
    Soft (probabilistic) clustering: fits a mixture of Gaussians: rows
    get a hard label from ``predict`` (usable on new data, unlike the
    other clustering nodes here) or per-cluster probabilities from
    ``predict_proba`` (wire it to the ``predict`` node's
    ``probabilities`` toggle).
    """

    node_type = "gaussian_mixture_fit"
    params_schema = GaussianMixtureFitParams
    ESTIMATORS = {"cluster": ("sklearn.mixture", "GaussianMixture")}
