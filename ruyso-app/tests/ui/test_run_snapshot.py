"""
Tests for ``ui.run_snapshot``: detecting steps changed since a run.
"""

from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph
from ruyso_app.ui.run_snapshot import modified_since_run, pipeline_signatures


def _pipeline(load_params=None, clean_params=None) -> PipelineGraph:
    g = PipelineGraph()
    g.add_node(NodeSpec(id="load", node_type="csv_loader", params=load_params or {"filepath": "a.csv"}))
    g.add_node(NodeSpec(id="clean", node_type="drop_na", params=clean_params or {}))
    g.add_node(NodeSpec(id="plot", node_type="matplotlib_plot", params={"x": "a", "y": "b"}))
    g.add_connection(Connection(source_node="load", source_port="df", target_node="clean", target_port="df"))
    g.add_connection(Connection(source_node="clean", source_port="df", target_node="plot", target_port="df"))
    return g


def test_nothing_modified_when_signatures_match():
    pipeline = _pipeline()
    snapshot = pipeline_signatures(pipeline)
    assert modified_since_run(pipeline, snapshot) == set()


def test_empty_snapshot_means_nothing_flagged():
    assert modified_since_run(_pipeline(), {}) == set()


def test_param_change_flags_that_node_and_everything_downstream():
    snapshot = pipeline_signatures(_pipeline())
    changed = _pipeline(load_params={"filepath": "OTHER.csv"})
    assert modified_since_run(changed, snapshot) == {"load", "clean", "plot"}


def test_downstream_only_change_does_not_flag_upstream():
    snapshot = pipeline_signatures(_pipeline())
    changed = _pipeline(clean_params={"how": "all"})
    assert modified_since_run(changed, snapshot) == {"clean", "plot"}


def test_new_node_absent_from_snapshot_is_flagged():
    snapshot = pipeline_signatures(_pipeline())
    grown = _pipeline()
    grown.add_node(NodeSpec(id="scale", node_type="scaler", params={}))
    grown.add_connection(
        Connection(source_node="clean", source_port="df", target_node="scale", target_port="df")
    )
    assert "scale" in modified_since_run(grown, snapshot)
