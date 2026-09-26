"""
Tests for the bundled example-dataset loader.
"""

import pandas as pd
import pytest

from ruyso_app.nodes.example_data import _SEABORN, ExampleData, ExampleDataParams


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


def test_seaborn_dataset_loads_without_touching_the_network(monkeypatch):
    # Every seaborn dataset this node offers is pre-seeded as a CSV and
    # passed to seaborn as its cache dir (data_home), so loading one
    # must never reach out to the network.
    def _boom(*_args, **_kwargs):
        raise AssertionError("seaborn tried to reach the network")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    monkeypatch.setattr("urllib.request.urlretrieve", _boom)

    out = ExampleData(params=ExampleDataParams(dataset="seaborn/tips")).run()["df"]
    assert isinstance(out, pd.DataFrame) and not out.empty


def test_every_bundled_seaborn_dataset_loads_without_touching_the_network(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("seaborn tried to reach the network")

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    monkeypatch.setattr("urllib.request.urlretrieve", _boom)

    for name in _SEABORN:
        out = ExampleData(params=ExampleDataParams(dataset=f"seaborn/{name}")).run()["df"]
        assert isinstance(out, pd.DataFrame) and not out.empty, name


def test_every_bundled_seaborn_dataset_has_a_pre_seeded_csv():
    from ruyso_app.nodes.example_data import _SEABORN_DATA_HOME

    missing = [n for n in _SEABORN if not (_SEABORN_DATA_HOME / f"{n}.csv").exists()]
    assert missing == []


def test_example_data_is_a_source_node():
    assert ExampleData.inputs == []
    assert [p.name for p in ExampleData.outputs] == ["df"]
    assert ExampleData.category == "loading"
