"""
Tests for the auto-run skip cache (``engine.run_cache`` +
``PipelineScheduler.run_available(result_cache=...)``).

Two things are being balanced, and both are load-bearing:

* **Speed** -- a re-run where nothing changed must execute nothing, and
  an edit must re-execute only what it actually affects. Graphers opt
  out of the joblib cache, so without this every background run
  re-rendered every figure on the canvas.
* **Freshness** -- a cached result must never be served when it could be
  wrong: a file edited on disk under an unchanged path, a failing
  loader, an export whose whole point is its side effect.

The freshness half is the one worth being paranoid about; a stale
result looks exactly like a correct one.
"""

import joblib
import pandas as pd
import pytest

import ruyso_app.nodes  # noqa: F401 - registers the node classes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph
from ruyso_app.engine.run_cache import ResultCache, content_token, is_skippable
from ruyso_app.engine.scheduler import PipelineScheduler

NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture
def scheduler():
    """
    A scheduler with the *joblib disk* cache switched off.

    Distinct from the ResultCache under test here: joblib memoises
    individual node executions on disk, while the skip cache decides
    whether a node is executed at all. Disabling joblib keeps these
    tests measuring only the second one.
    """
    return PipelineScheduler(memory=joblib.Memory(location=None))


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]}).to_csv(path, index=False)
    return str(path)


def _loader_chain(csv_path, n_plots=0):
    """load -> head, plus ``n_plots`` graphers hanging off the head."""
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": csv_path})
    )
    graph.add_node(NodeSpec(id="head", node_type="head", params={"n": 2}))
    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="head", target_port="df")
    )
    for i in range(n_plots):
        graph.add_node(
            NodeSpec(id=f"p{i}", node_type="matplotlib_plot", params={"x": "a", "y": "b"})
        )
        graph.add_connection(
            Connection(source_node="head", source_port="df", target_node=f"p{i}", target_port="df")
        )
    return graph


def _executed(scheduler, graph, cache):
    """``(node ids that actually ran, report)``."""
    ran: list[str] = []
    report = scheduler.run_available(
        graph,
        node_callback=lambda node_id, phase: ran.append(node_id) if phase == "running" else None,
        result_cache=cache,
    )
    return ran, report


# -- the ResultCache itself ----------------------------------------------


def test_a_hit_needs_both_the_node_and_the_signature():
    cache = ResultCache()
    cache.put("a", "sig1", {"df": 1})

    assert cache.get("a", "sig1") == {"df": 1}
    assert cache.get("a", "sig2") is None  # stale: something changed
    assert cache.get("b", "sig1") is None  # different node


def test_putting_replaces_rather_than_accumulating():
    cache = ResultCache()
    cache.put("a", "sig1", {"df": 1})
    cache.put("a", "sig2", {"df": 2})

    assert len(cache) == 1  # one entry per node -- never a history
    assert cache.get("a", "sig1") is None
    assert cache.get("a", "sig2") == {"df": 2}


def test_pruning_drops_nodes_that_left_the_pipeline():
    cache = ResultCache()
    cache.put("a", "s", {})
    cache.put("gone", "s", {})
    cache.prune(["a"])

    assert "a" in cache and "gone" not in cache


def test_a_snapshot_is_independent_of_the_original():
    cache = ResultCache()
    cache.put("a", "s", {"df": 1})
    snapshot = cache.snapshot()
    snapshot.put("b", "s", {"df": 2})

    assert "b" in snapshot and "b" not in cache  # the worker's additions stay put
    assert snapshot.get("a", "s") is cache.get("a", "s")  # results are shared


def test_loaders_and_exports_are_never_skippable():
    """Their value is reading the world, or changing it."""
    assert not is_skippable(NodeRegistry.get("csv_loader"))
    assert not is_skippable(NodeRegistry.get("export_figure"))
    assert is_skippable(NodeRegistry.get("head"))
    assert is_skippable(NodeRegistry.get("matplotlib_plot"))


def test_a_content_token_changes_with_the_content():
    frame = pd.DataFrame({"a": [1, 2]})
    same = pd.DataFrame({"a": [1, 2]})
    other = pd.DataFrame({"a": [9, 9]})

    assert content_token("sig", {"df": frame}) == content_token("sig", {"df": same})
    assert content_token("sig", {"df": frame}) != content_token("sig", {"df": other})


def test_an_unhashable_output_is_assumed_to_have_changed():
    unhashable = {"x": (lambda: None)}
    assert content_token("sig", unhashable) != content_token("sig", unhashable)


# -- speed: what gets skipped --------------------------------------------


def test_a_second_run_with_no_changes_executes_only_the_loader(
    csv_path, scheduler
):
    graph = _loader_chain(csv_path, n_plots=3)
    cache = ResultCache()

    first, _ = _executed(scheduler, graph, cache)
    second, report = _executed(scheduler, graph, cache)

    assert len(first) == 5  # load + head + 3 plots
    assert second == ["load"]  # loaders always re-read
    assert report.reused == {"head", "p0", "p1", "p2"}


def test_editing_one_node_re_executes_it_and_its_descendants_only(
    csv_path, scheduler
):
    graph = _loader_chain(csv_path, n_plots=3)
    cache = ResultCache()
    _executed(scheduler, graph, cache)

    graph.nodes["p1"].params["kind"] = "line"
    graph._nodes["p1"].params["kind"] = "line"  # the graph's own copy
    ran, report = _executed(scheduler, graph, cache)

    assert set(ran) == {"load", "p1"}
    assert {"head", "p0", "p2"} <= report.reused


def test_editing_an_upstream_node_re_executes_everything_below_it(
    csv_path, scheduler
):
    graph = _loader_chain(csv_path, n_plots=3)
    cache = ResultCache()
    _executed(scheduler, graph, cache)

    graph._nodes["head"].params["n"] = 1
    ran, report = _executed(scheduler, graph, cache)

    assert set(ran) == {"load", "head", "p0", "p1", "p2"}
    assert report.reused == set()


def test_a_reused_node_hands_back_the_very_same_object(csv_path, scheduler):
    """What lets the UI skip re-rasterising a figure it already drew."""
    graph = _loader_chain(csv_path, n_plots=1)
    cache = ResultCache()

    _, first = _executed(scheduler, graph, cache)
    _, second = _executed(scheduler, graph, cache)

    assert second.outputs["p0"]["figure"] is first.outputs["p0"]["figure"]


def test_a_deleted_node_is_dropped_from_the_cache(csv_path, scheduler):
    graph = _loader_chain(csv_path, n_plots=2)
    cache = ResultCache()
    _executed(scheduler, graph, cache)
    assert "p1" in cache

    smaller = _loader_chain(csv_path, n_plots=1)
    _executed(scheduler, smaller, cache)

    assert "p1" not in cache  # nothing keeps its figure alive


# -- freshness: what must never be skipped -------------------------------


def test_a_file_changed_on_disk_invalidates_everything_downstream(
    csv_path, scheduler
):
    """
    The trap this guards. A loader always re-runs, but its *signature* --
    node type, params, wiring -- does not move when the file behind an
    unchanged path is edited. Without folding the loaded content into
    what dependents key on, they keep serving results computed from the
    old file while the loader happily reads the new one.
    """
    graph = _loader_chain(csv_path)
    cache = ResultCache()

    _, first = _executed(scheduler, graph, cache)
    assert first.outputs["head"]["df"]["a"].tolist() == [1, 2]

    pd.DataFrame({"a": [9, 9, 9], "b": [0, 0, 0]}).to_csv(csv_path, index=False)
    ran, second = _executed(scheduler, graph, cache)

    assert second.outputs["head"]["df"]["a"].tolist() == [9, 9]
    assert "head" in ran and second.reused == set()


def test_a_file_changed_on_disk_is_re_read_through_the_joblib_cache(
    csv_path, tmp_path
):
    """
    The same trap one level down, and the reason every other test here
    disables joblib: a loader has no *inputs*, so joblib keyed it on its
    path alone and served the first read of that path for ever. An
    edited CSV was then invisible to the whole app -- Run included --
    until the disk cache was cleared by hand.
    """
    disk = PipelineScheduler(
        memory=joblib.Memory(location=str(tmp_path / "joblib"), verbose=0)
    )
    graph = _loader_chain(csv_path)
    cache = ResultCache()

    _executed(disk, graph, cache)
    pd.DataFrame({"a": [9, 9, 9], "b": [0, 0, 0]}).to_csv(csv_path, index=False)

    assert disk.run(graph).outputs["load"]["df"]["a"].tolist() == [9, 9, 9]
    _, auto = _executed(disk, graph, cache)
    assert auto.outputs["head"]["df"]["a"].tolist() == [9, 9]


def test_an_unchanged_file_still_lets_everything_downstream_be_skipped(
    csv_path, scheduler
):
    """The other half: re-reading must not invalidate on its own."""
    graph = _loader_chain(csv_path)
    cache = ResultCache()
    _executed(scheduler, graph, cache)
    ran, report = _executed(scheduler, graph, cache)

    assert ran == ["load"]
    assert report.reused == {"head"}


def test_a_failing_loader_never_serves_a_stale_downstream_result(
    csv_path, tmp_path, scheduler
):
    graph = _loader_chain(csv_path)
    cache = ResultCache()
    _executed(scheduler, graph, cache)

    (tmp_path / "d.csv").unlink()
    _, report = _executed(scheduler, graph, cache)

    assert "load" in report.errors
    assert "head" not in report.outputs  # not served from cache
    assert report.blocked["head"] == "load"


def test_an_export_re_runs_even_when_nothing_changed(tmp_path, scheduler):
    """Its value is the side effect, so a skipped export is a missing file."""
    out = tmp_path / "out.csv"
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="data", node_type="example_data", params={"dataset": "seaborn/tips"})
    )
    graph.add_node(
        NodeSpec(
            id="save",
            node_type="export_table",
            params={"filepath": str(out), "format": "csv"},
        )
    )
    graph.add_connection(
        Connection(source_node="data", source_port="df", target_node="save", target_port="table")
    )
    cache = ResultCache()
    _executed(scheduler, graph, cache)
    assert out.exists()

    out.unlink()  # someone deletes the output
    ran, _ = _executed(scheduler, graph, cache)

    assert "save" in ran and out.exists()  # written again


# -- the Run button ------------------------------------------------------


def test_a_full_run_can_reuse_what_nothing_changed_for(csv_path, scheduler):
    """What the Run button passes: the same skip rules as a background
    run, so pressing Run on a pipeline that is already current is not a
    minute of recomputation."""
    graph = _loader_chain(csv_path)
    cache = ResultCache()

    first = scheduler.run(graph, result_cache=cache)
    assert first.reused == set()

    second = scheduler.run(graph, result_cache=cache)
    assert second.reused == {"head"}  # the loader always re-runs
    assert second.outputs["head"]["df"].equals(first.outputs["head"]["df"])

    graph.get_node("head").params["n"] = 1  # an edit invalidates that node
    third = scheduler.run(graph, result_cache=cache)
    assert third.reused == set()
    assert len(third.outputs["head"]["df"]) == 1


def test_a_full_run_without_a_cache_still_runs_everything(csv_path, scheduler):
    """Force Full Run passes no cache, and that has to keep meaning
    every single step."""
    graph = _loader_chain(csv_path)
    cache = ResultCache()
    scheduler.run(graph, result_cache=cache)

    report = scheduler.run(graph)

    assert report.reused == set()
    assert set(report.outputs) == {"load", "head"}


def test_without_a_cache_every_node_runs_every_time(csv_path, scheduler):
    """The manual Run passes no cache, so Run always means run."""
    graph = _loader_chain(csv_path, n_plots=2)
    ran_first: list[str] = []
    ran_again: list[str] = []
    for collected in (ran_first, ran_again):
        scheduler.run_available(
            graph,
            node_callback=lambda n, p, c=collected: c.append(n) if p == "running" else None,
        )

    assert ran_first == ran_again
    assert len(ran_again) == 4
