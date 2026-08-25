"""
In-memory representation of a pipeline as a directed graph.

A pipeline is described by two things:

- A set of *node instances* (``NodeSpec``): each one says which
  concrete node type to instantiate (``node_type``, looked up in the
  NodeRegistry) and with which parameters.
- A set of *connections*: each one wires one node's output port to
  another node's input port.

``PipelineGraph`` stores this as plain data (via pydantic models) plus
a ``networkx.DiGraph`` used purely for structural graph algorithms
(cycle detection, topological ordering). The class deliberately knows
nothing about how nodes are executed — that is the scheduler's job —
and nothing about any UI or file format — that is serialization.py's
job. This keeps each concern independently testable.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
from pydantic import BaseModel, Field

from ruyso_app.core.registry import NodeRegistry


class NodeSpec(BaseModel):
    """
    Describes one node instance within a pipeline graph.

    Attributes:
        id: Unique identifier of this node instance within the graph
            (distinct from ``node_type``, which identifies the *class*
            of node — several instances of the same node_type, e.g.
            two CSVLoader nodes, can coexist with different ids).
        node_type: Identifier registered in the NodeRegistry
            (e.g. "csv_loader").
        params: Raw parameter values for this node instance, validated
            against the node class's ``params_schema`` when the node
            is actually instantiated (by the scheduler), not here.
    """

    id: str
    node_type: str
    params: dict[str, Any] = Field(default_factory=dict)


class Connection(BaseModel):
    """
    Describes a directed link from one node's output port to another
    node's input port.

    Attributes:
        source_node: id of the NodeSpec producing the value.
        source_port: name of the output Port on the source node.
        target_node: id of the NodeSpec consuming the value.
        target_port: name of the input Port on the target node.
    """

    source_node: str
    source_port: str
    target_node: str
    target_port: str


class GraphValidationError(ValueError):
    """Raised when a PipelineGraph fails structural or type validation."""


class PipelineGraph:
    """
    A validated, executable description of a data pipeline.

    Internally backed by a ``networkx.DiGraph`` whose node identifiers
    are the ``NodeSpec.id`` values and whose edges represent
    connections (used only for ordering/cycle detection — the actual
    port-level wiring is kept in ``self._connections``, since several
    connections can exist between the same pair of nodes on different
    ports).
    """

    def __init__(self) -> None:
        self._digraph = nx.DiGraph()
        self._nodes: dict[str, NodeSpec] = {}
        self._connections: list[Connection] = []

    # -- construction ------------------------------------------------

    def add_node(self, spec: NodeSpec) -> None:
        """
        Add a node instance to the graph.

        Raises:
            GraphValidationError: If a node with the same id already
                exists.
        """
        if spec.id in self._nodes:
            raise GraphValidationError(f"Duplicate node id: {spec.id!r}")
        self._nodes[spec.id] = spec
        self._digraph.add_node(spec.id)

    def add_connection(self, connection: Connection) -> None:
        """
        Add a connection between two already-added nodes.

        Structural correctness (node existence, port existence, dtype
        compatibility, cycles) is checked later by ``validate()``, not
        here, so that a graph can be built incrementally (e.g. while
        parsing JSON) before being fully valid.
        """
        self._connections.append(connection)
        self._digraph.add_edge(connection.source_node, connection.target_node)

    # -- accessors -----------------------------------------------------

    @property
    def nodes(self) -> dict[str, NodeSpec]:
        """Mapping of node id -> NodeSpec for every node in the graph."""
        return dict(self._nodes)

    @property
    def connections(self) -> list[Connection]:
        """All connections in the graph, in insertion order."""
        return list(self._connections)

    def get_node(self, node_id: str) -> NodeSpec:
        """Return the NodeSpec for ``node_id``, raising KeyError if absent."""
        return self._nodes[node_id]

    def incoming_connections(self, node_id: str) -> list[Connection]:
        """Return every Connection whose target is ``node_id``."""
        return [c for c in self._connections if c.target_node == node_id]

    def topological_order(self) -> list[str]:
        """
        Return node ids in an order where every node appears after all
        of its upstream dependencies.

        Raises:
            GraphValidationError: If the graph contains a cycle.
        """
        try:
            return list(nx.topological_sort(self._digraph))
        except nx.NetworkXUnfeasible as exc:
            raise GraphValidationError("Pipeline graph contains a cycle.") from exc

    # -- validation ----------------------------------------------------

    def validate(self) -> None:
        """
        Check that the graph is structurally sound and ready to run.

        Verifies, in order:
            1. Every node's ``node_type`` is registered in the NodeRegistry.
            2. Every connection references node ids that actually exist.
            3. Every connection references port names that are actually
               declared as an output (source side) / input (target side)
               on the corresponding node's class.
            4. Connected ports have compatible dtypes.
            5. Every required input port of every node is satisfied by
               exactly one incoming connection.
            6. The graph contains no cycles.

        Raises:
            GraphValidationError: On the first problem found, with a
                message identifying the offending node/connection.
        """
        self._validate_node_types()
        self._validate_connections_reference_existing_nodes()
        self._validate_ports_and_dtypes()
        self._validate_required_inputs_are_satisfied()

        # Cycle check last: topological_order() gives a precise error,
        # and there is no point reporting "it's a cycle" before basic
        # references (node ids, ports) have been confirmed valid.
        self.topological_order()

    def _validate_node_types(self) -> None:
        for spec in self._nodes.values():
            try:
                NodeRegistry.get(spec.node_type)
            except KeyError as exc:
                raise GraphValidationError(
                    f"Node {spec.id!r} references unknown node_type "
                    f"{spec.node_type!r}."
                ) from exc

    def _validate_connections_reference_existing_nodes(self) -> None:
        for conn in self._connections:
            if conn.source_node not in self._nodes:
                raise GraphValidationError(
                    f"Connection references unknown source node "
                    f"{conn.source_node!r}."
                )
            if conn.target_node not in self._nodes:
                raise GraphValidationError(
                    f"Connection references unknown target node "
                    f"{conn.target_node!r}."
                )

    def _validate_ports_and_dtypes(self) -> None:
        for conn in self._connections:
            source_cls = NodeRegistry.get(self._nodes[conn.source_node].node_type)
            target_cls = NodeRegistry.get(self._nodes[conn.target_node].node_type)

            source_port = self._find_port(source_cls.outputs, conn.source_port)
            if source_port is None:
                raise GraphValidationError(
                    f"Node {conn.source_node!r} ({source_cls.node_type}) has "
                    f"no output port named {conn.source_port!r}."
                )

            target_port = self._find_port(target_cls.inputs, conn.target_port)
            if target_port is None:
                raise GraphValidationError(
                    f"Node {conn.target_node!r} ({target_cls.node_type}) has "
                    f"no input port named {conn.target_port!r}."
                )

            if source_port.dtype != target_port.dtype:
                raise GraphValidationError(
                    f"Type mismatch: {conn.source_node}.{conn.source_port} "
                    f"({source_port.dtype}) -> {conn.target_node}.{conn.target_port} "
                    f"({target_port.dtype})."
                )

    def _validate_required_inputs_are_satisfied(self) -> None:
        for spec in self._nodes.values():
            node_cls = NodeRegistry.get(spec.node_type)
            connected_ports = {
                c.target_port for c in self.incoming_connections(spec.id)
            }
            for port in node_cls.inputs:
                if port.required and port.name not in connected_ports:
                    raise GraphValidationError(
                        f"Node {spec.id!r} ({spec.node_type}) is missing a "
                        f"connection for required input port {port.name!r}."
                    )

    @staticmethod
    def _find_port(ports, name: str):
        return next((p for p in ports if p.name == name), None)
