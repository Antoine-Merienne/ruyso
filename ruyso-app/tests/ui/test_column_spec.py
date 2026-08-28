"""
Tests for ``ui.column_spec`` and the ``core.params`` column marker.
"""

import numpy as np
import pandas as pd
from NodeGraphQt import NodeGraph

import ruyso_app.nodes  # noqa: F401
from ruyso_app.core.params import column_ref_dtypes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.column_spec import (
    UNKNOWN_COLUMN,
    UNSUPPORTED_TYPE,
    dtype_kind,
    input_dataframe_columns,
    kind_accepted,
    validate_column_value,
    warning_message,
)
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes

NodeRegistry.discover_package(ruyso_app.nodes)


def test_core_marks_column_params():
    plot = NodeRegistry.get("matplotlib_plot")
    assert column_ref_dtypes(plot.params_schema.model_fields["x"]) == ["any"]
    assert column_ref_dtypes(plot.params_schema.model_fields["y"]) == ["any"]
    assert column_ref_dtypes(plot.params_schema.model_fields["kind"]) is None

    # standard_scaler genuinely needs numeric columns.
    scaler = NodeRegistry.get("standard_scaler")
    assert column_ref_dtypes(scaler.params_schema.model_fields["columns"]) == ["numeric"]


def test_dtype_kind_and_kind_accepted():
    assert dtype_kind(np.dtype("int64")) == "numeric"
    assert dtype_kind(np.dtype("bool")) == "boolean"
    assert dtype_kind(pd.Series(pd.date_range("2020", periods=1)).dtype) == "datetime"
    assert dtype_kind(np.dtype("object")) == "categorical"

    assert kind_accepted(["any"], "categorical")
    assert kind_accepted(None, "categorical")
    assert kind_accepted(["numeric"], "numeric")
    assert not kind_accepted(["numeric"], "categorical")


def test_input_dataframe_columns_follows_the_wire(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    loader = graph.create_node(qt_type_for("csv_loader"), name="load")
    plot = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    loader.set_output(0, plot.input(0))

    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    cols = input_dataframe_columns(plot, {"load": {"df": df}})
    assert cols == {"a": "numeric", "b": "categorical"}

    # No run output yet -> None (free text, no validation).
    assert input_dataframe_columns(plot, {}) is None


def test_source_node_uses_its_own_produced_columns(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    loader = graph.create_node(qt_type_for("csv_loader"), name="load")

    # A loader has no table inputs -> its column params draw from its
    # own last-run output.
    df = pd.DataFrame({"when": ["2020-01-01"], "value": [1.0]})
    cols = input_dataframe_columns(loader, {"load": {"df": df}})
    assert cols == {"when": "categorical", "value": "numeric"}
    assert input_dataframe_columns(loader, {}) is None


def test_validate_column_value_codes():
    columns = {"age": "numeric", "city": "categorical"}
    assert validate_column_value("age", ["numeric"], columns) is None
    assert validate_column_value("city", ["numeric"], columns) == UNSUPPORTED_TYPE
    assert validate_column_value("missing", ["any"], columns) == UNKNOWN_COLUMN
    # Nothing to check against.
    assert validate_column_value("whatever", ["numeric"], None) is None
    assert validate_column_value("", ["numeric"], columns) is None


def test_warning_messages_are_distinct():
    columns = {"city": "categorical"}
    unknown = warning_message(UNKNOWN_COLUMN, "nope", ["any"], columns)
    bad = warning_message(UNSUPPORTED_TYPE, "city", ["numeric"], columns)
    assert "not a column" in unknown
    assert "numeric" in bad and "categorical" in bad
    assert unknown != bad
