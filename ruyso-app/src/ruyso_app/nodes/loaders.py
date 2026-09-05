"""
Data-loading nodes: read a file from disk into a pandas DataFrame that
downstream nodes can consume.

Each concrete format from the pandas I/O toolkit that fits a
file-path-based UI gets its own micro type (CSV, fixed-width, Excel,
JSON, Parquet, Feather, Stata). Geospatial formats live in
``geo_loaders.py`` and produce a ``geodataframe`` instead.

Loaders only read the file -- they do not coerce column dtypes.
Parsing a column as datetime is a transform's job: use ``change_type``
(target ``datetime``, with an optional strptime format) or, to build a
datetime column out of separate part columns, ``combine_datetime``
(both in ``nodes/transforms.py``).
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import Field

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node


class LoaderParams(NodeParams):
    """Parameters common to every file loader."""

    filepath: str


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
        return {"df": df}


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
        return {"df": df}


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
        return {"df": df}


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
        return {"df": df}


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
