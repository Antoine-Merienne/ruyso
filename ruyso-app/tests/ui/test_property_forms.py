"""
Tests for property_forms: every supported field shape must survive a
round trip through add_properties_to_node() -> extract_params_from_node().
"""

from NodeGraphQt import BaseNode

from ruyso_app.core.node import NodeParams
from ruyso_app.nodes.loaders import CSVLoaderParams
from ruyso_app.nodes.models import LinearRegressionFitParams, TrainTestSplitParams
from ruyso_app.nodes.transforms import DropNAParams, StandardScalerParams
from ruyso_app.nodes.viz import MatplotlibPlotParams
from ruyso_app.ui.property_forms import add_properties_to_node, extract_params_from_node


class _Bare(BaseNode):
    """A minimal BaseNode with no ports, used only to host properties in isolation."""

    __identifier__ = "test"
    NODE_NAME = "Bare"


def _node_for(params_schema: type[NodeParams], qapp) -> BaseNode:
    node = _Bare()
    add_properties_to_node(node, params_schema)
    return node


def test_required_string_field_defaults_to_empty_and_round_trips(qapp):
    node = _node_for(CSVLoaderParams, qapp)
    assert node.get_property("filepath") == ""

    node.set_property("filepath", "data/train.csv")
    params = extract_params_from_node(node, CSVLoaderParams)
    assert params == {"filepath": "data/train.csv", "sep": ","}


def test_optional_list_of_str_round_trips_as_comma_separated_text(qapp):
    node = _node_for(DropNAParams, qapp)
    assert node.get_property("columns") == ""  # None displayed as empty text

    node.set_property("columns", "a, b, c")
    params = extract_params_from_node(node, DropNAParams)
    assert params["columns"] == ["a", "b", "c"]


def test_optional_list_left_blank_parses_back_to_none(qapp):
    node = _node_for(StandardScalerParams, qapp)
    params = extract_params_from_node(node, StandardScalerParams)
    assert params["columns"] is None


def test_literal_field_becomes_combo_box_with_correct_choices(qapp):
    node = _node_for(MatplotlibPlotParams, qapp)
    assert node.get_property("kind") == "scatter"

    node.set_property("kind", "bar")
    params = extract_params_from_node(node, MatplotlibPlotParams)
    assert params["kind"] == "bar"


def test_bool_field_round_trips(qapp):
    node = _node_for(LinearRegressionFitParams, qapp)
    assert node.get_property("fit_intercept") is True

    node.set_property("fit_intercept", False)
    params = extract_params_from_node(node, LinearRegressionFitParams)
    assert params["fit_intercept"] is False


def test_int_and_float_fields_round_trip(qapp):
    node = _node_for(TrainTestSplitParams, qapp)
    node.set_property("test_size", 0.3)
    node.set_property("random_state", 7)

    params = extract_params_from_node(node, TrainTestSplitParams)
    assert params["test_size"] == 0.3
    assert params["random_state"] == 7
    assert isinstance(params["random_state"], int)


def test_optional_str_left_blank_parses_back_to_none(qapp):
    node = _node_for(MatplotlibPlotParams, qapp)
    node.set_property("x", "col_x")
    node.set_property("y", "col_y")
    # "title" left at its blank default.

    params = extract_params_from_node(node, MatplotlibPlotParams)
    assert params["title"] is None
