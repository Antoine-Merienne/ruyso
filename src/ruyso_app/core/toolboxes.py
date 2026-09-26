"""
Node families that can be switched off, to keep the app to what you use.

129 nodes is a lot to scroll past when your work is loading a CSV and
plotting it. A *toolbox* groups nodes into a family that can be turned
off in Preferences, which does two things:

* **Shortens the menus.** ``node_factory.core_node_types_by_category``
  filters by the enabled set, so the New Node menu, the canvas menu and
  the micro-type dropdown all narrow together. This is immediate.
* **Skips the import.** ``NodeRegistry.discover_package(only=...)`` is
  given the enabled modules at startup, so a disabled family's module
  is never imported. Only the geo family carries real weight -- around
  220ms of the ~680ms discovery step, and the whole geopandas/pyproj
  import with it -- because pandas and numpy are already loaded by
  ``transforms`` regardless. This applies at the *next* launch: a module
  already imported cannot be un-imported.

A family is defined by its **modules**, not by node category, because
that is the granularity an import can be skipped at. The two do not line
up: ``models.py`` holds one transform node among its model nodes, and
the geo family spans three modules across three categories.

Three families are marked essential and cannot be turned off -- loading,
transforming and plotting are what the app *is*, and a build without
them is not a lighter version of it.

GUI-free, so the enabled set can be consulted anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

#: Preference holding the keys of the optional toolboxes that are on.
SETTING = "toolbox.enabled"


@dataclass(frozen=True)
class Toolbox:
    """One switchable family of nodes."""

    key: str
    title: str
    #: Submodules of ``ruyso_app.nodes`` that define this family's nodes.
    modules: tuple[str, ...]
    #: Essential families are always on and are shown as such.
    essential: bool = False
    description: str = ""


TOOLBOXES: tuple[Toolbox, ...] = (
    Toolbox(
        "loading", "Loading", ("loaders", "example_data"),
        essential=True, description="Read files and bundled example data.",
    ),
    Toolbox(
        "transform", "Transform", ("transforms",),
        essential=True, description="Clean, reshape and combine tables.",
    ),
    Toolbox(
        "charts", "Charts", ("viz",),
        essential=True, description="Plots and table views.",
    ),
    Toolbox("export", "Export", ("export",), description="Write figures, tables and maps out."),
    Toolbox(
        "ml", "Machine learning", ("models", "model_ops"),
        description="Fit models, predict, score.",
    ),
    Toolbox(
        "statistics", "Statistics & time series", ("statistics",),
        description="Tests, regressions, ARIMA / VAR.",
    ),
    Toolbox(
        "geo", "Geo / maps", ("geo_loaders", "geo_transforms", "geo_viz"),
        description="Geographic data and maps. The heaviest to load.",
    ),
)

_BY_KEY = {toolbox.key: toolbox for toolbox in TOOLBOXES}
_BY_MODULE = {
    module: toolbox for toolbox in TOOLBOXES for module in toolbox.modules
}

#: Turned on by "Only essentials": enough to load a file, reshape it,
#: plot it and save the result.
ESSENTIAL_PRESET = ("export",)


def all_toolboxes() -> tuple[Toolbox, ...]:
    return TOOLBOXES


def get(key: str) -> Toolbox | None:
    return _BY_KEY.get(key)


def optional_keys() -> tuple[str, ...]:
    """Keys of the families that can actually be switched off."""
    return tuple(t.key for t in TOOLBOXES if not t.essential)


def essential_keys() -> tuple[str, ...]:
    return tuple(t.key for t in TOOLBOXES if t.essential)


def default_enabled() -> list[str]:
    """Everything optional, on. A fresh install has the whole node set."""
    return list(optional_keys())


# -- the enabled set -----------------------------------------------------


def enabled_keys(stored: Iterable[str] | None = None) -> set[str]:
    """
    Which families are on, essentials included.

    ``stored`` defaults to the preference. An unknown key in the stored
    list is ignored rather than believed: a settings file written by a
    version with different families should not switch on something that
    no longer exists.
    """
    if stored is None:
        from ruyso_app.engine import settings

        stored = settings.get(SETTING)
    chosen = {str(key) for key in (stored or [])} & set(optional_keys())
    return chosen | set(essential_keys())


def enabled_modules(stored: Iterable[str] | None = None) -> frozenset[str]:
    """The ``ruyso_app.nodes`` submodules the enabled families define."""
    keys = enabled_keys(stored)
    return frozenset(
        module for key in keys for module in _BY_KEY[key].modules
    )


def is_enabled(key: str, stored: Iterable[str] | None = None) -> bool:
    return key in enabled_keys(stored)


# -- mapping nodes back to their family ----------------------------------


def toolbox_for_module(module: str) -> Toolbox | None:
    """The family a ``ruyso_app.nodes`` submodule belongs to."""
    return _BY_MODULE.get(module.rsplit(".", 1)[-1])


def toolbox_for_node_class(node_cls: Any) -> Toolbox | None:
    """
    The family a registered ``Node`` subclass belongs to.

    Read off ``__module__`` rather than from a table: the module a node
    is defined in *is* the fact that decides which import carries it, so
    there is nothing to keep in sync.
    """
    module = getattr(node_cls, "__module__", "")
    return toolbox_for_module(module) if module else None


def node_types_by_toolbox() -> dict[str, list[str]]:
    """
    ``{toolbox key: [node_type, ...]}`` across *every* family.

    Imports the whole node package, so it is for the Preferences dialog
    (opened deliberately) and the open-a-pipeline guard, never for
    startup -- the point of the enabled set is not to do this.
    """
    import ruyso_app.nodes
    from ruyso_app.core.registry import NodeRegistry

    NodeRegistry.discover_package(ruyso_app.nodes)
    grouped: dict[str, list[str]] = {t.key: [] for t in TOOLBOXES}
    for node_type, node_cls in NodeRegistry.all().items():
        toolbox = toolbox_for_node_class(node_cls)
        if toolbox is not None:
            grouped[toolbox.key].append(node_type)
    return {key: sorted(types) for key, types in grouped.items()}
