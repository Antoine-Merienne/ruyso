"""
Tests for the file-loading node family: each format round-trips a
known DataFrame, and every loader applies the shared
``datetime_columns`` / ``datetime_format`` handling.
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
    parse_datetime_columns,
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


# -- shared datetime handling ------------------------------------------


def test_datetime_columns_are_parsed(tmp_path, frame):
    path = tmp_path / "s.csv"
    frame.to_csv(path, index=False)
    df = CSVLoader(
        params=CSVLoaderParams(
            filepath=str(path), datetime_columns=["when"], datetime_format="%Y-%m-%d"
        )
    ).run()["df"]
    assert pd.api.types.is_datetime64_any_dtype(df["when"])
    assert df["when"].iloc[0] == pd.Timestamp("2021-01-01")


def test_datetime_format_can_be_inferred_when_blank(frame):
    out = parse_datetime_columns(frame.copy(), CSVLoaderParams(filepath="x", datetime_columns=["when"]))
    assert pd.api.types.is_datetime64_any_dtype(out["when"])


def test_unknown_datetime_column_raises(frame):
    with pytest.raises(ValueError, match="not found"):
        parse_datetime_columns(
            frame.copy(), CSVLoaderParams(filepath="x", datetime_columns=["nope"])
        )


def test_every_file_loading_node_shares_the_datetime_params():
    # ``example_data`` is a loader with no file / no datetime parsing; the
    # shared params are for the file-path loaders (they subclass LoaderParams).
    for node_type, cls in NodeRegistry.all().items():
        if cls.category != "loading" or node_type == "example_data":
            continue
        fields = cls.params_schema.model_fields
        assert "datetime_columns" in fields
        assert "datetime_format" in fields
        assert "filepath" in fields
