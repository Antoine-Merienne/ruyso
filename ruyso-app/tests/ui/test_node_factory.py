"""
Tests for node_factory: every registered core node must produce a
matching, correctly configured NodeGraphQt node class.
"""

import pytest
from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import (
    core_node_types_by_category,
    qt_type_for,
    register_all_nodes,
)

NodeRegistry.discover_package(ruyso_app.nodes)


def test_register_all_nodes_registers_every_core_node_type(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)

    registered = set(graph.registered_nodes())
    for node_type in NodeRegistry.all():
        assert qt_type_for(node_type) in registered


def test_created_node_has_matching_input_and_output_ports(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)

    node = graph.create_node(qt_type_for("train_test_split"), name="split")
    node_cls = NodeRegistry.get("train_test_split")

    assert set(node.inputs().keys()) == {p.name for p in node_cls.inputs}
    assert set(node.outputs().keys()) == {p.name for p in node_cls.outputs}


def test_created_node_color_matches_its_category(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)

    node = graph.create_node(qt_type_for("csv_loader"), name="load")
    node_cls = NodeRegistry.get("csv_loader")

    assert node.color() == theme.color_for_category(node_cls.category)


def test_created_node_exposes_a_property_per_param_field(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)

    node = graph.create_node(qt_type_for("matplotlib_plot"), name="plot")
    node_cls = NodeRegistry.get("matplotlib_plot")

    for field_name in node_cls.params_schema.model_fields:
        assert node.has_property(field_name)


# -- the toolbox filter --------------------------------------------------

from ruyso_app.core import toolboxes as _toolboxes  # noqa: E402
from ruyso_app.engine import settings as _settings  # noqa: E402


@pytest.fixture
def _restore_toolboxes():
    yield
    _settings.reset()


def _total(grouped):
    return sum(len(v) for v in grouped.values())


def test_all_families_on_offers_every_node(qapp, _restore_toolboxes):
    _settings.set(_toolboxes.SETTING, list(_toolboxes.optional_keys()))
    assert _total(core_node_types_by_category()) == len(NodeRegistry.all())


def test_switching_a_family_off_removes_its_nodes(qapp, _restore_toolboxes):
    everything = _total(core_node_types_by_category())
    _settings.set(
        _toolboxes.SETTING,
        [k for k in _toolboxes.optional_keys() if k != "geo"],
    )
    assert _total(core_node_types_by_category()) == everything - 20
    assert "geo_buffer" not in core_node_types_by_category().get("transform", [])


def test_a_category_left_with_nothing_disappears(qapp, _restore_toolboxes):
    """So its menu entry is shown disabled rather than empty."""
    _settings.set(_toolboxes.SETTING, [])  # essentials only
    grouped = core_node_types_by_category()
    assert "export" not in grouped
    assert "statistics" not in grouped
    assert "loading" in grouped  # essential


def test_the_essential_families_cannot_be_filtered_away(qapp, _restore_toolboxes):
    _settings.set(_toolboxes.SETTING, [])
    grouped = core_node_types_by_category()
    assert grouped["loading"] and grouped["transform"] and grouped["grapher"]


def test_the_filter_does_not_touch_the_registry(qapp, _restore_toolboxes):
    """The registry is the truth about what the app has; a preference
    about what to *show* is not its business."""
    before = set(NodeRegistry.all())
    _settings.set(_toolboxes.SETTING, [])
    core_node_types_by_category()
    assert set(NodeRegistry.all()) >= before


def test_registering_twice_on_one_graph_is_allowed(qapp, _restore_toolboxes):
    """Enabling a family has to add its classes to a canvas that
    already has the others; NodeGraphQt raises rather than replacing."""
    from NodeGraphQt import NodeGraph

    graph = NodeGraph()
    _settings.set(_toolboxes.SETTING, [])
    register_all_nodes(graph)
    narrow = len(graph.node_factory.nodes)

    _settings.set(_toolboxes.SETTING, list(_toolboxes.optional_keys()))
    register_all_nodes(graph)  # must not raise
    assert len(graph.node_factory.nodes) > narrow


def test_only_enabled_families_get_a_canvas_class(qapp, _restore_toolboxes):
    """So the Tab search agrees with the menus about what exists."""
    from NodeGraphQt import NodeGraph

    _settings.set(_toolboxes.SETTING, [])
    graph = NodeGraph()
    register_all_nodes(graph)
    assert qt_type_for("geo_buffer") not in graph.node_factory.nodes
    assert qt_type_for("drop_na") in graph.node_factory.nodes
