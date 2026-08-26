"""
Tests for node_factory: every registered core node must produce a
matching, correctly configured NodeGraphQt node class.
"""

from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui import theme
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes

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
