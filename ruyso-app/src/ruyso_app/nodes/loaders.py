# Example from Claude

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.port import Port
import pandas as pd

class CSVLoaderParams(NodeParams):
    filepath: str
    sep: str = ","

class CSVLoader(Node):
    node_type = "csv_loader"
    category = "loading"
    inputs = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = CSVLoaderParams

    def run(self, **inputs) -> dict:
        df = pd.read_csv(self.params.filepath, sep=self.params.sep)
        return {"df": df}