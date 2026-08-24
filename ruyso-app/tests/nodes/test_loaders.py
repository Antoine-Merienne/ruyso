"""
Tests for loading nodes (CSVLoader): known input file -> expected
DataFrame output.
"""

import pandas as pd
import pytest

from pipeline_app.nodes.loaders import CSVLoader, CSVLoaderParams


@pytest.fixture
def sample_csv(tmp_path):
    """Write a small, known CSV file and return its path."""
    path = tmp_path / "sample.csv"
    path.write_text("a,b\n1,10\n2,20\n3,30\n")
    return str(path)


def test_csv_loader_reads_expected_shape_and_values(sample_csv):
    node = CSVLoader(params=CSVLoaderParams(filepath=sample_csv))
    result = node.run()

    df = result["df"]
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["a", "b"]
    assert df.shape == (3, 2)
    assert df["b"].tolist() == [10, 20, 30]


def test_csv_loader_respects_custom_separator(tmp_path):
    path = tmp_path / "semicolon.csv"
    path.write_text("a;b\n1;10\n2;20\n")

    node = CSVLoader(params=CSVLoaderParams(filepath=str(path), sep=";"))
    df = node.run()["df"]

    assert df.shape == (2, 2)
    assert df["a"].tolist() == [1, 2]
