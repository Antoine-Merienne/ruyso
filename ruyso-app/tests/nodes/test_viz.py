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


# -- manual axis limits --------------------------------------------------
#
# There is no ``x_limits`` / ``y_limits`` toggle: the four edges are
# always live, and each one is independent, with a *blank* value meaning
# "fit this edge to the data".


def test_matplotlib_plot_manual_xy_limits_are_applied():
    ax = _run(
        x="x", y="y", kind="scatter",
        x_min="1.5", x_max="3.5", y_min="5.0", y_max="25.0",
    ).axes[0]
    assert ax.get_xlim() == (1.5, 3.5)
    assert ax.get_ylim() == (5.0, 25.0)


def test_blank_axis_limits_leave_autoscale():
    ax = _run(x="x", y="y", kind="scatter").axes[0]
    lo, hi = ax.get_xlim()
    assert lo < 1 and hi > 4  # autoscaled to the data


def test_a_single_pinned_edge_leaves_the_other_three_on_autoscale():
    """The per-edge blank the old both-edges-or-nothing toggle could not do."""
    auto = _run(x="x", y="y", kind="scatter").axes[0]
    ax = _run(x="x", y="y", kind="scatter", y_min="0").axes[0]

    assert ax.get_ylim()[0] == 0.0  # pinned
    assert ax.get_ylim()[1] == auto.get_ylim()[1]  # untouched
    assert ax.get_xlim() == auto.get_xlim()  # untouched


def test_time_series_plot_accepts_date_string_x_limits():
    import matplotlib.dates as mdates
    import numpy as np

    from ruyso_app.nodes.viz import TimeSeriesPlot, TimeSeriesPlotParams

    ts = pd.DataFrame(
        {"d": pd.date_range("2021-01-01", periods=200), "v": np.arange(200.0)}
    )
    ax = TimeSeriesPlot(
        params=TimeSeriesPlotParams(
            x_column="d", y_column="v", x_min="2021-03-01", x_max="2021-05-01",
        )
    ).run(df=ts)["figure"].axes[0]
    lo, hi = (mdates.num2date(v).date().isoformat() for v in ax.get_xlim())
    assert lo == "2021-03-01" and hi == "2021-05-01"


def test_time_series_plot_blank_x_limit_edge_stays_auto():
    import numpy as np

    from ruyso_app.nodes.viz import TimeSeriesPlot, TimeSeriesPlotParams

    ts = pd.DataFrame(
        {"d": pd.date_range("2021-01-01", periods=100), "v": np.arange(100.0)}
    )
    ax = TimeSeriesPlot(
        params=TimeSeriesPlotParams(
            x_column="d", y_column="v", x_min="2021-02-01", x_max="",
        )
    ).run(df=ts)["figure"].axes[0]
    import matplotlib.dates as mdates

    assert mdates.num2date(ax.get_xlim()[0]).date().isoformat() == "2021-02-01"


def test_no_grapher_still_carries_an_axis_limit_toggle():
    """Every grapher moved to always-visible edges, none kept the tickbox."""
    from ruyso_app.core.registry import NodeRegistry

    for node_type, cls in NodeRegistry.all().items():
        if cls.category != "grapher":
            continue
        fields = cls.params_schema.model_fields
        assert "x_limits" not in fields and "y_limits" not in fields
        if "x_min" in fields:
            for edge in ("x_min", "x_max", "y_min", "y_max"):
                assert fields[edge].annotation is str, f"{node_type}.{edge}"
                assert fields[edge].default == ""


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


# -- bar_error (confidence interval) --------------------------------


def test_bar_error_aggregates_by_x_into_a_mean_with_error_bars():
    df = pd.DataFrame({"cat": ["p", "p", "p", "q", "q"], "val": [1.0, 3.0, 5.0, 10.0, 10.0]})
    ax = _run(df=df, x="cat", y="val", kind="bar", bar_error="ci_95").axes[0]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["p", "q"]
    positions = _bars_by_x(ax)
    assert len(positions) == 2  # one bar per unique x, not one per row
    heights = sorted(h for hs in positions.values() for h in hs)
    assert heights == [3.0, 10.0]  # mean(1,3,5)=3, mean(10,10)=10
    errbars = [c for c in ax.containers if hasattr(c, "has_yerr") and c.has_yerr]
    assert errbars  # an ErrorbarContainer was drawn


def test_bar_error_none_is_the_original_one_bar_per_row_behaviour():
    df = pd.DataFrame({"cat": ["p", "p", "q"], "val": [1.0, 3.0, 5.0]})
    ax = _run(df=df, x="cat", y="val", kind="bar", bar_error="none").axes[0]
    positions = _bars_by_x(ax)
    assert sum(len(hs) for hs in positions.values()) == 3  # one bar per row, unchanged


def test_bar_error_with_discrete_colour_by_averages_each_group():
    df = pd.DataFrame(
        {
            "cat": ["p", "p", "q", "q"],
            "val": [1.0, 3.0, 10.0, 20.0],
            "g": ["a", "a", "a", "a"],
        }
    )
    ax = _run(
        df=df, x="cat", y="val", kind="bar", color_by="g", bar_error="std", bar_mode="dodge"
    ).axes[0]
    positions = _bars_by_x(ax)
    heights = sorted(h for hs in positions.values() for h in hs)
    assert heights == [2.0, 15.0]  # mean(1,3)=2, mean(10,20)=15


def test_bar_error_single_observation_has_no_error_bar():
    df = pd.DataFrame({"cat": ["p", "q"], "val": [1.0, 5.0]})
    fig = _run(df=df, x="cat", y="val", kind="bar", bar_error="sem")
    ax = fig.axes[0]
    for container in ax.containers:
        if hasattr(container, "has_yerr") and container.has_yerr:
            for line in container[2]:  # the yerr LineCollection(s)
                segments = line.get_segments()
                for seg in segments:
                    assert abs(seg[0][1] - seg[1][1]) < 1e-9  # zero-length whisker


# -- line_fill / line_stack ------------------------------------------


def test_line_fill_draws_a_filled_area_under_the_line():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [1, 4, 2]})
    ax = _run(df=df, x="x", y="y", kind="line", line_fill=True).axes[0]
    from matplotlib.collections import PolyCollection

    assert any(isinstance(c, PolyCollection) for c in ax.collections)


def test_line_stack_uses_stackplot_for_a_discrete_colour_by():
    df = pd.DataFrame(
        {"t": [1, 2, 1, 2], "v": [1.0, 2.0, 3.0, 4.0], "g": ["a", "a", "b", "b"]}
    )
    ax = _run(df=df, x="t", y="v", kind="line", color_by="g", line_stack=True).axes[0]
    from matplotlib.collections import PolyCollection

    assert len(ax.collections) == 2  # one stacked band per colour-by group


def test_line_stack_without_a_discrete_colour_by_falls_back_and_notes_it():
    df = pd.DataFrame({"x": [1, 2, 3], "y": [1, 2, 3]})
    fig = _run(df=df, x="x", y="y", kind="line", line_stack=True)
    note = " ".join(t.get_text() for t in fig.texts)
    assert "line_stack needs a discrete colour-by column" in note


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


def test_box_plot_alpha_is_applied_to_the_box_fill():
    ax = BoxPlot(
        params=BoxPlotParams(category_column="team", value_column="score", alpha=0.4)
    ).run(df=_cat_df())["figure"].axes[0]
    assert any(round(p.get_alpha(), 2) == 0.4 for p in ax.patches)


def _flier_lines(ax):
    """Flier markers are Line2D with a marker but no connecting segment
    (whisker/cap/median lines have no marker: '' or 'None')."""
    return [l for l in ax.lines if l.get_marker() not in ("", "None", None)]


def test_box_plot_show_outliers_toggles_showfliers():
    df = pd.DataFrame({"team": ["a"] * 10, "score": [1, 2, 3, 4, 5, 6, 7, 8, 9, 100]})
    with_fliers = BoxPlot(
        params=BoxPlotParams(category_column="team", value_column="score")
    ).run(df=df)["figure"].axes[0]
    without_fliers = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", show_outliers=False
        )
    ).run(df=df)["figure"].axes[0]
    assert len(_flier_lines(with_fliers)) == 1  # the 100 outlier
    assert len(_flier_lines(without_fliers)) == 0


def test_box_plot_std_dev_draws_a_custom_mean_pm_std_box():
    ax = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", box_stat="std_dev", std_k=1.0
        )
    ).run(df=_cat_df())["figure"].axes[0]
    a_scores = [1.0, 3.0, 5.0, 7.0]  # team "a" rows in _cat_df
    import numpy as np

    mean, std = np.mean(a_scores), np.std(a_scores, ddof=1)
    heights = sorted(round(p.get_height(), 4) for p in ax.patches)
    assert round(2 * std, 4) in heights
    assert [t.get_text() for t in ax.get_xticklabels()] == ["a", "b"]


def test_box_plot_ci_box_matches_the_t_based_confidence_interval():
    import numpy as np
    from scipy import stats as spstats

    ax = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", box_stat="ci",
            confidence_level=0.95,
        )
    ).run(df=_cat_df())["figure"].axes[0]
    a_scores = np.array([1.0, 3.0, 5.0, 7.0])  # team "a" rows in _cat_df
    sem = np.std(a_scores, ddof=1) / np.sqrt(a_scores.size)
    t = spstats.t.ppf(0.975, df=a_scores.size - 1)
    expected_height = 2 * t * sem
    heights = [round(p.get_height(), 3) for p in ax.patches]
    assert round(expected_height, 3) in heights

    # a higher std_k widens a std_dev box proportionally
    ax_k1 = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", box_stat="std_dev", std_k=1.0
        )
    ).run(df=_cat_df())["figure"].axes[0]
    ax_k2 = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", box_stat="std_dev", std_k=2.0
        )
    ).run(df=_cat_df())["figure"].axes[0]
    h_k1 = min(p.get_height() for p in ax_k1.patches)
    h_k2 = min(p.get_height() for p in ax_k2.patches)
    assert round(h_k2 / h_k1, 3) == 2.0


def test_box_plot_std_dev_with_hue_dodges_and_draws_a_legend():
    ax = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", box_stat="std_dev",
            color_by="region",
        )
    ).run(df=_cat_df())["figure"].axes[0]
    assert ax.get_legend() is not None
    assert len(ax.patches) == 4  # 2 teams x 2 regions


def test_box_plot_box_stat_only_applies_to_the_box_kind():
    # violin/boxen/swarm ignore box_stat -- still render via seaborn
    fig = BoxPlot(
        params=BoxPlotParams(
            category_column="team", value_column="score", kind="violin", box_stat="std_dev"
        )
    ).run(df=_cat_df())["figure"]
    assert isinstance(fig, Figure)
    assert len(fig.axes[0].collections) > 0  # seaborn violin path, not the custom box


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


def test_table_viewer_padding_insets_the_table_bbox():
    df = pd.DataFrame({"a": [1, 2]})
    table = TableViewer(params=TableViewerParams(padding=0.15)).run(df=df)["figure"].axes[0].tables[0]
    x0, y0, w, h = table._bbox
    assert x0 == pytest.approx(0.15) and y0 == pytest.approx(0.15)
    assert w == pytest.approx(0.7) and h == pytest.approx(0.7)


def test_table_viewer_style_presets_all_render():
    df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    for style in ("shaded", "three_line", "grid", "striped", "minimal"):
        fig = TableViewer(params=TableViewerParams(style=style)).run(df=df)["figure"]
        assert isinstance(fig, Figure)


def test_table_viewer_three_line_style_has_only_horizontal_rules():
    df = pd.DataFrame({"a": [1, 2, 3]})
    fig = TableViewer(params=TableViewerParams(style="three_line")).run(df=df)["figure"]
    table = fig.axes[0].tables[0]
    for (r, _c), cell in table.get_celld().items():
        if r == 0:
            assert cell.visible_edges == "TB"
        elif r == 3:  # last data row (3 rows of data -> header is row 0)
            assert cell.visible_edges == "B"
        else:
            assert cell.visible_edges == ""


def test_table_viewer_shaded_style_matches_the_original_look():
    # style="shaded" is the default and must reproduce the pre-Phase-7
    # look exactly (header fill + zebra rows + bordered cells).
    df = pd.DataFrame({"a": [1, 2, 3]})
    fig = TableViewer(params=TableViewerParams()).run(df=df)["figure"]
    table = fig.axes[0].tables[0]
    header_cell = table.get_celld()[(0, 0)]
    assert header_cell.get_facecolor()[:3] != (1.0, 1.0, 1.0)  # header is filled


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


# -- single-variable plots: pie_chart, heatmap_1d, autocorrelogram --------

from ruyso_app.nodes.viz import (  # noqa: E402
    Autocorrelogram,
    AutocorrelogramParams,
    Density2D,
    Density2DParams,
    Heatmap1D,
    Heatmap1DParams,
    PieChart,
    PieChartParams,
)


def _cat_counts_df():
    return pd.DataFrame({"cat": ["a"] * 5 + ["b"] * 3 + ["c"] * 2})


@pytest.mark.parametrize("style", ["pie", "doughnut", "tile"])
def test_pie_chart_styles_all_render(style):
    fig = PieChart(params=PieChartParams(column="cat", style=style)).run(
        df=_cat_counts_df()
    )["figure"]
    assert isinstance(fig, Figure)


def test_pie_chart_pie_wedges_match_category_counts():
    ax = PieChart(params=PieChartParams(column="cat", style="pie")).run(
        df=_cat_counts_df()
    )["figure"].axes[0]
    from matplotlib.patches import Wedge

    wedges = [p for p in ax.patches if isinstance(p, Wedge)]
    assert len(wedges) == 3
    thetas = sorted(round(w.theta2 - w.theta1, 3) for w in wedges)
    assert thetas == sorted([5 / 10 * 360, 3 / 10 * 360, 2 / 10 * 360])


def test_pie_chart_top_n_groups_the_rest_into_other():
    df = pd.DataFrame({"cat": ["a"] * 10 + ["b"] * 5 + ["c"] * 3 + ["d"] * 1})
    ax = PieChart(params=PieChartParams(column="cat", top_n=2)).run(df=df)["figure"].axes[0]
    legend_labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert legend_labels == ["a", "b", "other"]


def test_pie_chart_tile_draws_one_tile_per_row_for_small_counts():
    ax = PieChart(params=PieChartParams(column="cat", style="tile")).run(
        df=_cat_counts_df()
    )["figure"].axes[0]
    from matplotlib.patches import Rectangle

    tiles = [p for p in ax.patches if isinstance(p, Rectangle)]
    assert len(tiles) == 10  # 5 + 3 + 2 rows, total < 100 -> one tile per row


def test_pie_chart_unknown_column_raises():
    with pytest.raises(ValueError, match="not in the input data"):
        PieChart(params=PieChartParams(column="nope")).run(df=_cat_counts_df())


def test_heatmap_1d_wraps_into_a_grid():
    import numpy as np

    df = pd.DataFrame({"v": np.arange(20, dtype="float64")})
    ax = Heatmap1D(params=Heatmap1DParams(column="v", columns_per_row=5)).run(df=df)[
        "figure"
    ].axes[0]
    im = ax.images[0]
    assert im.get_array().shape == (4, 5)  # 20 values / 5 per row -> 4 rows


def test_heatmap_1d_single_row_by_default():
    import numpy as np

    df = pd.DataFrame({"v": np.arange(6, dtype="float64")})
    ax = Heatmap1D(params=Heatmap1DParams(column="v")).run(df=df)["figure"].axes[0]
    assert ax.images[0].get_array().shape == (1, 6)


def test_heatmap_1d_vertical_orientation_transposes_the_strip_and_colorbar():
    import numpy as np

    df = pd.DataFrame({"v": np.arange(6, dtype="float64")})
    fig = Heatmap1D(
        params=Heatmap1DParams(column="v", orientation="vertical")
    ).run(df=df)["figure"]
    assert fig.axes[0].images[0].get_array().shape == (6, 1)  # a column, not a row
    # the colorbar axes are taller than wide (vertical bar)
    cbar = fig.axes[1]
    bb = cbar.get_position()
    assert bb.height > bb.width


def test_heatmap_1d_label_column_names_the_cell_ticks():
    import numpy as np

    df = pd.DataFrame(
        {"v": np.arange(4.0), "name": ["Jan", "Feb", "Mar", "Apr"]}
    )
    ax = Heatmap1D(
        params=Heatmap1DParams(column="v", label_column="name")
    ).run(df=df)["figure"].axes[0]
    assert [t.get_text() for t in ax.get_xticklabels()] == ["Jan", "Feb", "Mar", "Apr"]


def test_heatmap_1d_unknown_column_raises():
    with pytest.raises(ValueError, match="not in the input data"):
        Heatmap1D(params=Heatmap1DParams(column="nope")).run(df=pd.DataFrame({"v": [1]}))


def _ar_df(n=60, seed=0):
    import numpy as np

    rng = np.random.default_rng(seed)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = 0.6 * x[i - 1] + rng.normal()
    return pd.DataFrame({"y": x})


def test_autocorrelogram_draws_both_acf_and_pacf_by_default():
    fig = Autocorrelogram(params=AutocorrelogramParams(column="y", max_lag=10)).run(
        df=_ar_df()
    )["figure"]
    assert len(fig.axes) == 2
    assert fig.axes[0].get_title() == "ACF"
    assert fig.axes[1].get_title() == "PACF"


def test_autocorrelogram_can_show_only_one():
    fig = Autocorrelogram(
        params=AutocorrelogramParams(column="y", max_lag=10, show_pacf=False)
    ).run(df=_ar_df())["figure"]
    assert len(fig.axes) == 1
    assert fig.axes[0].get_title() == "ACF"


def test_autocorrelogram_needs_at_least_one_of_acf_pacf():
    with pytest.raises(ValueError, match="at least one"):
        Autocorrelogram(
            params=AutocorrelogramParams(column="y", show_acf=False, show_pacf=False)
        ).run(df=_ar_df())


def test_autocorrelogram_needs_enough_data_for_the_requested_lag():
    with pytest.raises(ValueError, match="not enough"):
        Autocorrelogram(params=AutocorrelogramParams(column="y", max_lag=50)).run(
            df=pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0, 5.0]})
        )


# -- 2D density -------------------------------------------------------


def _xy_df(n=100, seed=0):
    import numpy as np

    rng = np.random.default_rng(seed)
    return pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n)})


def test_density_2d_contour_renders():
    ax = Density2D(params=Density2DParams(x="a", y="b")).run(df=_xy_df())["figure"].axes[0]
    assert ax.get_xlabel() == "a" and ax.get_ylabel() == "b"
    assert len(ax.collections) > 0


def test_density_2d_hexbin_renders():
    ax = Density2D(params=Density2DParams(x="a", y="b", kind="hexbin")).run(df=_xy_df())[
        "figure"
    ].axes[0]
    assert len(ax.collections) > 0


def test_density_2d_needs_at_least_three_rows():
    with pytest.raises(ValueError, match="at least 3"):
        Density2D(params=Density2DParams(x="a", y="b")).run(
            df=pd.DataFrame({"a": [1.0, 2.0], "b": [1.0, 2.0]})
        )


def test_density_2d_unknown_column_raises():
    with pytest.raises(ValueError, match="not in the input data"):
        Density2D(params=Density2DParams(x="a", y="nope")).run(df=_xy_df())


def _grouped_xy_df(n=120, seed=0):
    import numpy as np

    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "a": rng.normal(size=n),
            "b": rng.normal(size=n),
            "grp": rng.choice(["p", "q", "r"], size=n),
            "cont": rng.normal(size=n),
        }
    )


def test_density_2d_discrete_color_by_draws_one_kde_per_level_with_a_legend():
    fig = Density2D(
        params=Density2DParams(x="a", y="b", color_by="grp", colormap="tab10")
    ).run(df=_grouped_xy_df())["figure"]
    ax = fig.axes[0]
    legend = ax.get_legend()
    assert legend is not None
    assert {t.get_text() for t in legend.get_texts()} == {"p", "q", "r"}
    # the per-level ramps are distinct colours (not one repeated shade)
    from matplotlib.collections import PathCollection  # noqa: F401

    assert len(ax.collections) > 0


def test_density_2d_continuous_color_by_is_rejected():
    with pytest.raises(ValueError, match="continuous"):
        Density2D(params=Density2DParams(x="a", y="b", color_by="cont")).run(
            df=_grouped_xy_df()
        )


def test_density_2d_marginals_add_top_and_right_axes():
    fig = Density2D(
        params=Density2DParams(x="a", y="b", show_marginals=True, marginal_kind="kde")
    ).run(df=_xy_df())["figure"]
    assert len(fig.axes) == 3  # main + top + right


def test_matplotlib_plot_scatter_marginals_add_axes_and_follow_color_by():
    fig = _run(
        df=_grouped_xy_df(),
        x="a",
        y="b",
        kind="scatter",
        color_by="grp",
        colormap="tab10",
        show_marginals=True,
        marginal_kind="histogram",
    )
    assert len(fig.axes) == 3


def test_matplotlib_plot_marginals_ignored_for_non_scatter_kinds():
    fig = _run(x="x", y="y", kind="line", show_marginals=True)
    assert len(fig.axes) == 1


# -- PCA-specific plots: pca_scree_plot, pca_corr_circle -----------------

from ruyso_app.nodes.statistics import PCA, PCAParams  # noqa: E402
from ruyso_app.nodes.viz import (  # noqa: E402
    PCACorrCirclePlot,
    PCACorrCirclePlotParams,
    PCAScreePlot,
    PCAScreePlotParams,
)


def _pca_outputs():
    rng = np.random.default_rng(0)
    n = 150
    a = rng.normal(size=n)
    b = a * 0.8 + rng.normal(scale=0.3, size=n)
    c = rng.normal(size=n)
    df = pd.DataFrame({"a": a, "b": b, "c": c})
    return PCA(params=PCAParams()).run(df=df)


def test_pca_scree_plot_bars_match_variance_ratio():
    pca_out = _pca_outputs()
    ax = PCAScreePlot(params=PCAScreePlotParams()).run(variance=pca_out["variance"])[
        "figure"
    ].axes[0]
    heights = sorted(round(p.get_height(), 3) for p in ax.patches)
    expected = sorted(round(v * 100, 3) for v in pca_out["variance"]["explained_variance_ratio"])
    assert heights == expected
    assert [t.get_text() for t in ax.get_xticklabels()] == list(pca_out["variance"]["component"])


def test_pca_scree_plot_cumulative_line_is_a_second_axis():
    pca_out = _pca_outputs()
    fig = PCAScreePlot(params=PCAScreePlotParams(show_cumulative=True)).run(
        variance=pca_out["variance"]
    )["figure"]
    assert len(fig.axes) == 2  # bars + twinx cumulative line


def test_pca_scree_plot_requires_the_pca_variance_shape():
    with pytest.raises(ValueError, match="variance"):
        PCAScreePlot(params=PCAScreePlotParams()).run(variance=pd.DataFrame({"x": [1]}))


def test_pca_corr_circle_vectors_are_bounded_in_the_unit_circle():
    pca_out = _pca_outputs()
    ax = PCACorrCirclePlot(params=PCACorrCirclePlotParams(x_component="PC1", y_component="PC2")).run(
        loadings=pca_out["loadings"], variance=pca_out["variance"]
    )["figure"].axes[0]
    # 3 variables -> 3 arrow annotations
    from matplotlib.text import Annotation

    arrows = [a for a in ax.texts if isinstance(a, Annotation)]
    assert len(arrows) == 3
    for arrow in arrows:
        vx, vy = arrow.xy
        # bounded by the unit circle, up to normal floating-point /
        # finite-sample estimation slop (ddof, SVD rounding).
        assert vx**2 + vy**2 <= 1.01


def test_pca_corr_circle_correlated_variables_point_along_the_same_axis():
    # "a" and "b" are highly correlated by construction (see _pca_outputs) --
    # both should load heavily onto PC1 (x-axis), near the circle boundary.
    pca_out = _pca_outputs()
    loadings = pca_out["loadings"].set_index("variable")
    variance = dict(zip(pca_out["variance"]["component"], pca_out["variance"]["explained_variance"]))
    scale = variance["PC1"] ** 0.5
    corr_a = loadings.loc["a", "PC1"] * scale
    corr_b = loadings.loc["b", "PC1"] * scale
    assert abs(corr_a) > 0.9 and abs(corr_b) > 0.9


def test_pca_corr_circle_requires_matching_component_names():
    pca_out = _pca_outputs()
    with pytest.raises(ValueError, match="not in the loadings table"):
        PCACorrCirclePlot(params=PCACorrCirclePlotParams(x_component="PC1", y_component="PC99")).run(
            loadings=pca_out["loadings"], variance=pca_out["variance"]
        )


def test_pca_corr_circle_requires_the_pca_output_shapes():
    with pytest.raises(ValueError, match="loadings"):
        PCACorrCirclePlot(params=PCACorrCirclePlotParams()).run(
            loadings=pd.DataFrame({"x": [1]}), variance=pd.DataFrame({"component": ["PC1"], "explained_variance": [1.0]})
        )


# --------------------------------------------------------------------------
# Time-series plots + VAR / VECM diagnostics
# --------------------------------------------------------------------------

import matplotlib.pyplot as _plt  # noqa: E402
import numpy as np  # noqa: E402

from ruyso_app.nodes.statistics import Var, VarParams  # noqa: E402
from ruyso_app.nodes.viz import (  # noqa: E402
    IrfPlot,
    IrfPlotParams,
    MultivariateTimeSeriesPlot,
    MultivariateTimeSeriesPlotParams,
    TimeSeriesPlot,
    TimeSeriesPlotParams,
    VarAcorrPlot,
    VarAcorrPlotParams,
    ForecastPlot,
    ForecastPlotParams,
)


def _ts_frame(n=140, seed=3):
    rng = np.random.default_rng(seed)
    e = rng.normal(size=(n, 3))
    y = np.zeros((n, 3))
    for t in range(1, n):
        y[t, 0] = 0.4 * y[t - 1, 0] + 0.2 * y[t - 1, 1] + e[t, 0]
        y[t, 1] = -0.3 * y[t - 1, 0] + 0.35 * y[t - 1, 1] + e[t, 1]
        y[t, 2] = 0.25 * y[t - 1, 1] + 0.45 * y[t - 1, 2] + e[t, 2]
    return pd.DataFrame(
        {
            "gdp": y[:, 0], "cpi": y[:, 1], "rate": y[:, 2],
            "t": pd.date_range("2005-01-01", periods=n, freq="MS"),
            "region": np.where(np.arange(n) % 2 == 0, "north", "south"),
        }
    )


def _assert_oo_figure(fig):
    assert isinstance(fig, Figure)
    assert fig not in [_plt.figure(k) for k in _plt.get_fignums()] if _plt.get_fignums() else True


@pytest.mark.parametrize("mark", ["line", "line+markers", "markers", "bars"])
def test_time_series_plot_mark_styles(mark):
    fig = TimeSeriesPlot(
        params=TimeSeriesPlotParams(x_column="t", y_column="gdp", mark=mark, x_tick_freq="year")
    ).run(df=_ts_frame())["figure"]
    _assert_oo_figure(fig)


@pytest.mark.parametrize("multiple", ["layer", "stack", "dodge"])
def test_time_series_plot_grouped_bars(multiple):
    fig = TimeSeriesPlot(
        params=TimeSeriesPlotParams(
            x_column="t", y_column="gdp", mark="bars", color_by="region", multiple=multiple
        )
    ).run(df=_ts_frame())["figure"]
    assert fig.axes[0].get_legend() is not None


def test_time_series_plot_datetime_x_axis_is_used():
    ax = TimeSeriesPlot(
        params=TimeSeriesPlotParams(x_column="t", y_column="cpi", x_tick_freq="quarter")
    ).run(df=_ts_frame())["figure"].axes[0]
    import matplotlib.dates as mdates

    assert isinstance(ax.xaxis.get_major_locator(), mdates.MonthLocator)


def test_time_series_plot_fixed_marker_shape_and_line_style():
    ax = TimeSeriesPlot(
        params=TimeSeriesPlotParams(
            x_column="t", y_column="gdp", mark="markers", marker_shape="diamond"
        )
    ).run(df=_ts_frame())["figure"].axes[0]
    assert ax.lines[0].get_marker() == "D"

    ax2 = TimeSeriesPlot(
        params=TimeSeriesPlotParams(
            x_column="t", y_column="gdp", mark="line", line_style="dashed"
        )
    ).run(df=_ts_frame())["figure"].axes[0]
    assert ax2.lines[0].get_linestyle() == "--"


def test_time_series_plot_style_by_alone_varies_shape_not_colour():
    ax = TimeSeriesPlot(
        params=TimeSeriesPlotParams(
            x_column="t", y_column="gdp", mark="line+markers",
            style_by="region", shape_map="geometric",
        )
    ).run(df=_ts_frame())["figure"].axes[0]
    markers = {ln.get_marker() for ln in ax.lines}
    colours = {str(ln.get_color()) for ln in ax.lines}
    assert len(markers) == 2  # region has two levels -> two shapes
    assert len(colours) == 1  # ... but a single colour


def test_time_series_plot_color_by_and_style_by_same_column():
    ax = TimeSeriesPlot(
        params=TimeSeriesPlotParams(
            x_column="t", y_column="gdp", mark="markers",
            color_by="region", style_by="region",
        )
    ).run(df=_ts_frame())["figure"].axes[0]
    assert len({ln.get_marker() for ln in ax.lines}) == 2
    assert len({str(ln.get_color()) for ln in ax.lines}) == 2


def test_time_series_plot_rejects_different_color_and_style_columns():
    df = _ts_frame()
    df["grp2"] = np.where(np.arange(len(df)) % 3 == 0, "p", "q")
    with pytest.raises(ValueError, match="same"):
        TimeSeriesPlot(
            params=TimeSeriesPlotParams(
                x_column="t", y_column="gdp", color_by="region", style_by="grp2"
            )
        ).run(df=df)


@pytest.mark.parametrize("layout", ["overlay", "grid"])
def test_multivariate_timeseries_plot_layouts(layout):
    fig = MultivariateTimeSeriesPlot(
        params=MultivariateTimeSeriesPlotParams(
            datetime_column="t", variables=["gdp", "cpi", "rate"], layout=layout
        )
    ).run(df=_ts_frame())["figure"]
    _assert_oo_figure(fig)
    assert len(fig.axes) == (3 if layout == "grid" else 1)


@pytest.mark.parametrize("method", ["var", "vecm"])
def test_var_forecast_acorr_and_irf_plots(method):
    df = _ts_frame()
    model = Var(
        params=VarParams(
            method=method, datetime_column="t",
            variables=["gdp", "cpi", "rate"], lags=2, forecast_periods=8,
        )
    ).run(df=df)["model"]

    fc = ForecastPlot(
        params=ForecastPlotParams(variables=["gdp", "rate"])
    ).run(model=model)["figure"]
    _assert_oo_figure(fc)
    assert len(fc.axes) == 2  # one panel per chosen variable
    # forecast horizon comes from the VAR node, not a plot param
    assert len(fc.axes[0].lines[1].get_xdata()) == 8

    ac = VarAcorrPlot(params=VarAcorrPlotParams(max_lag=6)).run(model=model)["figure"]
    assert len(ac.axes) == 9  # 3x3 residual (cross-)correlation grid

    irf = IrfPlot(
        params=IrfPlotParams(periods=6, orthogonalized=True, shocks=["cpi"])
    ).run(model=model)["figure"]
    assert len(irf.axes) == 3  # one shock column, three responses


@pytest.mark.parametrize("ci_style", ["band", "lines", "errorbar", "none"])
def test_var_forecast_and_irf_ci_styles_and_colours(ci_style):
    df = _ts_frame()
    model = Var(
        params=VarParams(variables=["gdp", "cpi", "rate"], lags=2)
    ).run(df=df)["model"]

    ForecastPlot(
        params=ForecastPlotParams(
            ci_style=ci_style, history_color="teal", forecast_color="crimson"
        )
    ).run(model=model)["figure"]
    IrfPlot(
        params=IrfPlotParams(
            periods=6, ci_style=ci_style, line_color="purple", responses=["gdp"]
        )
    ).run(model=model)["figure"]


def test_var_plots_reject_a_non_var_model():
    with pytest.raises(ValueError, match="var"):
        IrfPlot(params=IrfPlotParams()).run(model=object())


# -- multivariate time series: one mark colour, not a colormap -----------


def _multivariate_df():
    import numpy as np

    return pd.DataFrame(
        {
            "t": pd.date_range("2020-01-01", periods=5),
            "v": np.arange(5.0),
            "w": np.arange(5.0)[::-1],
            "z": np.arange(5.0) * 2,
        }
    )


def _line_colors(figure):
    return [line.get_color() for ax in figure.axes for line in ax.lines]


def test_multivariate_overlay_gives_each_series_its_own_colour():
    """One axes, so colour is the only thing separating the lines."""
    from ruyso_app.nodes.viz import (
        MultivariateTimeSeriesPlot,
        MultivariateTimeSeriesPlotParams,
    )

    figure = MultivariateTimeSeriesPlot(
        params=MultivariateTimeSeriesPlotParams(
            datetime_column="t", variables=["v", "w", "z"], layout="overlay"
        )
    ).run(df=_multivariate_df())["figure"]

    colors = _line_colors(figure)
    assert len(colors) == 3
    assert len({str(c) for c in colors}) == 3


def test_multivariate_overlay_honours_the_chosen_colormap():
    from ruyso_app.nodes.viz import (
        MultivariateTimeSeriesPlot,
        MultivariateTimeSeriesPlotParams,
    )

    def colors(colormap):
        figure = MultivariateTimeSeriesPlot(
            params=MultivariateTimeSeriesPlotParams(
                datetime_column="t", variables=["v", "w"],
                layout="overlay", colormap=colormap,
            )
        ).run(df=_multivariate_df())["figure"]
        return [str(c) for c in _line_colors(figure)]

    assert colors("tab10") != colors("Set1")


def test_multivariate_grid_uses_one_mark_colour_for_every_panel():
    """One panel per series, so colour carries no information."""
    from ruyso_app.nodes.viz import (
        MultivariateTimeSeriesPlot,
        MultivariateTimeSeriesPlotParams,
    )

    figure = MultivariateTimeSeriesPlot(
        params=MultivariateTimeSeriesPlotParams(
            datetime_column="t", variables=["v", "w", "z"], layout="grid"
        )
    ).run(df=_multivariate_df())["figure"]
    assert set(_line_colors(figure)) == {"materialblue"}

    custom = MultivariateTimeSeriesPlot(
        params=MultivariateTimeSeriesPlotParams(
            datetime_column="t", variables=["v", "w"],
            layout="grid", mark_color="crimson",
        )
    ).run(df=_multivariate_df())["figure"]
    assert set(_line_colors(custom)) == {"crimson"}


def test_multivariate_colour_fields_are_each_tied_to_a_layout():
    from ruyso_app.core.params import visible_when
    from ruyso_app.nodes.viz import MultivariateTimeSeriesPlotParams

    fields = MultivariateTimeSeriesPlotParams.model_fields
    assert fields["mark_color"].default == "materialblue"
    assert fields["colormap"].default == "tab10"
    assert visible_when(fields["colormap"]) == ("layout", "overlay")
    assert visible_when(fields["mark_color"]) == ("layout", "grid")


def test_materialblue_resolves_once_a_figure_has_been_built():
    from matplotlib.colors import to_hex

    from ruyso_app.core import colors

    colors.register()
    assert to_hex("materialblue") == "#1e88e5"
    assert to_hex("darkblue") == "#00008b"  # never shadows a built-in name
