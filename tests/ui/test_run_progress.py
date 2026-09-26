"""
Tests for ``ui.run_progress.RunProgressBar`` state handling.
"""

from ruyso_app.ui.run_progress import RunProgressBar


def test_idle_and_shown_before_any_run(qapp):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    # always in the tab band now -- a flat grey track before the first
    # run, so __init__ must not hide it.
    host = QWidget()
    QVBoxLayout(host).addWidget(RunProgressBar(host))
    host.show()
    bar = host.findChild(RunProgressBar)
    assert bar.isVisible()
    assert bar.property("state") == "idle"


def test_start_and_progress(qapp):
    bar = RunProgressBar()
    bar.start(4)
    assert bar.property("state") == "running"
    assert bar.maximum() == 4 and bar.value() == 0
    assert bar.percent_text() == "0%"

    bar.set_progress(3, 4)
    assert bar.value() == 3
    assert bar.percent_text() == "75%"


def test_success_fills_and_turns_green(qapp):
    bar = RunProgressBar()
    bar.start(3)
    bar.finish_success()
    assert bar.property("state") == "success"
    assert bar.value() == bar.maximum()
    assert bar.percent_text() == "100%"


def test_error_state(qapp):
    bar = RunProgressBar()
    bar.start(3)
    bar.set_progress(1, 3)
    bar.finish_error()
    assert bar.property("state") == "error"
