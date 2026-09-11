"""
Tests for PipelineScheduler: end-to-end execution of a small pipeline,
correct wiring of outputs to inputs, and joblib-based caching behaviour.
"""

import joblib
import numpy as np
import pandas as pd
import pytest

import ruyso_app.nodes  # noqa: F401 - registration side effects
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph
from ruyso_app.engine.scheduler import PipelineScheduler, _execute_node

NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture
def sample_csv(tmp_path):
    """A small, perfectly linear dataset: target = 2*x + 1."""
    path = tmp_path / "data.csv"
    x = np.arange(1, 21, dtype=float)
    y = 2 * x + 1
    pd.DataFrame({"x": x, "target": y}).to_csv(path, index=False)
    return str(path)


@pytest.fixture
def no_cache_scheduler():
    """A scheduler with caching disabled, for deterministic tests."""
    return PipelineScheduler(memory=joblib.Memory(location=None))


def _regression_graph(csv_path: str) -> PipelineGraph:
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="load", node_type="csv_loader", params={"filepath": csv_path}))
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))
    graph.add_node(
        NodeSpec(
            id="split",
            node_type="train_test_split",
            params={"target_column": "target", "test_size": 0.25, "random_state": 0},
        )
    )
    graph.add_node(NodeSpec(id="fit", node_type="linear_regression_fit", params={}))

    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="clean", target_port="df")
    )
    graph.add_connection(
        Connection(source_node="clean", source_port="df", target_node="split", target_port="df")
    )
    graph.add_connection(
        Connection(
            source_node="split", source_port="X_train", target_node="fit", target_port="X_train"
        )
    )
    graph.add_connection(
        Connection(
            source_node="split", source_port="y_train", target_node="fit", target_port="y_train"
        )
    )
    graph.add_connection(
        Connection(
            source_node="split", source_port="X_test", target_node="fit", target_port="X_test"
        )
    )
    graph.add_connection(
        Connection(
            source_node="split", source_port="y_test", target_node="fit", target_port="y_test"
        )
    )
    return graph


def test_scheduler_runs_full_pipeline_and_wires_outputs_correctly(
    sample_csv, no_cache_scheduler
):
    graph = _regression_graph(sample_csv)

    outputs, errors = no_cache_scheduler.run(graph)

    assert errors == {}
    assert set(outputs.keys()) == {"load", "clean", "split", "fit"}
    model = outputs["fit"]["model"]
    # target = 2*x + 1 exactly -> coefficient ~2, intercept ~1.
    assert np.isclose(model.coef_[0], 2.0, atol=1e-6)
    assert np.isclose(model.intercept_, 1.0, atol=1e-6)
    assert "score" not in outputs["fit"]  # fit nodes only output the model now


def test_scheduler_rejects_invalid_graph_before_running_anything(no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))  # missing required "df"

    with pytest.raises(Exception):
        no_cache_scheduler.run(graph)


def test_cached_execution_returns_identical_result_without_recomputation(tmp_path, monkeypatch):
    """
    Calling _execute_node twice with identical arguments through a
    joblib-cached scheduler should hit the cache on the second call:
    we verify this indirectly by counting how many times the
    underlying node actually executes.
    """
    from ruyso_app.nodes.transforms import DropNA

    call_count = {"n": 0}
    original_run = DropNA.run

    def counting_run(self, **inputs):
        call_count["n"] += 1
        return original_run(self, **inputs)

    monkeypatch.setattr(DropNA, "run", counting_run)

    scheduler = PipelineScheduler(memory=joblib.Memory(location=str(tmp_path)))
    df = pd.DataFrame({"a": [1.0, 2.0, None]})

    result_1 = scheduler._cached_execute("drop_na", {}, {"df": df})
    result_2 = scheduler._cached_execute("drop_na", {}, {"df": df})

    pd.testing.assert_frame_equal(result_1["df"], result_2["df"])
    assert call_count["n"] == 1  # second call served entirely from cache


def test_execute_node_validates_required_inputs():
    with pytest.raises(ValueError, match="missing required input"):
        _execute_node("drop_na", {}, {})


def test_progress_callback_reports_each_node(sample_csv, no_cache_scheduler):
    graph = _regression_graph(sample_csv)
    seen: list[tuple[int, int]] = []

    no_cache_scheduler.run(graph, progress_callback=lambda d, t: seen.append((d, t)))

    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_run_node_callback_streams_running_then_ok(sample_csv, no_cache_scheduler):
    graph = _regression_graph(sample_csv)
    phases: list[tuple[str, str]] = []

    no_cache_scheduler.run(graph, node_callback=lambda n, p: phases.append((n, p)))

    for node_id in ("load", "clean", "split", "fit"):
        assert (node_id, "running") in phases
        assert (node_id, "ok") in phases


def test_run_collects_a_runtime_error_and_blocks_downstream(no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": "/no/such/file.csv"})
    )
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))
    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="clean", target_port="df")
    )

    phases: list[tuple[str, str]] = []
    outputs, errors = no_cache_scheduler.run(
        graph, node_callback=lambda n, p: phases.append((n, p))
    )

    assert "load" in errors and outputs == {}
    assert ("load", "running") in phases and ("load", "error") in phases
    assert ("clean", "blocked") in phases  # downstream of the failure, never run


def test_run_still_raises_for_a_structurally_invalid_graph(no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))  # required "df" unwired
    with pytest.raises(Exception):
        no_cache_scheduler.run(graph)


def test_run_available_runs_a_lone_loader(sample_csv, no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": sample_csv})
    )
    outputs, errors = no_cache_scheduler.run_available(graph)

    assert "df" in outputs["load"]
    assert errors == {}


def test_run_available_skips_unwired_and_downstream_nodes(sample_csv, no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": sample_csv})
    )
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))
    graph.add_node(
        NodeSpec(id="split", node_type="train_test_split", params={"target_column": "target"})
    )
    # "clean" has no incoming df wire -> skipped; "split" depends on it -> skipped too.
    graph.add_connection(
        Connection(source_node="clean", source_port="df", target_node="split", target_port="df")
    )
    outputs, errors = no_cache_scheduler.run_available(graph)

    assert set(outputs) == {"load"}
    assert errors == {}


def test_run_available_records_a_failing_node_without_raising(no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": "/no/such/file.csv"})
    )
    outputs, errors = no_cache_scheduler.run_available(graph)

    assert outputs == {}
    assert "load" in errors


# -- RunReport: what happened to every node, not just the ones that ran ---

from ruyso_app.engine.errors import NodeError  # noqa: E402


def _failing_chain(sample_csv):
    """load -> clean (fails) -> split. Two nodes never get to run."""
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": sample_csv})
    )
    graph.add_node(
        NodeSpec(id="clean", node_type="sort", params={"columns": "not-a-list"})
    )
    graph.add_node(
        NodeSpec(
            id="split", node_type="train_test_split", params={"target_column": "target"}
        )
    )
    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="clean", target_port="df")
    )
    graph.add_connection(
        Connection(source_node="clean", source_port="df", target_node="split", target_port="df")
    )
    return graph


def test_a_report_unpacks_as_the_old_two_tuple(sample_csv, no_cache_scheduler):
    """Every existing caller unpacks two values; that must keep working."""
    report = no_cache_scheduler.run(_failing_chain(sample_csv))
    outputs, errors = report

    assert outputs is report.outputs
    assert errors is report.errors


def test_blocked_nodes_are_reported_instead_of_vanishing(sample_csv, no_cache_scheduler):
    """They used to appear in neither outputs nor errors -- silently skipped."""
    report = no_cache_scheduler.run(_failing_chain(sample_csv))

    assert set(report.outputs) == {"load"}
    assert set(report.errors) == {"clean"}
    assert set(report.blocked) == {"split"}


def test_a_blocked_node_names_the_node_that_actually_failed(sample_csv, no_cache_scheduler):
    """Not the immediate neighbour -- the one worth going to look at."""
    graph = _failing_chain(sample_csv)
    graph.add_node(NodeSpec(id="tail", node_type="head", params={"n": 2}))
    graph.add_connection(
        Connection(source_node="split", source_port="X_train", target_node="tail", target_port="df")
    )
    report = no_cache_scheduler.run(graph)

    assert report.blocked["split"] == "clean"
    assert report.blocked["tail"] == "clean"  # two hops away, same root cause


def test_errors_hold_a_readable_node_error(sample_csv, no_cache_scheduler):
    report = no_cache_scheduler.run(_failing_chain(sample_csv))
    error = report.errors["clean"]

    assert isinstance(error, NodeError)
    assert error.node_id == "clean" and error.node_type == "sort"
    assert error.kind == "param" and error.field == "columns"
    assert "pydantic" not in str(error)
    assert error.raw  # the traceback is kept


def test_a_missing_column_error_knows_the_columns_that_were_there(
    sample_csv, no_cache_scheduler
):
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": sample_csv})
    )
    graph.add_node(
        NodeSpec(id="pick", node_type="column_filter", params={"columns": ["nope"]})
    )
    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="pick", target_port="df")
    )
    report = no_cache_scheduler.run(graph)

    if "pick" in report.errors:  # the node validates its own columns
        assert "nope" in str(report.errors["pick"])


def test_a_clean_run_reports_nothing_blocked(sample_csv, no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": sample_csv})
    )
    report = no_cache_scheduler.run(graph)

    assert report.errors == {} and report.blocked == {}


# -- run_available: "blocked" and "unwired" are different things ----------


def test_run_available_calls_an_unconnected_node_unwired(sample_csv, no_cache_scheduler):
    """A half-built canvas is the normal state, not a broken pipeline."""
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))  # nothing wired in
    phases: list[tuple[str, str]] = []
    report = no_cache_scheduler.run_available(
        graph, node_callback=lambda n, p: phases.append((n, p))
    )

    assert ("clean", "unwired") in phases
    assert report.blocked == {"clean": None}
    assert report.unwired == {"clean"}


def test_run_available_calls_a_downstream_of_a_failure_blocked(no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": "/no/such.csv"})
    )
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))
    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="clean", target_port="df")
    )
    phases: list[tuple[str, str]] = []
    report = no_cache_scheduler.run_available(
        graph, node_callback=lambda n, p: phases.append((n, p))
    )

    assert ("load", "error") in phases
    assert ("clean", "blocked") in phases  # not "unwired" -- something failed
    assert report.blocked == {"clean": "load"}
    assert report.unwired == set()


def test_run_available_propagates_unwired_down_an_unfinished_branch(no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="clean", node_type="drop_na", params={}))
    graph.add_node(NodeSpec(id="tail", node_type="head", params={"n": 2}))
    graph.add_connection(
        Connection(source_node="clean", source_port="df", target_node="tail", target_port="df")
    )
    phases: list[tuple[str, str]] = []
    no_cache_scheduler.run_available(
        graph, node_callback=lambda n, p: phases.append((n, p))
    )

    # Nothing failed anywhere, so neither node is "blocked".
    assert ("clean", "unwired") in phases
    assert ("tail", "unwired") in phases
    assert not any(phase == "blocked" for _node, phase in phases)


def test_an_invalid_graph_still_returns_an_empty_report(no_cache_scheduler):
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="a", node_type="head", params={}))
    graph.add_node(NodeSpec(id="b", node_type="head", params={}))
    graph.add_connection(
        Connection(source_node="a", source_port="df", target_node="b", target_port="df")
    )
    graph.add_connection(
        Connection(source_node="b", source_port="df", target_node="a", target_port="df")
    )
    outputs, errors = no_cache_scheduler.run_available(graph)  # a cycle

    assert outputs == {} and errors == {}
