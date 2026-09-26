"""
Tests for property_forms: every supported field shape must survive a
round trip through add_properties_to_node() -> extract_params_from_node().
"""

from NodeGraphQt import BaseNode

from ruyso_app.core.node import NodeParams
from ruyso_app.nodes.loaders import CSVLoaderParams
from ruyso_app.nodes.models import LinearRegressionFitParams, TrainTestSplitParams
from ruyso_app.nodes.transforms import DropNAParams, ScalerParams
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
    assert params["filepath"] == "data/train.csv"
    assert params["sep"] == ","


def test_optional_list_of_str_round_trips_as_comma_separated_text(qapp):
    node = _node_for(DropNAParams, qapp)
    assert node.get_property("columns") == ""  # None displayed as empty text

    node.set_property("columns", "a, b, c")
    params = extract_params_from_node(node, DropNAParams)
    assert params["columns"] == ["a", "b", "c"]


def test_optional_list_left_blank_parses_back_to_none(qapp):
    node = _node_for(ScalerParams, qapp)
    params = extract_params_from_node(node, ScalerParams)
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


def test_grapher_field_specs_carry_the_new_markers():
    from ruyso_app.ui.property_forms import iter_field_specs

    specs = {sp.name: sp for sp in iter_field_specs(MatplotlibPlotParams)}

    assert specs["color_by"].column_allow_none is True
    assert specs["color_by"].is_column_list is False

    # colour channel: mark_color shown only while colour-by is empty
    assert specs["mark_color"].color_choices  # colour picker widget
    assert specs["mark_color"].visible_when_unset == "color_by"
    assert specs["colormap"].reactive_choice["options"] == "colormaps"
    assert specs["colormap"].visible_when_set == "color_by"

    # bar_mode has BOTH conditions -> shown only for a coloured bar chart
    assert specs["bar_mode"].visible_when == ("kind", "bar")
    assert specs["bar_mode"].visible_when_set == "color_by"

    # shape channel: fixed shape fields show only while shape-by is empty
    assert specs["shape_by"].column_allow_none is True
    assert specs["marker_shape"].visible_when == ("kind", "scatter")
    assert specs["marker_shape"].visible_when_unset == "shape_by"
    assert specs["line_style"].visible_when_unset == "shape_by"
    assert specs["bar_hatch"].visible_when_unset == "shape_by"
    assert specs["shape_map"].visible_when_kind == (
        "shape_by", ("categorical", "boolean")
    )

    # size channel: fixed size hidden and the range shown while size-by is set
    assert specs["point_size"].visible_when == ("kind", "scatter")
    assert specs["point_size"].visible_when_unset == "size_by"
    assert specs["size_min"].visible_when == ("kind", "scatter")
    assert specs["size_min"].visible_when_set == "size_by"
    assert specs["width_max"].visible_when == ("kind", "line")
    assert specs["width_max"].visible_when_set == "size_by"

    # alpha channel: bounded-float sliders
    assert specs["alpha"].unit_interval == {"lo": 0.0, "hi": 1.0, "step": 0.01}
    assert specs["alpha"].visible_when_unset == "alpha_by"
    assert specs["alpha_min"].visible_when_set == "alpha_by"


def test_bin_field_specs_carry_visible_unless():
    from ruyso_app.nodes.transforms import BinParams
    from ruyso_app.ui.property_forms import iter_field_specs

    specs = {sp.name: sp for sp in iter_field_specs(BinParams)}
    assert specs["bin_count"].visible_unless == ("method", "explicit")
    assert specs["cut_points"].visible_when == ("method", "explicit")
    assert specs["labels"].visible_when == ("output_type", "string")


def test_rename_categories_renames_field_is_a_category_map():
    from ruyso_app.nodes.transforms import RenameCategoriesParams
    from ruyso_app.ui.property_forms import iter_field_specs

    specs = {sp.name: sp for sp in iter_field_specs(RenameCategoriesParams)}
    assert specs["renames"].category_map == {"column": "column"}
