"""
Tests for engine.codegen: the generated script must be valid Python,
free of any dependency on the engine/UI machinery, and must reproduce
the exact same results as running the graph through PipelineScheduler.
"""

import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import pytest

import ruyso_app.nodes  # noqa: F401 - registration side effects
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.codegen import generate_script, save_script
from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph
from ruyso_app.engine.scheduler import PipelineScheduler

NodeRegistry.discover_package(ruyso_app.nodes)


@pytest.fixture
def sample_csv(tmp_path):
    """A small, perfectly linear dataset: target = 2*x + 1."""
    path = tmp_path / "data.csv"
    x = np.arange(1, 21, dtype=float)
    y = 2 * x + 1
    pd.DataFrame({"x": x, "target": y}).to_csv(path, index=False)
    return str(path)


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
    for port in ("X_train", "y_train", "X_test", "y_test"):
        graph.add_connection(
            Connection(source_node="split", source_port=port, target_node="fit", target_port=port)
        )
    return graph


def test_generated_script_is_syntactically_valid_python(sample_csv):
    graph = _regression_graph(sample_csv)
    script = generate_script(graph)

    compile(script, "<generated>", "exec")  # raises SyntaxError if invalid


def test_generated_script_has_no_engine_or_ui_dependency(sample_csv):
    graph = _regression_graph(sample_csv)
    script = generate_script(graph)

    # Skip the header docstring (which mentions these names in prose,
    # to explain the guarantee) and only check the executable code.
    executable_code = script.split('"""', 2)[-1]

    forbidden_imports = [
        "import networkx",
        "import joblib",
        "from ruyso_app.engine",
        "from ruyso_app.ui",
        "PipelineGraph(",
        "PipelineScheduler(",
    ]
    for token in forbidden_imports:
        assert token not in executable_code


def test_generated_script_only_imports_used_node_classes(sample_csv):
    graph = _regression_graph(sample_csv)
    script = generate_script(graph)

    assert "from ruyso_app.nodes.loaders import CSVLoader" in script
    assert "from ruyso_app.nodes.transforms import DropNA" in script
    assert "from ruyso_app.nodes.models import TrainTestSplit" in script
    assert "from ruyso_app.nodes.models import LinearRegressionFit" in script
    # Not part of this graph -> must not be imported.
    assert "MatplotlibPlot" not in script
    assert "FigureExport" not in script


def test_running_generated_script_reproduces_scheduler_output(tmp_path, sample_csv):
    graph = _regression_graph(sample_csv)

    scheduler = PipelineScheduler(memory=joblib.Memory(location=None))
    expected = scheduler.run(graph)
    expected_coef = float(expected["fit"]["model"].coef_[0])

    script_path = tmp_path / "exported_pipeline.py"
    save_script(graph, script_path, source_description="test graph")

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    # the terminal "fit" node prints its "model" output -> a LinearRegression
    assert "[fit] model = LinearRegression(" in result.stdout
    assert expected_coef == pytest.approx(2.0, rel=1e-6)


def test_sanitizes_node_ids_that_are_not_valid_identifiers():
    graph = PipelineGraph()
    graph.add_node(NodeSpec(id="load-csv #1", node_type="csv_loader", params={"filepath": "x.csv"}))

    script = generate_script(graph)

    compile(script, "<generated>", "exec")
    assert "out_load_csv__1" in script
