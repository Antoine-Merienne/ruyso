"""
Tests for ``engine.errors`` -- reading an exception as a sentence.

Two properties matter throughout. First, a recognised failure names the
*setting* or the *column* at fault, in the words the Options panel uses.
Second, an unrecognised one is never made worse: it degrades to
``TypeName: message``, which is what the app showed before this module
existed. No Qt, no pipeline -- just exceptions in, sentences out.
"""

import pytest

import ruyso_app.nodes  # noqa: F401 - registers the node classes
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine import errors

NodeRegistry.discover_package(ruyso_app.nodes)


def _translate(exc, node_type="sort", **kwargs):
    return errors.translate(
        exc,
        node_id="N1",
        node_type=node_type,
        node_cls=NodeRegistry.all().get(node_type),
        **kwargs,
    )


def _validation_error(node_type, params):
    """The ValidationError a node raises for bad params."""
    with pytest.raises(Exception) as caught:
        NodeRegistry.get(node_type)(params=params)
    return caught.value


# -- the NodeError itself ------------------------------------------------


def test_str_is_the_plain_title_so_old_call_sites_read_as_prose():
    error = errors.NodeError("N1", "sort", "runtime", "Something went wrong.")
    assert str(error) == "Something went wrong."
    assert f"ERROR [{error.node_id}]: {error}" == "ERROR [N1]: Something went wrong."


def test_full_text_joins_title_and_detail():
    assert errors.NodeError("N", "t", "runtime", "A.", "B.").full_text() == "A.\nB."
    assert errors.NodeError("N", "t", "runtime", "A.").full_text() == "A."


def test_field_label_matches_how_the_options_panel_spells_a_row():
    assert errors.field_label("na_position") == "na position"
    assert errors.field_label("columns") == "columns"


# -- pydantic: the parameter failures ------------------------------------


def test_a_missing_setting_is_named():
    error = _translate(_validation_error("bin", {}), node_type="bin")
    assert error.kind == "param"
    assert error.field == "column"
    assert '"column" setting is required' in error.title


def test_a_wrong_type_says_what_it_wanted_and_what_it_got():
    """The original complaint: 'Input should be a valid list [type=list_type…]'."""
    error = _translate(_validation_error("sort", {"columns": "nope"}))
    assert error.kind == "param"
    assert error.field == "columns"
    assert error.title == (
        'The "columns" setting expects a list of values, not the text \'nope\'.'
    )
    assert "pydantic" not in error.title


def test_a_bad_choice_lists_the_allowed_values_and_the_current_one():
    error = _translate(
        _validation_error("example_data", {"dataset": "iris"}),
        node_type="example_data",
    )
    assert error.field == "dataset"
    assert "seaborn/tips" in error.title or "sklearn/iris" in error.title
    assert "it is currently 'iris'" in error.title


def test_a_long_list_of_allowed_values_is_truncated():
    """example_data has 29 datasets; the message must stay one line."""
    error = _translate(
        _validation_error("example_data", {"dataset": "iris"}),
        node_type="example_data",
    )
    assert "more)" in error.title
    assert error.title.count(",") <= errors._MAX_LISTED + 1


def test_a_misspelled_setting_suggests_the_real_one_and_points_at_it():
    error = _translate(
        _validation_error("bin", {"column": "a", "columns": "x"}), node_type="bin"
    )
    assert 'did you mean "column"?' in error.title
    assert error.field == "column"  # so the UI can focus that row


def test_several_bad_settings_summarise_in_the_title_and_list_in_the_detail():
    error = _translate(
        _validation_error("bin", {"columns": "x", "method": "nope"}), node_type="bin"
    )
    assert "more problem" in error.title
    assert error.detail  # the rest, one per line


# -- runtime failures ----------------------------------------------------


def test_a_missing_column_says_which_columns_do_exist():
    import pandas as pd

    frame = pd.DataFrame({"total_bill": [1.0], "tip": [0.1], "day": ["a"]})
    error = _translate(
        KeyError("tipp"), input_columns=errors.columns_from_inputs({"df": frame})
    )
    assert "no column named 'tipp'" in error.title
    assert 'did you mean "tip"?' in error.title
    assert "total_bill" in error.detail


def test_a_missing_column_with_no_tabular_input_still_reads_as_a_sentence():
    error = _translate(KeyError("x"))
    assert "no column named 'x'" in error.title
    assert error.detail == ""


def test_text_in_a_numeric_column():
    error = _translate(ValueError("could not convert string to float: 'abc'"))
    assert "needs numeric columns" in error.title
    assert "'abc'" in error.title
    assert "change_type" in error.detail


def test_mismatched_row_counts():
    error = _translate(
        ValueError("Found input variables with inconsistent numbers of samples: [100, 80]")
    )
    assert "different numbers of rows" in error.title
    assert "[100, 80]" in error.detail  # the numbers are kept


def test_a_missing_file_names_the_path_and_the_setting():
    exc = FileNotFoundError(2, "No such file", "/no/such/file.csv")
    error = _translate(exc, node_type="csv_loader")
    assert "/no/such/file.csv" in error.title
    assert error.field == "filepath"


def test_a_permission_problem_is_told_apart_from_a_missing_file():
    exc = PermissionError(13, "Denied", "/root/secret.csv")
    error = _translate(exc, node_type="csv_loader")
    assert "Not allowed" in error.title


def test_running_out_of_memory_suggests_something_to_do():
    error = _translate(MemoryError())
    assert "Ran out of memory" in error.title
    assert "head" in error.detail


def test_an_unfitted_model():
    class NotFittedError(Exception):
        pass

    error = _translate(NotFittedError("not fitted"))
    assert "has not been fitted" in error.title


def test_an_unconnected_input_port_is_its_own_kind():
    error = _translate(ValueError("Node 'sort': missing required input port(s): ['df']"))
    assert error.kind == "input"
    assert "Nothing is connected" in error.title


# -- never worse than before ---------------------------------------------


def test_an_unrecognised_exception_keeps_its_own_message():
    error = _translate(RuntimeError("something odd happened"))
    assert error.title == "something odd happened"
    assert error.kind == "runtime"


def test_an_exception_with_no_message_still_produces_a_title():
    error = _translate(RuntimeError())
    assert error.title == "RuntimeError: "


def test_translate_never_raises_on_a_hostile_exception():
    class Awkward(Exception):
        def __str__(self):
            raise RuntimeError("cannot render me")

    # str(exc) blows up, so translate must fall back rather than propagate.
    with pytest.raises(RuntimeError):
        str(Awkward())
    error = errors.translate(Awkward(), node_id="N", node_type="sort", raw="kept")
    assert error.raw == "kept"


def test_the_raw_text_is_kept_for_the_details_disclosure():
    error = _translate(RuntimeError("boom"), raw="Traceback (most recent call last): ...")
    assert error.raw.startswith("Traceback")


def test_raw_defaults_to_the_type_and_message():
    assert _translate(RuntimeError("boom")).raw == "RuntimeError: boom"


# -- helpers -------------------------------------------------------------


def test_columns_from_inputs_only_picks_up_tabular_values():
    import pandas as pd

    inputs = {
        "df": pd.DataFrame({"a": [1], "b": [2]}),
        "model": object(),
        "figure": None,
    }
    assert errors.columns_from_inputs(inputs) == {"df": ["a", "b"]}


def test_columns_from_inputs_tolerates_a_non_dict():
    assert errors.columns_from_inputs(None) == {}


def test_blocked_error_names_the_node_that_actually_failed():
    error = errors.blocked_error("Plot 1", "matplotlib_plot", blocked_by="Sort 1")
    assert error.kind == "blocked"
    assert error.blocked_by == "Sort 1"
    assert "waiting on Sort 1" in error.title


def test_blocked_error_without_a_cause_reads_as_unfinished_not_broken():
    error = errors.blocked_error("Plot 1", "matplotlib_plot")
    assert error.blocked_by is None
    assert "not connected" in error.title
