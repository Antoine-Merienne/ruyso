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
"""

from typing import Any, ClassVar, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import column_field, unit_interval_field, visible_field
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


class SklearnFitNode(Node):
    """
    Base for the model nodes: fit ``ESTIMATORS[task]`` on
    (X_train, y_train) and output the fitted estimator.

    ``X_test`` / ``y_test`` are still accepted as (optional) inputs so a
    held-out set can be carried alongside a pipeline, but evaluation is
    done by the ``model_scores`` / ``residuals`` / model-plot nodes.
    """

    category = "model"
    inputs = [
        Port(name="X_train", dtype="dataframe"),
        Port(name="y_train", dtype="array"),
        Port(name="X_test", dtype="dataframe", required=False),
        Port(name="y_test", dtype="array", required=False),
    ]
    outputs = [Port(name="model", dtype="model")]

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
        return field, False

    def _make_estimator(self) -> Any:
        import importlib
        import inspect

        p = self.params
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
        estimator = self._make_estimator()
        estimator.fit(inputs["X_train"], inputs["y_train"])
        return {"model": estimator}


# --------------------------------------------------------------------------
# Concrete model nodes
# --------------------------------------------------------------------------


class LinearRegressionFitParams(NodeParams):
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


class LogisticRegressionFitParams(NodeParams):
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


class RidgeFitParams(NodeParams):
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


class LassoFitParams(NodeParams):
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


class ElasticNetFitParams(NodeParams):
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


class DecisionTreeFitParams(NodeParams):
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


class RandomForestFitParams(NodeParams):
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


class GradientBoostingFitParams(NodeParams):
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


class AdaBoostFitParams(NodeParams):
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


class SVMFitParams(NodeParams):
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


class KNNFitParams(NodeParams):
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


class NaiveBayesFitParams(NodeParams):
    """Parameters for NaiveBayesFit (scikit-learn GaussianNB)."""

    var_smoothing: float = 1e-9


@register_node
class NaiveBayesFit(SklearnFitNode):
    """Gaussian naive-Bayes classifier."""

    node_type = "naive_bayes_fit"
    params_schema = NaiveBayesFitParams
    ESTIMATORS = {"classifier": ("sklearn.naive_bayes", "GaussianNB")}
