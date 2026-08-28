"""
Modeling nodes: split data for training/evaluation, and fit
scikit-learn estimators on it.
"""

from typing import Any

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import column_field
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
    """

    target_column: str = column_field(
        dtypes=("any",), description="Column to use as the target (y)."
    )
    test_size: float = 0.2
    random_state: int = 42


@register_node
class TrainTestSplit(Node):
    """
    Split a DataFrame into train/test feature and target sets.

    Splits the input DataFrame into features (every column except
    ``target_column``) and target (``target_column``), then performs
    a train/test split on both.
    """

    node_type = "train_test_split"
    category = "model"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [
        Port(name="X_train", dtype="dataframe"),
        Port(name="X_test", dtype="dataframe"),
        Port(name="y_train", dtype="array"),
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
        X = df.drop(columns=[target])
        y = df[target]

        X_train, X_test, y_train, y_test = train_test_split(
            X,
            y,
            test_size=self.params.test_size,
            random_state=self.params.random_state,
        )
        return {
            "X_train": X_train,
            "X_test": X_test,
            "y_train": y_train,
            "y_test": y_test,
        }


class LinearRegressionFitParams(NodeParams):
    """
    Parameters for LinearRegressionFit.

    Attributes:
        fit_intercept: Whether to fit an intercept term, forwarded
            directly to scikit-learn's LinearRegression.
    """

    fit_intercept: bool = True


@register_node
class LinearRegressionFit(Node):
    """
    Fit a scikit-learn LinearRegression model on training data, and
    optionally score it on a held-out test set if provided.

    "X_test"/"y_test" are declared as optional inputs: when they are
    connected, an R^2 "score" is produced; when they are not, "score"
    is simply absent from the output.
    """

    node_type = "linear_regression_fit"
    category = "model"
    inputs = [
        Port(name="X_train", dtype="dataframe"),
        Port(name="y_train", dtype="array"),
        Port(name="X_test", dtype="dataframe", required=False),
        Port(name="y_test", dtype="array", required=False),
    ]
    outputs = [
        Port(name="model", dtype="model"),
        Port(name="score", dtype="scalar", required=False),
    ]
    params_schema = LinearRegressionFitParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Fit the model on (X_train, y_train), score on (X_test, y_test)
        if both are given.

        Returns:
            Dict with "model" always present, and "score" present only
            if X_test/y_test were both supplied.
        """
        self.validate_inputs(inputs)
        from sklearn.linear_model import LinearRegression

        model = LinearRegression(fit_intercept=self.params.fit_intercept)
        model.fit(inputs["X_train"], inputs["y_train"])

        result: dict[str, Any] = {"model": model}
        X_test = inputs.get("X_test")
        y_test = inputs.get("y_test")
        if X_test is not None and y_test is not None:
            result["score"] = model.score(X_test, y_test)
        return result
