"""
Curated grouping + ordering of each macro type's "Micro type" dropdown
in the Options panel, rendered with a separator line between groups
(see ``options_panel.OptionsPanel.show_node``).

A category not listed in :data:`MICRO_TYPE_GROUPS` -- or a node_type
registered under a listed category but not mentioned by any of its
groups -- still shows up: :func:`grouped_micro_types` falls back to a
single alphabetical group (respectively for the whole category, or as
a trailing group for the unlisted node types), so a node is never
silently missing from the dropdown just because this file has not
been updated yet.
"""

from __future__ import annotations

#: category -> ordered list of groups, each an ordered list of node_type.
MICRO_TYPE_GROUPS: dict[str, list[list[str]]] = {
    "loading": [
        # general-purpose file loaders
        [
            "csv_loader",
            "fixed_width_loader",
            "excel_loader",
            "json_loader",
            "parquet_loader",
            "feather_loader",
            "stata_loader",
        ],
        # geographic / border data
        [
            "geojson_loader",
            "shapefile_loader",
            "geopackage_loader",
            "geoparquet_loader",
            "geofeather_loader",
        ],
        # bundled example datasets
        ["example_data"],
    ],
    "transform": [
        # base operations
        ["head", "tail", "sample", "drop_na", "sort", "reset_index"],
        # filters
        ["row_filter", "column_filter", "dtype_filter"],
        # type operations (except type/dtype filter, grouped above)
        [
            "change_type",
            "fill_na",
            "scaler",
            "one_hot_encode",
            "ordinal_encode",
            "rename_categories",
        ],
        # reshaping operations
        [
            "group_by",
            "aggregate",
            "bin",
            "concat",
            "merge",
            "pivot",
            "unpivot",
            "pivot_table",
            "train_test_split",
            "covariance_matrix",
        ],
        # datetime operations
        ["combine_datetime", "split_datetime", "resample_datetime", "diff"],
        # geo: conversion & CRS
        ["dataframe_to_geo", "geo_to_dataframe", "reproject", "set_crs"],
        # geo: relate / combine layers
        ["spatial_join", "spatial_filter", "geo_clip", "geo_overlay"],
        # geo: reshape & derive geometry
        [
            "geo_dissolve",
            "geo_explode",
            "geo_buffer",
            "geometry_op",
            "geo_measures",
        ],
        # free-form
        ["custom_operation"],
    ],
    "model": [
        # utilities -- consume a fitted model (or an optimization run)
        [
            "predict",
            "model_coeffs",
            "model_scores",
            "residuals",
            "optim_diagnostic",
            "optim_scores",
        ],
        # supervised fits (need a target column)
        [
            "linear_regression_fit",
            "logistic_regression_fit",
            "ridge_fit",
            "lasso_fit",
            "elastic_net_fit",
            "decision_tree_fit",
            "random_forest_fit",
            "gradient_boosting_fit",
            "adaboost_fit",
            "svm_fit",
            "knn_fit",
            "naive_bayes_fit",
        ],
        # unsupervised fits (clustering -- no target column) are a
        # trailing, alphabetical group: everything not listed above.
        # New clustering nodes join it automatically.
    ],
    "statistics": [
        # non-tests -- model-fitting / data-transforming tools
        ["regression", "pca", "ica", "tsne", "multiple_testing"],
        # time-series models
        ["arima", "auto_arima", "var", "seasonal_decompose"],
        # everything else (every *_test node, incl. var_test) is a
        # trailing, alphabetical "tests" group -- new tests join it
        # automatically, with nothing to update here.
    ],
    "grapher": [
        # table_viewer stands alone -- it renders a table, not a chart
        ["table_viewer"],
        # base plots -- general-purpose, single/two-variable, no model needed
        [
            "matplotlib_plot",
            "regression_plot",
            "box_plot",
            "histogram_plot",
            "heatmap_plot",
            "pie_chart",
            "heatmap_1d",
            "density_2d",
            "autocorrelogram",
        ],
        # time-series plots
        [
            "time_series_plot",
            "multivariate_timeseries_plot",
            "forecast_plot",
            "var_acorr_plot",
            "irf_plot",
        ],
        # ML plots: classification-specific or usable for either task
        [
            "confusion_matrix_plot",
            "roc_curve_plot",
            "precision_recall_plot",
            "det_curve_plot",
            "calibration_curve_plot",
            "learning_curve_plot",
        ],
        # ML plots: regression only
        ["qq_plot"],
        # stats plots (PCA, ...)
        ["pca_scree_plot", "pca_corr_circle"],
        # geo / maps
        ["geo_plot", "geo_density"],
    ],
}


def grouped_micro_types(category: str, node_types: list[str]) -> list[list[str]]:
    """
    Split ``node_types`` (the registered node types for ``category``)
    into the curated groups for ``category``, in curated order.

    Args:
        category: The macro type, e.g. "loading".
        node_types: The registered node_type identifiers for that
            category (as produced by ``NodeRegistry.by_category()``).

    Returns:
        A list of groups (each a list of node_type strings); the caller
        draws a separator between consecutive groups. A category with
        no curated grouping yields a single group holding every type,
        in the order given.
    """
    curated = MICRO_TYPE_GROUPS.get(category)
    if not curated:
        return [list(node_types)]

    available = set(node_types)
    groups: list[list[str]] = []
    seen: set[str] = set()
    for group in curated:
        shown = [nt for nt in group if nt in available]
        if shown:
            groups.append(shown)
            seen.update(shown)

    leftover = sorted(available - seen)
    if leftover:
        groups.append(leftover)
    return groups or [list(node_types)]
