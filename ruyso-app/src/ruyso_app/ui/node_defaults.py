"""
Seeding a freshly created node from the Chart / Export / Data preferences.

"Default figure size", "default export format", "default CSV separator"
are preferences about *new work*, not about existing pipelines. So they
are applied here, at the moment a node is created on the canvas, rather
than by rewriting the ``params_schema`` defaults:

* A saved pipeline keeps the values it was saved with. ``pipeline_to_canvas``
  sets every stored parameter after the node is built, overwriting these
  seeds, so opening a file cannot be changed by someone's preferences.
* A headless run is unaffected -- it never goes through the canvas, and
  a pipeline JSON that omits a parameter still means the schema default,
  the same thing on every machine.
* The preference can change later without touching anything already on
  the canvas, which is what "default" means.

Each rule names a preference, the parameter it seeds, and which nodes it
applies to. A rule whose parameter the node does not have is skipped, so
the table can mention a field only some nodes in a category carry.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable

from ruyso_app.core.params import colormap_field_kind
from ruyso_app.engine import settings


@dataclass(frozen=True)
class DefaultRule:
    """One preference, and the parameter on which nodes it seeds."""

    setting: str
    param: str
    #: Which node classes it applies to. Given the core ``Node`` subclass.
    applies_to: Callable[[type], bool]

    def value(self) -> Any:
        return settings.get(self.setting)


def _category(*names: str) -> Callable[[type], bool]:
    wanted = frozenset(names)
    return lambda node_cls: getattr(node_cls, "category", "") in wanted


def _node_type(*names: str) -> Callable[[type], bool]:
    wanted = frozenset(names)
    return lambda node_cls: getattr(node_cls, "node_type", "") in wanted


#: Every seeding rule, in the order they are applied.
RULES: tuple[DefaultRule, ...] = (
    # -- Chart defaults ------------------------------------------------
    DefaultRule("charts.fig_width", "fig_width", _category("grapher")),
    DefaultRule("charts.fig_height", "fig_height", _category("grapher")),
    # -- Export defaults -----------------------------------------------
    DefaultRule("export.figure_format", "format", _node_type("export_figure")),
    DefaultRule("export.figure_dpi", "dpi", _node_type("export_figure")),
    DefaultRule("export.transparent", "transparent", _node_type("export_figure")),
    DefaultRule("export.bbox_tight", "bbox_tight", _node_type("export_figure")),
    DefaultRule("export.table_format", "format", _node_type("export_table")),
    # -- Data defaults -------------------------------------------------
    DefaultRule("data.csv_separator", "sep", _node_type("csv_loader")),
    DefaultRule("data.csv_encoding", "encoding", _node_type("csv_loader")),
    DefaultRule("data.csv_decimal", "decimal", _node_type("csv_loader")),
)


def _colormap_default(node_cls: type, param: str) -> str | None:
    """
    The configured default for a colormap parameter, by its *kind*.

    Continuous and qualitative maps are not interchangeable -- a
    categorical plot coloured with ``viridis`` is unreadable -- so the
    two preferences are kept apart and matched against what the field
    itself declares.
    """
    schema = getattr(node_cls, "params_schema", None)
    field = getattr(schema, "model_fields", {}).get(param) if schema else None
    if field is None:
        return None
    kind = colormap_field_kind(field)
    if kind == "continuous":
        return settings.get("charts.continuous_colormap")
    if kind == "qualitative":
        return settings.get("charts.categorical_colormap")
    return None


def seeded_values(node_cls: type) -> dict[str, Any]:
    """
    ``{param: value}`` this node type should start with, from preferences.

    Only parameters the node actually declares are returned, and only
    where the preference holds something (a blank preference means
    "leave the node's own default alone").
    """
    schema = getattr(node_cls, "params_schema", None)
    fields = getattr(schema, "model_fields", {}) if schema else {}
    seeds: dict[str, Any] = {}

    for rule in RULES:
        if rule.param not in fields or not rule.applies_to(node_cls):
            continue
        value = rule.value()
        # Blank / zero means "leave the node's own default alone" --
        # see the note on the chart keys in engine.settings.DEFAULTS.
        if value in ("", None) or (isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0):
            continue
        seeds[rule.param] = value

    for param in fields:
        chosen = _colormap_default(node_cls, param)
        if chosen:
            seeds[param] = chosen

    return seeds


#: Set while a pipeline file is being rebuilt onto the canvas.
_suspended = False


@contextmanager
def suspended():
    """
    Turn seeding off for the duration of a block.

    Used by ``graph_bridge.pipeline_to_canvas``. Loading a file creates
    canvas nodes exactly as the user would, so without this a pipeline
    whose JSON *omits* a parameter -- hand-written files do, and the
    format allows it -- would pick up whatever the local preferences
    say, and the same file would draw differently on two machines. A
    stored parameter is written over the seed either way; this is about
    the ones that were never stored.
    """
    global _suspended
    previous = _suspended
    _suspended = True
    try:
        yield
    finally:
        _suspended = previous


def apply_to(node: Any, node_cls: type) -> None:
    """
    Push the seeded values onto a just-created canvas node.

    A no-op inside :func:`suspended`. Written with ``push_undo=False``:
    this is part of *creating* the node, not an edit made to it, and it
    would otherwise land on the undo stack as a pile of separate steps
    between "create node" and whatever the person does next.
    """
    if _suspended:
        return
    for param, value in seeded_values(node_cls).items():
        try:
            node.set_property(param, value, push_undo=False)
        except Exception:  # noqa: BLE001 - a seed must never block creation
            continue
