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


def test_box_plot_draws_box_and_violin_kinds():
    for kind in ("box", "violin"):
        fig = BoxPlot(
            params=BoxPlotParams(category_column="team", value_column="score", kind=kind)
        ).run(df=_cat_df())["figure"]
        assert isinstance(fig, Figure)


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
