"""
Changing a node's *micro type* after it has been created.

The two-step creation flow (spec section 2) is: pick a macro type from
a menu, get a node on the canvas, then choose the concrete micro type
in the Options panel. But ``node_factory`` builds one fully typed
NodeGraphQt class per concrete node -- ports and parameters differ
between micro types, so a node cannot be "re-typed" in place.

Chosen mechanism (spec section 8): **recreate**. The old canvas node
is deleted and a fresh node of the new micro type is created in its
place, preserving:

* the canvas position;
* every wire whose port still exists, by name, on the new node
  (an incompatible wire is simply dropped);
* the value of any parameter whose field name is shared by both micro
  types.

The display name is **not** preserved: the new node takes the new
type's default name (e.g. "Drop Na" -> "Standard Scaler"), so the
label on the canvas always matches what the node actually is.

This is a plain function on the NodeGraphQt graph -- no UI widgets --
so it is straightforward to test headlessly.
"""

from __future__ import annotations

from NodeGraphQt import BaseNode, NodeGraph

from ruyso_app.ui.node_factory import qt_type_for


def change_node_micro_type(
    graph: NodeGraph, node: BaseNode, new_node_type: str
) -> BaseNode:
    """
    Replace ``node`` with a new node of ``new_node_type`` in the same spot.

    Args:
        graph: The NodeGraphQt graph ``node`` belongs to.
        node: The existing canvas node to replace.
        new_node_type: The core node_type to switch to (e.g. "drop_na").

    Returns:
        The newly created node. If ``new_node_type`` is already the
        node's type, the original node is returned untouched.
    """
    current_type = getattr(type(node), "CORE_NODE_TYPE", None)
    if current_type == new_node_type:
        return node

    pos = node.pos()
    old_schema = type(node).CORE_NODE_CLASS.params_schema
    saved_params = {
        field: node.get_property(field) for field in old_schema.model_fields
    }

    inbound = [
        (port_name, cp.node().name(), cp.name())
        for port_name, port in node.inputs().items()
        for cp in port.connected_ports()
    ]
    outbound = [
        (port_name, cp.node().name(), cp.name())
        for port_name, port in node.outputs().items()
        for cp in port.connected_ports()
    ]

    graph.delete_node(node, push_undo=False)
    new_node = graph.create_node(
        qt_type_for(new_node_type), pos=pos, push_undo=False
    )

    new_schema = type(new_node).CORE_NODE_CLASS.params_schema
    for field in new_schema.model_fields:
        if field in saved_params:
            new_node.set_property(field, saved_params[field])

    nodes_by_name = {n.name(): n for n in graph.all_nodes()}
    for in_port, up_name, up_port in inbound:
        up = nodes_by_name.get(up_name)
        if up is not None and in_port in new_node.inputs() and up_port in up.outputs():
            up.outputs()[up_port].connect_to(new_node.inputs()[in_port])
    for out_port, down_name, down_port in outbound:
        down = nodes_by_name.get(down_name)
        if (
            down is not None
            and out_port in new_node.outputs()
            and down_port in down.inputs()
        ):
            new_node.outputs()[out_port].connect_to(down.inputs()[down_port])

    return new_node
