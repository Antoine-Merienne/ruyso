"""
Data-loading nodes: read a file from disk into a pandas DataFrame that
downstream nodes can consume.

Each concrete format from the pandas I/O toolkit that fits a
file-path-based UI gets its own micro type (CSV, fixed-width, Excel,
JSON, Parquet, Feather, Stata). Geospatial formats live in
``geo_loaders.py`` and produce a ``geodataframe`` instead.

Every loader shares two parameters, defined on :class:`LoaderParams`:

* ``datetime_columns`` -- names of columns to coerce to datetime after
  loading (comma-separated in the UI);
* ``datetime_format`` -- an optional ``strptime`` pattern applied to
  those columns (blank = let pandas infer).
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import Field

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import column_field, suggestions_field
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

_DATETIME_COLUMNS_DESC = (
    "Names of columns to parse as datetime (comma-separated)."
)
_DATETIME_FORMAT_DESC = (
    "strptime format for those columns, e.g. %Y-%m-%d. Blank = infer."
)

#: A handful of common ``strptime`` patterns offered (non-binding) in
#: the datetime-format dropdown.
COMMON_DATETIME_FORMATS = [
    "%Y-%m-%d",
    "%Y-%m-%d %H:%M:%S",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y%m%d",
    "ISO8601",
]


class LoaderParams(NodeParams):
    """Parameters common to every file loader."""

    filepath: str
    datetime_columns: list[str] | None = column_field(
        dtypes=("any",), default=None, description=_DATETIME_COLUMNS_DESC
    )
    datetime_format: str | None = suggestions_field(
        suggestions=COMMON_DATETIME_FORMATS,
        default=None,
        description=_DATETIME_FORMAT_DESC,
    )


def parse_datetime_columns(df: pd.DataFrame, params: LoaderParams) -> pd.DataFrame:
    """
    Convert every column named in ``params.datetime_columns`` to datetime.

    Uses ``params.datetime_format`` when given, otherwise lets pandas
    infer. Raises ``ValueError`` if a named column is not in the data,
    so a typo surfaces instead of being silently ignored.
    """
    columns = params.datetime_columns or []
    if not columns:
        return df

    missing = [c for c in columns if c not in df.columns]
    if missing:
        raise ValueError(
            f"datetime column(s) not found in the loaded data: {missing}"
        )

    fmt = params.datetime_format or None
    for column in columns:
        df[column] = pd.to_datetime(df[column], format=fmt)
    return df


# --------------------------------------------------------------------------
# tabular loaders
# --------------------------------------------------------------------------


class CSVLoaderParams(LoaderParams):
    """Parameters for :class:`CSVLoader`."""

    sep: str = ","


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
        df = pd.read_csv(self.params.filepath, sep=self.params.sep)
        return {"df": parse_datetime_columns(df, self.params)}


class FixedWidthLoaderParams(LoaderParams):
    """Parameters for :class:`FixedWidthLoader`."""

    widths: str | None = Field(
        default=None,
        description="Comma-separated column widths. Blank = infer from the file.",
    )


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
        return {"df": parse_datetime_columns(df, self.params)}


class ExcelLoaderParams(LoaderParams):
    """Parameters for :class:`ExcelLoader`."""

    sheet: str = Field(
        default="0",
        description="Sheet name, or 0-based index as a number.",
    )
    header_row: int = 0


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
        return {"df": parse_datetime_columns(df, self.params)}


class JSONLoaderParams(LoaderParams):
    """Parameters for :class:`JSONLoader`."""

    orient: Literal["", "records", "columns", "index", "split", "table"] = ""
    lines: bool = False


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
        return {"df": parse_datetime_columns(df, self.params)}


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
        return {"df": parse_datetime_columns(df, self.params)}


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
        return {"df": parse_datetime_columns(df, self.params)}


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
        return {"df": parse_datetime_columns(df, self.params)}
