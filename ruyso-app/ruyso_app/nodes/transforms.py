"""
Data cleaning / transformation nodes: take a DataFrame in, produce a
modified DataFrame out. Each node performs a single, well-defined
transformation so pipelines stay easy to read and to compose.
"""

from typing import Any

from pydantic import Field

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


class DropNAParams(NodeParams):
    """
    Parameters for DropNA.

    Attributes:
        columns: Restrict the NA-check to these columns only. If None
            (default), a row is dropped if it has a missing value in
            ANY column (pandas.DataFrame.dropna default behaviour).
        how: "any" drops a row if at least one relevant value is NA;
            "all" drops a row only if every relevant value is NA.
    """

    columns: list[str] | None = None
    how: str = Field(default="any", pattern="^(any|all)$")


@register_node
class DropNA(Node):
    """
    Remove rows containing missing values from a DataFrame.
    """

    node_type = "drop_na"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = DropNAParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Drop rows with missing values according to ``self.params``.

        Args:
            df: Input pandas.DataFrame (via the "df" input port).

        Returns:
            {"df": pandas.DataFrame} with offending rows removed.
        """
        self.validate_inputs(inputs)
        df = inputs["df"]
        cleaned = df.dropna(subset=self.params.columns, how=self.params.how)
        return {"df": cleaned}


class StandardScalerParams(NodeParams):
    """
    Parameters for StandardScalerNode.

    Attributes:
        columns: Numeric columns to scale. If None (default), every
            numeric column in the DataFrame is scaled.
    """

    columns: list[str] | None = None


@register_node
class StandardScalerNode(Node):
    """
    Standardize numeric columns to zero mean and unit variance, using
    scikit-learn's StandardScaler.
    """

    node_type = "standard_scaler"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = StandardScalerParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Scale the configured (or auto-detected numeric) columns.

        Args:
            df: Input pandas.DataFrame (via the "df" input port).

        Returns:
            {"df": pandas.DataFrame} with the target columns scaled.
        """
        self.validate_inputs(inputs)
        from sklearn.preprocessing import StandardScaler

        df = inputs["df"].copy()
        columns = self.params.columns or df.select_dtypes(
            include="number"
        ).columns.tolist()
        df[columns] = StandardScaler().fit_transform(df[columns])
        return {"df": df}
