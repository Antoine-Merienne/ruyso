"""
Tests for the bundled example-dataset loader.
"""

import pandas as pd
import pytest

from ruyso_app.nodes.example_data import ExampleData, ExampleDataParams


def test_sklearn_toy_set_loads_with_a_target_column():
    out = ExampleData(params=ExampleDataParams(dataset="sklearn/iris")).run()["df"]
    assert isinstance(out, pd.DataFrame)
    assert out.shape == (150, 5)
    assert "target" in out.columns


def test_statsmodels_dataset_loads_offline():
    out = ExampleData(
        params=ExampleDataParams(dataset="statsmodels/longley")
    ).run()["df"]
    assert isinstance(out, pd.DataFrame)
    assert "TOTEMP" in out.columns and len(out) == 16


def test_seaborn_dataset_without_network_raises_a_clear_error():
    # In an offline sandbox the seaborn fetch fails; the node must
    # re-raise with a helpful message rather than a raw HTTP error.
    try:
        out = ExampleData(
            params=ExampleDataParams(dataset="seaborn/tips")
        ).run()["df"]
    except ValueError as exc:
        assert "network access" in str(exc)
        return
    assert isinstance(out, pd.DataFrame) and not out.empty  # cached locally -> fine


def test_example_data_is_a_source_node():
    assert ExampleData.inputs == []
    assert [p.name for p in ExampleData.outputs] == ["df"]
    assert ExampleData.category == "loading"
