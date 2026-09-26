

"""
Tests for ``engine.serialization`` -- the saved-file format.

A saved file is more than its graph: the Dashboard's layout rides along
in a separate top-level section, so sending someone a pipeline sends the
report with it. The line these defend is that the *graph* half is
untouched by any of that -- hand-written files, the bundled examples and
the headless CLI neither produce nor need a single extra key.
"""

from ruyso_app.engine.graph import NodeSpec, PipelineGraph
from ruyso_app.engine.serialization import (
    DASHBOARD_KEY,
    document_from_dict,
    document_to_dict,
    graph_to_dict,
    load_document,
    save_document,
    save_graph,
)


def _one_node_graph():
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="a", node_type="csv_loader", params={"filepath": "x.csv"}))
    return graph


def test_a_document_is_the_graph_plus_its_extra_sections():
    data = document_to_dict(_one_node_graph(), {DASHBOARD_KEY: {"version": 1, "items": []}})

    assert sorted(data) == ["connections", DASHBOARD_KEY, "nodes"]
    assert data["nodes"][0]["id"] == "a"


def test_an_empty_extra_section_is_not_written():
    """A file only grows the key once it has a report to carry."""
    data = document_to_dict(_one_node_graph(), {DASHBOARD_KEY: {}})
    assert DASHBOARD_KEY not in data


def test_no_extra_may_overwrite_the_graph():
    """Losing a report is a nuisance; losing the pipeline is losing work."""
    data = document_to_dict(_one_node_graph(), {"nodes": "sabotage"})
    assert isinstance(data["nodes"], list)


def test_a_document_round_trips(tmp_path):
    path = tmp_path / "doc.json"
    save_document(_one_node_graph(), path, {DASHBOARD_KEY: {"version": 1, "items": [1]}})

    graph, extras = load_document(path)

    assert list(graph.nodes) == ["a"]
    assert extras[DASHBOARD_KEY] == {"version": 1, "items": [1]}


def test_a_section_this_version_does_not_know_survives_a_round_trip():
    """An older build must not silently strip a newer one's work."""
    graph, extras = document_from_dict(
        {"nodes": [], "connections": [], "from_the_future": {"x": 1}}
    )
    assert extras["from_the_future"] == {"x": 1}
    assert "from_the_future" in document_to_dict(graph, extras)


def test_a_plain_graph_file_loads_as_a_document_with_no_extras(tmp_path):
    """Every file written before documents existed is one of these."""
    path = tmp_path / "old.json"
    save_graph(_one_node_graph(), path)

    graph, extras = load_document(path)

    assert list(graph.nodes) == ["a"]
    assert extras == {}


def test_graph_to_dict_is_still_only_the_graph():
    """The headless format is unchanged: hand-written files and the
    examples neither produce nor need any of this."""
    assert sorted(graph_to_dict(_one_node_graph())) == ["connections", "nodes"]
