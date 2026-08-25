"""
Data loading nodes: read raw data from an external source into a
pandas DataFrame that downstream nodes can consume.
"""

from typing import Any

import pandas as pd

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


class CSVLoaderParams(NodeParams):
    """
    Parameters for CSVLoader.

    Attributes:
        filepath: Path to the CSV file to load.
        sep: Field separator used in the file (default: comma).
    """

    filepath: str
    sep: str = ","


@register_node
class CSVLoader(Node):
    """
    Load a CSV file from disk into a pandas DataFrame.

    This is a source node: it has no input ports and produces a
    single "df" output port.
    """

    node_type = "csv_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = CSVLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Read the CSV file configured in ``self.params``.

        Returns:
            {"df": pandas.DataFrame} with the loaded data.
        """
        self.validate_inputs(inputs)
        df = pd.read_csv(self.params.filepath, sep=self.params.sep)
        return {"df": df}
