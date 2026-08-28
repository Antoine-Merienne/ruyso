"""
The Table tab's step navigator model: a flat, execution-ordered list
of every table a pipeline step can produce.

The mockups showed a miniature node diagram here; that was judged a
clumsy way to pick a table, so this is instead a plain file-navigator
style list. One entry per dataframe-typed output port, so a step that
emits several tables (e.g. ``train_test_split`` -> ``X_train`` /
``X_test``) appears as several entries.

This module is pure data (no widgets) so the ordering / labelling
rules are headless-testable; ``TablePage`` renders the result.
"""

from __future__ import annotations

from dataclasses import dataclass

from NodeGraphQt import NodeGraph

from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.graph_bridge import canvas_to_pipeline

#: Port dtypes considered "an inspectable table".
TABLE_DTYPES = frozenset({"dataframe"})


@dataclass(frozen=True)
class TableEntry:
    """One selectable table in the navigator."""

    node_id: str
    port: str
    label: str


def build_table_entries(order: list[str], node_types: dict[str, str]) -> list[TableEntry]:
    """
    Args:
        order: Node ids in execution (topological) order.
        node_types: ``node_id -> core node_type``.

    Returns:
        One :class:`TableEntry` per dataframe output port, in ``order``.
        The label is just the node id when the node has a single table
        output, or ``"<node id> / <port>"`` when it has several.
    """
    entries: list[TableEntry] = []
    for node_id in order:
        node_cls = NodeRegistry.all().get(node_types.get(node_id, ""))
        if node_cls is None:
            continue
        table_ports = [
            port.name
            for port in node_cls.outputs
            if getattr(port, "dtype", None) in TABLE_DTYPES
        ]
        for port in table_ports:
            label = node_id if len(table_ports) == 1 else f"{node_id} / {port}"
            entries.append(TableEntry(node_id, port, label))
    return entries


def table_entries_from_graph(graph: NodeGraph) -> list[TableEntry]:
    """Build entries from a live canvas graph, in topological order.

    Falls back to canvas creation order if the graph is not yet a
    valid DAG (e.g. mid-edit, with a cycle or a dangling node).
    """
    try:
        pipeline = canvas_to_pipeline(graph)
        order = pipeline.topological_order()
        node_types = {nid: spec.node_type for nid, spec in pipeline.nodes.items()}
    except Exception:  # noqa: BLE001 - navigator must never break the tab
        order = [n.name() for n in graph.all_nodes()]
        node_types = {
            n.name(): type(n).CORE_NODE_TYPE
            for n in graph.all_nodes()
            if hasattr(type(n), "CORE_NODE_TYPE")
        }
    return build_table_entries(order, node_types)
