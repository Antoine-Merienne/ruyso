# Example from Claude

class StandardScalerParams(NodeParams):
    columns: list[str] | None = None  # None = toutes les colonnes numériques

class StandardScalerNode(Node):
    node_type = "standard_scaler"
    category = "transform"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = StandardScalerParams

    def run(self, **inputs) -> dict:
        from sklearn.preprocessing import StandardScaler
        df = inputs["df"].copy()
        cols = self.params.columns or df.select_dtypes("number").columns.tolist()
        df[cols] = StandardScaler().fit_transform(df[cols])
        return {"df": df}