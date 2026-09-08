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

from typing import Any, Callable

import joblib

from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine import colormaps as _colormaps
from ruyso_app.engine.cache import get_memory
from ruyso_app.engine.graph import GraphValidationError, PipelineGraph


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
        ExportFigure) declare ``cacheable = False`` and are always
        re-executed directly.
        """
        node_cls = NodeRegistry.get(node_type)
        if node_cls.cacheable:
            return self._cached_execute(node_type, params, inputs)
        return _execute_node(node_type, params, inputs)

    def run(
        self,
        graph: PipelineGraph,
        progress_callback: Callable[[int, int], None] | None = None,
        node_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """
        Execute ``graph`` in dependency order, attempting *every* node.

        The graph is structurally validated first — an invalid graph
        (bad node type, unsatisfied required port, cycle) raises
        ``GraphValidationError`` before any node runs. Past that, a node
        that raises at runtime is recorded rather than aborting the run,
        and its descendants are reported *blocked* (never executed).

        Args:
            graph: The pipeline to run.
            progress_callback: If given, called ``(done, total)`` after
                each node is dealt with (run, failed, or blocked).
            node_callback: If given, called ``(node_id, phase)`` as each
                node is reached, with ``phase`` one of
                ``"running"`` / ``"ok"`` / ``"error"`` / ``"blocked"``.

        Returns:
            ``(outputs, errors)`` — ``outputs`` maps node id -> output
            dict for the nodes that ran cleanly; ``errors`` maps node id
            -> message for the nodes that raised.
        """
        _colormaps.register_all(force=False)  # custom colormaps -> matplotlib
        graph.validate()

        order = graph.topological_order()
        total = len(order)
        outputs: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        blocked: set[str] = set()

        def emit(node_id: str, phase: str) -> None:
            if node_callback is not None:
                node_callback(node_id, phase)

        for index, node_id in enumerate(order, start=1):
            spec = graph.get_node(node_id)
            if any(
                conn.source_node in errors or conn.source_node in blocked
                for conn in graph.incoming_connections(node_id)
            ):
                blocked.add(node_id)
                emit(node_id, "blocked")
            else:
                emit(node_id, "running")
                inputs = self._collect_inputs(graph, node_id, outputs)
                try:
                    outputs[node_id] = self._execute(
                        spec.node_type, spec.params, inputs
                    )
                except Exception as exc:  # noqa: BLE001 - collected, not raised
                    errors[node_id] = str(exc)
                    emit(node_id, "error")
                else:
                    emit(node_id, "ok")
            if progress_callback is not None:
                progress_callback(index, total)

        return outputs, errors

    def run_available(
        self,
        graph: PipelineGraph,
        node_callback: Callable[[str, str], None] | None = None,
    ) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
        """
        Best-effort partial execution: run every node whose inputs are
        all present and whose execution succeeds, silently skipping
        nodes that are unwired, misconfigured, or downstream of a
        skipped/failed node. Never raises.

        This backs the UI's automatic background refresh (loading a
        data file, wiring up a node) so results appear without an
        explicit Run, even while the rest of the pipeline is unfinished.

        Args:
            node_callback: If given, called ``(node_id, phase)`` as each
                node is reached -- ``"running"`` / ``"ok"`` /
                ``"error"`` / ``"blocked"`` (unwired or downstream of a
                skip/failure).

        Returns:
            ``(outputs, errors)`` -- ``outputs`` maps node id -> output
            dict for the nodes that ran; ``errors`` maps node id ->
            message for nodes that were reached but raised.
        """

        def emit(node_id: str, phase: str) -> None:
            if node_callback is not None:
                node_callback(node_id, phase)

        _colormaps.register_all(force=False)  # custom colormaps -> matplotlib
        try:
            order = graph.topological_order()
        except GraphValidationError:
            return {}, {}

        outputs: dict[str, dict[str, Any]] = {}
        errors: dict[str, str] = {}
        for node_id in order:
            spec = graph.get_node(node_id)
            node_cls = NodeRegistry.all().get(spec.node_type)
            if node_cls is None:
                continue

            inputs: dict[str, Any] = {}
            missing_upstream = False
            for conn in graph.incoming_connections(node_id):
                upstream = outputs.get(conn.source_node)
                if upstream is None or conn.source_port not in upstream:
                    missing_upstream = True
                    break
                inputs[conn.target_port] = upstream[conn.source_port]
            if missing_upstream:
                emit(node_id, "blocked")
                continue

            required = {p.name for p in node_cls.inputs if p.required}
            if not required.issubset(inputs):
                emit(node_id, "blocked")
                continue

            emit(node_id, "running")
            try:
                outputs[node_id] = self._execute(spec.node_type, spec.params, inputs)
            except Exception as exc:  # noqa: BLE001 - collected, not raised
                errors[node_id] = str(exc)
                emit(node_id, "error")
            else:
                emit(node_id, "ok")

        return outputs, errors

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
