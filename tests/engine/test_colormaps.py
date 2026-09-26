"""
Tests for ``engine.colormaps`` -- the custom-colormap store and its
matplotlib registration.

The session-wide ``_isolate_ruyso_config`` fixture (tests/conftest.py)
already points the store at a throwaway dir; each test here further
resets it so they don't see each other's writes.
"""

import matplotlib
import pytest

import ruyso_app.nodes  # noqa: F401 - registration side effects
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine import colormaps as cm

NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture(autouse=True)
def _fresh_store():
    cm.save_store({"custom": {}, "lists": {}})
    cm._last_signature = None
    yield
    cm.save_store({"custom": {}, "lists": {}})


def test_resolved_lists_defaults_to_the_builtins():
    lists = cm.resolved_lists()
    assert lists["continuous"] == cm.BUILTIN["continuous"]
    assert lists["qualitative"] == cm.BUILTIN["qualitative"]


def test_upsert_adds_a_custom_map_to_the_right_list_and_matplotlib():
    cm.upsert("Ocean", {"kind": "continuous", "stops": [[0.0, "#012"], [1.0, "#9ef"]]})
    cm.upsert("Teams", {"kind": "qualitative", "colors": ["#e41", "#37b", "#4a4"]})

    lists = cm.resolved_lists()
    assert "Ocean" in lists["continuous"] and "Ocean" not in lists["qualitative"]
    assert "Teams" in lists["qualitative"]
    assert "Ocean" in matplotlib.colormaps and "Teams" in matplotlib.colormaps


def test_forget_removes_from_store_lists_and_registry():
    cm.upsert("Ocean", {"kind": "continuous", "stops": [[0.0, "#012"], [1.0, "#9ef"]]})
    cm.set_lists({"continuous": ["Ocean", "viridis"], "qualitative": ["tab10"]})

    cm.forget("Ocean")

    assert "Ocean" not in cm.custom_definitions()
    assert "Ocean" not in cm.resolved_lists()["continuous"]
    assert "Ocean" not in matplotlib.colormaps


def test_set_lists_controls_visibility_and_order():
    cm.set_lists({"continuous": ["coolwarm", "viridis"], "qualitative": ["Set2"]})
    lists = cm.resolved_lists()
    assert lists["continuous"] == ["coolwarm", "viridis"]  # order honoured, rest hidden
    assert lists["qualitative"] == ["Set2"]

    cm.reset_lists()
    assert cm.resolved_lists()["continuous"] == cm.BUILTIN["continuous"]


def test_resolved_lists_never_empty_even_if_selection_is():
    cm.set_lists({"continuous": [], "qualitative": []})
    lists = cm.resolved_lists()
    assert lists["continuous"] and lists["qualitative"]


def test_build_cmap_continuous_and_qualitative():
    from matplotlib.colors import LinearSegmentedColormap, ListedColormap

    cont = cm.build_cmap("c", {"kind": "continuous", "stops": [[0.0, "#000000"], [1.0, "#ffffff"]]})
    assert isinstance(cont, LinearSegmentedColormap)
    r, g, b, _a = cont(1.0)
    assert (round(r), round(g), round(b)) == (1, 1, 1)

    qual = cm.build_cmap("q", {"kind": "qualitative", "colors": ["#ff0000", "#00ff00"]})
    assert isinstance(qual, ListedColormap)
    assert len(qual.colors) == 2


def test_register_all_makes_custom_names_resolvable_by_get_cmap():
    cm.upsert("Ocean", {"kind": "continuous", "stops": [[0.0, "#001d3d"], [1.0, "#caf0f8"]]})
    cm._last_signature = None
    cm.register_all(force=True)

    import matplotlib.pyplot as plt

    assert plt.get_cmap("Ocean") is not None  # a grapher passing this name will work


def test_scheduler_run_registers_custom_maps():
    from ruyso_app.engine.graph import NodeSpec, PipelineGraph
    from ruyso_app.engine.scheduler import PipelineScheduler

    cm.upsert("Reef", {"kind": "qualitative", "colors": ["#0a9", "#f60"]})
    cm._last_signature = None

    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="n", node_type="example_data", params={}))
    PipelineScheduler().run(graph)  # any run triggers register_all

    assert "Reef" in matplotlib.colormaps
