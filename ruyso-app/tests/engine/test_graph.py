"""
Tests for PipelineGraph: node/connection construction, topological
ordering, and every category of validation error.
"""

import pytest

from ruyso_app.core.registry import NodeRegistry
import ruyso_app.nodes  # noqa: F401 - imported for its registration side effects
from ruyso_app.engine.graph import (
    Connection,
    GraphValidationError,
    NodeSpec,
    PipelineGraph,
)

# Ensure all beta nodes are registered once for this test module.
NodeRegistry.discover_package(ruyso_app.nodes)


def _linear_pipeline_graph() -> PipelineGraph:
    """Build a small, valid graph: csv_loader -> drop_na -> standard_scaler."""
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="load", node_type="csv_loader", params={"filepath": "x.csv"}))
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))
    graph.add_node(NodeSpec(id="scale", node_type="standard_scaler", params={}))

    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="clean", target_port="df")
    )
    graph.add_connection(
        Connection(source_node="clean", source_port="df", target_node="scale", target_port="df")
    )
    return graph


def test_topological_order_respects_dependencies():
    graph = _linear_pipeline_graph()
    order = graph.topological_order()

    assert order.index("load") < order.index("clean") < order.index("scale")


def test_valid_graph_passes_validation():
    graph = _linear_pipeline_graph()
    graph.validate()  # should not raise


def test_duplicate_node_id_is_rejected():
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="a", node_type="csv_loader", params={"filepath": "x.csv"}))
    with pytest.raises(GraphValidationError, match="Duplicate node id"):
        graph.add_node(NodeSpec(id="a", node_type="drop_na", params={}))


def test_validate_rejects_unknown_node_type():
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="a", node_type="does_not_exist", params={}))
    with pytest.raises(GraphValidationError, match="unknown node_type"):
        graph.validate()


def test_validate_rejects_connection_to_unknown_node():
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="a", node_type="csv_loader", params={"filepath": "x.csv"}))
    graph.add_connection(
        Connection(source_node="a", source_port="df", target_node="ghost", target_port="df")
    )
    with pytest.raises(GraphValidationError, match="unknown target node"):
        graph.validate()


def test_validate_rejects_unknown_port_name():
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="a", node_type="csv_loader", params={"filepath": "x.csv"}))
    graph.add_node(NodeSpec(id="b", node_type="drop_na", params={}))
    graph.add_connection(
        Connection(
            source_node="a", source_port="not_a_real_port", target_node="b", target_port="df"
        )
    )
    with pytest.raises(GraphValidationError, match="no output port"):
        graph.validate()


def test_validate_rejects_dtype_mismatch():
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="split", node_type="train_test_split", params={"target_column": "y"})
    )
    graph.add_node(NodeSpec(id="scale", node_type="standard_scaler", params={}))
    # y_train is an "array", standard_scaler's "df" input expects "dataframe".
    graph.add_connection(
        Connection(
            source_node="split", source_port="y_train", target_node="scale", target_port="df"
        )
    )
    with pytest.raises(GraphValidationError, match="Type mismatch"):
        graph.validate()


def test_validate_rejects_missing_required_input():
    graph = PipelineGraph()
    # drop_na requires a "df" input, but nothing feeds it here.
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))
    with pytest.raises(GraphValidationError, match="missing a connection"):
        graph.validate()


def test_validate_detects_cycle():
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="a", node_type="drop_na", params={}))
    graph.add_node(NodeSpec(id="b", node_type="drop_na", params={}))
    graph.add_connection(
        Connection(source_node="a", source_port="df", target_node="b", target_port="df")
    )
    graph.add_connection(
        Connection(source_node="b", source_port="df", target_node="a", target_port="df")
    )
    with pytest.raises(GraphValidationError, match="cycle"):
        graph.validate()


def test_json_round_trip_preserves_structure():
    from src.ruyso_app.engine.serialization import graph_from_json, graph_to_json

    original = _linear_pipeline_graph()
    restored = graph_from_json(graph_to_json(original))

    assert restored.nodes.keys() == original.nodes.keys()
    assert len(restored.connections) == len(original.connections)
    restored.validate()  # round-tripped graph must still be valid
