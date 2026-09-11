"""
Tests for ``ui.error_panel`` and ``ui.problems_chip``.

What the panel is for: a failure that stays visible until it is fixed,
reads as a sentence, and leads to the node it is about. The old modal
did none of those.
"""

import pytest

from ruyso_app.engine.errors import NodeError
from ruyso_app.ui.error_panel import GRAPH_PROBLEM, ProblemRow, ProblemsPanel
from ruyso_app.ui.problems_chip import ProblemsChip


def _error(node_id="Sort 1", field="columns", detail="More about it.", raw="Traceback..."):
    return NodeError(
        node_id=node_id,
        node_type="sort",
        kind="param",
        title='The "columns" setting expects a list of values.',
        detail=detail,
        field=field,
        raw=raw,
    )


# -- the panel -----------------------------------------------------------


def test_an_empty_panel_says_so(qapp):
    panel = ProblemsPanel()
    assert panel.count() == 0
    assert panel._empty.isVisibleTo(panel)


def test_problems_become_rows_in_the_order_given(qapp):
    panel = ProblemsPanel()
    panel.set_problems([_error("A"), _error("B")])

    assert panel.count() == 2
    assert [row.error.node_id for row in panel.rows()] == ["A", "B"]
    assert not panel._empty.isVisibleTo(panel)


def test_setting_problems_replaces_rather_than_appends(qapp):
    panel = ProblemsPanel()
    panel.set_problems([_error("A"), _error("B")])
    panel.set_problems([_error("C")])

    assert [row.error.node_id for row in panel.rows()] == ["C"]


def test_clearing_empties_the_panel(qapp):
    panel = ProblemsPanel()
    panel.set_problems([_error()])
    panel.clear()
    assert panel.count() == 0


def test_the_count_is_announced(qapp):
    panel = ProblemsPanel()
    seen: list[int] = []
    panel.count_changed.connect(seen.append)

    panel.set_problems([_error("A"), _error("B")])
    panel.clear()

    assert seen == [2, 0]


def test_clicking_a_row_asks_for_its_node_and_field(qapp):
    panel = ProblemsPanel()
    panel.set_problems([_error("Sort 1", field="columns")])
    asked: list[tuple[str, str]] = []
    panel.problem_activated.connect(lambda node, field: asked.append((node, field)))

    panel.rows()[0]._headline.click()

    assert asked == [("Sort 1", "columns")]


# -- one row -------------------------------------------------------------


def test_a_row_leads_with_the_node_and_the_sentence(qapp):
    row = ProblemRow(_error("Sort 1"))
    text = row._headline.text()
    assert text.startswith("Sort 1")
    assert "expects a list of values" in text
    assert "pydantic" not in text


def test_details_start_folded_away(qapp):
    row = ProblemRow(_error())
    assert not row.is_expanded()
    assert not row._details.isVisibleTo(row)

    row.set_expanded(True)
    assert row._details.isVisibleTo(row)


def test_the_traceback_is_kept_but_not_shown_by_default(qapp):
    row = ProblemRow(_error(raw="Traceback (most recent call last): ..."))
    assert row._raw.toPlainText().startswith("Traceback")
    assert not row._raw.isVisibleTo(row)


def test_a_pipeline_wide_problem_names_no_node(qapp):
    error = NodeError(
        node_id=GRAPH_PROBLEM, node_type="", kind="input",
        title="Pipeline graph contains a cycle.", raw="...",
    )
    row = ProblemRow(error)
    assert row._headline.text() == "Pipeline graph contains a cycle."
    assert GRAPH_PROBLEM not in row._headline.text()


def test_copying_puts_the_raw_text_on_the_clipboard(qapp):
    from PySide6.QtGui import QGuiApplication

    row = ProblemRow(_error(raw="the whole traceback"))
    row._copy_raw()
    assert QGuiApplication.clipboard().text() == "the whole traceback"


# -- the chip ------------------------------------------------------------


def test_the_chip_is_hidden_when_there_is_nothing_wrong(qapp):
    """An always-present '0 problems' is a thing to learn to ignore."""
    chip = ProblemsChip()
    assert chip.count() == 0
    assert chip.isHidden()


@pytest.mark.parametrize("count, text", [(1, "1 problem"), (3, "3 problems")])
def test_the_chip_counts_in_words(qapp, count, text):
    chip = ProblemsChip()
    chip.set_count(count)
    assert chip._label.text() == text
    assert not chip.isHidden()


def test_the_chip_hides_again_when_the_problems_go(qapp):
    chip = ProblemsChip()
    chip.set_count(2)
    chip.set_count(0)
    assert chip.isHidden()
