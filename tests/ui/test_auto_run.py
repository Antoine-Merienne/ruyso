"""
Tests for ``ui.auto_run.AutoRunController`` scheduling / gating.

The heavy lifting (``PipelineScheduler.run_available``) is covered in
tests/engine/test_scheduler.py; here we only check the debounce timer
and the enable/disable gate.
"""

from PySide6.QtWidgets import QApplication

import ruyso_app.nodes  # noqa: F401 - registers the node classes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine.graph import Connection, NodeSpec, PipelineGraph
from ruyso_app.ui.auto_run import AutoRunController

NodeRegistry.discover_package(ruyso_app.nodes)


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


def test_user_toggle_gates_scheduling_independently_of_the_manual_gate(qapp):
    controller = AutoRunController(_loader_pipeline)

    controller.set_user_enabled(False)
    controller.schedule()
    assert not controller._timer.isActive()  # user turned auto off

    controller.set_user_enabled(True)
    controller.set_enabled(False)  # transient manual-run gate
    controller.schedule()
    assert not controller._timer.isActive()

    controller.set_enabled(True)
    controller.schedule()
    assert controller._timer.isActive()  # both gates open


def test_interrupt_stops_the_timer_and_is_safe_without_a_worker(qapp):
    controller = AutoRunController(_loader_pipeline)
    controller.schedule()
    assert controller._timer.isActive()

    controller.interrupt()  # no worker running
    assert not controller._timer.isActive()
    assert controller._worker is None
    assert controller._rerun_pending is False


def test_fire_emits_started(qapp, tmp_path):
    import numpy as np
    import pandas as pd

    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": np.arange(5)}).to_csv(csv, index=False)

    controller = AutoRunController(lambda: _loader_pipeline(str(csv)))
    seen: list[int] = []
    controller.started.connect(lambda: seen.append(1))

    controller._fire()
    controller._worker.wait(5000)
    qapp.processEvents()

    assert seen == [1]


def test_fire_runs_and_emits_finished(qapp, tmp_path):
    import numpy as np
    import pandas as pd

    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": np.arange(5)}).to_csv(csv, index=False)

    controller = AutoRunController(lambda: _loader_pipeline(str(csv)))
    results: list[tuple[dict, dict]] = []
    controller.finished.connect(results.append)

    controller._fire()
    controller._worker.wait(5000)
    qapp.processEvents()

    assert results
    outputs, errors = results[0]
    assert "df" in outputs["load"]
    assert errors == {}


# -- the skip cache carried across auto-runs ------------------------------


def _real_pipeline(tmp_path):
    """A pipeline that actually produces something to cache."""
    import pandas as pd

    csv = tmp_path / "d.csv"
    pd.DataFrame({"a": [1, 2, 3]}).to_csv(csv, index=False)
    graph = PipelineGraph()
    graph.add_node(
        NodeSpec(id="load", node_type="csv_loader", params={"filepath": str(csv)})
    )
    graph.add_node(NodeSpec(id="head", node_type="head", params={"n": 2}))
    graph.add_connection(
        Connection(source_node="load", source_port="df", target_node="head", target_port="df")
    )
    return graph


def test_the_controller_keeps_a_cache_across_runs(qapp, tmp_path):
    """Otherwise every background run re-renders every figure."""
    from ruyso_app.engine.run_cache import ResultCache

    controller = AutoRunController(lambda: _real_pipeline(tmp_path))
    assert isinstance(controller._cache, ResultCache)
    assert len(controller._cache) == 0

    controller._fire()
    controller._worker.wait(5000)
    QApplication.processEvents()

    assert len(controller._cache) > 0  # results survive for the next run


def test_the_worker_gets_a_snapshot_not_the_live_cache(qapp, tmp_path):
    """
    interrupt() terminates the thread at an arbitrary instruction, so
    the live cache must never be the thing being written to.
    """
    controller = AutoRunController(lambda: _real_pipeline(tmp_path))
    live = controller._cache

    controller._fire()
    worker_cache = controller._worker.result_cache

    assert worker_cache is not live
    assert worker_cache is controller._pending_cache
    controller._worker.wait(5000)
    QApplication.processEvents()

    assert controller._cache is worker_cache  # adopted only once finished


def test_interrupting_discards_what_the_killed_run_built(qapp, tmp_path):
    controller = AutoRunController(lambda: _real_pipeline(tmp_path))
    controller._fire()
    live = controller._cache

    controller.interrupt()

    assert controller._pending_cache is None
    assert controller._cache is live  # untouched by the terminated run
