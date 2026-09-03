"""
Tests for the visualization node (MatplotlibPlot): known input
DataFrame -> a valid matplotlib Figure with the expected styling and
optional colour-by-column behaviour.
"""

import matplotlib
import pandas as pd

matplotlib.use("Agg")  # ensure headless backend before importing pyplot anywhere
from matplotlib.figure import Figure

from ruyso_app.nodes.viz import MatplotlibPlot, MatplotlibPlotParams


def _run(**params):
    df = params.pop("df", pd.DataFrame({"x": [1, 2, 3, 4], "y": [10, 20, 30, 40]}))
    node = MatplotlibPlot(params=MatplotlibPlotParams(**params))
    return node.run(df=df)["figure"]


def test_matplotlib_plot_returns_a_figure_with_correct_labels():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]})
    node = MatplotlibPlot(params=MatplotlibPlotParams(x="x", y="y", title="Test plot"))

    result = node.run(df=df)

    fig = result["figure"]
    assert isinstance(fig, Figure)
    ax = fig.axes[0]
    assert ax.get_xlabel() == "x"
    assert ax.get_ylabel() == "y"
    assert ax.get_title() == "Test plot"


def test_matplotlib_plot_supports_line_and_bar_kinds():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [10, 20, 30]})

    for kind in ("scatter", "line", "bar"):
        node = MatplotlibPlot(params=MatplotlibPlotParams(x="x", y="y", kind=kind))
        result = node.run(df=df)
        assert isinstance(result["figure"], Figure)


def test_default_style_despines_top_and_right_keeps_bottom_and_left():
    fig = _run(x="x", y="y")
    ax = fig.axes[0]
    assert ax.spines["top"].get_visible() is False
    assert ax.spines["right"].get_visible() is False
    assert ax.spines["bottom"].get_visible() is True
    assert ax.spines["left"].get_visible() is True


def test_show_box_brings_back_the_full_frame():
    ax = _run(x="x", y="y", show_box=True).axes[0]
    assert ax.spines["top"].get_visible() is True
    assert ax.spines["right"].get_visible() is True


def test_grid_is_on_by_default_and_can_be_turned_off():
    on = _run(x="x", y="y").axes[0]
    assert on.get_xgridlines() and all(g.get_visible() for g in on.get_xgridlines())

    off = _run(x="x", y="y", show_grid=False).axes[0]
    assert not any(g.get_visible() for g in off.get_xgridlines())


def test_figure_size_and_log_scales_are_honoured():
    fig = _run(x="x", y="y", fig_width=8.0, fig_height=3.0, log_x=True, log_y=True)
    assert tuple(fig.get_size_inches()) == (8.0, 3.0)
    ax = fig.axes[0]
    assert ax.get_xscale() == "log" and ax.get_yscale() == "log"


def test_axis_label_overrides_and_font_size():
    ax = _run(x="x", y="y", x_label="Age", y_label="Score", axis_font_size=14).axes[0]
    assert ax.get_xlabel() == "Age" and ax.get_ylabel() == "Score"
    assert ax.xaxis.label.get_fontsize() == 14


def test_title_style_bold_italic_and_size():
    ax = _run(x="x", y="y", title="T", title_font_size=20, title_bold=True, title_italic=True).axes[0]
    assert ax.title.get_fontsize() == 20
    assert ax.title.get_fontweight() == "bold"
    assert ax.title.get_fontstyle() == "italic"


def test_colour_by_categorical_column_draws_a_legend_of_the_categories():
    df = pd.DataFrame(
        {"x": [1, 2, 3, 4], "y": [1, 2, 3, 4], "team": ["a", "b", "a", "b"]}
    )
    ax = _run(df=df, x="x", y="y", color_by="team").axes[0]
    legend = ax.get_legend()
    assert legend is not None
    assert [t.get_text() for t in legend.get_texts()] == ["a", "b"]
    assert legend.get_title().get_text() == "team"


def test_discrete_legend_sits_in_a_translucent_box():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [1, 2, 3, 4], "g": ["a", "b", "a", "b"]})
    legend = _run(df=df, x="x", y="y", color_by="g").axes[0].get_legend()
    assert legend.get_frame_on() is True
    assert legend.get_frame().get_alpha() == 0.7


def test_colour_by_categorical_can_be_hidden_and_retitled():
    df = pd.DataFrame({"x": [1, 2], "y": [1, 2], "g": ["a", "b"]})
    ax = _run(df=df, x="x", y="y", color_by="g", show_legend=False).axes[0]
    assert ax.get_legend() is None

    ax2 = _run(df=df, x="x", y="y", color_by="g", legend_title="Group").axes[0]
    assert ax2.get_legend().get_title().get_text() == "Group"


def test_colour_by_continuous_column_adds_a_colorbar():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [1, 2, 3], "val": [0.1, 0.5, 0.9]})
    with_bar = _run(df=df, x="x", y="y", color_by="val")
    assert len(with_bar.axes) == 2  # main axes + colorbar axes

    without = _run(df=df, x="x", y="y", color_by="val", show_legend=False)
    assert len(without.axes) == 1


def test_colour_by_categorical_line_draws_one_line_per_group():
    df = pd.DataFrame(
        {"x": [1, 2, 1, 2], "y": [1, 2, 3, 4], "g": ["a", "a", "b", "b"]}
    )
    ax = _run(df=df, x="x", y="y", kind="line", color_by="g").axes[0]
    assert len(ax.get_lines()) == 2
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["a", "b"]


def test_unknown_colour_by_column_falls_back_to_a_single_colour():
    ax = _run(x="x", y="y", color_by="missing").axes[0]
    assert ax.get_legend() is None
    assert len(ax.collections) == 1  # a plain scatter, no per-point colouring


def _bars_by_x(ax):
    """{x-position: [bar heights]} for every bar patch drawn on ax."""
    from matplotlib.patches import Rectangle

    out: dict[float, list[float]] = {}
    for patch in ax.patches:
        if isinstance(patch, Rectangle):
            out.setdefault(round(patch.get_x() + patch.get_width() / 2, 3), []).append(
                round(patch.get_height(), 3)
            )
    return out


def test_bar_colour_by_discrete_stack_mode_stacks_group_totals():
    df = pd.DataFrame(
        {"cat": ["p", "p", "q", "q"], "val": [1, 2, 3, 4], "g": ["a", "b", "a", "b"]}
    )
    ax = _run(df=df, x="cat", y="val", kind="bar", color_by="g", bar_mode="stack").axes[0]
    # two x groups (p, q), each with two stacked bars at the same x position
    assert [t.get_text() for t in ax.get_xticklabels()] == ["p", "q"]
    positions = _bars_by_x(ax)
    assert len(positions) == 2
    assert all(len(heights) == 2 for heights in positions.values())


def test_bar_colour_by_discrete_dodge_mode_offsets_the_groups():
    df = pd.DataFrame(
        {"cat": ["p", "p", "q", "q"], "val": [1, 2, 3, 4], "g": ["a", "b", "a", "b"]}
    )
    ax = _run(df=df, x="cat", y="val", kind="bar", color_by="g", bar_mode="dodge").axes[0]
    xs = sorted(round(patch.get_x(), 3) for patch in ax.patches)
    assert len(set(xs)) == 4  # 2 groups x 2 categories, all at distinct x offsets


# -- colour / shape / size / alpha channels ------------------------


def _style_df():
    return pd.DataFrame(
        {
            "x": list(range(12)),
            "y": list(range(12)),
            "grp": ["a", "b", "c"] * 4,
            "shp": ["p", "q"] * 6,
            "mag": [float(v) for v in range(12)],
        }
    )


def _legends(ax):
    return [c for c in ax.get_children() if c.__class__.__name__ == "Legend"]


def test_fixed_line_style_is_applied():
    ax = _run(x="x", y="y", kind="line", line_style="dashed").axes[0]
    assert ax.get_lines()[0].get_linestyle() == "--"


def test_shape_by_discrete_column_draws_one_group_per_level_with_its_own_shape():
    ax = _run(df=_style_df(), x="x", y="y", kind="scatter", shape_by="shp").axes[0]
    assert len(ax.collections) == 2  # one scatter call per shape level
    markers = {c.get_paths()[0].vertices.tobytes() for c in ax.collections}
    assert len(markers) == 2
    legend = ax.get_legend()
    assert [t.get_text() for t in legend.get_texts()] == ["p", "q"]
    assert legend.get_title().get_text() == "shp"


def test_shape_map_choice_changes_the_marker_series():
    df = pd.DataFrame({"x": range(9), "y": range(9), "s": ["p", "q", "r"] * 3})
    per_map = {}
    for shape_map in ("assorted", "geometric", "bold", "minimal"):
        ax = _run(
            df=df, x="x", y="y", kind="scatter", shape_by="s", shape_map=shape_map
        ).axes[0]
        per_map[shape_map] = tuple(
            c.get_paths()[0].vertices.tobytes() for c in ax.collections
        )
        assert len(set(per_map[shape_map])) == 3
    assert len(set(per_map.values())) >= 2


def test_size_by_continuous_scales_area_and_shape_stays_the_fixed_one():
    from matplotlib.markers import MarkerStyle

    ax = _run(
        df=_style_df(),
        x="x", y="y", kind="scatter", size_by="mag", marker_shape="square",
        size_min=20.0, size_max=200.0,
    ).axes[0]
    sizes = ax.collections[0].get_sizes()
    assert sizes.min() == 20.0 and sizes.max() == 200.0
    # the fixed marker_shape is still respected while sizing by a column
    square_verts = MarkerStyle("s").get_path().vertices.shape
    assert ax.collections[0].get_paths()[0].vertices.shape == square_verts


def test_shape_by_and_size_by_are_independent_channels():
    ax = _run(
        df=_style_df(),
        x="x", y="y", kind="scatter", shape_by="shp", size_by="mag",
        size_min=15.0, size_max=150.0,
    ).axes[0]
    assert len(ax.collections) == 2  # one per shape level
    import numpy as np

    all_sizes = np.concatenate([c.get_sizes() for c in ax.collections])
    assert all_sizes.min() == 15.0 and all_sizes.max() == 150.0


def test_size_by_continuous_scales_line_width():
    ax = _run(
        df=_style_df(),
        x="x", y="y", kind="line", size_by="mag", width_min=1.0, width_max=5.0,
    ).axes[0]
    assert 1.0 <= ax.get_lines()[0].get_linewidth() <= 5.0


def test_fixed_alpha_and_alpha_by_column():
    ax = _run(df=_style_df(), x="x", y="y", alpha=0.4).axes[0]
    assert round(float(ax.collections[0].get_facecolors()[0][3]), 3) == 0.4

    ax2 = _run(
        df=_style_df(), x="x", y="y", alpha_by="mag", alpha_min=0.2, alpha_max=0.9
    ).axes[0]
    alphas = ax2.collections[0].get_facecolors()[:, 3]
    assert round(alphas.min(), 2) == 0.2 and round(alphas.max(), 2) == 0.9


def test_colour_by_and_shape_by_different_columns_get_two_legends():
    ax = _run(
        df=_style_df(), x="x", y="y", kind="scatter", color_by="grp", shape_by="shp"
    ).axes[0]
    titles = sorted(lg.get_title().get_text() for lg in _legends(ax))
    assert titles == ["grp", "shp"]


def test_colour_by_and_shape_by_same_column_get_one_combined_legend():
    ax = _run(
        df=_style_df(), x="x", y="y", kind="scatter", color_by="grp", shape_by="grp"
    ).axes[0]
    assert len(_legends(ax)) == 1


def test_too_many_shape_levels_draws_a_repeat_note():
    df = pd.DataFrame(
        {"x": range(10), "y": range(10), "many": [f"c{i}" for i in range(10)]}
    )
    fig = _run(df=df, x="x", y="y", kind="scatter", shape_by="many")
    assert any("repeat" in t.get_text() for t in fig.texts)


def test_bar_shape_by_discrete_hatches_each_bar_and_size_by_notes_no_effect():
    df = pd.DataFrame(
        {"x": ["a", "b", "c", "d"], "y": [1, 2, 3, 4], "s": ["p", "q", "p", "q"]}
    )
    ax = _run(df=df, x="x", y="y", kind="bar", shape_by="s").axes[0]
    assert len({rect.get_hatch() for rect in ax.patches}) == 2

    fig = _run(df=_style_df(), x="grp", y="y", kind="bar", size_by="mag")
    assert any("no effect on bars" in t.get_text() for t in fig.texts)


# -- box / violin -----------------------------------------------------

from ruyso_app.nodes.viz import (  # noqa: E402
    BoxPlot,
    BoxPlotParams,
    HeatmapPlot,
    HeatmapPlotParams,
    HistogramPlot,
    HistogramPlotParams,
)


def _cat_df():
    return pd.DataFrame(
        {
            "team": ["a", "b", "a", "b", "a", "b", "a", "b"],
            "region": ["n", "n", "s", "s", "n", "s", "n", "s"],
            "score": [1.0, 2, 3, 4, 5, 6, 7, 8],
            "n": [0.0, 1, 2, 3, 4, 5, 6, 7],
        }
    )


def test_box_plot_draws_all_four_catplot_kinds():
    for kind in ("box", "violin", "boxen", "swarm"):
        fig = BoxPlot(
            params=BoxPlotParams(category_column="team", value_column="score", kind=kind)
        ).run(df=_cat_df())["figure"]
        assert isinstance(fig, Figure)


def test_box_plot_swarm_subsamples_large_data_and_notes_it():
    import numpy as np

    rng = np.random.default_rng(0)
    big = pd.DataFrame(
        {"team": rng.choice(list("ab"), 4000), "score": rng.normal(size=4000)}
    )
    fig = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", kind="swarm",
            swarm_max_points=500,
        )
    ).run(df=big)["figure"]
    assert any("subsample" in t.get_text() for t in fig.texts)
    # a small dataset draws every point with no note
    small = BoxPlot(
        params=BoxPlotParams(category_column="team", value_column="score", kind="swarm")
    ).run(df=_cat_df())["figure"]
    assert not any("subsample" in t.get_text() for t in small.texts)


def test_box_plot_orientation_swaps_the_axes():
    v = BoxPlot(
        params=BoxPlotParams(category_column="team", value_column="score")
    ).run(df=_cat_df())["figure"].axes[0]
    assert v.get_xlabel() == "team" and v.get_ylabel() == "score"

    h = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", orientation="horizontal"
        )
    ).run(df=_cat_df())["figure"].axes[0]
    assert h.get_xlabel() == "score" and h.get_ylabel() == "team"


def test_box_plot_colour_by_categorical_adds_a_legend():
    ax = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", color_by="region"
        )
    ).run(df=_cat_df())["figure"].axes[0]
    legend = ax.get_legend()
    assert legend is not None
    assert legend.get_frame().get_alpha() == 0.7


def test_box_plot_rejects_a_continuous_colour_by_column():
    import pytest

    with pytest.raises(ValueError, match="continuous"):
        BoxPlot(
            params=BoxPlotParams(
                category_column="team", value_column="score", color_by="n"
            )
        ).run(df=_cat_df())


# -- histogram ------------------------------------------------------


def test_histogram_modes_histogram_kde_and_both():
    hist = HistogramPlot(
        params=HistogramPlotParams(value_column="n", mode="histogram", bins=5)
    ).run(df=_cat_df())["figure"].axes[0]
    assert len(hist.patches) == 5 and not hist.get_lines()

    kde = HistogramPlot(
        params=HistogramPlotParams(value_column="n", mode="kde")
    ).run(df=_cat_df())["figure"].axes[0]
    assert kde.collections and not kde.patches  # filled density, no bars

    both = HistogramPlot(
        params=HistogramPlotParams(value_column="n", mode="both", bins=5)
    ).run(df=_cat_df())["figure"].axes[0]
    assert both.patches and both.get_lines()  # bars + KDE curve


def test_histogram_colour_by_categorical_draws_one_group_per_value():
    ax = HistogramPlot(
        params=HistogramPlotParams(
            value_column="score", mode="histogram", color_by="team", multiple="stack"
        )
    ).run(df=_cat_df())["figure"].axes[0]
    assert ax.get_legend() is not None


def test_histogram_rejects_a_continuous_colour_by_column():
    import pytest

    with pytest.raises(ValueError, match="continuous"):
        HistogramPlot(
            params=HistogramPlotParams(value_column="score", color_by="n")
        ).run(df=_cat_df())


# -- heatmap ------------------------------------------------------


def test_heatmap_count_and_proportion_statistics():
    for stat in ("count", "row_percent", "column_percent"):
        fig = HeatmapPlot(
            params=HeatmapPlotParams(x_column="team", y_column="region", statistic=stat)
        ).run(df=_cat_df())["figure"]
        assert isinstance(fig, Figure)
        assert len(fig.axes) == 2  # heatmap + colourbar


def test_heatmap_aggregate_statistic_needs_a_value_column():
    import pytest

    with pytest.raises(ValueError, match="value column"):
        HeatmapPlot(
            params=HeatmapPlotParams(
                x_column="team", y_column="region", statistic="aggregate"
            )
        ).run(df=_cat_df())

    fig = HeatmapPlot(
        params=HeatmapPlotParams(
            x_column="team",
            y_column="region",
            statistic="aggregate",
            value_column="score",
            aggregate="mean",
        )
    ).run(df=_cat_df())["figure"]
    assert isinstance(fig, Figure)


def test_heatmap_association_puts_cramers_v_in_the_title():
    ax = HeatmapPlot(
        params=HeatmapPlotParams(
            x_column="team", y_column="region", statistic="association"
        )
    ).run(df=_cat_df())["figure"].axes[0]
    assert "Cram" in ax.get_title() and "V =" in ax.get_title()


# -- table_viewer ---------------------------------------------------------

from ruyso_app.nodes.viz import TableViewer, TableViewerParams  # noqa: E402


def test_table_viewer_renders_a_table_figure_with_rounding():
    df = pd.DataFrame({"name": ["a", "b"], "v": [0.123456, 9.87654], "n": [10, 20]})
    fig = TableViewer(params=TableViewerParams(decimals=2, title="T")).run(df=df)["figure"]
    assert isinstance(fig, Figure)
    cells = fig.axes[0].tables[0].get_celld()
    texts = {c.get_text().get_text() for c in cells.values()}
    assert "0.12" in texts and "9.88" in texts  # numeric rounding applied
    assert fig.axes[0].get_title() == "T"


def test_table_viewer_truncates_large_input_and_notes_it():
    import numpy as np

    big = pd.DataFrame(np.arange(60 * 20).reshape(60, 20))
    fig = TableViewer(params=TableViewerParams(max_rows=8, max_cols=4)).run(df=big)[
        "figure"
    ]
    note = " ".join(t.get_text() for t in fig.texts)
    assert "8 of 60 rows" in note and "4 of 20 columns" in note


# -- model-visualization plots -------------------------------------------

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from ruyso_app.nodes.models import (  # noqa: E402
    LinearRegressionFit,
    LinearRegressionFitParams,
    LogisticRegressionFit,
    LogisticRegressionFitParams,
    RandomForestFit,
    RandomForestFitParams,
    TrainTestSplit,
    TrainTestSplitParams,
)
from ruyso_app.nodes.viz import (  # noqa: E402
    CalibrationCurvePlot,
    CalibrationCurvePlotParams,
    ConfusionMatrixPlot,
    ConfusionMatrixPlotParams,
    DetCurvePlot,
    LearningCurvePlot,
    LearningCurvePlotParams,
    PrecisionRecallPlot,
    QQPlot,
    QQPlotParams,
    RocCurvePlot,
    _CurvePlotParams,
)


def _mv_data(kind="binary", n=200):
    rng = np.random.default_rng(1)
    X = pd.DataFrame(
        {"a": rng.normal(size=n), "b": rng.normal(size=n), "c": rng.normal(size=n)}
    )
    if kind == "binary":
        y = (X["a"] + X["b"] > 0).astype(int)
    elif kind == "multiclass":
        y = pd.cut(X["a"] + X["b"], bins=3, labels=["lo", "mid", "hi"]).astype(object)
    else:  # regression
        y = 2 * X["a"] - X["b"] + 0.2 * rng.normal(size=n)
    split = TrainTestSplit(
        params=TrainTestSplitParams(target_column="t", test_size=0.3, random_state=0)
    ).run(df=X.assign(t=y))
    return split


def _rf(split):
    return RandomForestFit(
        params=RandomForestFitParams(task="classifier", n_estimators=25)
    ).run(X_train=split["X_train"], y_train=split["y_train"])["model"]


def test_confusion_matrix_plot_binary_and_multiclass():
    for kind in ("binary", "multiclass"):
        split = _mv_data(kind)
        model = _rf(split)
        fig = ConfusionMatrixPlot(
            params=ConfusionMatrixPlotParams(normalize="true")
        ).run(model=model, X=split["X_test"], y=split["y_test"])["figure"]
        assert isinstance(fig, Figure)


def test_roc_pr_det_draw_one_curve_binary_and_one_per_class_multiclass():
    for node_cls in (RocCurvePlot, PrecisionRecallPlot, DetCurvePlot):
        b = _mv_data("binary")
        ax = node_cls(params=_CurvePlotParams()).run(
            model=_rf(b), X=b["X_test"], y=b["y_test"]
        )["figure"].axes[0]
        # at least the model's own curve is present
        assert len(ax.get_lines()) >= 1

        m = _mv_data("multiclass")
        ax_m = node_cls(params=_CurvePlotParams(colormap="Set2")).run(
            model=_rf(m), X=m["X_test"], y=m["y_test"]
        )["figure"].axes[0]
        assert len(ax_m.get_lines()) >= 3  # one per class


def test_roc_plot_rejects_a_regressor():
    r = _mv_data("regression")
    model = LinearRegressionFit(params=LinearRegressionFitParams()).run(
        X_train=r["X_train"], y_train=r["y_train"]
    )["model"]
    with pytest.raises(ValueError, match="classification model"):
        RocCurvePlot(params=_CurvePlotParams()).run(
            model=model, X=r["X_test"], y=r["y_test"]
        )


def test_calibration_curve_plot_binary_only():
    b = _mv_data("binary")
    model = LogisticRegressionFit(
        params=LogisticRegressionFitParams(max_iter=300)
    ).run(X_train=b["X_train"], y_train=b["y_train"])["model"]
    fig = CalibrationCurvePlot(params=CalibrationCurvePlotParams(n_bins=8)).run(
        model=model, X=b["X_test"], y=b["y_test"]
    )["figure"]
    assert isinstance(fig, Figure)

    m = _mv_data("multiclass")
    with pytest.raises(ValueError, match="binary"):
        CalibrationCurvePlot(params=CalibrationCurvePlotParams()).run(
            model=_rf(m), X=m["X_test"], y=m["y_test"]
        )


def test_learning_curve_plot_draws_train_and_test_lines():
    b = _mv_data("binary")
    ax = LearningCurvePlot(
        params=LearningCurvePlotParams(cv=3, n_points=4)
    ).run(model=_rf(b), X=b["X_train"], y=b["y_train"])["figure"].axes[0]
    assert len(ax.get_lines()) >= 2


def test_qq_plot_regression_only():
    r = _mv_data("regression")
    model = LinearRegressionFit(params=LinearRegressionFitParams()).run(
        X_train=r["X_train"], y_train=r["y_train"]
    )["model"]
    ax = QQPlot(params=QQPlotParams()).run(
        model=model, X=r["X_test"], y=r["y_test"]
    )["figure"].axes[0]
    assert ax.get_xlabel() == "Theoretical quantiles"
    assert len(ax.collections) == 1  # the residual scatter

    b = _mv_data("binary")
    with pytest.raises(ValueError, match="regression model"):
        QQPlot(params=QQPlotParams()).run(
            model=_rf(b), X=b["X_test"], y=b["y_test"]
        )
