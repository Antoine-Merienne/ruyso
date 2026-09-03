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

    outputs = no_cache_scheduler.run(graph)

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
