"""
Tests for ``ui.table_nav``: the flat, execution-ordered list of the
tables a pipeline can produce.
"""

import ruyso_app.nodes  # noqa: F401 - registers node types
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.ui.table_nav import build_table_entries

NodeRegistry.discover_package(ruyso_app.nodes)


def test_single_table_output_is_labelled_by_node_id():
    entries = build_table_entries(["load"], {"load": "csv_loader"})
    assert len(entries) == 1
    assert (entries[0].node_id, entries[0].port, entries[0].label) == ("load", "df", "load")


def test_multi_table_output_yields_one_entry_per_port():
    entries = build_table_entries(["split"], {"split": "train_test_split"})
    labels = [e.label for e in entries]
    # only the two dataframe ports, not the array ports
    assert labels == ["split / X_train", "split / X_test"]


def test_node_with_no_table_output_is_skipped():
    entries = build_table_entries(["m"], {"m": "linear_regression_fit"})
    assert entries == []


def test_execution_order_is_preserved():
    order = ["load", "clean", "split"]
    node_types = {
        "load": "csv_loader",
        "clean": "drop_na",
        "split": "train_test_split",
    }
    entries = build_table_entries(order, node_types)
    assert [e.node_id for e in entries] == ["load", "clean", "split", "split"]
