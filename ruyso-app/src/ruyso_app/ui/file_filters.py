"""
File-dialog filters for node parameters that hold a file path.

Kept as a small UI-side map keyed by core ``node_type`` so the core /
nodes layer stays free of any UI concern. A node type not listed here
falls back to :data:`DEFAULT_FILTER` ("All files").
"""

from __future__ import annotations

#: ``node_type`` -> Qt ``QFileDialog`` filter string.
FILE_FILTERS: dict[str, str] = {
    "csv_loader": "CSV files (*.csv);;All files (*)",
    "figure_export": "Images (*.png *.pdf *.svg *.jpg *.jpeg);;All files (*)",
}

DEFAULT_FILTER = "All files (*)"


def filter_for(node_type: str | None) -> str:
    """The QFileDialog filter string to use for ``node_type``'s path field."""
    return FILE_FILTERS.get(node_type or "", DEFAULT_FILTER)
