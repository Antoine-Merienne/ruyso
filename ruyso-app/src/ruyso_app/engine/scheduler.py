"""
Pipeline scheduler: executes a PipelineGraph node by node.

The scheduler's job is strictly limited to orchestration:
    1. Ask the graph for a valid topological execution order.
    2. For each node, collect its inputs from the already-computed
       outputs of its upstream connections.
    3. Execute the node (through a joblib-cached function) and record
       its outputs.

It knows nothing about pandas, scikit-learn, or any specific node —
only about the generic Node/NodeSpec/Connection contracts from
``core`` and ``graph.py``. This is what lets a graph be executed
headlessly (from a script, a test, or a CLI) with no UI involved.
"""

from __future__ import annotations

from typing import Any

import joblib

from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.cache import get_memory
from ruyso_app.engine.graph import PipelineGraph


def _execute_node(
    node_type: str, params: dict[str, Any], inputs: dict[str, Any]
) -> dict[str, Any]:
    """
    Instantiate and run a single node — a pure function of its inputs.

    Kept as a standalone module-level function (rather than a method)
    specifically so it can be wrapped by ``joblib.Memory.cache``:
    joblib hashes exactly this function's arguments — ``node_type``,
    ``params``, and ``inputs`` — to decide whether a previously cached
    result can be reused instead of re-running the node. This is the
    "node + params + hash(inputs)" cache key from the design.

    Args:
        node_type: Identifier registered in the NodeRegistry.
        params: Raw parameter values for the node (validated here,
            when the node is constructed).
        inputs: Values for the node's input ports, keyed by port name.

    Returns:
        The node's output dict, keyed by output port name.
    """
    node_cls = NodeRegistry.get(node_type)
    node = node_cls(params=params)
    node.validate_inputs(inputs)
    return node.run(**inputs)


class PipelineScheduler:
    """
    Executes a validated PipelineGraph and returns every node's outputs.
    """

    def __init__(self, memory: joblib.Memory | None = None) -> None:
        """
        Args:
            memory: A joblib.Memory instance used to cache node
                executions. Defaults to ``engine.cache.get_memory()``.
                Pass ``joblib.Memory(location=None)`` to disable
                caching (e.g. in tests).
        """
        self._memory = memory if memory is not None else get_memory()
        self._cached_execute = self._memory.cache(_execute_node)

    def _execute(self, node_type: str, params: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
        """
        Run a node, going through the joblib cache only if its class
        opts into caching (``Node.cacheable``). Nodes with side
        effects or non-hashable inputs/outputs (e.g. MatplotlibPlot,
        FigureExport) declare ``cacheable = False`` and are always
        re-executed directly.
        """
        node_cls = NodeRegistry.get(node_type)
        if node_cls.cacheable:
            return self._cached_execute(node_type, params, inputs)
        return _execute_node(node_type, params, inputs)

    def run(self, graph: PipelineGraph) -> dict[str, dict[str, Any]]:
        """
        Execute every node in ``graph``, in dependency order.

        Args:
            graph: The pipeline to run. Validated internally before
                execution — an invalid graph raises before any node
                runs.

        Returns:
            Mapping of node id -> its output dict (port name -> value),
            for every node in the graph.
        """
        graph.validate()

        outputs: dict[str, dict[str, Any]] = {}
        for node_id in graph.topological_order():
            spec = graph.get_node(node_id)
            inputs = self._collect_inputs(graph, node_id, outputs)
            outputs[node_id] = self._execute(spec.node_type, spec.params, inputs)

        return outputs

    @staticmethod
    def _collect_inputs(
        graph: PipelineGraph,
        node_id: str,
        computed_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build the input dict for ``node_id`` from upstream outputs.

        Args:
            graph: The pipeline graph being executed.
            node_id: The node whose inputs are being assembled.
            computed_outputs: Outputs already produced by upstream
                nodes (guaranteed available because nodes are visited
                in topological order).

        Returns:
            Dict mapping each connected input port name to the value
            produced by the corresponding upstream output port.
        """
        inputs: dict[str, Any] = {}
        for connection in graph.incoming_connections(node_id):
            upstream_outputs = computed_outputs[connection.source_node]
            inputs[connection.target_port] = upstream_outputs[connection.source_port]
        return inputs
