"""
Data-loading nodes: read a file from disk into a pandas DataFrame that
downstream nodes can consume.

Each concrete format from the pandas I/O toolkit that fits a
file-path-based UI gets its own micro type (CSV, fixed-width, Excel,
JSON, Parquet, Feather, Stata). Geospatial formats live in
``geo_loaders.py`` and produce a ``geodataframe`` instead.

Loaders otherwise leave dtypes alone, with one exception: the text
formats (CSV, fixed-width, Excel, JSON) offer a **Parse dates** option,
because a date that arrives as text stays text for the rest of the
pipeline and then sorts *lexically* -- ``01/02/2020`` before
``15/07/2019`` -- which is nobody's idea of chronological. Converting at
the source is the cheapest place to prevent that. The binary formats
(Parquet, Feather, Stata) already carry real dtypes and need no option.

Beyond that, reshaping a datetime is still a transform's job: use
``change_type`` (target ``datetime``) for a column that arrived as text
in a pipeline whose loader had the option off, or ``combine_datetime``
to build one out of separate part columns (both in
``nodes/transforms.py``).
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import Field

from ruyso_app.core import dtformat
from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import suggestions_field, visible_field
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


class LoaderParams(NodeParams):
    """Parameters common to every file loader."""

    filepath: str


# --------------------------------------------------------------------------
# shared "parse dates" option (text formats only)
# --------------------------------------------------------------------------
#
# Declared as three factory functions rather than a mixin class: pydantic
# orders a model's fields base-class-first, so inheriting these would
# push them above each loader's own options (``sep``, ``sheet``, ...) and
# bury the setting that actually identifies the file. Each call returns a
# fresh ``FieldInfo``, so reusing them across models is safe.


def _parse_dates_field() -> Any:
    return Field(
        default=False,
        description="Convert date columns to real datetimes as the file is read.",
    )


def _datetime_columns_field() -> Any:
    return visible_field(
        "",
        visible_when=("parse_dates", "True"),
        description=(
            "Comma-separated columns to convert. Blank = detect them "
            "automatically (only columns that clearly hold dates)."
        ),
    )


def _datetime_format_field() -> Any:
    return suggestions_field(
        suggestions=dtformat.COMMON_DATETIME_FORMATS,
        default="",
        visible_when=("parse_dates", "True"),
        description="strptime format of the dates in the file. Blank = infer.",
    )


def _apply_date_parsing(df: Any, params: Any) -> Any:
    """Run the shared "parse dates" option over a freshly loaded frame."""
    if not getattr(params, "parse_dates", False):
        return df
    return dtformat.parse_datetime_columns(
        df, columns=params.datetime_columns, fmt=params.datetime_format
    )


# --------------------------------------------------------------------------
# tabular loaders
# --------------------------------------------------------------------------


class CSVLoaderParams(LoaderParams):
    """Parameters for :class:`CSVLoader`."""

    sep: str = ","
    encoding: str = Field(
        default="utf-8", description="Text encoding of the file, e.g. utf-8, latin-1."
    )
    decimal: str = Field(
        default=".", description="Character used as the decimal point (',' in much of Europe)."
    )
    parse_dates: bool = _parse_dates_field()
    datetime_columns: str = _datetime_columns_field()
    datetime_format: str = _datetime_format_field()


@register_node
class CSVLoader(Node):
    """Load a delimited text file (CSV/TSV) into a DataFrame."""

    node_type = "csv_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = CSVLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = pd.read_csv(
            self.params.filepath,
            sep=self.params.sep,
            encoding=self.params.encoding or "utf-8",
            decimal=self.params.decimal or ".",
        )
        return {"df": _apply_date_parsing(df, self.params)}


class FixedWidthLoaderParams(LoaderParams):
    """Parameters for :class:`FixedWidthLoader`."""

    widths: str | None = Field(
        default=None,
        description="Comma-separated column widths. Blank = infer from the file.",
    )
    parse_dates: bool = _parse_dates_field()
    datetime_columns: str = _datetime_columns_field()
    datetime_format: str = _datetime_format_field()


@register_node
class FixedWidthLoader(Node):
    """Load a fixed-width formatted text file into a DataFrame."""

    node_type = "fixed_width_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = FixedWidthLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        widths = None
        if self.params.widths:
            widths = [int(w.strip()) for w in self.params.widths.split(",") if w.strip()]
        df = pd.read_fwf(self.params.filepath, widths=widths)
        return {"df": _apply_date_parsing(df, self.params)}


class ExcelLoaderParams(LoaderParams):
    """Parameters for :class:`ExcelLoader`."""

    sheet: str = Field(
        default="0",
        description="Sheet name, or 0-based index as a number.",
    )
    header_row: int = 0
    parse_dates: bool = _parse_dates_field()
    datetime_columns: str = _datetime_columns_field()
    datetime_format: str = _datetime_format_field()


@register_node
class ExcelLoader(Node):
    """Load one sheet of an Excel workbook into a DataFrame."""

    node_type = "excel_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ExcelLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        sheet: str | int = self.params.sheet
        if isinstance(sheet, str) and sheet.strip().isdigit():
            sheet = int(sheet.strip())
        df = pd.read_excel(
            self.params.filepath, sheet_name=sheet, header=self.params.header_row
        )
        return {"df": _apply_date_parsing(df, self.params)}


class JSONLoaderParams(LoaderParams):
    """Parameters for :class:`JSONLoader`."""

    orient: Literal["", "records", "columns", "index", "split", "table"] = ""
    lines: bool = False
    parse_dates: bool = _parse_dates_field()
    datetime_columns: str = _datetime_columns_field()
    datetime_format: str = _datetime_format_field()


@register_node
class JSONLoader(Node):
    """Load a JSON document (or JSON-lines file) into a DataFrame."""

    node_type = "json_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = JSONLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = pd.read_json(
            self.params.filepath,
            orient=self.params.orient or None,
            lines=self.params.lines,
        )
        return {"df": _apply_date_parsing(df, self.params)}


class ParquetLoaderParams(LoaderParams):
    """Parameters for :class:`ParquetLoader`."""

    columns: list[str] | None = Field(
        default=None, description="Subset of columns to read (comma-separated)."
    )


@register_node
class ParquetLoader(Node):
    """Load an Apache Parquet file into a DataFrame."""

    node_type = "parquet_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = ParquetLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = pd.read_parquet(self.params.filepath, columns=self.params.columns or None)
        return {"df": df}


class FeatherLoaderParams(LoaderParams):
    """Parameters for :class:`FeatherLoader`."""

    columns: list[str] | None = Field(
        default=None, description="Subset of columns to read (comma-separated)."
    )


@register_node
class FeatherLoader(Node):
    """Load an Arrow/Feather file into a DataFrame."""

    node_type = "feather_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = FeatherLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = pd.read_feather(self.params.filepath, columns=self.params.columns or None)
        return {"df": df}


class StataLoaderParams(LoaderParams):
    """Parameters for :class:`StataLoader`."""

    convert_categoricals: bool = True


@register_node
class StataLoader(Node):
    """Load a Stata ``.dta`` file into a DataFrame."""

    node_type = "stata_loader"
    category = "loading"
    inputs: list[Port] = []
    outputs = [Port(name="df", dtype="dataframe")]
    params_schema = StataLoaderParams

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        df = pd.read_stata(
            self.params.filepath,
            convert_categoricals=self.params.convert_categoricals,
        )
        return {"df": df}
