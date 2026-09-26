"""
Tests for ``ui.node_defaults`` -- Chart / Export / Data preferences
seeding a newly created node.

The line being defended: a preference shapes *new work*, and nothing
else. It must not reach into an existing node, a saved pipeline, or a
headless run, and out of the box it must change nothing at all.
"""

import pytest

import ruyso_app.nodes  # noqa: F401 - registers the node classes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine import settings
from ruyso_app.ui import node_defaults

NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    settings.reset()


def _seeds(node_type):
    return node_defaults.seeded_values(NodeRegistry.get(node_type))


# -- out of the box, nothing is overridden -----------------------------


def test_by_default_a_grapher_keeps_its_own_figure_size():
    """
    Eight different figure sizes are in use across the graphers, one of
    them a 6.0x2.2 strip. A single default applied to all of them would
    flatten choices their authors made on purpose.
    """
    assert "fig_width" not in _seeds("matplotlib_plot")
    assert "fig_height" not in _seeds("matplotlib_plot")


def test_by_default_the_export_seeds_match_the_nodes_own_defaults():
    fields = NodeRegistry.get("export_figure").params_schema.model_fields
    for param, value in _seeds("export_figure").items():
        assert value == fields[param].default, param


def test_a_zero_or_blank_preference_means_leave_it_alone():
    settings.update({"charts.fig_width": 0.0, "charts.categorical_colormap": ""})
    seeds = _seeds("matplotlib_plot")
    assert "fig_width" not in seeds


# -- a set preference is honoured --------------------------------------


def test_setting_a_figure_size_seeds_every_grapher():
    settings.update({"charts.fig_width": 9.0, "charts.fig_height": 3.0})
    seeds = _seeds("matplotlib_plot")
    assert seeds["fig_width"] == 9.0 and seeds["fig_height"] == 3.0


def test_the_export_format_preference_seeds_the_export_node():
    settings.set("export.figure_format", "svg")
    assert _seeds("export_figure")["format"] == "svg"
    # ...and not the table exporter, which has its own format setting.
    settings.set("export.table_format", "parquet")
    assert _seeds("export_table")["format"] == "parquet"


def test_the_csv_preferences_seed_only_the_csv_loader():
    settings.update({"data.csv_separator": ";", "data.csv_decimal": ","})
    assert _seeds("csv_loader")["sep"] == ";"
    assert _seeds("csv_loader")["decimal"] == ","
    assert "sep" not in _seeds("excel_loader")


def test_a_rule_is_skipped_when_the_node_lacks_the_parameter():
    settings.set("charts.fig_width", 9.0)
    assert "fig_width" not in _seeds("csv_loader")


# -- colormaps are matched by kind -------------------------------------


def test_a_qualitative_colormap_field_takes_the_categorical_preference():
    settings.update(
        {"charts.categorical_colormap": "Set1", "charts.continuous_colormap": "magma"}
    )
    seeds = _seeds("multivariate_timeseries_plot")  # colormap_field(kind="qualitative")
    assert seeds["colormap"] == "Set1"


def test_a_field_that_is_not_a_colormap_field_is_left_alone():
    settings.set("charts.categorical_colormap", "Set1")
    # matplotlib_plot's colormap is a reactive choice, not a colormap_field,
    # so its options depend on the colour-by column and must not be forced.
    assert "colormap" not in _seeds("matplotlib_plot")


# -- the boundary: creation only ---------------------------------------


def test_seeding_can_be_suspended(qapp):
    settings.set("charts.fig_width", 9.0)
    with node_defaults.suspended():
        assert node_defaults._suspended
    assert not node_defaults._suspended


def test_opening_a_pipeline_does_not_pick_up_local_preferences(qapp, tmp_path):
    """
    A file describes the pipeline completely: a parameter it does not
    mention means the node's own default, the same on every machine.
    """
    from ruyso_app.engine.serialization import graph_from_json
    from ruyso_app.ui.canvas import PipelineCanvas
    from ruyso_app.ui.graph_bridge import pipeline_to_canvas

    settings.set("charts.fig_width", 9.0)
    pipeline = graph_from_json(
        '{"nodes": [{"id": "p", "node_type": "matplotlib_plot",'
        ' "params": {"x": "a", "y": "b"}}], "connections": []}'
    )
    canvas = PipelineCanvas()
    nodes = pipeline_to_canvas(pipeline, canvas.graph)

    schema_default = (
        NodeRegistry.get("matplotlib_plot").params_schema.model_fields["fig_width"].default
    )
    assert nodes["p"].get_property("fig_width") == schema_default


def test_creating_a_node_by_hand_does_pick_them_up(qapp):
    from ruyso_app.ui.canvas import PipelineCanvas
    from ruyso_app.ui.node_factory import qt_type_for

    settings.set("charts.fig_width", 9.0)
    canvas = PipelineCanvas()
    node = canvas.graph.create_node(qt_type_for("matplotlib_plot"), name="p")

    assert node.get_property("fig_width") == 9.0
