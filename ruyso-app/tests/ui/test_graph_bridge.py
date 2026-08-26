"""
Tests for graph_bridge: a pipeline built on the canvas must convert to
a valid engine PipelineGraph, and a PipelineGraph (including one
loaded from hand-written JSON) must render correctly back onto a fresh
canvas -- this is what keeps UI-built and CLI-built pipelines fully
interchangeable.
"""

import pytest

from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.graph import GraphValidationError
from ruyso_app.engine.serialization import graph_from_json, graph_to_json, load_graph
from ruyso_app.ui.canvas import PipelineCanvas
from ruyso_app.ui.graph_bridge import (
    UnsupportedCanvasNodeError,
    canvas_to_pipeline,
    pipeline_to_canvas,
)
from ruyso_app.ui.node_factory import qt_type_for


def test_canvas_to_pipeline_reflects_nodes_params_and_connections(qapp):
    canvas = PipelineCanvas()
    graph = canvas.graph

    loader = graph.create_node(qt_type_for("csv_loader"), name="load")
    loader.set_property("filepath", "examples/sample_data.csv")

    cleaner = graph.create_node(qt_type_for("drop_na"), name="clean")
    loader.outputs()["df"].connect_to(cleaner.inputs()["df"])

    pipeline = canvas_to_pipeline(graph)
    pipeline.validate()

    assert pipeline.nodes["load"].node_type == "csv_loader"
    assert pipeline.nodes["load"].params["filepath"] == "examples/sample_data.csv"
    assert pipeline.nodes["clean"].node_type == "drop_na"

    conns = pipeline.connections
    assert len(conns) == 1
    assert conns[0].source_node == "load"
    assert conns[0].source_port == "df"
    assert conns[0].target_node == "clean"
    assert conns[0].target_port == "df"


def test_canvas_to_pipeline_rejects_invalid_incomplete_graph(qapp):
    canvas = PipelineCanvas()
    # "clean" (drop_na) requires a "df" input that is left unconnected.
    canvas.graph.create_node(qt_type_for("drop_na"), name="clean")

    pipeline = canvas_to_pipeline(canvas.graph)
    with pytest.raises(GraphValidationError):
        pipeline.validate()


def test_pipeline_to_canvas_round_trips_through_the_example_json(qapp):
    pipeline = load_graph("examples/simple_regression_pipeline.json")
    pipeline.validate()

    canvas = PipelineCanvas()
    canvas_nodes = pipeline_to_canvas(pipeline, canvas.graph)

    assert set(canvas_nodes.keys()) == set(pipeline.nodes.keys())

    rebuilt = canvas_to_pipeline(canvas.graph)
    rebuilt.validate()

    assert rebuilt.nodes.keys() == pipeline.nodes.keys()
    for node_id, spec in pipeline.nodes.items():
        assert rebuilt.nodes[node_id].node_type == spec.node_type
        # Compare through the node's own params_schema rather than the
        # raw params dicts: the canvas always materializes every
        # schema field (with its default), while hand-written JSON may
        # omit fields that are left at their default (e.g. "sep" for
        # csv_loader) -- both are semantically equivalent pipelines.
        node_cls = NodeRegistry.get(spec.node_type)
        assert node_cls.params_schema(**rebuilt.nodes[node_id].params) == node_cls.params_schema(
            **spec.params
        )
    assert len(rebuilt.connections) == len(pipeline.connections)


def test_full_round_trip_canvas_json_canvas_preserves_pipeline(qapp):
    """
    Build on the canvas -> export to JSON (engine.serialization) ->
    reload into a fresh canvas -> convert back: the pipeline must be
    identical, proving canvas-built pipelines are fully interchangeable
    with the hand-written JSON format used by the headless CLI.
    """
    original_canvas = PipelineCanvas()
    loader = original_canvas.graph.create_node(qt_type_for("csv_loader"), name="load")
    loader.set_property("filepath", "data.csv")
    scaler = original_canvas.graph.create_node(qt_type_for("standard_scaler"), name="scale")
    loader.outputs()["df"].connect_to(scaler.inputs()["df"])

    original_pipeline = canvas_to_pipeline(original_canvas.graph)
    json_text = graph_to_json(original_pipeline)

    reloaded_pipeline = graph_from_json(json_text)
    new_canvas = PipelineCanvas()
    pipeline_to_canvas(reloaded_pipeline, new_canvas.graph)
    final_pipeline = canvas_to_pipeline(new_canvas.graph)

    assert final_pipeline.nodes.keys() == original_pipeline.nodes.keys()
    for node_id in original_pipeline.nodes:
        node_type = original_pipeline.nodes[node_id].node_type
        node_cls = NodeRegistry.get(node_type)
        expected = node_cls.params_schema(**original_pipeline.nodes[node_id].params)
        actual = node_cls.params_schema(**final_pipeline.nodes[node_id].params)
        assert actual == expected
    assert len(final_pipeline.connections) == len(original_pipeline.connections)


def test_canvas_to_pipeline_rejects_unsupported_builtin_node(qapp):
    canvas = PipelineCanvas()
    # NodeGraphQt auto-registers a "Backdrop" node on every NodeGraph
    # for purely visual grouping; it has no core Node counterpart.
    backdrop_type = next(t for t in canvas.graph.registered_nodes() if "Backdrop" in t)
    canvas.graph.create_node(backdrop_type)

    with pytest.raises(UnsupportedCanvasNodeError):
        canvas_to_pipeline(canvas.graph)
