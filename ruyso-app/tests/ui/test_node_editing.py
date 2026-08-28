"""
Tests for ``ui.node_editing.change_node_micro_type``: swapping a node's
concrete type after creation must preserve its identity and wiring.
"""

from NodeGraphQt import NodeGraph

import ruyso_app.nodes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.node_editing import change_node_micro_type
from ruyso_app.ui.node_factory import qt_type_for, register_all_nodes

NodeRegistry.discover_package(ruyso_app.nodes)


def _graph(qapp):
    graph = NodeGraph()
    register_all_nodes(graph)
    return graph


def test_swap_adopts_new_type_name_and_keeps_position(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean", pos=(123.0, 45.0))

    new_node = change_node_micro_type(graph, node, "standard_scaler")

    assert type(new_node).CORE_NODE_TYPE == "standard_scaler"
    # name follows the new type, not the old node's name
    assert new_node.name() != "clean"
    assert "Standard Scaler" in new_node.name()
    assert new_node.pos() == [123.0, 45.0]
    assert len(graph.all_nodes()) == 1


def test_swap_is_a_noop_for_the_same_type(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    assert change_node_micro_type(graph, node, "drop_na") is node


def test_swap_reconnects_compatible_wires(qapp):
    graph = _graph(qapp)
    loader = graph.create_node(qt_type_for("csv_loader"), name="load")
    cleaner = graph.create_node(qt_type_for("drop_na"), name="clean")
    loader.set_output(0, cleaner.input(0))

    new_node = change_node_micro_type(graph, cleaner, "standard_scaler")

    upstream = new_node.inputs()["df"].connected_ports()
    assert [p.node().name() for p in upstream] == ["load"]


def test_swap_copies_shared_parameter_values(qapp):
    graph = _graph(qapp)
    node = graph.create_node(qt_type_for("drop_na"), name="clean")
    # "columns" (list[str], shown as comma text) exists on both drop_na
    # and standard_scaler.
    node.set_property("columns", "a, b")

    new_node = change_node_micro_type(graph, node, "standard_scaler")

    assert new_node.get_property("columns") == "a, b"
