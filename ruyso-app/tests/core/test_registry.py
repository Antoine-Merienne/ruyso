"""
Tests for NodeRegistry: registration, lookup, duplicate protection,
and package-based discovery.
"""

import pytest

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.registry import NodeRegistry, register_node


def test_register_and_get_round_trip():
    @register_node
    class SampleNode(Node):
        node_type = "sample_node_for_registry_test"
        category = "test"
        params_schema = NodeParams

        def run(self, **inputs):
            return {}

    assert NodeRegistry.get("sample_node_for_registry_test") is SampleNode


def test_get_unknown_node_type_raises_key_error():
    with pytest.raises(KeyError):
        NodeRegistry.get("this_node_type_does_not_exist")


def test_registering_same_class_twice_is_idempotent():
    @register_node
    class IdempotentNode(Node):
        node_type = "idempotent_node_for_registry_test"
        category = "test"
        params_schema = NodeParams

        def run(self, **inputs):
            return {}

    # Registering the exact same class again must not raise.
    register_node(IdempotentNode)
    assert NodeRegistry.get("idempotent_node_for_registry_test") is IdempotentNode


def test_registering_conflicting_class_under_same_node_type_raises():
    @register_node
    class FirstNode(Node):
        node_type = "conflicting_node_type_for_registry_test"
        category = "test"
        params_schema = NodeParams

        def run(self, **inputs):
            return {}

    with pytest.raises(ValueError, match="already registered"):

        @register_node
        class SecondNode(Node):
            node_type = "conflicting_node_type_for_registry_test"
            category = "test"
            params_schema = NodeParams

            def run(self, **inputs):
                return {}


def test_discover_package_registers_all_beta_nodes():
    import ruyso_app.nodes as nodes_package

    NodeRegistry.discover_package(nodes_package)

    expected_node_types = {
        "csv_loader",
        "drop_na",
        "standard_scaler",
        "train_test_split",
        "linear_regression_fit",
        "matplotlib_plot",
    }
    assert expected_node_types.issubset(NodeRegistry.all().keys())
