"""
Visualization nodes: turn data into a matplotlib Figure object that
downstream nodes (or the UI canvas) can display or export.

The nodes stay free of any UI-toolkit dependency: they import only
matplotlib (headless "Agg" backend) and seaborn, and return the Figure
as an output value for the caller to render or save.
"""

from typing import Any, Literal

from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    color_field,
    column_field,
    reactive_choice_field,
    visible_field,
)
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

#: Base matplotlib style, applied per-figure via a local context so it
#: never leaks into other nodes or the host process.
_BASE_STYLE = "seaborn-v0_8-whitegrid"

#: Default single colour for dots / lines / bars / boxes.
_DEFAULT_COLOR = "darkblue"

#: Suggested colours offered in the colour-picker dropdown (any
#: matplotlib colour string is still accepted).
_COMMON_COLORS = [
    "darkblue", "steelblue", "royalblue", "black", "dimgray",
    "crimson", "seagreen", "darkorange", "purple", "teal",
]

#: Continuous colormaps offered by the heatmap node.
_SEQUENTIAL_COLORMAPS = [
    "viridis", "plasma", "cividis", "magma", "coolwarm", "Spectral", "Blues", "Greens",
]

_LEGEND_LOCATIONS = Literal[
    "best", "upper right", "upper left", "lower right", "lower left",
    "center", "outside right",
]


def _fig_size(p: Any) -> tuple[float, float]:
    return (max(float(p.fig_width), 1.0), max(float(p.fig_height), 1.0))


def _place_legend(
    ax: Any, p: Any, title: str, handles: list | None = None, labels: list | None = None
) -> None:
    """(Re)draw ``ax``'s legend at the params' location in a translucent box.

    With no ``handles`` the currently-labelled artists are used (this is
    how a seaborn-drawn legend is restyled); an empty set removes any
    legend instead.
    """
    if handles is None:
        handles, labels = ax.get_legend_handles_labels()
    if not handles:
        # seaborn builds its own legend without leaving retrievable
        # labels on the artists -- reuse its handles/texts.
        existing = ax.get_legend()
        if existing is None:
            return
        handles = list(
            getattr(existing, "legend_handles", getattr(existing, "legendHandles", []))
        )
        labels = [t.get_text() for t in existing.get_texts()]
    if labels is None:
        labels = [h.get_label() for h in handles]
    if not handles:
        return
    kwargs: dict[str, Any] = {
        "title": title,
        "fontsize": p.legend_font_size,
        "frameon": True,
        "framealpha": 0.7,
    }
    if p.legend_location == "outside right":
        ax.legend(handles, labels, loc="center left", bbox_to_anchor=(1.02, 0.5), **kwargs)
    else:
        ax.legend(handles, labels, loc=p.legend_location, **kwargs)


def _remove_legend(ax: Any) -> None:
    old = ax.get_legend()
    if old is not None:
        old.remove()


def _finalize_plot(
    fig: Any,
    ax: Any,
    p: Any,
    *,
    default_xlabel: str = "",
    default_ylabel: str = "",
    frame: bool = True,
) -> None:
    """Apply the shared axis / grid / spine / title styling and lay out."""
    ax.set_xlabel(p.x_label or default_xlabel, fontsize=p.axis_font_size)
    ax.set_ylabel(p.y_label or default_ylabel, fontsize=p.axis_font_size)
    ax.tick_params(axis="both", labelsize=p.axis_font_size)
    if frame:
        ax.grid(bool(getattr(p, "show_grid", True)))
        ax.spines["top"].set_visible(bool(getattr(p, "show_box", False)))
        ax.spines["right"].set_visible(bool(getattr(p, "show_box", False)))
        if getattr(p, "log_x", False):
            ax.set_xscale("log")
        if getattr(p, "log_y", False):
            ax.set_yscale("log")
    if p.title:
        ax.set_title(
            p.title,
            fontsize=p.title_font_size,
            fontweight="bold" if p.title_bold else "normal",
            fontstyle="italic" if p.title_italic else "normal",
        )
    fig.tight_layout()


def _categorical_hue(df: Any, color_by: str | None) -> str | None:
    """Validate a 'colour by' column for the box / histogram nodes.

    Returns the column name (or ``None`` when unset / missing). Raises
    ``ValueError`` for a continuous column -- these plots split into one
    group per distinct value, which only makes sense for a categorical
    column.
    """
    col = (color_by or "").strip()
    if not col or col not in df.columns:
        return None
    from pandas.api.types import (
        is_bool_dtype,
        is_datetime64_any_dtype,
        is_numeric_dtype,
    )

    series = df[col]
    if (is_numeric_dtype(series) or is_datetime64_any_dtype(series)) and not is_bool_dtype(
        series
    ):
        raise ValueError(
            f"'colour by' column {col!r} is continuous; this plot colours by a "
            f"categorical column only -- bin it first with the Bin node."
        )
    return col


class MatplotlibPlotParams(NodeParams):
    """
    Parameters for MatplotlibPlot.

    Attributes:
        x, y: Columns for the two axes (any dtype -- matplotlib plots
            categorical axes fine).
        kind: scatter / line / bar.
        title: Optional plot title.
        color_by: Optional column to colour the marks by; empty means a
            single colour.
        single_color: The colour used when ``color_by`` is empty.
        colormap: Colormap for the ``color_by`` column; the offered
            options are discrete for a text/category/bool column and
            continuous otherwise.
        bar_mode: For a bar chart coloured by a discrete column, whether
            the groups' bars are dodged / stacked / layered.
        point_size / line_width: Marker area / line width.
        x_label / y_label: Axis label overrides (blank = column name).
        axis_font_size: Font size for tick and axis labels.
        show_grid: Draw the background grid.
        show_box: Show the top and right spines (bottom + left always shown).
        log_x / log_y: Log-scale the axes.
        fig_width / fig_height: Figure size in inches.
        title_font_size / title_bold / title_italic: Title text style.
        show_legend / legend_title / legend_location / legend_font_size:
            Legend controls (only meaningful when colouring by a column).
    """

    x: str = column_field(dtypes=("any",), description="Column for the x-axis.")
    y: str = column_field(dtypes=("any",), description="Column for the y-axis.")
    kind: Literal["scatter", "line", "bar"] = "scatter"
    title: str | None = None

    # -- colouring --------------------------------------------------------
    color_by: str = column_field(
        dtypes=("any",),
        default="",
        allow_none=True,
        description="Colour the marks by this column (None = a single colour).",
    )
    single_color: str = color_field(
        suggestions=_COMMON_COLORS,
        default=_DEFAULT_COLOR,
        visible_when=("color_by", ""),
        description="Colour of the marks when not colouring by a column.",
    )
    colormap: str = reactive_choice_field(
        options="colormaps",
        depends_on="color_by",
        default="viridis",
        visible_when_set="color_by",
        description="Colormap for the colour-by column.",
    )
    bar_mode: Literal["dodge", "stack", "layer"] = visible_field(
        "dodge",
        visible_when=("kind", "bar"),
        visible_when_set="color_by",
        description="Arrangement of the colour-by groups' bars: side by side "
        "(dodge), stacked, or overlaid (layer). Used only for a discrete "
        "colour-by column.",
    )

    # -- marks ----------------------------------------------------------
    point_size: float = visible_field(
        18.0, visible_when=("kind", "scatter"), description="Scatter marker area."
    )
    line_width: float = visible_field(
        1.2, visible_when=("kind", "line"), description="Line width."
    )

    # -- axes ---------------------------------------------------------
    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    log_x: bool = False
    log_y: bool = False
    fig_width: float = 6.0
    fig_height: float = 4.0

    # -- title ------------------------------------------------------
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False

    # -- legend (only meaningful when colouring by a column) -------
    show_legend: bool = visible_field(True, visible_when_set="color_by")
    legend_title: str = visible_field("", visible_when_set="color_by")
    legend_location: _LEGEND_LOCATIONS = visible_field("best", visible_when_set="color_by")
    legend_font_size: int = visible_field(9, visible_when_set="color_by")


@register_node
class MatplotlibPlot(Node):
    """
    Create a matplotlib Figure from two columns of a DataFrame.

    The figure is returned as an output value (not displayed
    directly), so the caller (engine or UI) decides how/where to
    render or save it. This keeps the node free of any UI dependency.
    """

    node_type = "matplotlib_plot"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = MatplotlibPlotParams
    # matplotlib Figure objects can embed internal masked arrays that
    # joblib's fast hasher cannot process; the figure is cheap to
    # rebuild anyway, so this node always re-runs rather than being cached.
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        """
        Draw the configured plot.

        Args:
            df: Input pandas.DataFrame (via the "df" input port).

        Returns:
            {"figure": matplotlib.figure.Figure}
        """
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")  # non-interactive backend, safe for headless/test runs
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        from pandas.api.types import (
            is_bool_dtype,
            is_datetime64_any_dtype,
            is_numeric_dtype,
        )

        p = self.params
        df = inputs["df"]
        x = df[p.x]
        y = df[p.y]
        color_by = (p.color_by or "").strip()
        use_color = bool(color_by) and color_by in df.columns
        single = p.single_color or _DEFAULT_COLOR

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))

            if not use_color:
                if p.kind == "scatter":
                    ax.scatter(x, y, s=p.point_size, color=single)
                elif p.kind == "line":
                    ax.plot(x, y, linewidth=p.line_width, color=single)
                else:
                    ax.bar(x, y, color=single)
            else:
                cvals = df[color_by]
                continuous = (
                    is_numeric_dtype(cvals) or is_datetime64_any_dtype(cvals)
                ) and not is_bool_dtype(cvals)
                cmap_obj = plt.get_cmap(p.colormap or ("viridis" if continuous else "tab10"))
                legend_label = p.legend_title or color_by

                if continuous:
                    cnum = (
                        cvals.astype("int64")
                        if is_datetime64_any_dtype(cvals)
                        else cvals.astype("float64")
                    )
                    if p.kind == "line":
                        span = cnum.max() - cnum.min()
                        frac = float((cnum.mean() - cnum.min()) / span) if span else 0.5
                        ax.plot(x, y, linewidth=p.line_width, color=cmap_obj(frac))
                    elif p.kind == "bar":
                        norm = plt.Normalize(cnum.min(), cnum.max())
                        ax.bar(x, y, color=cmap_obj(norm(cnum)))
                        if p.show_legend:
                            sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap_obj)
                            sm.set_array([])
                            fig.colorbar(sm, ax=ax, label=legend_label)
                    else:
                        sc = ax.scatter(x, y, c=cnum, s=p.point_size, cmap=cmap_obj)
                        if p.show_legend:
                            fig.colorbar(sc, ax=ax, label=legend_label)
                else:
                    cats = cvals.astype("category")
                    categories = list(cats.cat.categories)
                    palette = [cmap_obj(i % cmap_obj.N) for i in range(max(len(categories), 1))]
                    grey = (0.6, 0.6, 0.6, 1.0)
                    row_colors = [
                        palette[c] if c >= 0 else grey for c in cats.cat.codes
                    ]

                    if p.kind == "line":
                        for i, cat in enumerate(categories):
                            mask = (cvals == cat).to_numpy()
                            ax.plot(
                                x[mask], y[mask],
                                linewidth=p.line_width, color=palette[i], label=str(cat),
                            )
                    elif p.kind == "bar":
                        x_values = list(dict.fromkeys(x.tolist()))  # unique, in order
                        base = np.arange(len(x_values))
                        groups = max(len(categories), 1)
                        span = 0.8
                        bottoms = [0.0] * len(x_values)
                        for i, cat in enumerate(categories):
                            heights_by_x = df[cvals == cat].groupby(p.x)[p.y].sum()
                            heights = [float(heights_by_x.get(xv, 0.0)) for xv in x_values]
                            if p.bar_mode == "dodge":
                                width = span / groups
                                ax.bar(
                                    base + i * width - span / 2 + width / 2, heights,
                                    width=width, color=palette[i], label=str(cat),
                                )
                            elif p.bar_mode == "stack":
                                ax.bar(
                                    base, heights, width=span, color=palette[i],
                                    bottom=bottoms, label=str(cat),
                                )
                                bottoms = [b + h for b, h in zip(bottoms, heights)]
                            else:  # layer
                                ax.bar(
                                    base, heights, width=span, color=palette[i],
                                    alpha=0.6, label=str(cat),
                                )
                        ax.set_xticks(base)
                        ax.set_xticklabels([str(xv) for xv in x_values])
                    else:
                        ax.scatter(x, y, c=row_colors, s=p.point_size)

                    if p.show_legend and categories:
                        if p.kind == "line":
                            handles = [
                                Line2D([], [], color=palette[i], label=str(cat))
                                for i, cat in enumerate(categories)
                            ]
                        elif p.kind == "bar":
                            handles = [
                                Patch(color=palette[i], label=str(cat))
                                for i, cat in enumerate(categories)
                            ]
                        else:
                            handles = [
                                Line2D(
                                    [], [], marker="o", linestyle="",
                                    markersize=8, color=palette[i], label=str(cat),
                                )
                                for i, cat in enumerate(categories)
                            ]
                        _place_legend(ax, p, legend_label, handles=handles)

            _finalize_plot(fig, ax, p, default_xlabel=p.x, default_ylabel=p.y)

        return {"figure": fig}


class BoxPlotParams(NodeParams):
    """
    Parameters for BoxPlot.

    Attributes:
        category_column: The categorical axis.
        value_column: The numeric axis.
        kind: "box" or "violin".
        orientation: Whether the categorical axis is x (vertical boxes)
            or y (horizontal boxes).
        color_by: Optional categorical column that splits each category
            into hue sub-groups; a continuous column is rejected.
        colormap / single_color: Palette for the hue groups / colour
            when not grouping.
        show_legend / legend_*: Legend controls (hue only).
        the remaining fields: shared axis / title styling.
    """

    category_column: str = column_field(
        dtypes=("categorical", "boolean"), description="Categorical axis column."
    )
    value_column: str = column_field(
        dtypes=("numeric",), description="Numeric axis column."
    )
    kind: Literal["box", "violin"] = "box"
    orientation: Literal["vertical", "horizontal"] = "vertical"

    color_by: str = column_field(
        dtypes=("categorical", "boolean"),
        default="",
        allow_none=True,
        description="Split each category by this column (categorical only).",
    )
    colormap: str = reactive_choice_field(
        options="colormaps",
        depends_on="color_by",
        default="tab10",
        visible_when_set="color_by",
        description="Palette for the hue groups.",
    )
    single_color: str = color_field(
        suggestions=_COMMON_COLORS,
        default=_DEFAULT_COLOR,
        visible_when=("color_by", ""),
        description="Box / violin colour when not grouping.",
    )

    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    log_x: bool = False
    log_y: bool = False
    fig_width: float = 6.0
    fig_height: float = 4.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = visible_field(True, visible_when_set="color_by")
    legend_title: str = visible_field("", visible_when_set="color_by")
    legend_location: _LEGEND_LOCATIONS = visible_field("best", visible_when_set="color_by")
    legend_font_size: int = visible_field(9, visible_when_set="color_by")


@register_node
class BoxPlot(Node):
    """Box / violin plot of a numeric column across a categorical one."""

    node_type = "box_plot"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = BoxPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        p = self.params
        df = inputs["df"]
        for col in (p.category_column, p.value_column):
            if col not in df.columns:
                raise ValueError(f"BoxPlot: column {col!r} is not in the input data.")
        hue = _categorical_hue(df, p.color_by)

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
            vertical = p.orientation == "vertical"
            axis_kw = (
                {"x": p.category_column, "y": p.value_column}
                if vertical
                else {"x": p.value_column, "y": p.category_column}
            )
            draw_kw: dict[str, Any] = {"data": df, "ax": ax, **axis_kw}
            if hue:
                draw_kw["hue"] = hue
                draw_kw["palette"] = p.colormap or "tab10"
            else:
                draw_kw["color"] = p.single_color or _DEFAULT_COLOR

            (sns.violinplot if p.kind == "violin" else sns.boxplot)(**draw_kw)

            if hue and p.show_legend:
                _place_legend(ax, p, p.legend_title or hue)
            else:
                _remove_legend(ax)

            _finalize_plot(
                fig, ax, p,
                default_xlabel=axis_kw["x"], default_ylabel=axis_kw["y"],
            )

        return {"figure": fig}


class HistogramPlotParams(NodeParams):
    """
    Parameters for HistogramPlot.

    Attributes:
        value_column: The numeric variable whose distribution is drawn.
        mode: "histogram" (bars), "kde" (smooth density curve) or
            "both" (bars with a KDE overlay).
        bins: Number of histogram bins (ignored for pure KDE).
        stat: Histogram normalisation -- count / density / probability
            (ignored for pure KDE).
        color_by: Optional categorical column; one distribution per
            distinct value. A continuous column is rejected.
        multiple: How the per-group distributions are combined
            (layer / stack / dodge).
        colormap / single_color: Palette / colour.
        show_legend / legend_*: Legend controls (grouped only).
        the remaining fields: shared axis / title styling.
    """

    value_column: str = column_field(
        dtypes=("numeric",), description="Variable whose distribution to plot."
    )
    mode: Literal["histogram", "kde", "both"] = "histogram"
    bins: int = visible_field(
        30, visible_unless=("mode", "kde"), description="Number of histogram bins."
    )
    stat: Literal["count", "density", "probability"] = visible_field(
        "count", visible_unless=("mode", "kde"), description="Histogram normalisation."
    )

    color_by: str = column_field(
        dtypes=("categorical", "boolean"),
        default="",
        allow_none=True,
        description="One distribution per category of this column (categorical only).",
    )
    multiple: Literal["layer", "stack", "dodge"] = visible_field(
        "layer",
        visible_when_set="color_by",
        description="How the per-group distributions are combined.",
    )
    colormap: str = reactive_choice_field(
        options="colormaps",
        depends_on="color_by",
        default="tab10",
        visible_when_set="color_by",
        description="Palette for the groups.",
    )
    single_color: str = color_field(
        suggestions=_COMMON_COLORS,
        default=_DEFAULT_COLOR,
        visible_when=("color_by", ""),
        description="Colour when not grouping.",
    )

    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    log_x: bool = False
    log_y: bool = False
    fig_width: float = 6.0
    fig_height: float = 4.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = visible_field(True, visible_when_set="color_by")
    legend_title: str = visible_field("", visible_when_set="color_by")
    legend_location: _LEGEND_LOCATIONS = visible_field("best", visible_when_set="color_by")
    legend_font_size: int = visible_field(9, visible_when_set="color_by")


@register_node
class HistogramPlot(Node):
    """Distribution of one numeric column: histogram, KDE, or both."""

    node_type = "histogram_plot"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = HistogramPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import seaborn as sns

        p = self.params
        df = inputs["df"]
        if p.value_column not in df.columns:
            raise ValueError(
                f"HistogramPlot: column {p.value_column!r} is not in the input data."
            )
        hue = _categorical_hue(df, p.color_by)

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
            common: dict[str, Any] = {"data": df, "x": p.value_column, "ax": ax}
            if hue:
                common["hue"] = hue
                common["palette"] = p.colormap or "tab10"
                common["multiple"] = p.multiple
            else:
                common["color"] = p.single_color or _DEFAULT_COLOR

            if p.mode == "kde":
                if common.get("multiple") == "dodge":
                    common["multiple"] = "layer"  # kdeplot cannot dodge
                sns.kdeplot(fill=True, **common)
                default_ylabel = "Density"
            else:
                sns.histplot(
                    bins=max(int(p.bins), 1),
                    stat=p.stat,
                    kde=(p.mode == "both"),
                    **common,
                )
                default_ylabel = {
                    "count": "Count", "density": "Density", "probability": "Probability",
                }[p.stat]

            if hue and p.show_legend:
                _place_legend(ax, p, p.legend_title or hue)
            else:
                _remove_legend(ax)

            _finalize_plot(
                fig, ax, p,
                default_xlabel=p.value_column, default_ylabel=default_ylabel,
            )

        return {"figure": fig}


class HeatmapPlotParams(NodeParams):
    """
    Parameters for HeatmapPlot.

    Attributes:
        x_column / y_column: The two categorical columns.
        statistic: What each cell shows -- "count" (crosstab), row /
            column proportions, "aggregate" of a numeric column, or
            "association" (standardised residuals from independence,
            with Cramer's V in the title).
        value_column / aggregate: Numeric column and reduction for the
            "aggregate" statistic.
        colormap: Sequential / diverging colormap.
        annotate: Write each cell's value on it.
        the remaining fields: title + axis styling.
    """

    x_column: str = column_field(
        dtypes=("categorical", "boolean"), description="Categorical column across the top."
    )
    y_column: str = column_field(
        dtypes=("categorical", "boolean"), description="Categorical column down the side."
    )
    statistic: Literal[
        "count", "row_percent", "column_percent", "aggregate", "association"
    ] = "count"
    value_column: str = column_field(
        dtypes=("numeric",),
        default="",
        allow_none=True,
        visible_when=("statistic", "aggregate"),
        description="Numeric column to aggregate in each cell.",
    )
    aggregate: Literal["mean", "median", "sum", "count", "min", "max"] = visible_field(
        "mean",
        visible_when=("statistic", "aggregate"),
        description="Reduction applied to the value column per cell.",
    )
    colormap: Literal[
        "viridis", "plasma", "cividis", "magma", "coolwarm", "Spectral", "Blues", "Greens"
    ] = "viridis"
    annotate: bool = True

    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    fig_width: float = 6.0
    fig_height: float = 4.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class HeatmapPlot(Node):
    """Heatmap of a statistic over two categorical columns."""

    node_type = "heatmap_plot"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = HeatmapPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        import seaborn as sns

        p = self.params
        df = inputs["df"]
        xcol, ycol = p.x_column, p.y_column
        for col in (xcol, ycol):
            if col not in df.columns:
                raise ValueError(f"HeatmapPlot: column {col!r} is not in the input data.")

        center: float | None = None
        cramers_v: float | None = None

        if p.statistic == "count":
            table = pd.crosstab(df[ycol], df[xcol])
            fmt, cbar_label = "d", "Count"
        elif p.statistic == "row_percent":
            table = pd.crosstab(df[ycol], df[xcol], normalize="index").mul(100.0)
            fmt, cbar_label = ".1f", "Row %"
        elif p.statistic == "column_percent":
            table = pd.crosstab(df[ycol], df[xcol], normalize="columns").mul(100.0)
            fmt, cbar_label = ".1f", "Column %"
        elif p.statistic == "aggregate":
            value_column = (p.value_column or "").strip()
            if not value_column or value_column not in df.columns:
                raise ValueError(
                    "HeatmapPlot: choose a numeric 'value column' for the "
                    "aggregate statistic."
                )
            table = df.pivot_table(
                index=ycol, columns=xcol, values=value_column, aggfunc=p.aggregate
            )
            fmt, cbar_label = ".2f", f"{p.aggregate}({value_column})"
        else:  # association -- standardised residuals from independence
            from scipy.stats import chi2_contingency

            observed = pd.crosstab(df[ycol], df[xcol])
            chi2, _pval, _dof, expected = chi2_contingency(observed)
            table = (observed - expected) / np.sqrt(expected)
            fmt, cbar_label, center = ".2f", "Std. residual", 0.0
            total = float(observed.to_numpy().sum())
            k = min(observed.shape)
            cramers_v = (
                float(np.sqrt(chi2 / (total * (k - 1)))) if total and k > 1 else 0.0
            )

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
            sns.heatmap(
                table,
                ax=ax,
                cmap=p.colormap,
                center=center,
                annot=bool(p.annotate),
                fmt=fmt,
                cbar_kws={"label": cbar_label},
            )
            title = p.title or (
                f"Cramér's V = {cramers_v:.3f}" if cramers_v is not None else ""
            )
            if title:
                ax.set_title(
                    title,
                    fontsize=p.title_font_size,
                    fontweight="bold" if p.title_bold else "normal",
                    fontstyle="italic" if p.title_italic else "normal",
                )
            ax.set_xlabel(p.x_label or xcol, fontsize=p.axis_font_size)
            ax.set_ylabel(p.y_label or ycol, fontsize=p.axis_font_size)
            ax.tick_params(axis="both", labelsize=p.axis_font_size)
            fig.tight_layout()

        return {"figure": fig}
