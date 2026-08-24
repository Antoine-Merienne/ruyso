"""
Tests for transformation nodes (DropNA, StandardScalerNode): known
input DataFrame -> expected output DataFrame.
"""

import numpy as np
import pandas as pd

from pipeline_app.nodes.transforms import (
    DropNA,
    DropNAParams,
    StandardScalerNode,
    StandardScalerParams,
)


def test_drop_na_removes_rows_with_any_missing_value():
    df = pd.DataFrame({"a": [1, None, 3], "b": [10, 20, None]})
    node = DropNA(params=DropNAParams())

    result = node.run(df=df)["df"]

    assert result.shape == (1, 2)
    assert result.iloc[0].tolist() == [1.0, 10.0]


def test_drop_na_respects_column_subset_and_how_all():
    df = pd.DataFrame({"a": [1, None, None], "b": [10, None, 30]})
    node = DropNA(params=DropNAParams(columns=["a", "b"], how="all"))

    result = node.run(df=df)["df"]

    # Only the row where BOTH a and b are missing should be dropped.
    assert result.shape == (2, 2)


def test_standard_scaler_produces_zero_mean_unit_variance():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0]})
    node = StandardScalerNode(params=StandardScalerParams())

    result = node.run(df=df)["df"]

    assert np.isclose(result["x"].mean(), 0.0, atol=1e-9)
    assert np.isclose(result["x"].std(ddof=0), 1.0, atol=1e-9)


def test_standard_scaler_only_scales_requested_columns():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [100.0, 200.0, 300.0]})
    node = StandardScalerNode(params=StandardScalerParams(columns=["x"]))

    result = node.run(df=df)["df"]

    # "y" must be untouched.
    assert result["y"].tolist() == [100.0, 200.0, 300.0]
    assert np.isclose(result["x"].mean(), 0.0, atol=1e-9)
