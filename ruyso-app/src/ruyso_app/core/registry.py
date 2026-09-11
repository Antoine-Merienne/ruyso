"""
Node registry: central lookup table mapping ``node_type`` strings to
concrete Node subclasses.

Two ways to populate the registry are supported:

1. Manual/explicit registration via the ``@register_node`` decorator,
   applied directly on each concrete Node subclass. This is the
   simplest approach and the one used by the ``nodes/`` package in
   this beta.
2. Dynamic discovery via ``NodeRegistry.discover_package(package)``,
   which imports every submodule of a given package so that any
   ``@register_node``-decorated classes they contain get registered
   as a side effect of the import. This is what lets the engine (or
   the UI) simply call ``discover_package(ruyso_app.nodes)`` once
   at startup instead of importing every node module by hand.

An entry_points-based discovery mechanism (for out-of-tree/third-party
node packages) can be added later on top of the same registry without
changing this interface — external packages would just need to expose
an ``ruyso_app.nodes`` entry point group pointing at modules to import.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Container

from ruyso_app.core.node import Node


class NodeRegistry:
    """
    Holds the mapping from ``node_type`` identifiers to Node subclasses.

    This is intentionally a simple class-level dict rather than a
    singleton instance, so that registration via the decorator can
    happen at import time without needing an app-wide object to be
    constructed first.
    """

    _nodes: dict[str, type[Node]] = {}

    @classmethod
    def register(cls, node_cls: type[Node]) -> type[Node]:
        """
        Register a Node subclass under its ``node_type`` identifier.

        Args:
            node_cls: The Node subclass to register.

        Returns:
            The same class, so this method can be used as a decorator.

        Raises:
            ValueError: If ``node_type`` is already registered by a
                different class (guards against accidental duplicate
                identifiers across node modules).
        """
        node_type = node_cls.node_type
        existing = cls._nodes.get(node_type)
        if existing is not None and existing is not node_cls:
            raise ValueError(
                f"node_type '{node_type}' is already registered to "
                f"{existing.__name__}; cannot register {node_cls.__name__}."
            )
        cls._nodes[node_type] = node_cls
        return node_cls

    @classmethod
    def get(cls, node_type: str) -> type[Node]:
        """
        Look up a registered Node subclass by its ``node_type``.

        Args:
            node_type: The identifier to look up (e.g. "csv_loader").

        Returns:
            The corresponding Node subclass.

        Raises:
            KeyError: If no node is registered under this identifier.
        """
        try:
            return cls._nodes[node_type]
        except KeyError as exc:
            available = ", ".join(sorted(cls._nodes)) or "(none registered)"
            raise KeyError(
                f"No node registered under node_type={node_type!r}. "
                f"Available: {available}"
            ) from exc

    @classmethod
    def all(cls) -> dict[str, type[Node]]:
        """Return a copy of the full node_type -> Node class mapping."""
        return dict(cls._nodes)

    @classmethod
    def by_category(cls) -> dict[str, list[str]]:
        """
        Group every registered node_type by its ``category`` (macro type).

        Returns:
            Mapping of category -> sorted list of node_type identifiers
            in that category. A category with no registered node is
            simply absent from the result (callers building a menu of
            macro types should treat a missing key as "nothing to show
            here yet", not as an error).
        """
        grouped: dict[str, list[str]] = {}
        for node_type, node_cls in cls._nodes.items():
            grouped.setdefault(node_cls.category, []).append(node_type)
        return {category: sorted(node_types) for category, node_types in grouped.items()}

    @classmethod
    def discover_package(
        cls, package: ModuleType, only: Container[str] | None = None
    ) -> None:
        """
        Import every submodule of ``package`` so that any
        ``@register_node``-decorated Node subclasses they define
        get registered as a side effect.

        Args:
            package: An already-imported package object whose
                submodules should be scanned (e.g. ``ruyso_app.nodes``).
            only: If given, the submodule names to import; the rest are
                left alone. Backs the Preferences toolboxes
                (``core.toolboxes``): a family switched off is a family
                whose modules are never imported, which is the only way
                to actually not pay for it. Note that a module another
                one imports arrives anyway -- ``geo_viz`` pulls in
                ``viz`` -- so this shortens the import list rather than
                guaranteeing an exact set.
        """
        if not hasattr(package, "__path__"):
            raise TypeError(f"{package!r} is not a package (no __path__).")

        for module_info in pkgutil.iter_modules(package.__path__):
            if only is not None and module_info.name not in only:
                continue
            importlib.import_module(f"{package.__name__}.{module_info.name}")


def register_node(node_cls: type[Node]) -> type[Node]:
    """
    Class decorator shorthand for ``NodeRegistry.register``.

    Usage:
        @register_node
        class CSVLoader(Node):
            node_type = "csv_loader"
            ...
    """
    return NodeRegistry.register(node_cls)