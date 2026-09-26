"""
Tests for ``core.toolboxes`` -- the switchable node families.

Two properties. A family is defined by its *modules*, because that is
the granularity an import can actually be skipped at; and the enabled
set must be robust to a settings file that names families this version
does not have, since that is what an upgrade or a downgrade produces.
"""

import pytest

import ruyso_app.nodes  # noqa: F401 - registers the node classes
from ruyso_app.core import toolboxes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine import settings

NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture(autouse=True)
def _restore_settings():
    yield
    settings.reset()


# -- the declaration -----------------------------------------------------


def test_every_node_module_belongs_to_exactly_one_family():
    """A module in no family would have its nodes silently unswitchable."""
    import pkgutil

    declared = {m for t in toolboxes.all_toolboxes() for m in t.modules}
    actual = {
        info.name
        for info in pkgutil.iter_modules(ruyso_app.nodes.__path__)
        if not info.name.startswith("_")
    }
    assert actual - declared == set(), "node modules missing from a toolbox"
    assert declared - actual == set(), "toolbox names a module that is gone"

    seen: set[str] = set()
    for toolbox in toolboxes.all_toolboxes():
        assert not (seen & set(toolbox.modules)), toolbox.key
        seen |= set(toolbox.modules)


def _shipped_nodes() -> dict:
    """
    The nodes that come with the app.

    The registry is a process-wide dict, so a node another test defined
    is in it too. Those are exactly the out-of-tree case
    ``toolbox_for_node_class`` returns ``None`` for -- and which the
    node factory treats as enabled, so an out-of-tree node shows up
    rather than vanishing because nobody put it in a toolbox.
    """
    return {
        node_type: cls
        for node_type, cls in NodeRegistry.all().items()
        if getattr(cls, "__module__", "").startswith("ruyso_app.nodes.")
    }


def test_every_shipped_node_maps_back_to_a_family():
    for node_type, node_cls in _shipped_nodes().items():
        assert toolboxes.toolbox_for_node_class(node_cls) is not None, node_type


def test_a_node_from_outside_the_app_belongs_to_no_family():
    class Outsider:
        __module__ = "somebody_elses_plugin.nodes"

    assert toolboxes.toolbox_for_node_class(Outsider) is None


def test_the_families_account_for_every_shipped_node():
    counts = {k: len(v) for k, v in toolboxes.node_types_by_toolbox().items()}
    assert sum(counts.values()) == len(_shipped_nodes())


def test_loading_transforming_and_plotting_cannot_be_switched_off():
    """A build without them is not a lighter version of the app."""
    assert set(toolboxes.essential_keys()) == {"loading", "transform", "charts"}
    assert "geo" in toolboxes.optional_keys()


# -- the enabled set -----------------------------------------------------


def test_everything_is_on_by_default():
    assert toolboxes.enabled_keys(None) == set(
        toolboxes.optional_keys()
    ) | set(toolboxes.essential_keys())


def test_essentials_are_on_even_when_the_stored_list_omits_them():
    assert toolboxes.enabled_keys([]) == set(toolboxes.essential_keys())


def test_an_unknown_stored_family_is_ignored():
    """A settings file from another version must not switch on a ghost."""
    enabled = toolboxes.enabled_keys(["geo", "quantum"])
    assert "geo" in enabled and "quantum" not in enabled


def test_the_enabled_modules_are_the_ones_to_import():
    modules = toolboxes.enabled_modules(["geo"])
    assert {"geo_loaders", "geo_transforms", "geo_viz"} <= modules
    assert "loaders" in modules  # essential
    assert "statistics" not in modules


def test_switching_a_family_off_drops_exactly_its_modules():
    everything = toolboxes.enabled_modules(list(toolboxes.optional_keys()))
    without_geo = toolboxes.enabled_modules(
        [k for k in toolboxes.optional_keys() if k != "geo"]
    )
    assert everything - without_geo == {"geo_loaders", "geo_transforms", "geo_viz"}


def test_is_enabled_reads_the_preference():
    settings.set(toolboxes.SETTING, ["geo"])
    assert toolboxes.is_enabled("geo")
    assert not toolboxes.is_enabled("statistics")
    assert toolboxes.is_enabled("charts")  # essential


# -- discovery honours the enabled set -----------------------------------


def _imported_by(monkeypatch, **kwargs) -> list[str]:
    """
    The submodule names ``discover_package`` asks Python to import.

    Asserting on registered nodes cannot answer this: the modules are
    already in ``sys.modules`` from other tests, so importing them again
    is free and registers nothing new. What is being tested is precisely
    that the import is *not attempted*, which is where the time goes.
    """
    from ruyso_app.core import registry

    asked: list[str] = []
    real = registry.importlib.import_module

    def spy(name, *args, **kw):
        asked.append(name.rsplit(".", 1)[-1])
        return real(name, *args, **kw)

    monkeypatch.setattr(registry.importlib, "import_module", spy)
    NodeRegistry.discover_package(ruyso_app.nodes, **kwargs)
    return asked


def test_discovery_can_be_limited_to_some_modules(monkeypatch):
    """The import skip: a switched-off family is never even imported."""
    asked = _imported_by(monkeypatch, only=frozenset({"transforms", "loaders"}))

    assert set(asked) == {"transforms", "loaders"}
    assert not any(name.startswith("geo") for name in asked)


def test_discovery_with_no_filter_imports_every_module(monkeypatch):
    asked = _imported_by(monkeypatch)

    declared = {m for t in toolboxes.all_toolboxes() for m in t.modules}
    assert set(asked) == declared


def test_the_enabled_set_drives_what_gets_imported(monkeypatch):
    settings.set(toolboxes.SETTING, ["statistics"])  # no geo, no ml, no export
    asked = _imported_by(monkeypatch, only=toolboxes.enabled_modules())

    assert "statistics" in asked
    assert not any(name.startswith("geo") for name in asked)
    assert "models" not in asked
    assert "transforms" in asked  # essential, always
