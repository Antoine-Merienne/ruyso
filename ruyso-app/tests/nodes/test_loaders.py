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


# -- date parsing: off by default, opt-in on the text formats ------------
#
# Loaders still do not coerce dtypes on their own. The one exception is
# the opt-in "parse dates" option on the text formats, which exists
# because a date left as text sorts lexically for the rest of the
# pipeline (see ``test_parsed_dates_sort_chronologically`` below).

#: Loaders that offer the option, and those that deliberately do not
#: (the binary formats already carry real dtypes).
_TEXT_LOADERS = {"csv_loader", "fixed_width_loader", "excel_loader", "json_loader"}
_TYPED_LOADERS = {"parquet_loader", "feather_loader", "stata_loader"}


def test_csv_loader_leaves_a_date_looking_column_as_text_by_default(tmp_path, frame):
    path = tmp_path / "s.csv"
    frame.to_csv(path, index=False)
    df = CSVLoader(params=CSVLoaderParams(filepath=str(path))).run()["df"]
    assert not pd.api.types.is_datetime64_any_dtype(df["when"])


def test_only_the_text_loaders_offer_date_parsing():
    for node_type, cls in NodeRegistry.all().items():
        if cls.category != "loading" or node_type == "example_data":
            continue
        fields = cls.params_schema.model_fields
        assert "filepath" in fields
        if node_type in _TEXT_LOADERS:
            assert {"parse_dates", "datetime_columns", "datetime_format"} <= set(fields)
            assert fields["parse_dates"].default is False  # opt-in, never automatic
        elif node_type in _TYPED_LOADERS:
            assert "parse_dates" not in fields


def test_csv_loader_parses_dates_when_asked(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("d,v\n01/02/2020,1\n15/07/2019,2\n")
    df = CSVLoader(
        params=CSVLoaderParams(
            filepath=str(path), parse_dates=True, datetime_format="%d/%m/%Y"
        )
    ).run()["df"]
    assert pd.api.types.is_datetime64_any_dtype(df["d"])
    assert df["d"].iloc[0] == pd.Timestamp("2020-02-01")  # 1 Feb, not 2 Jan


def test_auto_detection_leaves_non_date_text_alone(tmp_path):
    path = tmp_path / "mixed.csv"
    path.write_text("d,version,word\n2020-01-01,1.2.3,alpha\n2019-07-15,1.10.0,beta\n")
    df = CSVLoader(
        params=CSVLoaderParams(filepath=str(path), parse_dates=True)
    ).run()["df"]
    assert pd.api.types.is_datetime64_any_dtype(df["d"])
    assert df["version"].tolist() == ["1.2.3", "1.10.0"]
    assert df["word"].tolist() == ["alpha", "beta"]


def test_naming_a_column_that_is_not_there_is_reported(tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("d,v\n2020-01-01,1\n")
    with pytest.raises(ValueError, match="not in the file"):
        CSVLoader(
            params=CSVLoaderParams(
                filepath=str(path), parse_dates=True, datetime_columns="dat"
            )
        ).run()


def test_parsed_dates_sort_chronologically(tmp_path):
    """The bug this option exists to prevent: text dates sort lexically."""
    from ruyso_app.nodes.transforms import Sort, SortParams

    path = tmp_path / "d.csv"
    path.write_text("d,label\n01/02/2020,b\n15/07/2019,a\n03/12/2021,c\n")

    as_text = CSVLoader(params=CSVLoaderParams(filepath=str(path))).run()["df"]
    sorted_text = Sort(params=SortParams(columns=["d"])).run(df=as_text)["df"]
    assert sorted_text["label"].tolist() == ["b", "c", "a"]  # lexical: 01, 03, 15

    as_dates = CSVLoader(
        params=CSVLoaderParams(
            filepath=str(path), parse_dates=True, datetime_format="%d/%m/%Y"
        )
    ).run()["df"]
    sorted_dates = Sort(params=SortParams(columns=["d"])).run(df=as_dates)["df"]
    assert sorted_dates["label"].tolist() == ["a", "b", "c"]  # chronological


def test_json_and_fixed_width_loaders_parse_dates_too(tmp_path):
    json_path = tmp_path / "d.json"
    json_path.write_text('[{"d": "2020-02-01"}, {"d": "2019-07-15"}]')
    df = JSONLoader(
        params=JSONLoaderParams(filepath=str(json_path), parse_dates=True)
    ).run()["df"]
    assert pd.api.types.is_datetime64_any_dtype(df["d"])

    fwf_path = tmp_path / "d.txt"
    fwf_path.write_text("d           v\n2020-02-01  1\n2019-07-15  2\n")
    df = FixedWidthLoader(
        params=FixedWidthLoaderParams(filepath=str(fwf_path), parse_dates=True)
    ).run()["df"]
    assert pd.api.types.is_datetime64_any_dtype(df["d"])
