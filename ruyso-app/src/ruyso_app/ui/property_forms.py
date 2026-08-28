"""
Translate a node's pydantic ``params_schema`` into NodeGraphQt editable
properties, and back.

This is what makes every node's parameter form appear automatically in
NodeGraphQt's built-in Properties Bin panel, with no per-node UI code
to write: ``add_properties_to_node()`` walks the pydantic model's
fields once, at node-creation time, and creates one NodeGraphQt
property per field with an appropriate editor widget (checkbox, spin
box, combo box, ...). ``extract_params_from_node()`` does the reverse:
it reads the current value of each property back into a plain dict
suitable for constructing (or re-validating against) the
``params_schema`` -- this is what ``graph_bridge.py`` uses to turn a
canvas node into a ``NodeSpec`` for the execution engine.

Supported field shapes (covers every node in ``nodes/`` as of this
beta):
    - ``str``                    -> single-line text edit
    - ``str`` named like a path  -> file picker (field name containing
      "path" or "file", e.g. "filepath")
    - ``bool``                   -> checkbox
    - ``int``                    -> integer spin box
    - ``float``                  -> float spin box
    - ``Literal[...]``           -> combo box, one entry per choice
    - ``list[str] | None``       -> comma-separated text edit

Extending this mapping for a new parameter shape used by a future node
only requires adding one branch to ``_infer_widget`` and the matching
parsing branch in ``_parse_value`` -- nothing in ``node_factory.py`` or
elsewhere needs to change.
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from typing import Any, get_args, get_origin, Iterator

from NodeGraphQt import BaseNode
from NodeGraphQt.constants import NodePropWidgetEnum
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from ruyso_app.core.node import NodeParams

# Both spellings of "optional union" need to be recognized: pydantic
# models in this project use the modern `X | None` syntax (PEP 604,
# `types.UnionType`), but `typing.Optional[X]` / `typing.Union[X, None]`
# are equivalent and may appear in nodes written elsewhere.
_UNION_ORIGINS = (typing.Union, types.UnionType)


def add_properties_to_node(node: BaseNode, params_schema: type[NodeParams]) -> None:
    """
    Create one NodeGraphQt property per field of ``params_schema`` on ``node``.

    Args:
        node: The node instance being constructed (called from within
            its own ``__init__``, before it is added to a graph).
        params_schema: The node's parameter pydantic model.
    """
    for field_name, field_info in params_schema.model_fields.items():
        widget_type, default_value, items = _infer_widget(field_name, field_info)
        node.create_property(
            field_name,
            default_value,
            items=items,
            widget_type=widget_type.value,
            tab="Parameters",
        )


@dataclass(frozen=True)
class FieldSpec:
    """A rendering-agnostic description of one parameter field.

    Produced by :func:`iter_field_specs` so a form can be built with
    plain Qt widgets (e.g. the Options panel) without re-deriving the
    pydantic-field -> widget mapping that :func:`_infer_widget` already
    encodes. ``widget`` is a ``NodePropWidgetEnum`` value; ``choices``
    is populated only for ``QCOMBO_BOX``.
    """

    name: str
    widget: NodePropWidgetEnum
    default: Any
    choices: list[str] | None


def iter_field_specs(params_schema: type[NodeParams]) -> Iterator[FieldSpec]:
    """Yield one :class:`FieldSpec` per field of ``params_schema``, in order."""
    for field_name, field_info in params_schema.model_fields.items():
        widget_type, default_value, items = _infer_widget(field_name, field_info)
        yield FieldSpec(field_name, widget_type, default_value, items)


def extract_params_from_node(node: BaseNode, params_schema: type[NodeParams]) -> dict[str, Any]:
    """
    Read every ``params_schema`` field back from ``node``'s current
    property values, parsed to the type the schema expects.

    Args:
        node: A node created via a class built by ``node_factory``.
        params_schema: The node's parameter pydantic model.

    Returns:
        A plain dict suitable for ``NodeSpec(params=...)``.
    """
    params: dict[str, Any] = {}
    for field_name, field_info in params_schema.model_fields.items():
        raw_value = node.get_property(field_name)
        params[field_name] = _parse_value(raw_value, field_info.annotation)
    return params


# --- internals --------------------------------------------------------------


def _infer_widget(
    field_name: str, field_info: FieldInfo
) -> tuple[NodePropWidgetEnum, Any, list[str] | None]:
    """Decide which NodeGraphQt widget, default value, and choices a field gets."""
    annotation, optional = _unwrap_optional(field_info.annotation)
    default = _default_value(field_info, annotation, optional)

    literal_choices = _literal_choices(annotation)
    if literal_choices is not None:
        return NodePropWidgetEnum.QCOMBO_BOX, str(default), literal_choices

    if annotation is bool:
        return NodePropWidgetEnum.QCHECK_BOX, bool(default), None

    if annotation is int:
        return NodePropWidgetEnum.INT, int(default), None

    if annotation is float:
        return NodePropWidgetEnum.FLOAT, float(default), None

    if _is_str_list(annotation):
        # Edited as one comma-separated string; parsed back into a
        # list[str] (or None if left blank) by _parse_value.
        text = ", ".join(default) if isinstance(default, list) else ""
        return NodePropWidgetEnum.QLINE_EDIT, text, None

    # Plain string is the fallback (covers str and Optional[str]).
    if "path" in field_name.lower() or "file" in field_name.lower():
        return NodePropWidgetEnum.FILE_OPEN, "" if default is None else str(default), None
    return NodePropWidgetEnum.QLINE_EDIT, "" if default is None else str(default), None


def _parse_value(raw_value: Any, annotation: Any) -> Any:
    """Convert a raw NodeGraphQt property value back to its schema type."""
    annotation, optional = _unwrap_optional(annotation)

    if _literal_choices(annotation) is not None:
        return raw_value  # combo box already returns one of the valid strings

    if annotation is bool:
        return bool(raw_value)
    if annotation is int:
        return int(raw_value)
    if annotation is float:
        return float(raw_value)
    if _is_str_list(annotation):
        text = str(raw_value).strip()
        if not text:
            return None
        return [item.strip() for item in text.split(",") if item.strip()]

    text = str(raw_value)
    if optional and not text:
        return None
    return text


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Return (inner_type, was_optional) for an ``X | None`` annotation."""
    if get_origin(annotation) in _UNION_ORIGINS:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _literal_choices(annotation: Any) -> list[str] | None:
    if get_origin(annotation) is typing.Literal:
        return [str(choice) for choice in get_args(annotation)]
    return None


def _is_str_list(annotation: Any) -> bool:
    return get_origin(annotation) is list and get_args(annotation) == (str,)


def _default_value(field_info: FieldInfo, annotation: Any, optional: bool) -> Any:
    """Compute a display default even for required fields (which have none)."""
    if field_info.default is not PydanticUndefined:
        return field_info.default
    if optional:
        return None
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if _is_str_list(annotation):
        return []
    return ""
