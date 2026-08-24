"""
Tests for the core Node abstraction itself (not any concrete node):
parameter validation, dict-based construction, and required-input
checking.
"""

import pytest

from pipeline_app.core.node import Node, NodeParams
from pipeline_app.core.port import Port


class DummyParams(NodeParams):
    factor: int = 2


class DummyNode(Node):
    """Minimal concrete Node used only to exercise the base class."""

    node_type = "dummy_node"
    category = "test"
    inputs = [Port(name="x", dtype="scalar"), Port(name="y", dtype="scalar", required=False)]
    outputs = [Port(name="result", dtype="scalar")]
    params_schema = DummyParams

    def run(self, **inputs):
        return {"result": inputs["x"] * self.params.factor}


def test_default_params_are_used_when_none_given():
    node = DummyNode()
    assert node.params.factor == 2


def test_params_accepts_dict_and_validates_it():
    node = DummyNode(params={"factor": 5})
    assert node.params.factor == 5


def test_params_rejects_unknown_fields():
    with pytest.raises(Exception):
        DummyNode(params={"unknown_field": 1})


def test_validate_inputs_passes_with_required_port_present():
    node = DummyNode()
    node.validate_inputs({"x": 10})  # should not raise


def test_validate_inputs_raises_on_missing_required_port():
    node = DummyNode()
    with pytest.raises(ValueError, match="missing required input"):
        node.validate_inputs({})


def test_run_produces_expected_output():
    node = DummyNode(params={"factor": 3})
    result = node.run(x=4)
    assert result == {"result": 12}
