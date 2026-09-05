"""
Tests for the file-loading node family: each format round-trips a
known DataFrame. Loaders do not coerce dtypes -- see
``tests/nodes/test_transforms.py`` for ``change_type``'s datetime
conversion (with an optional strptime format).
"""

import pandas as pd
import pytest

from ruyso_app.core.registry import NodeRegistry
from ruyso_app.nodes.loaders import (
    CSVLoader,
    CSVLoaderParams,
    ExcelLoader,
    ExcelLoaderParams,
    FeatherLoader,
    FeatherLoaderParams,
    FixedWidthLoader,
    FixedWidthLoaderParams,
    JSONLoader,
    JSONLoaderParams,
    ParquetLoader,
    ParquetLoaderParams,
    StataLoader,
    StataLoaderParams,
)

import ruyso_app.nodes  # noqa: F401

NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture
def frame():
    return pd.DataFrame(
        {
            "id": [1, 2, 3],
            "when": ["2021-01-01", "2021-06-15", "2021-12-31"],
            "value": [10.5, 20.0, 30.25],
        }
    )


# -- per-format round trips ------------------------------------------------


def test_csv_loader_reads_expected_shape_and_values(tmp_path):
    path = tmp_path / "s.csv"
    path.write_text("a,b\n1,10\n2,20\n3,30\n")
    df = CSVLoader(params=CSVLoaderParams(filepath=str(path))).run()["df"]
    assert list(df.columns) == ["a", "b"]
    assert df["b"].tolist() == [10, 20, 30]


def test_csv_loader_respects_custom_separator(tmp_path):
    path = tmp_path / "semi.csv"
    path.write_text("a;b\n1;10\n2;20\n")
    df = CSVLoader(params=CSVLoaderParams(filepath=str(path), sep=";")).run()["df"]
    assert df["a"].tolist() == [1, 2]


def test_fixed_width_loader(tmp_path, frame):
    path = tmp_path / "s.txt"
    path.write_text("id   value\n1    10.5\n2    20.0\n")
    df = FixedWidthLoader(params=FixedWidthLoaderParams(filepath=str(path))).run()["df"]
    assert list(df.columns) == ["id", "value"]
    assert df.shape == (2, 2)


def test_excel_loader(tmp_path, frame):
    path = tmp_path / "s.xlsx"
    frame.to_excel(path, index=False)
    df = ExcelLoader(params=ExcelLoaderParams(filepath=str(path))).run()["df"]
    assert list(df.columns) == ["id", "when", "value"]
    assert df.shape == (3, 3)


def test_json_loader(tmp_path, frame):
    path = tmp_path / "s.json"
    frame.to_json(path, orient="records")
    df = JSONLoader(
        params=JSONLoaderParams(filepath=str(path), orient="records")
    ).run()["df"]
    assert sorted(df.columns) == ["id", "value", "when"]


def test_parquet_loader_with_column_subset(tmp_path, frame):
    path = tmp_path / "s.parquet"
    frame.to_parquet(path)
    df = ParquetLoader(
        params=ParquetLoaderParams(filepath=str(path), columns=["id", "value"])
    ).run()["df"]
    assert list(df.columns) == ["id", "value"]


def test_feather_loader(tmp_path, frame):
    path = tmp_path / "s.feather"
    frame.to_feather(path)
    df = FeatherLoader(params=FeatherLoaderParams(filepath=str(path))).run()["df"]
    assert df.shape == (3, 3)


def test_stata_loader(tmp_path, frame):
    path = tmp_path / "s.dta"
    frame.to_stata(path, write_index=False)
    df = StataLoader(params=StataLoaderParams(filepath=str(path))).run()["df"]
    assert df["value"].tolist() == [10.5, 20.0, 30.25]


# -- loaders do not coerce dtypes ---------------------------------------


def test_csv_loader_leaves_a_date_looking_column_as_text(tmp_path, frame):
    # dtype coercion is a transform's job (change_type) now, not a loader's.
    path = tmp_path / "s.csv"
    frame.to_csv(path, index=False)
    df = CSVLoader(params=CSVLoaderParams(filepath=str(path))).run()["df"]
    assert not pd.api.types.is_datetime64_any_dtype(df["when"])


def test_no_file_loading_node_has_a_datetime_param():
    for node_type, cls in NodeRegistry.all().items():
        if cls.category != "loading" or node_type == "example_data":
            continue
        fields = cls.params_schema.model_fields
        assert "datetime_columns" not in fields
        assert "datetime_format" not in fields
        assert "filepath" in fields
