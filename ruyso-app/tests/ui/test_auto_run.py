"""
Tests for ``ui.auto_run.AutoRunController`` scheduling / gating.

The heavy lifting (``PipelineScheduler.run_available``) is covered in
tests/engine/test_scheduler.py; here we only check the debounce timer
and the enable/disable gate.
"""

from ruyso_app.engine.graph import NodeSpec, PipelineGraph
from ruyso_app.ui.auto_run import AutoRunController


def _loader_pipeline(path: str = "x.csv") -> PipelineGraph:
    g = PipelineGraph()
    g.add_node(NodeSpec(id="load", node_type="csv_loader", params={"filepath": path}))
    return g


def test_schedule_arms_the_timer(qapp):
    controller = AutoRunController(_loader_pipeline)
    assert not controller._timer.isActive()

    controller.schedule()
    assert controller._timer.isActive()


def test_schedule_is_ignored_while_disabled(qapp):
    controller = AutoRunController(_loader_pipeline)
    controller.set_enabled(False)

    controller.schedule()
    assert not controller._timer.isActive()

    controller.set_enabled(True)
    controller.schedule()
    assert controller._timer.isActive()


def test_fire_runs_and_emits_finished(qapp, tmp_path):
    import numpy as np
    import pandas as pd

    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": np.arange(5)}).to_csv(csv, index=False)

    controller = AutoRunController(lambda: _loader_pipeline(str(csv)))
    results: list[tuple[dict, dict]] = []
    controller.finished.connect(lambda o, e: results.append((o, e)))

    controller._fire()
    controller._worker.wait(5000)
    qapp.processEvents()

    assert results
    outputs, errors = results[0]
    assert "df" in outputs["load"]
    assert errors == {}
