"""
Visualization nodes: turn data into a matplotlib Figure object that
downstream nodes (or the UI canvas) can display or export.

The nodes stay free of any UI-toolkit dependency: they import only
matplotlib (headless "Agg" backend) and seaborn, and return the Figure
as an output value for the caller to render or save.
"""

from typing import Any, Literal

from ruyso_app.core import colors, dtformat
from ruyso_app.core.node import Node, NodeParams
from ruyso_app.core.params import (
    axis_limit_field,
    checkbox_list_field,
    color_field,
    colormap_field,
    column_field,
    reactive_choice_field,
    unit_interval_field,
    visible_field,
)
from ruyso_app.core.port import Port
from ruyso_app.core.registry import register_node

#: Base matplotlib style, applied per-figure via a local context so it
#: never leaks into other nodes or the host process.
_BASE_STYLE = "seaborn-v0_8-whitegrid"


def _plot_context(plt: Any):
    """
    The style context every figure is drawn inside.

    Layers the Chart-defaults preferences (``charts.style`` /
    ``charts.font_family`` / ``charts.dpi``) over the built-in base
    style, as a *context* rather than a global rcParams change so a
    figure never leaks its styling into whatever draws next. Falls back
    to the built-in style if the configured one is not installed --
    a preference naming a missing style should not stop plots rendering.

    Note that this makes a figure depend on machine-local preferences,
    which an exported script will not carry: the same caveat that
    already applies to custom colormaps (see README).
    """
    from ruyso_app.engine import settings

    overrides: dict[str, Any] = {}
    family = settings.get("charts.font_family")
    if family:
        overrides["font.family"] = family
    dpi = settings.get("charts.dpi")
    if dpi:
        overrides["figure.dpi"] = float(dpi)

    style = settings.get("charts.style") or _BASE_STYLE
    try:
        return plt.style.context([style, overrides])
    except (OSError, ValueError):
        return plt.style.context([_BASE_STYLE, overrides])

#: Default single colour for dots / lines / bars / boxes.
_DEFAULT_COLOR = "darkblue"

#: Suggested colours offered in the colour-picker dropdown (any
#: matplotlib colour string is still accepted).
_COMMON_COLORS = [
    "materialblue",  # the app's accent (core.colors.NAMED_COLORS)
    "darkblue", "steelblue", "royalblue", "black", "dimgray",
    "crimson", "seagreen", "darkorange", "purple", "teal",
]

#: Continuous colormaps offered by the heatmap node.
_SEQUENTIAL_COLORMAPS = [
    "viridis", "plasma", "cividis", "magma", "coolwarm", "Spectral", "Blues", "Greens",
]

#: Fixed-styling shape choices -> matplotlib marker / linestyle / hatch.
_MARKER_SHAPES = {
    "circle": "o", "square": "s", "triangle": "^", "diamond": "D",
    "plus": "P", "cross": "X", "star": "*", "point": ".",
}
_LINE_STYLES = {"solid": "-", "dashed": "--", "dash-dot": "-.", "dotted": ":"}
_BAR_HATCHES = {
    "none": None, "diagonal": "/", "back-diagonal": "\\",
    "cross": "x", "dots": ".", "stars": "*",
}

#: Named *series* of shapes used when a discrete column drives the mark
#: shape -- the shape analogue of a colormap. One entry per grapher
#: "shape map" choice, resolved per plot kind (marker / linestyle / hatch).
_SHAPE_MAPS = ("assorted", "geometric", "bold", "minimal")
_SHAPE_MAP_MARKERS = {
    "assorted": ["o", "s", "^", "D", "v", "P", "X", "*"],
    "geometric": ["o", "s", "^", "D", "p", "h", "8", "v"],
    "bold": ["*", "P", "X", "D", "o", "s", "^", "v"],
    "minimal": ["o", "^", "s", "D", "v", "<", ">", "p"],
}
_SHAPE_MAP_LINESTYLES = {
    "assorted": ["-", "--", "-.", ":"],
    "geometric": ["-", (0, (3, 1)), (0, (1, 1)), (0, (3, 1, 1, 1))],
    "bold": ["-", (0, (5, 1)), (0, (3, 1, 1, 1, 1, 1)), (0, (1, 1))],
    "minimal": ["-", ":", "--", "-."],
}
_SHAPE_MAP_HATCHES = {
    "assorted": ["/", "\\", "x", ".", "*", "o", "+", "O"],
    "geometric": ["/", "\\", "|", "-", "+", "x", "o", "O"],
    "bold": ["xx", "**", "..", "//", "\\\\", "OO", "++", "oo"],
    "minimal": ["/", ".", "\\", "x", "-", "+", "o", "*"],
}


def _bar_error_value(values: Any, method: str) -> float:
    """
    Error-bar half-length for one bar's y values (see
    ``MatplotlibPlotParams.bar_error``): sample standard deviation,
    standard error of the mean, or a t-distribution confidence
    interval. ``values`` is assumed already-numeric with NaNs removed;
    fewer than 2 values gives 0 (nothing to estimate spread from).
    """
    import numpy as np

    arr = np.asarray(values, dtype="float64")
    n = arr.size
    if n < 2:
        return 0.0
    std = float(np.std(arr, ddof=1))
    if method == "std":
        return std
    sem = std / np.sqrt(n)
    if method == "sem":
        return float(sem)
    from scipy import stats as _spstats

    level = 0.95 if method == "ci_95" else 0.99
    t = float(_spstats.t.ppf((1 + level) / 2, df=n - 1))
    return t * sem


def _shape_sequence(kind: str, shape_map: str) -> list:
    """The ordered marker / linestyle / hatch series for ``shape_map``."""
    table = {
        "scatter": _SHAPE_MAP_MARKERS,
        "line": _SHAPE_MAP_LINESTYLES,
        "bar": _SHAPE_MAP_HATCHES,
    }[kind]
    return list(table.get(shape_map, table["assorted"]))


#: Caption drawn when a discrete style column has more levels than its series.
_STYLE_OVERFLOW_NOTE = "note: mark shapes repeat past the series length"

#: Corners used for the 2nd, 3rd... legend when two encodings are shown.
_SECONDARY_LEGEND_LOCS = ["lower right", "lower left", "upper left"]

_LEGEND_LOCATIONS = Literal[
    "best", "upper right", "upper left", "lower right", "lower left",
    "center", "outside right",
]


def _fig_size(p: Any) -> tuple[float, float]:
    return (max(float(p.fig_width), 1.0), max(float(p.fig_height), 1.0))


def _z_value(confidence_level: float) -> float:
    """Two-sided standard-normal critical value for ``confidence_level``."""
    from scipy import stats as _spstats

    return float(_spstats.norm.ppf((1.0 + float(confidence_level)) / 2.0))


def _new_figure(p: Any, nrows: int = 1, ncols: int = 1, *, squeeze: bool = True):
    """
    A standalone matplotlib ``Figure`` (plus its ``Axes``) sized from ``p``.

    Deliberately uses the object-oriented ``Figure`` constructor rather
    than ``pyplot.subplots``: a ``pyplot`` figure is registered in the
    global figure manager and is only released by ``pyplot.close``, so
    in a long-running session every (auto-)run would leak one figure per
    grapher node (eventually tripping matplotlib's ``max_open_warning``).
    A directly constructed ``Figure`` is owned solely by its caller and
    freed by normal garbage collection once the pipeline output holding
    it is dropped. ``savefig`` / ``FigureCanvasAgg`` attach a canvas on
    demand, so the returned figure renders exactly as before.

    Call this inside a ``with _plot_context(plt):`` block so
    the axes still pick up the shared style.
    """
    from matplotlib.figure import Figure

    # Every grapher comes through here, so this is the one place that has
    # to teach matplotlib the app's extra colour names before any param
    # value reaches it. Idempotent and cheap (a dict setdefault).
    colors.register()

    fig = Figure(figsize=_fig_size(p))
    axes = fig.subplots(nrows, ncols, squeeze=squeeze)
    return fig, axes


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


def _encoding_handles(
    kind: str, labels: list, *, colors: list | None, shape_seq: list | None
) -> list:
    """Legend handles describing one encoding of ``labels``.

    ``colors`` gives one RGBA per label (``None`` -> neutral grey);
    ``shape_seq`` (a marker / linestyle / hatch series) also varies the
    mark shape per label -- pass it for a shape-by encoding or a
    combined colour+shape legend, ``None`` for a plain colour legend.
    """
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    handles: list = []
    for i, label in enumerate(labels):
        colour = colors[i] if colors is not None else "0.3"
        shape = shape_seq[i % len(shape_seq)] if shape_seq else None
        if kind == "line":
            handles.append(
                Line2D([], [], color=colour, linestyle=shape or "-", label=str(label))
            )
        elif kind == "bar":
            face = colors[i] if colors is not None else "0.85"
            handles.append(
                Patch(facecolor=face, edgecolor="0.3", hatch=shape, label=str(label))
            )
        else:  # scatter
            handles.append(
                Line2D(
                    [], [], color=colour, marker=shape or "o", linestyle="",
                    markersize=8, label=str(label),
                )
            )
    return handles


def _place_legends(ax: Any, p: Any, legends: list[tuple[str, list]]) -> None:
    """Draw one legend per (title, handles) pair.

    The first sits at the params' location; any further legends go to
    spread-out corners so a colour legend and a shape legend can both
    be shown at once.
    """
    if not legends:
        _remove_legend(ax)
        return
    title0, handles0 = legends[0]
    _place_legend(ax, p, title0, handles=handles0)
    for i, (title, handles) in enumerate(legends[1:]):
        primary = ax.get_legend()
        if primary is not None:
            ax.add_artist(primary)
        ax.legend(
            handles=handles,
            labels=[h.get_label() for h in handles],
            title=title,
            fontsize=p.legend_font_size,
            frameon=True,
            framealpha=0.7,
            loc=_SECONDARY_LEGEND_LOCS[i % len(_SECONDARY_LEGEND_LOCS)],
        )


def _limit_value(raw: Any) -> Any:
    """Parse one manual axis-limit value: a number, an ISO date string,
    or ``None`` for "leave this edge on autoscale"."""
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            import pandas as pd

            try:
                return pd.to_datetime(text)
            except (ValueError, TypeError):
                return None
    return float(raw)


def _apply_axis_limits(axes: Any, p: Any) -> None:
    """
    Apply whichever manual axis edges ``p`` carries to one Axes or a list.

    Each edge is independent and *blank means "fit this edge to the
    data"*, so a person can pin only the y-axis floor and leave the other
    three on autoscale. Passing ``None`` to ``set_xlim`` leaves that side
    exactly as matplotlib computed it, which is what makes a per-edge
    blank work. A no-op when the params carry none of the fields.
    """
    ax_list = list(axes) if isinstance(axes, (list, tuple)) else [axes]
    x_lo, x_hi = _limit_value(getattr(p, "x_min", None)), _limit_value(getattr(p, "x_max", None))
    if x_lo is not None or x_hi is not None:
        for ax in ax_list:
            ax.set_xlim(left=x_lo, right=x_hi)
    y_lo, y_hi = _limit_value(getattr(p, "y_min", None)), _limit_value(getattr(p, "y_max", None))
    if y_lo is not None or y_hi is not None:
        for ax in ax_list:
            ax.set_ylim(bottom=y_lo, top=y_hi)


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
    _apply_axis_limits(ax, p)
    if p.title:
        ax.set_title(
            p.title,
            fontsize=p.title_font_size,
            fontweight="bold" if p.title_bold else "normal",
            fontstyle="italic" if p.title_italic else "normal",
        )
    # A figure built by _new_joint_figure already carries a
    # (constrained) layout engine that understands the marginal axes;
    # tight_layout would fight it and warn.
    if fig.get_layout_engine() is None:
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


# --------------------------------------------------------------------------
# Marginal distributions (shared by matplotlib_plot scatter + density_2d):
# a strip summarising x along the top axis and y along the right axis.
# --------------------------------------------------------------------------

_MARGINAL_KINDS = Literal["histogram", "kde", "histogram+kde", "rug"]


def _new_joint_figure(p: Any):
    """A main ``Axes`` plus top (x) and right (y) marginal axes.

    The marginals share the main axis they summarise, carry no ticks,
    spines or grid and take ~1/6 of the figure. Returns
    ``(fig, ax_main, ax_top, ax_right)``. Use in place of
    :func:`_new_figure` when ``show_marginals`` is on.
    """
    from matplotlib.figure import Figure

    # constrained layout (not tight_layout) understands the marginal
    # grid; _finalize_plot skips its tight_layout when an engine is set.
    fig = Figure(figsize=_fig_size(p), layout="constrained")
    fig.get_layout_engine().set(w_pad=0.02, h_pad=0.02, wspace=0.02, hspace=0.02)
    gs = fig.add_gridspec(2, 2, width_ratios=(5, 1), height_ratios=(1, 5))
    ax_main = fig.add_subplot(gs[1, 0])
    ax_top = fig.add_subplot(gs[0, 0], sharex=ax_main)
    ax_right = fig.add_subplot(gs[1, 1], sharey=ax_main)
    for m in (ax_top, ax_right):
        for spine in m.spines.values():
            spine.set_visible(False)
        m.grid(False)
    ax_top.tick_params(axis="x", labelbottom=False, length=0)
    ax_top.tick_params(axis="y", labelleft=False, left=False, length=0)
    ax_right.tick_params(axis="y", labelleft=False, length=0)
    ax_right.tick_params(axis="x", labelbottom=False, bottom=False, length=0)
    return fig, ax_main, ax_top, ax_right


def _draw_marginals(
    ax_top: Any, ax_right: Any, xvals: Any, yvals: Any, *, kind: str, color: Any
) -> None:
    """Draw one group's x marginal on ``ax_top`` and y marginal on ``ax_right``.

    ``kind`` is one of :data:`_MARGINAL_KINDS`. Call once per colour
    group (passing that group's colour) so the marginals follow a
    discrete ``color_by``.
    """
    import numpy as np

    def _one(ax: Any, values: Any, vertical: bool) -> None:
        arr = np.asarray(values, dtype="float64")
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return
        orient = "vertical" if vertical else "horizontal"
        if kind in ("histogram", "histogram+kde"):
            ax.hist(
                arr, bins="auto", orientation=orient, color=color,
                alpha=0.5 if kind == "histogram+kde" else 0.8,
                density=kind == "histogram+kde",
            )
        if kind in ("kde", "histogram+kde") and arr.size > 2 and np.ptp(arr) > 0:
            from scipy.stats import gaussian_kde

            grid = np.linspace(arr.min(), arr.max(), 200)
            dens = gaussian_kde(arr)(grid)
            if vertical:
                ax.plot(grid, dens, color=color, linewidth=1.0)
                ax.fill_between(grid, dens, color=color, alpha=0.25)
            else:
                ax.plot(dens, grid, color=color, linewidth=1.0)
                ax.fill_betweenx(grid, dens, color=color, alpha=0.25)
        if kind == "rug":
            if vertical:
                ax.plot(arr, np.zeros_like(arr), "|", color=color, alpha=0.6, markersize=10)
                ax.set_ylim(-0.5, 1.0)
            else:
                ax.plot(np.zeros_like(arr), arr, "_", color=color, alpha=0.6, markersize=10)
                ax.set_xlim(-0.5, 1.0)

    _one(ax_top, xvals, vertical=True)
    _one(ax_right, yvals, vertical=False)


class MatplotlibPlotParams(NodeParams):
    """
    Parameters for MatplotlibPlot.

    Four independent visual channels, each a fixed value plus an
    optional "... by <column>":

    * **colour** -- ``mark_color`` / ``color_by`` (+ ``colormap``)
    * **shape**  -- ``marker_shape`` / ``line_style`` / ``bar_hatch`` /
      ``shape_by`` (+ ``shape_map``)
    * **size**   -- ``point_size`` / ``line_width`` / ``size_by``
      (+ ``size_min`` / ``size_max`` / ``width_min`` / ``width_max``)
    * **alpha**  -- ``alpha`` / ``alpha_by`` (+ ``alpha_min`` / ``alpha_max``)

    A *discrete* "by" column steps the channel across its levels
    (palette / shape series / evenly-spaced sizes / evenly-spaced
    alphas); a *continuous* one interpolates (colormap / size range /
    alpha range -- shape keeps its fixed value).

    Plus two kind-specific extras: ``bar_error`` (bar only) adds a
    confidence-interval / std-dev / SEM whisker per bar, averaging its
    y values instead of summing them; ``line_fill`` / ``line_stack``
    (line only) turn the line(s) into a (stacked) area chart.
    """

    x: str = column_field(dtypes=("any",), description="Column for the x-axis.")
    y: str = column_field(dtypes=("any",), description="Column for the y-axis.")
    kind: Literal["scatter", "line", "bar"] = "scatter"
    title: str | None = None

    # -- colour channel -------------------------------------------------
    color_by: str = column_field(
        dtypes=("any",),
        default="",
        allow_none=True,
        description="Colour the marks by this column (None = a single colour).",
    )
    mark_color: str = color_field(
        suggestions=_COMMON_COLORS,
        default=_DEFAULT_COLOR,
        visible_when_unset="color_by",
        description="Mark colour when not colouring by a column.",
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
    bar_error: Literal["none", "sem", "std", "ci_95", "ci_99"] = visible_field(
        "none",
        visible_when=("kind", "bar"),
        description="Error bar per bar: standard error of the mean, standard "
        "deviation, or a t-based confidence interval. When not 'none', each "
        "bar's y values are averaged (mean) rather than summed / shown "
        "one-per-row, and per-row shape/opacity styling no longer applies.",
    )

    # -- line-only extras ----------------------------------------------
    line_fill: bool = visible_field(
        False, visible_when=("kind", "line"),
        description="Fill the area under each line (an area chart).",
    )
    line_stack: bool = visible_field(
        False,
        visible_when=("kind", "line"),
        visible_when_set="color_by",
        description="Stack the colour-by groups' lines into a stacked area "
        "chart instead of overlaying them. Needs a discrete colour-by column.",
    )

    # -- shape channel ------------------------------------------------
    shape_by: str = column_field(
        dtypes=("any",),
        default="",
        allow_none=True,
        description="Vary the mark shape by this (discrete) column.",
    )
    marker_shape: Literal[
        "circle", "square", "triangle", "diamond", "plus", "cross", "star", "point"
    ] = visible_field(
        "circle",
        visible_when=("kind", "scatter"),
        visible_when_unset="shape_by",
        description="Marker shape (fixed).",
    )
    line_style: Literal["solid", "dashed", "dash-dot", "dotted"] = visible_field(
        "solid",
        visible_when=("kind", "line"),
        visible_when_unset="shape_by",
        description="Line style (fixed).",
    )
    bar_hatch: Literal[
        "none", "diagonal", "back-diagonal", "cross", "dots", "stars"
    ] = visible_field(
        "none",
        visible_when=("kind", "bar"),
        visible_when_unset="shape_by",
        description="Bar hatch pattern (fixed).",
    )
    shape_map: Literal["assorted", "geometric", "bold", "minimal"] = visible_field(
        "assorted",
        visible_when_kind=("shape_by", ("categorical", "boolean")),
        description="Series of mark shapes assigned to a discrete shape-by "
        "column's levels (the shape analogue of a colormap).",
    )

    # -- size channel -----------------------------------------------
    size_by: str = column_field(
        dtypes=("any",),
        default="",
        allow_none=True,
        description="Vary the mark size by this column.",
    )
    point_size: float = visible_field(
        18.0,
        visible_when=("kind", "scatter"),
        visible_when_unset="size_by",
        description="Scatter marker area (fixed).",
    )
    line_width: float = visible_field(
        1.2,
        visible_when=("kind", "line"),
        visible_when_unset="size_by",
        description="Line width (fixed).",
    )
    size_min: float = visible_field(
        10.0,
        visible_when=("kind", "scatter"),
        visible_when_set="size_by",
        description="Marker area for the smallest / first size-by level.",
    )
    size_max: float = visible_field(
        200.0,
        visible_when=("kind", "scatter"),
        visible_when_set="size_by",
        description="Marker area for the largest / last size-by level.",
    )
    width_min: float = visible_field(
        0.6,
        visible_when=("kind", "line"),
        visible_when_set="size_by",
        description="Line width for the smallest / first size-by level.",
    )
    width_max: float = visible_field(
        4.0,
        visible_when=("kind", "line"),
        visible_when_set="size_by",
        description="Line width for the largest / last size-by level.",
    )

    # -- alpha channel --------------------------------------------
    alpha_by: str = column_field(
        dtypes=("any",),
        default="",
        allow_none=True,
        description="Vary the mark opacity by this column.",
    )
    alpha: float = unit_interval_field(
        0.9, visible_when_unset="alpha_by", description="Mark opacity (fixed)."
    )
    alpha_min: float = unit_interval_field(
        0.25,
        visible_when_set="alpha_by",
        description="Opacity for the smallest / first alpha-by level.",
    )
    alpha_max: float = unit_interval_field(
        1.0,
        visible_when_set="alpha_by",
        description="Opacity for the largest / last alpha-by level.",
    )

    # -- marginals (scatter only) ---------------------------------------
    show_marginals: bool = visible_field(
        False,
        visible_when=("kind", "scatter"),
        description="Add a distribution of x along the top and of y along "
        "the right. Follows a discrete colour-by column (one marginal per "
        "group, same palette).",
    )
    marginal_kind: _MARGINAL_KINDS = visible_field(
        "histogram",
        visible_when=("show_marginals", "True"),
        description="Style of the top / right marginal distributions.",
    )

    # -- axes ---------------------------------------------------------
    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
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

    # -- legend (drawn for a discrete colour-by / shape-by column) -------
    show_legend: bool = True
    legend_title: str = ""
    legend_location: _LEGEND_LOCATIONS = "best"
    legend_font_size: int = 9


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
        import pandas as pd
        from matplotlib.colors import to_rgba
        from pandas.api.types import (
            is_bool_dtype,
            is_datetime64_any_dtype,
            is_numeric_dtype,
        )

        p = self.params
        df = inputs["df"]
        for col in (p.x, p.y):
            if col not in df.columns:
                raise ValueError(
                    f"MatplotlibPlot: column {col!r} is not in the input data."
                )
        x, y = df[p.x], df[p.y]
        n = len(df)
        all_rows = np.ones(n, dtype=bool)

        def _is_continuous(s: Any) -> bool:
            return (
                is_numeric_dtype(s) or is_datetime64_any_dtype(s)
            ) and not is_bool_dtype(s)

        def _as_number(s: Any) -> Any:
            return (
                s.astype("int64") if is_datetime64_any_dtype(s) else s.astype("float64")
            ).to_numpy()

        def _encode(col: str) -> tuple[str, dict]:
            """('single' | 'discrete' | 'continuous', info) for one optional column."""
            col = (col or "").strip()
            if not col or col not in df.columns:
                return "single", {}
            s = df[col]
            if _is_continuous(s):
                num = _as_number(s).astype("float64")
                lo, hi = np.nanmin(num), np.nanmax(num)
                frac = (num - lo) / (hi - lo) if hi > lo else np.full(n, 0.5)
                return "continuous", {
                    "name": col, "num": num,
                    "frac": np.nan_to_num(np.asarray(frac, "float64"), nan=0.5),
                }
            cat = s.astype("category")
            cats = list(cat.cat.categories)
            codes = cat.cat.codes.to_numpy()
            m = max(len(cats), 1)
            frac = np.array(
                [(c / (m - 1)) if (c >= 0 and m > 1) else 0.5 for c in codes],
                dtype="float64",
            )
            return "discrete", {"name": col, "cats": cats, "codes": codes, "frac": frac}

        notes: list[str] = []

        # --- colour channel ------------------------------------------
        color_kind, ci = _encode(p.color_by)
        color_cmap = color_norm = None
        color_palette: list = []
        if color_kind != "single":
            color_cmap = plt.get_cmap(
                p.colormap or ("viridis" if color_kind == "continuous" else "tab10")
            )
        if color_kind == "continuous":
            color_norm = plt.Normalize(np.nanmin(ci["num"]), np.nanmax(ci["num"]))
        elif color_kind == "discrete":
            # A per-level palette needs a qualitative map: sampling a
            # continuous one (256-entry LUT) at 0, 1, 2 ... gives nearly
            # identical colours, so fall back to tab10.
            if getattr(color_cmap, "N", 256) > 32:
                color_cmap = plt.get_cmap("tab10")
            color_palette = [
                color_cmap(i % color_cmap.N) for i in range(max(len(ci["cats"]), 1))
            ]
        _grey = (0.6, 0.6, 0.6, 1.0)
        single_color = p.mark_color or _DEFAULT_COLOR

        def base_row_colors(mask: Any) -> list:
            """RGBA per masked row for the discrete / single colour cases."""
            if color_kind == "discrete":
                return [
                    color_palette[c] if c >= 0 else _grey for c in ci["codes"][mask]
                ]
            return [to_rgba(single_color)] * int(mask.sum())

        # --- shape channel -----------------------------------------
        shape_kind, si = _encode(p.shape_by)
        if shape_kind == "continuous":
            notes.append("mark shape can't vary continuously -- using the fixed shape")
            shape_kind, si = "single", {}
        shape_seq = _shape_sequence(p.kind, p.shape_map)
        if shape_kind == "discrete" and len(si["cats"]) > len(shape_seq):
            notes.append(_STYLE_OVERFLOW_NOTE)

        # --- size channel --------------------------------------
        size_kind, zi = _encode(p.size_by)
        if p.kind == "scatter":
            z_lo, z_hi = float(p.size_min), float(p.size_max)
        else:
            z_lo, z_hi = float(p.width_min), float(p.width_max)
        size_row = (
            z_lo + zi["frac"] * (z_hi - z_lo) if size_kind != "single" else None
        )
        fixed_size = float(p.point_size) if p.kind == "scatter" else float(p.line_width)
        if size_kind != "single" and p.kind == "bar":
            notes.append("size styling has no effect on bars")

        # --- alpha channel ------------------------------------
        alpha_kind, ai = _encode(p.alpha_by)
        fixed_alpha = float(p.alpha)
        alpha_row = (
            float(p.alpha_min) + ai["frac"] * (float(p.alpha_max) - float(p.alpha_min))
            if alpha_kind != "single"
            else None
        )

        combined = (
            color_kind == "discrete"
            and shape_kind == "discrete"
            and (p.color_by or "").strip() == (p.shape_by or "").strip()
        )
        legend_label = p.legend_title or (p.color_by or "").strip()

        marginals_on = bool(p.show_marginals) and p.kind == "scatter"

        with _plot_context(plt):
            if marginals_on:
                fig, ax, ax_top, ax_right = _new_joint_figure(p)
            else:
                fig, ax = _new_figure(p)

            # -- scatter --------------------------------------------
            if p.kind == "scatter":
                shape_groups = (
                    [(gi, si["codes"] == gi) for gi in range(len(si["cats"]))]
                    if shape_kind == "discrete"
                    else [(0, all_rows)]
                )
                colorbar_sc = None
                for gi, gmask in shape_groups:
                    marker = (
                        shape_seq[gi % len(shape_seq)]
                        if shape_kind == "discrete"
                        else _MARKER_SHAPES.get(p.marker_shape, "o")
                    )
                    s_val = size_row[gmask] if size_kind != "single" else fixed_size
                    if color_kind == "continuous":
                        a_val = alpha_row[gmask] if alpha_kind != "single" else fixed_alpha
                        colorbar_sc = ax.scatter(
                            x[gmask], y[gmask], c=ci["num"][gmask], s=s_val,
                            marker=marker, cmap=color_cmap, norm=color_norm, alpha=a_val,
                        )
                    elif alpha_kind != "single":
                        av = np.atleast_1d(alpha_row[gmask])
                        cols = [
                            (r, g, b, float(av[i] if av.size > 1 else av[0]))
                            for i, (r, g, b, _a) in enumerate(base_row_colors(gmask))
                        ]
                        ax.scatter(x[gmask], y[gmask], s=s_val, marker=marker, c=cols)
                    else:
                        ax.scatter(
                            x[gmask], y[gmask], s=s_val, marker=marker,
                            c=base_row_colors(gmask), alpha=fixed_alpha,
                        )
                if (
                    color_kind == "continuous"
                    and p.show_legend
                    and colorbar_sc is not None
                ):
                    fig.colorbar(colorbar_sc, ax=ax, label=legend_label)

            # -- line -------------------------------------------
            elif p.kind == "line":
                if p.line_stack and color_kind == "discrete":
                    # ax.stackplot needs every group's y aligned on one
                    # shared, ordered x axis (0 for an x value a group
                    # has no rows at).
                    x_arr = np.asarray(x)
                    x_values = sorted(set(x_arr.tolist()))
                    stacks = []
                    for cgi in range(len(ci["cats"])):
                        gmask = ci["codes"] == cgi
                        gy = np.asarray(y)[gmask]
                        gx = x_arr[gmask]
                        stacks.append(
                            [float(gy[gx == xv].sum()) for xv in x_values]
                        )
                    ax.stackplot(
                        x_values, *stacks,
                        labels=[str(c) for c in ci["cats"]],
                        colors=color_palette, alpha=fixed_alpha,
                    )
                    if shape_kind == "discrete":
                        notes.append("shape styling has no effect on stacked lines")
                else:
                    if p.line_stack:
                        notes.append(
                            "line_stack needs a discrete colour-by column -- "
                            "showing overlaid lines"
                        )
                    color_groups = (
                        [(cgi, ci["codes"] == cgi) for cgi in range(len(ci["cats"]))]
                        if color_kind == "discrete"
                        else [(0, all_rows)]
                    )
                    shape_groups = (
                        [(sgi, si["codes"] == sgi) for sgi in range(len(si["cats"]))]
                        if shape_kind == "discrete"
                        else [(0, all_rows)]
                    )
                    for cgi, cmask in color_groups:
                        if color_kind == "discrete":
                            line_color = color_palette[cgi]
                        elif color_kind == "continuous":
                            frac = (
                                float(color_norm(np.nanmean(ci["num"])))
                                if np.isfinite(ci["num"]).any()
                                else 0.5
                            )
                            line_color = color_cmap(frac)
                        else:
                            line_color = single_color
                        for sgi, smask in shape_groups:
                            mask = cmask & smask
                            if not mask.any():
                                continue
                            ls = (
                                shape_seq[sgi % len(shape_seq)]
                                if shape_kind == "discrete"
                                else _LINE_STYLES.get(p.line_style, "-")
                            )
                            lw = (
                                float(np.nanmean(size_row[mask]))
                                if size_kind != "single"
                                else fixed_size
                            )
                            la = (
                                float(np.nanmean(alpha_row[mask]))
                                if alpha_kind != "single"
                                else fixed_alpha
                            )
                            xm = np.asarray(x[mask])
                            order = np.argsort(xm)
                            xs, ys = xm[order], np.asarray(y[mask])[order]
                            ax.plot(
                                xs, ys, color=line_color, linestyle=ls,
                                linewidth=lw, alpha=la,
                            )
                            if p.line_fill:
                                ax.fill_between(
                                    xs, 0, ys, color=line_color,
                                    alpha=min(la, 0.3),
                                )

            # -- bar -------------------------------------------
            else:
                hatch_single = _BAR_HATCHES.get(p.bar_hatch)
                if color_kind == "discrete":
                    x_values = list(dict.fromkeys(x.tolist()))
                    base = np.arange(len(x_values))
                    span = 0.8
                    bottoms = [0.0] * len(x_values)
                    groups_n = max(len(ci["cats"]), 1)
                    for i, cat in enumerate(ci["cats"]):
                        sub = df[ci["codes"] == i]
                        errors = None
                        if p.bar_error != "none":
                            grouped = [
                                pd.to_numeric(
                                    sub.loc[sub[p.x] == xv, p.y], errors="coerce"
                                ).dropna().to_numpy("float64")
                                for xv in x_values
                            ]
                            heights = [float(v.mean()) if v.size else 0.0 for v in grouped]
                            errors = [_bar_error_value(v, p.bar_error) for v in grouped]
                        else:
                            heights = [
                                float(sub.loc[sub[p.x] == xv, p.y].sum()) for xv in x_values
                            ]
                        hatch = (
                            shape_seq[i % len(shape_seq)] if combined else hatch_single
                        )
                        alpha_v = (
                            min(fixed_alpha, 0.6)
                            if p.bar_mode == "layer"
                            else fixed_alpha
                        )
                        common = dict(
                            color=color_palette[i], hatch=hatch, alpha=alpha_v,
                            label=str(cat),
                        )
                        if errors is not None:
                            common["yerr"] = errors
                            common["capsize"] = 4
                        if p.bar_mode == "dodge":
                            w = span / groups_n
                            ax.bar(
                                base + i * w - span / 2 + w / 2, heights, width=w,
                                **common,
                            )
                        elif p.bar_mode == "stack":
                            ax.bar(base, heights, width=span, bottom=bottoms, **common)
                            bottoms = [b + h for b, h in zip(bottoms, heights)]
                        else:
                            ax.bar(base, heights, width=span, **common)
                    ax.set_xticks(base)
                    ax.set_xticklabels([str(xv) for xv in x_values])
                    if shape_kind == "discrete" and not combined:
                        notes.append(
                            f"shape styling by {si['name']!r} is not shown on grouped bars"
                        )
                elif p.bar_error != "none":
                    # aggregated (mean +/- error) bars, one per unique x --
                    # per-row shape/opacity styling doesn't apply to an
                    # aggregate of several rows, so it's skipped (noted below).
                    x_arr = np.asarray(x)
                    x_values = list(dict.fromkeys(x.tolist()))
                    base = np.arange(len(x_values))
                    grouped = [
                        pd.to_numeric(y[x_arr == xv], errors="coerce")
                        .dropna().to_numpy("float64")
                        for xv in x_values
                    ]
                    heights = [float(v.mean()) if v.size else 0.0 for v in grouped]
                    errors = [_bar_error_value(v, p.bar_error) for v in grouped]
                    if color_kind == "continuous":
                        group_means = np.array(
                            [
                                float(np.nanmean(ci["num"][x_arr == xv]))
                                for xv in x_values
                            ]
                        )
                        bar_colors = color_cmap(color_norm(group_means))
                    else:
                        bar_colors = single_color
                    bars = ax.bar(
                        base, heights, yerr=errors, capsize=4,
                        color=bar_colors, alpha=fixed_alpha,
                    )
                    if hatch_single:
                        for rect in bars:
                            rect.set_hatch(hatch_single)
                    ax.set_xticks(base)
                    ax.set_xticklabels([str(xv) for xv in x_values])
                    if shape_kind == "discrete" or alpha_kind != "single":
                        notes.append(
                            "shape / opacity styling has no effect on "
                            "confidence-interval bars"
                        )
                    if color_kind == "continuous" and p.show_legend:
                        sm = plt.cm.ScalarMappable(norm=color_norm, cmap=color_cmap)
                        sm.set_array([])
                        fig.colorbar(sm, ax=ax, label=legend_label)
                else:
                    if color_kind == "continuous":
                        bar_colors = color_cmap(color_norm(ci["num"]))
                    else:
                        bar_colors = single_color
                    bars = ax.bar(x, y, color=bar_colors)
                    for j, rect in enumerate(bars):
                        if shape_kind == "discrete":
                            code = si["codes"][j]
                            rect.set_hatch(
                                shape_seq[int(code) % len(shape_seq)]
                                if code >= 0
                                else None
                            )
                        elif hatch_single:
                            rect.set_hatch(hatch_single)
                        rect.set_alpha(
                            float(alpha_row[j])
                            if alpha_kind != "single"
                            else fixed_alpha
                        )
                    if color_kind == "continuous" and p.show_legend:
                        sm = plt.cm.ScalarMappable(norm=color_norm, cmap=color_cmap)
                        sm.set_array([])
                        fig.colorbar(sm, ax=ax, label=legend_label)

            # -- legends -------------------------------------
            legends: list[tuple[str, list]] = []
            if p.show_legend and color_kind == "discrete" and ci["cats"]:
                legends.append(
                    (
                        legend_label,
                        _encoding_handles(
                            p.kind, ci["cats"], colors=color_palette,
                            shape_seq=shape_seq if combined else None,
                        ),
                    )
                )
            if (
                p.show_legend
                and shape_kind == "discrete"
                and si["cats"]
                and not combined
            ):
                title = si["name"] if legends else (p.legend_title or si["name"])
                legends.append(
                    (
                        title,
                        _encoding_handles(
                            p.kind, si["cats"], colors=None, shape_seq=shape_seq
                        ),
                    )
                )
            _place_legends(ax, p, legends)

            if notes:
                fig.text(
                    0.99, 0.01, "  ·  ".join(dict.fromkeys(notes)),
                    ha="right", va="bottom",
                    fontsize=max(p.legend_font_size - 2, 6), style="italic", color="0.4",
                )

            if marginals_on:
                if color_kind == "discrete":
                    for cgi in range(len(ci["cats"])):
                        gmask = ci["codes"] == cgi
                        _draw_marginals(
                            ax_top, ax_right,
                            np.asarray(x)[gmask], np.asarray(y)[gmask],
                            kind=p.marginal_kind, color=color_palette[cgi],
                        )
                else:
                    _draw_marginals(
                        ax_top, ax_right, np.asarray(x), np.asarray(y),
                        kind=p.marginal_kind,
                        color=_grey if color_kind == "continuous" else single_color,
                    )

            _finalize_plot(fig, ax, p, default_xlabel=p.x, default_ylabel=p.y)

        return {"figure": fig}


# ==========================================================================
# Table viewer -- a small DataFrame rendered as a previewable table figure
# ==========================================================================


#: Table styling presets (see ``TableViewerParams.style``), chosen to
#: cover the table conventions most often seen in data/scientific
#: writing: a shaded "dashboard" look (this node's original default,
#: kept as-is), academic three-line tables (APA / most journals), a
#: plain full grid, alternating (zebra) stripes, and a border-free
#: minimalist look.
_TABLE_STYLES = ("shaded", "three_line", "grid", "striped", "minimal")


def _apply_table_style(
    table: Any, n_data_rows: int, style: str, header_color: Any
) -> None:
    """Border / shading preset for one ``ax.table`` (see ``_TABLE_STYLES``)."""
    for (r, _c), cell in table.get_celld().items():
        cell.set_text_props(weight="bold" if r == 0 else "normal")
        if style == "grid":
            cell.set_facecolor("white")
            cell.set_edgecolor("0.6")
            cell.visible_edges = "closed"
        elif style == "striped":
            cell.set_facecolor(
                (0.95, 0.95, 0.97, 1.0) if (r > 0 and r % 2 == 0) else "white"
            )
            cell.set_edgecolor("0.3")
            cell.visible_edges = "B" if r == 0 else ""
        elif style == "minimal":
            cell.set_facecolor("none")
            cell.set_edgecolor("0.2")
            cell.visible_edges = "B" if r == 0 else ""
        elif style == "three_line":
            cell.set_facecolor("none")
            cell.set_edgecolor("0.15")
            cell.set_linewidth(1.1)
            if r == 0:
                cell.visible_edges = "TB"
            elif r == n_data_rows:
                cell.visible_edges = "B"
            else:
                cell.visible_edges = ""
        else:  # "shaded" -- the original look
            cell.set_edgecolor("0.75")
            cell.visible_edges = "closed"
            if r == 0:
                cell.set_facecolor(header_color)
            elif r % 2 == 0:
                cell.set_facecolor((0.965, 0.965, 0.975, 1.0))
            else:
                cell.set_facecolor("white")


class TableViewerParams(NodeParams):
    """
    Parameters for TableViewer.

    Attributes:
        decimals: Rounding for numeric columns.
        max_rows / max_cols: Show at most this many rows / columns; the
            rest are dropped and a note is printed on the figure. This
            node is for a small, presentation-sized table -- not for
            browsing a full DataFrame (use the Table tab for that).
        show_index: Include the DataFrame index as a leading column.
        font_size: Cell text size.
        style: Table styling preset -- "shaded" (fill + zebra rows),
            "three_line" (the academic three-rule look used by APA and
            most journals: a rule above and below the header, one at
            the bottom, no vertical lines), "grid" (a full border on
            every cell), "striped" (zebra rows, no borders), or
            "minimal" (no lines at all but a header underline).
        header_color: Fill colour of the header row ("shaded" only).
        row_height: Vertical scale of the cells (1.0 = matplotlib default).
        padding: Empty margin between the figure edge and the table, as
            a fraction of the figure (so the table doesn't touch the
            window edge).
        the remaining fields: figure size + title styling.
    """

    decimals: int = 2
    max_rows: int = 30
    max_cols: int = 12
    show_index: bool = False
    font_size: int = 9
    style: Literal["shaded", "three_line", "grid", "striped", "minimal"] = "shaded"
    header_color: str = color_field(
        suggestions=["#cfe2f3", "#d9ead3", "#fce5cd", "lightgrey", "white"],
        default="#cfe2f3",
        visible_when=("style", "shaded"),
        description="Header row fill colour.",
    )
    row_height: float = 1.5
    padding: float = unit_interval_field(
        0.08, lo=0.0, hi=0.3,
        description="Empty margin between the figure edge and the table.",
    )
    fig_width: float = 6.0
    fig_height: float = 5.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class TableViewer(Node):
    """Render a (small) DataFrame as a table image, previewable like a plot."""

    node_type = "table_viewer"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = TableViewerParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
        from matplotlib.colors import to_rgba
        from pandas.api.types import is_bool_dtype, is_numeric_dtype

        p = self.params
        df = inputs["df"]
        n_rows, n_cols = df.shape

        notes: list[str] = []
        show = df
        if p.max_cols and n_cols > int(p.max_cols):
            show = show.iloc[:, : int(p.max_cols)]
            notes.append(f"{int(p.max_cols)} of {n_cols} columns")
        if p.max_rows and n_rows > int(p.max_rows):
            show = show.iloc[: int(p.max_rows), :]
            notes.append(f"{int(p.max_rows)} of {n_rows} rows")

        disp = show.copy()
        for col in disp.columns:
            if is_numeric_dtype(disp[col]) and not is_bool_dtype(disp[col]):
                disp[col] = disp[col].round(int(p.decimals))

        cell_text = [
            ["" if pd.isna(v) else str(v) for v in row] for row in disp.to_numpy()
        ]
        col_labels = [str(c) for c in disp.columns]
        row_labels = [str(i) for i in disp.index] if p.show_index else None
        if not cell_text:
            cell_text = [[""] * max(len(col_labels), 1)]

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            ax.axis("off")
            pad = float(p.padding)
            table = ax.table(
                cellText=cell_text,
                colLabels=col_labels,
                rowLabels=row_labels,
                cellLoc="center",
                bbox=(pad, pad, 1 - 2 * pad, 1 - 2 * pad),
            )
            table.auto_set_font_size(False)
            table.set_fontsize(int(p.font_size))
            table.scale(1.0, max(float(p.row_height), 0.5))

            header_rgba = to_rgba(p.header_color or "#cfe2f3")
            _apply_table_style(table, len(cell_text), p.style, header_rgba)

            try:
                table.auto_set_column_width(col=list(range(len(col_labels))))
            except Exception:  # noqa: BLE001 - width heuristic is best-effort
                pass

            if p.title:
                ax.set_title(
                    p.title,
                    fontsize=p.title_font_size,
                    fontweight="bold" if p.title_bold else "normal",
                    fontstyle="italic" if p.title_italic else "normal",
                )
            if notes:
                fig.text(
                    0.99, 0.01, "showing " + ", ".join(notes), ha="right", va="bottom",
                    fontsize=7, style="italic", color="0.4",
                )
            fig.tight_layout()

        return {"figure": fig}


def _stat_box_bounds(values: Any, box_stat: str, std_k: float, confidence_level: float) -> tuple[float, float]:
    """(low, high) for one group's custom stat box -- mean +/- k*std, or a
    t-based confidence interval around the mean. ``values`` is already
    numeric with NaNs removed."""
    import numpy as np

    arr = np.asarray(values, dtype="float64")
    mean = float(np.mean(arr)) if arr.size else 0.0
    if arr.size < 2:
        return mean, mean
    std = float(np.std(arr, ddof=1))
    if box_stat == "std_dev":
        half = std * float(std_k)
    else:  # "ci"
        from scipy import stats as _spstats

        sem = std / np.sqrt(arr.size)
        t = float(_spstats.t.ppf((1 + float(confidence_level)) / 2, df=arr.size - 1))
        half = t * sem
    return mean - half, mean + half


def _draw_stat_box(
    ax: Any, df: Any, category_column: str, value_column: str,
    hue_col: str | None, box_stat: str, std_k: float, confidence_level: float,
    colors: list, single_color: str, vertical: bool, alpha: float,
) -> tuple[list, list]:
    """
    Draw a box per category (per hue sub-group, if ``hue_col``) spanning
    a mean +/- std / CI range instead of seaborn's quartile box -- see
    ``BoxPlotParams.box_stat``. Returns (categories, legend_handles).
    """
    import pandas as pd
    from matplotlib.patches import Patch

    categories = list(dict.fromkeys(df[category_column].tolist()))
    hue_cats = list(dict.fromkeys(df[hue_col].tolist())) if hue_col else [None]
    n_groups = max(len(hue_cats), 1)
    span = 0.7
    handles: list = []

    for hi, hue_val in enumerate(hue_cats):
        color = colors[hi] if hue_col else (single_color or _DEFAULT_COLOR)
        if hue_col:
            handles.append(Patch(facecolor=color, label=str(hue_val)))
        for ci, cat in enumerate(categories):
            sub = df[df[category_column] == cat]
            if hue_col:
                sub = sub[sub[hue_col] == hue_val]
            values = pd.to_numeric(sub[value_column], errors="coerce").dropna().to_numpy("float64")
            if values.size == 0:
                continue
            lo, hi_val = _stat_box_bounds(values, box_stat, std_k, confidence_level)
            mean = (lo + hi_val) / 2

            if hue_col:
                w = span / n_groups
                pos = ci + hi * w - span / 2 + w / 2
                width = w * 0.9
            else:
                pos, width = float(ci), span

            if vertical:
                ax.bar(
                    pos, hi_val - lo, bottom=lo, width=width, color=color,
                    alpha=alpha, edgecolor="0.2", linewidth=1.0, zorder=3,
                )
                ax.plot(
                    [pos - width / 2, pos + width / 2], [mean, mean],
                    color="0.15", linewidth=1.4, zorder=4,
                )
            else:
                ax.barh(
                    pos, hi_val - lo, left=lo, height=width, color=color,
                    alpha=alpha, edgecolor="0.2", linewidth=1.0, zorder=3,
                )
                ax.plot(
                    [mean, mean], [pos - width / 2, pos + width / 2],
                    color="0.15", linewidth=1.4, zorder=4,
                )

    ticks = list(range(len(categories)))
    labels = [str(c) for c in categories]
    if vertical:
        ax.set_xticks(ticks)
        ax.set_xticklabels(labels)
        ax.set_xlim(-0.5, len(categories) - 0.5)
    else:
        ax.set_yticks(ticks)
        ax.set_yticklabels(labels)
        ax.set_ylim(-0.5, len(categories) - 0.5)
    return categories, handles


class BoxPlotParams(NodeParams):
    """
    Parameters for BoxPlot.

    Attributes:
        category_column: The categorical axis.
        value_column: The numeric axis.
        kind: One of seaborn's categorical plots -- "box", "violin",
            "boxen" or "swarm".
        orientation: Whether the categorical axis is x (vertical boxes)
            or y (horizontal boxes).
        point_size: Marker size for the "swarm" kind only.
        swarm_max_points: For "swarm", if the data has more rows than
            this a seeded random subsample is drawn (and noted on the
            figure) so the plot stays responsive.
        alpha: Fill opacity of the box / violin / boxen / swarm points.
        show_outliers: Show individual outlier points beyond the
            whiskers (box / boxen only; ignored for violin/swarm, which
            have no "outlier" concept of their own).
        box_stat: What the box spans (box kind only): "iqr" (the
            default -- Q1 to Q3, whiskers per the usual 1.5x-IQR rule),
            "std_dev" (mean +/- ``std_k`` standard deviations) or "ci"
            (a ``confidence_level`` confidence interval around the
            mean). The std_dev / ci boxes are drawn directly (not by
            seaborn) and show no whiskers or outlier points.
        std_k: Standard-deviation multiplier for ``box_stat="std_dev"``.
        confidence_level: Confidence level for ``box_stat="ci"``.
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
    kind: Literal["box", "violin", "boxen", "swarm"] = "box"
    orientation: Literal["vertical", "horizontal"] = "vertical"
    point_size: float = visible_field(
        4.0, visible_when=("kind", "swarm"), description="Swarm marker size."
    )
    swarm_max_points: int = visible_field(
        2000,
        visible_when=("kind", "swarm"),
        description="Rows above this are randomly subsampled (seeded) for the swarm.",
    )
    alpha: float = unit_interval_field(
        0.9, description="Fill opacity of the box / violin / boxen / swarm points."
    )
    show_outliers: bool = visible_field(
        True,
        visible_when_in=("kind", ("box", "boxen")),
        description="Show individual outlier points beyond the whiskers.",
    )
    box_stat: Literal["iqr", "std_dev", "ci"] = visible_field(
        "iqr",
        visible_when=("kind", "box"),
        description="What the box spans: the interquartile range, "
        "mean +/- k*std, or a confidence interval around the mean.",
    )
    std_k: float = visible_field(
        1.0,
        visible_when=("box_stat", "std_dev"),
        description="Standard-deviation multiplier for the std_dev box.",
    )
    confidence_level: float = unit_interval_field(
        0.95, lo=0.5, hi=0.999,
        visible_when=("box_stat", "ci"),
        description="Confidence level for the ci box.",
    )

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
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
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
    """box / violin / boxen / swarm plot of a numeric column across a
    categorical one (seaborn's categorical-plot family)."""

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

        plot_fn = {
            "box": sns.boxplot,
            "violin": sns.violinplot,
            "boxen": sns.boxenplot,
            "swarm": sns.swarmplot,
        }[p.kind]

        plot_df = df
        note = ""
        if p.kind == "swarm" and len(df) > max(int(p.swarm_max_points), 1):
            plot_df = df.sample(int(p.swarm_max_points), random_state=0)
            note = (
                f"swarm: {int(p.swarm_max_points):,} of {len(df):,} rows "
                f"(seeded random subsample)"
            )

        custom_box = p.kind == "box" and p.box_stat != "iqr"

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            vertical = p.orientation == "vertical"
            axis_kw = (
                {"x": p.category_column, "y": p.value_column}
                if vertical
                else {"x": p.value_column, "y": p.category_column}
            )

            if custom_box:
                if hue:
                    cmap = plt.get_cmap(p.colormap or "tab10")
                    hue_cats = list(dict.fromkeys(df[hue].tolist()))
                    box_colors = [cmap(i % cmap.N) for i in range(len(hue_cats))]
                else:
                    box_colors = []
                _categories, handles = _draw_stat_box(
                    ax, plot_df, p.category_column, p.value_column, hue,
                    p.box_stat, float(p.std_k), float(p.confidence_level),
                    box_colors, p.single_color or _DEFAULT_COLOR, vertical, float(p.alpha),
                )
                if hue and p.show_legend and handles:
                    _place_legend(ax, p, p.legend_title or hue, handles=handles)
                else:
                    _remove_legend(ax)
            else:
                draw_kw: dict[str, Any] = {"data": plot_df, "ax": ax, **axis_kw}
                if hue:
                    draw_kw["hue"] = hue
                    draw_kw["palette"] = p.colormap or "tab10"
                else:
                    draw_kw["color"] = p.single_color or _DEFAULT_COLOR
                if p.kind == "swarm":
                    draw_kw["size"] = float(p.point_size)
                if p.kind in ("box", "boxen"):
                    draw_kw["showfliers"] = bool(p.show_outliers)

                plot_fn(**draw_kw)

                for artist in list(ax.patches) + list(ax.collections):
                    artist.set_alpha(float(p.alpha))

                if hue and p.show_legend:
                    _place_legend(ax, p, p.legend_title or hue)
                else:
                    _remove_legend(ax)

            if note:
                fig.text(
                    0.99, 0.01, note, ha="right", va="bottom",
                    fontsize=max(p.legend_font_size - 2, 6), style="italic", color="0.4",
                )

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
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
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

        with _plot_context(plt):
            fig, ax = _new_figure(p)
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
    colormap: str = colormap_field(kind="continuous", default="viridis")
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

        with _plot_context(plt):
            fig, ax = _new_figure(p)
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


# ==========================================================================
# Model-visualization plots (consume a fitted model + a held-out X / y)
# ==========================================================================

_MODEL_PLOT_INPUTS = [
    Port(name="model", dtype="model"),
    Port(name="X", dtype="dataframe"),
    Port(name="y", dtype="array"),
]


def _aligned_X(node_inputs: dict) -> Any:
    from ruyso_app.nodes.model_ops import align_features_to_model

    return align_features_to_model(node_inputs["X"], node_inputs["model"])


def _model_classes(model: Any, y: Any) -> list:
    import numpy as np

    return list(getattr(model, "classes_", np.unique(np.asarray(y))))


def _class_scores(model: Any, X: Any) -> Any:
    """(n_samples, n_classes) probability / score matrix for OvR curves."""
    import numpy as np

    if hasattr(model, "predict_proba"):
        return np.asarray(model.predict_proba(X))
    if hasattr(model, "decision_function"):
        raw = np.asarray(model.decision_function(X))
        return raw if raw.ndim == 2 else np.c_[-raw, raw]
    raise ValueError(
        "this plot needs a classifier with predict_proba or decision_function."
    )


def _require_classifier(model: Any, what: str) -> None:
    from sklearn.base import is_classifier

    if not is_classifier(model):
        raise ValueError(f"{what}: this plot needs a classification model.")


def _require_regressor(model: Any, what: str) -> None:
    from sklearn.base import is_classifier

    if is_classifier(model):
        raise ValueError(f"{what}: this plot needs a regression model.")


def _curve_legend(ax: Any, p: Any) -> None:
    if getattr(p, "show_legend", True):
        _place_legend(ax, p, getattr(p, "legend_title", "") or "")
    else:
        _remove_legend(ax)


# -- confusion matrix ----------------------------------------------------


class ConfusionMatrixPlotParams(NodeParams):
    """
    Parameters for ConfusionMatrixPlot.

    Attributes:
        normalize: "none" (counts) / "true" (row) / "pred" (column) /
            "all" proportions.
        colormap: Sequential colormap for the cells.
        annotate: Write each cell's value.
        colorbar: Draw the colour scale.
    """

    normalize: Literal["none", "true", "pred", "all"] = "none"
    colormap: str = colormap_field(kind="continuous", default="Blues")
    annotate: bool = True
    colorbar: bool = True

    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    show_grid: bool = False
    show_box: bool = True
    fig_width: float = 6.0
    fig_height: float = 4.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class ConfusionMatrixPlot(Node):
    """Confusion matrix of a classifier on a held-out (X, y)."""

    node_type = "confusion_matrix_plot"
    category = "grapher"
    inputs = list(_MODEL_PLOT_INPUTS)
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = ConfusionMatrixPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.metrics import ConfusionMatrixDisplay

        p = self.params
        model = inputs["model"]
        _require_classifier(model, "confusion_matrix_plot")
        X = _aligned_X(inputs)

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            ConfusionMatrixDisplay.from_estimator(
                model,
                X,
                inputs["y"],
                ax=ax,
                normalize=None if p.normalize == "none" else p.normalize,
                cmap=p.colormap,
                colorbar=bool(p.colorbar),
                include_values=bool(p.annotate),
            )
            _finalize_plot(
                fig, ax, p,
                default_xlabel="Predicted label", default_ylabel="True label",
                frame=False,
            )
        return {"figure": fig}


# -- ROC / precision-recall / DET (share the same shape) ----------------


class _CurvePlotParams(NodeParams):
    """Common fields for the ROC / precision-recall / DET nodes."""

    show_chance_level: bool = True
    line_color: str = color_field(
        suggestions=_COMMON_COLORS,
        default=_DEFAULT_COLOR,
        description="Curve colour for a binary target.",
    )
    colormap: str = colormap_field(kind="qualitative", default="tab10")  # per-class, multiclass
    line_width: float = 1.6

    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.0
    fig_height: float = 5.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = True
    legend_title: str = ""
    legend_location: _LEGEND_LOCATIONS = "best"
    legend_font_size: int = 9


def _draw_ovr_curve(
    node: Node, inputs: dict, kind: str, *, default_xlabel: str, default_ylabel: str
) -> Any:
    """Shared body for the ROC / precision-recall / DET nodes.

    ``kind`` is "roc", "pr" or "det".
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.metrics import (
        DetCurveDisplay,
        PrecisionRecallDisplay,
        RocCurveDisplay,
    )

    p = node.params
    model = inputs["model"]
    _require_classifier(model, f"{kind}_plot")
    X = _aligned_X(inputs)
    y = inputs["y"]
    classes = _model_classes(model, y)
    display = {"roc": RocCurveDisplay, "pr": PrecisionRecallDisplay, "det": DetCurveDisplay}[kind]
    supports_chance = kind in ("roc", "pr")

    def _style_kw(colour: Any) -> dict[str, Any]:
        # DET keeps the old ``**kwargs`` passthrough; ROC / PR moved the
        # line styling into a ``curve_kwargs`` dict in newer scikit-learn.
        line = {"color": colour, "linewidth": p.line_width}
        return line if kind == "det" else {"curve_kwargs": line}

    with _plot_context(plt):
        fig, ax = _new_figure(p)

        if len(classes) <= 2:
            kw: dict[str, Any] = {
                "ax": ax,
                "name": str(classes[-1]) if classes else "positive",
                **_style_kw(p.line_color or _DEFAULT_COLOR),
            }
            if supports_chance:
                kw["plot_chance_level"] = bool(p.show_chance_level)
            display.from_estimator(model, X, y, **kw)
        else:
            from sklearn.preprocessing import label_binarize

            scores = _class_scores(model, X)
            y_bin = label_binarize(y, classes=classes)
            cmap = plt.get_cmap(p.colormap)
            for i, cls in enumerate(classes):
                kw = {"ax": ax, "name": str(cls), **_style_kw(cmap(i % cmap.N))}
                if supports_chance and i == 0:
                    kw["plot_chance_level"] = bool(p.show_chance_level)
                display.from_predictions(y_bin[:, i], scores[:, i], **kw)

        _curve_legend(ax, p)
        _finalize_plot(
            fig, ax, p, default_xlabel=default_xlabel, default_ylabel=default_ylabel
        )
    return fig


@register_node
class RocCurvePlot(Node):
    """ROC curve(s) for a classifier (one-vs-rest when multiclass)."""

    node_type = "roc_curve_plot"
    category = "grapher"
    inputs = list(_MODEL_PLOT_INPUTS)
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = _CurvePlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {
            "figure": _draw_ovr_curve(
                self, inputs, "roc",
                default_xlabel="False positive rate",
                default_ylabel="True positive rate",
            )
        }


@register_node
class PrecisionRecallPlot(Node):
    """Precision-recall curve(s) for a classifier (one-vs-rest when multiclass)."""

    node_type = "precision_recall_plot"
    category = "grapher"
    inputs = list(_MODEL_PLOT_INPUTS)
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = _CurvePlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {
            "figure": _draw_ovr_curve(
                self, inputs, "pr",
                default_xlabel="Recall", default_ylabel="Precision",
            )
        }


@register_node
class DetCurvePlot(Node):
    """Detection-error-tradeoff curve(s) for a classifier."""

    node_type = "det_curve_plot"
    category = "grapher"
    inputs = list(_MODEL_PLOT_INPUTS)
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = _CurvePlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        return {
            "figure": _draw_ovr_curve(
                self, inputs, "det",
                default_xlabel="False positive rate",
                default_ylabel="False negative rate",
            )
        }


# -- calibration curve -------------------------------------------------


class CalibrationCurvePlotParams(NodeParams):
    """
    Parameters for CalibrationCurvePlot (binary classifiers only).

    Attributes:
        n_bins: Number of probability bins.
        strategy: "uniform" (equal-width bins) or "quantile"
            (equal-count bins).
        show_reference_line: Draw the perfectly-calibrated diagonal.
    """

    n_bins: int = 10
    strategy: Literal["uniform", "quantile"] = "uniform"
    show_reference_line: bool = True
    line_color: str = color_field(suggestions=_COMMON_COLORS, default=_DEFAULT_COLOR)

    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.0
    fig_height: float = 5.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = True
    legend_title: str = ""
    legend_location: _LEGEND_LOCATIONS = "best"
    legend_font_size: int = 9


@register_node
class CalibrationCurvePlot(Node):
    """Reliability (calibration) curve of a binary classifier."""

    node_type = "calibration_curve_plot"
    category = "grapher"
    inputs = list(_MODEL_PLOT_INPUTS)
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = CalibrationCurvePlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.calibration import CalibrationDisplay

        p = self.params
        model = inputs["model"]
        _require_classifier(model, "calibration_curve_plot")
        if len(_model_classes(model, inputs["y"])) != 2:
            raise ValueError(
                "calibration_curve_plot: only binary classifiers are supported."
            )
        X = _aligned_X(inputs)

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            CalibrationDisplay.from_estimator(
                model,
                X,
                inputs["y"],
                ax=ax,
                n_bins=max(int(p.n_bins), 2),
                strategy=p.strategy,
                ref_line=bool(p.show_reference_line),
                color=p.line_color or _DEFAULT_COLOR,
            )
            _curve_legend(ax, p)
            _finalize_plot(
                fig, ax, p,
                default_xlabel="Mean predicted probability",
                default_ylabel="Fraction of positives",
            )
        return {"figure": fig}


# -- learning curve --------------------------------------------------


class LearningCurvePlotParams(NodeParams):
    """
    Parameters for LearningCurvePlot.

    Attributes:
        cv: Number of cross-validation folds at each training size.
        n_points: How many training-set sizes to evaluate.
        scoring: A scikit-learn scoring name (blank = the estimator's
            default). e.g. accuracy / f1 / r2 / neg_mean_squared_error.
        shade_std: Fill the +/-1 std band (off = error bars).
    """

    cv: int = 5
    n_points: int = 5
    scoring: str = ""
    shade_std: bool = True

    train_color: str = color_field(suggestions=_COMMON_COLORS, default="darkorange")
    test_color: str = color_field(suggestions=_COMMON_COLORS, default="darkblue")

    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.0
    fig_height: float = 5.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = True
    legend_title: str = ""
    legend_location: _LEGEND_LOCATIONS = "best"
    legend_font_size: int = 9


@register_node
class LearningCurvePlot(Node):
    """
    Training / cross-validation score vs. training-set size (the model
    is re-fit on growing subsets of the wired X / y).
    """

    node_type = "learning_curve_plot"
    category = "grapher"
    inputs = list(_MODEL_PLOT_INPUTS)
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = LearningCurvePlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from sklearn.base import clone
        from sklearn.model_selection import LearningCurveDisplay

        p = self.params
        model = inputs["model"]
        X = _aligned_X(inputs)

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            LearningCurveDisplay.from_estimator(
                clone(model),
                X,
                inputs["y"],
                ax=ax,
                cv=max(int(p.cv), 2),
                train_sizes=np.linspace(0.1, 1.0, max(int(p.n_points), 2)),
                scoring=p.scoring or None,
                std_display_style="fill_between" if p.shade_std else "errorbar",
                line_kw={"marker": "o"},
            )
            lines = ax.get_lines()
            if len(lines) >= 2:
                lines[0].set_color(p.train_color or "darkorange")
                lines[1].set_color(p.test_color or "darkblue")
            _curve_legend(ax, p)
            _finalize_plot(
                fig, ax, p,
                default_xlabel="Training examples", default_ylabel="Score",
            )
        return {"figure": fig}


# -- QQ plot (regression residuals vs. normal) --------------------------


class QQPlotParams(NodeParams):
    """
    Parameters for QQPlot.

    Attributes:
        standardize: Centre + scale the residuals before plotting.
        point_size: Marker area.
        point_color: Marker colour.
        show_reference_line: Draw the normal reference line.
    """

    standardize: bool = True
    point_size: float = 18.0
    point_color: str = color_field(suggestions=_COMMON_COLORS, default=_DEFAULT_COLOR)
    show_reference_line: bool = True

    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.0
    fig_height: float = 5.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class QQPlot(Node):
    """Normal quantile-quantile plot of a regression model's residuals."""

    node_type = "qq_plot"
    category = "grapher"
    inputs = list(_MODEL_PLOT_INPUTS)
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = QQPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from scipy import stats

        p = self.params
        model = inputs["model"]
        _require_regressor(model, "qq_plot")
        X = _aligned_X(inputs)
        y_true = np.asarray(inputs["y"], dtype="float64")
        residual = y_true - np.asarray(model.predict(X), dtype="float64")
        if p.standardize:
            spread = float(np.std(residual, ddof=1)) or 1.0
            residual = (residual - residual.mean()) / spread

        (theoretical, ordered), (slope, intercept, _r) = stats.probplot(
            residual, dist="norm"
        )

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            ax.scatter(
                theoretical, ordered, s=p.point_size,
                color=p.point_color or _DEFAULT_COLOR,
            )
            if p.show_reference_line:
                ax.plot(
                    theoretical, slope * theoretical + intercept,
                    color="0.4", linestyle="--", linewidth=1.2,
                )
            _finalize_plot(
                fig, ax, p,
                default_xlabel="Theoretical quantiles",
                default_ylabel="Ordered residuals",
            )
        return {"figure": fig}


# ==========================================================================
# Single-variable plots: pie_chart, heatmap_1d, autocorrelogram
# ==========================================================================


class PieChartParams(NodeParams):
    """
    Parameters for PieChart.

    Attributes:
        column: Categorical column to summarize -- each category's
            share is its count of rows.
        style: "pie", "doughnut" (a pie with a hole), or "tile" (a
            waffle-style grid of unit squares, one square per share of
            the total -- often easier to compare by eye than wedge
            angles, especially for close shares).
        top_n: Keep only the N largest categories, grouping the rest
            into "other". 0 = show every category.
        show_percent: Label each wedge with its percentage (pie /
            doughnut only).
        doughnut_width: Ring thickness as a fraction of the radius
            (doughnut only).
        tile_columns: Grid width, in tiles (tile only).
        colormap: Palette for the categories.
        the remaining fields: figure size + title styling + legend.
    """

    column: str = column_field(dtypes=("categorical", "boolean"))
    style: Literal["pie", "doughnut", "tile"] = "pie"
    top_n: int = 0
    show_percent: bool = visible_field(True, visible_unless=("style", "tile"))
    doughnut_width: float = unit_interval_field(
        0.4, lo=0.1, hi=0.9, visible_when=("style", "doughnut"),
    )
    tile_columns: int = visible_field(10, visible_when=("style", "tile"))
    colormap: str = reactive_choice_field(
        options="colormaps", depends_on="column", default="tab10",
    )
    fig_width: float = 6.0
    fig_height: float = 6.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = True
    legend_location: _LEGEND_LOCATIONS = "outside right"
    legend_font_size: int = 9


@register_node
class PieChart(Node):
    """Single-variable share plot: pie, doughnut, or a tile ('waffle') grid."""

    node_type = "pie_chart"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = PieChartParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        from matplotlib.patches import Patch, Rectangle

        p = self.params
        df = inputs["df"]
        if p.column not in df.columns:
            raise ValueError(f"pie_chart: column {p.column!r} is not in the input data.")

        counts = df[p.column].value_counts(dropna=True)
        if counts.empty:
            raise ValueError("pie_chart: no non-missing values to summarize.")
        if p.top_n and len(counts) > int(p.top_n):
            top = counts.iloc[: int(p.top_n)]
            other = float(counts.iloc[int(p.top_n) :].sum())
            counts = pd.concat([top, pd.Series({"other": other})])
        labels = [str(v) for v in counts.index]
        values = counts.to_numpy("float64")
        cmap = plt.get_cmap(p.colormap or "tab10")
        colors = [cmap(i % cmap.N) for i in range(len(values))]

        with _plot_context(plt):
            fig, ax = _new_figure(p)

            if p.style in ("pie", "doughnut"):
                width = float(p.doughnut_width) if p.style == "doughnut" else 1.0
                autopct = (lambda pct: f"{pct:.1f}%") if p.show_percent else None
                ax.pie(
                    values, colors=colors, autopct=autopct,
                    wedgeprops={"width": width, "edgecolor": "white"},
                    pctdistance=1 - width / 2 if p.style == "doughnut" else 0.6,
                )
                ax.set_aspect("equal")
                handles = [Patch(facecolor=c) for c in colors]
            else:  # tile
                cols = max(int(p.tile_columns), 1)
                total = float(values.sum())
                # cap the tile count at ~100 so a large dataset doesn't
                # draw thousands of squares; each tile then represents
                # more than one row.
                unit = total / 100 if total > 100 else 1.0
                tile_counts = [max(int(round(v / unit)), 1 if v > 0 else 0) for v in values]
                cat_of_tile = [i for i, n in enumerate(tile_counts) for _ in range(n)]
                n_tiles = len(cat_of_tile) or 1
                rows = int(np.ceil(n_tiles / cols))
                for idx, cat_i in enumerate(cat_of_tile):
                    r, c = divmod(idx, cols)
                    ax.add_patch(
                        Rectangle(
                            (c, rows - 1 - r), 0.9, 0.9,
                            facecolor=colors[cat_i], edgecolor="white",
                        )
                    )
                ax.set_xlim(0, cols)
                ax.set_ylim(0, rows)
                ax.set_aspect("equal")
                ax.axis("off")
                handles = [Patch(facecolor=c) for c in colors]

            if p.show_legend:
                _place_legend(ax, p, p.column, handles=handles, labels=labels)
            if p.title:
                ax.set_title(
                    p.title, fontsize=p.title_font_size,
                    fontweight="bold" if p.title_bold else "normal",
                    fontstyle="italic" if p.title_italic else "normal",
                )
            fig.tight_layout()
        return {"figure": fig}


class Heatmap1DParams(NodeParams):
    """
    Parameters for Heatmap1D.

    Attributes:
        column: Numeric column to render as a strip of coloured cells
            (value -> colour) -- a single-variable alternative to a
            histogram for spotting a sequence's pattern or outliers at
            a glance.
        columns_per_row: Wrap the strip into a grid this many cells
            wide (0 = one single row) -- e.g. 7 turns a daily series
            into a calendar-style heatmap.
        colormap: Continuous colormap.
        show_colorbar: Draw a colour scale.
        show_values: Print each cell's (rounded) value.
        decimals: Rounding for the printed values.
        the remaining fields: figure size + title styling.
    """

    column: str = column_field(dtypes=("numeric",))
    label_column: str = column_field(
        dtypes=("any",), default="", allow_none=True,
        description="Optional column whose values label the cells along the "
        "strip (used only when the strip is not wrapped).",
    )
    orientation: Literal["horizontal", "vertical"] = "horizontal"
    columns_per_row: int = 0
    colormap: str = reactive_choice_field(
        options="colormaps", depends_on="column", default="viridis",
    )
    show_colorbar: bool = True
    show_values: bool = False
    decimals: int = visible_field(2, visible_when=("show_values", "True"))
    fig_width: float = 6.0
    fig_height: float = 2.2
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class Heatmap1D(Node):
    """
    1D heat map: a numeric column rendered as a strip (or wrapped
    grid) of coloured cells, one cell per value.
    """

    node_type = "heatmap_1d"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = Heatmap1DParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        p = self.params
        df = inputs["df"]
        if p.column not in df.columns:
            raise ValueError(f"heatmap_1d: column {p.column!r} is not in the input data.")
        values = pd.to_numeric(df[p.column], errors="coerce").to_numpy("float64")
        if values.size == 0:
            raise ValueError("heatmap_1d: no values to plot.")

        vertical = p.orientation == "vertical"
        wrapped = int(p.columns_per_row) > 0
        per = int(p.columns_per_row) or values.size
        n_blocks = int(np.ceil(values.size / per))
        padded = np.full(n_blocks * per, np.nan)
        padded[: values.size] = values
        # horizontal: rows = wrap blocks, cols = cells along the strip;
        # vertical: the same laid out as columns (cells run top -> bottom).
        grid = padded.reshape(n_blocks, per)
        if vertical:
            grid = grid.T
        rows, cols = grid.shape

        # the "strip" (cell) axis and how many cells it has
        cell_axis = "y" if vertical else "x"
        n_cells = rows if vertical else cols

        label_col = (p.label_column or "").strip()
        labels: list[str] | None = None
        if label_col and label_col in df.columns and not wrapped:
            labels = [str(v) for v in df[label_col].tolist()[: n_cells]]

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            im = ax.imshow(grid, aspect="auto", cmap=p.colormap or "viridis")
            ax.set_xticks([])
            ax.set_yticks([])
            if labels is not None:
                step = max(1, len(labels) // 30)  # keep the axis readable
                ticks = list(range(0, len(labels), step))
                getattr(ax, f"set_{cell_axis}ticks")(ticks)
                getattr(ax, f"set_{cell_axis}ticklabels")(
                    [labels[i] for i in ticks],
                    rotation=0 if vertical else 90, fontsize=7,
                )
            if p.show_values:
                for r in range(rows):
                    for c in range(cols):
                        v = grid[r, c]
                        if np.isfinite(v):
                            ax.text(
                                c, r, f"{v:.{max(int(p.decimals), 0)}f}",
                                ha="center", va="center", fontsize=7, color="white",
                            )
            if p.show_colorbar:
                fig.colorbar(
                    im, ax=ax,
                    orientation="vertical" if vertical else "horizontal",
                    fraction=0.15, pad=0.15,
                )
            if p.title:
                ax.set_title(
                    p.title, fontsize=p.title_font_size,
                    fontweight="bold" if p.title_bold else "normal",
                    fontstyle="italic" if p.title_italic else "normal",
                )
            fig.tight_layout()
        return {"figure": fig}


class AutocorrelogramParams(NodeParams):
    """
    Parameters for Autocorrelogram.

    Attributes:
        column: Numeric (discrete-time) series column, already ordered
            by time (see the ``sort`` transform).
        show_acf / show_pacf: Which correlogram(s) to draw -- unselect
            one to show only the other; at least one must stay on.
        max_lag: Number of lags to show.
        show_ci: Draw the confidence band (shaded).
        confidence_level: Confidence level for the band.
        pacf_method: Estimation method for the partial ACF.
    """

    column: str = column_field(dtypes=("numeric",))
    show_acf: bool = True
    show_pacf: bool = True
    max_lag: int = 20
    show_ci: bool = True
    confidence_level: float = unit_interval_field(
        0.95, lo=0.5, hi=0.999, visible_when=("show_ci", "True"),
    )
    pacf_method: Literal["ywm", "ywadjusted", "ols", "ld"] = visible_field(
        "ywm", visible_when=("show_pacf", "True"),
    )
    fig_width: float = 6.0
    fig_height: float = 4.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class Autocorrelogram(Node):
    """ACF and/or PACF of a discrete time series, with an optional confidence band."""

    node_type = "autocorrelogram"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = AutocorrelogramParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        p = self.params
        if not p.show_acf and not p.show_pacf:
            raise ValueError("autocorrelogram: at least one of ACF / PACF must be selected.")

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        df = inputs["df"]
        if p.column not in df.columns:
            raise ValueError(f"autocorrelogram: column {p.column!r} is not in the input data.")
        x = pd.to_numeric(df[p.column], errors="coerce").dropna().to_numpy("float64")
        max_lag = max(int(p.max_lag), 1)
        if x.size < max_lag + 2:
            raise ValueError(
                "autocorrelogram: not enough non-missing values for the requested max_lag."
            )

        alpha = (1.0 - float(p.confidence_level)) if p.show_ci else None
        n_plots = int(p.show_acf) + int(p.show_pacf)

        with _plot_context(plt):
            fig, axes = _new_figure(p, n_plots, 1, squeeze=False)
            axes = axes[:, 0]
            i = 0
            if p.show_acf:
                from statsmodels.graphics.tsaplots import plot_acf

                plot_acf(x, lags=max_lag, alpha=alpha, ax=axes[i], title="ACF")
                i += 1
            if p.show_pacf:
                from statsmodels.graphics.tsaplots import plot_pacf

                plot_pacf(
                    x, lags=max_lag, alpha=alpha, ax=axes[i],
                    method=p.pacf_method, title="PACF",
                )
                i += 1
            if p.title:
                fig.suptitle(
                    p.title, fontsize=p.title_font_size,
                    fontweight="bold" if p.title_bold else "normal",
                    fontstyle="italic" if p.title_italic else "normal",
                )
            fig.tight_layout()
        return {"figure": fig}


# ==========================================================================
# 2D density plot
# ==========================================================================


class Density2DParams(NodeParams):
    """
    Parameters for Density2D.

    Attributes:
        x / y: Numeric columns.
        kind: "contour" (a bivariate KDE, contour lines or filled) or
            "hexbin" (binned counts -- scales better to a lot of data).
        color_by: (contour only) a categorical column -- draw one KDE
            per level, each in a single-hue colormap derived from
            ``colormap`` (colour i of the qualitative map -> a
            white->colour ramp). None = a single density.
        fill: Fill the KDE contours (contour only).
        levels: Number of contour levels (contour only).
        gridsize: Hexagon grid resolution (hexbin only).
        colormap: Continuous colormap (no ``color_by``) or the
            qualitative map the per-level ramps are derived from.
        show_points: Overlay the raw (x, y) points, lightly.
        show_marginals / marginal_kind: Add a distribution of x along
            the top and of y along the right; follows ``color_by``.
        show_legend / legend_location / legend_font_size: the
            per-level legend, shown only when ``color_by`` is set.
        the remaining fields: axes + figure size + title styling.
    """

    x: str = column_field(dtypes=("numeric",))
    y: str = column_field(dtypes=("numeric",))
    kind: Literal["contour", "hexbin"] = "contour"
    color_by: str = column_field(
        dtypes=("any",),
        default="",
        allow_none=True,
        visible_when=("kind", "contour"),
        description="Categorical column: one KDE per level, each a single-hue "
        "ramp from 'colormap'. None = one density in 'colormap'.",
    )
    fill: bool = visible_field(True, visible_when=("kind", "contour"))
    levels: int = visible_field(10, visible_when=("kind", "contour"))
    gridsize: int = visible_field(30, visible_when=("kind", "hexbin"))
    colormap: str = reactive_choice_field(
        options="colormaps", depends_on="color_by", default="viridis",
    )
    show_points: bool = False
    show_marginals: bool = False
    marginal_kind: _MARGINAL_KINDS = visible_field(
        "histogram",
        visible_when=("show_marginals", "True"),
        description="Style of the top / right marginal distributions.",
    )
    show_legend: bool = visible_field(True, visible_when_set="color_by")
    legend_location: _LEGEND_LOCATIONS = visible_field(
        "best", visible_when_set="color_by"
    )
    legend_font_size: int = visible_field(9, visible_when_set="color_by")
    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.0
    fig_height: float = 4.5
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class Density2D(Node):
    """2D density of two numeric columns: a bivariate KDE contour, or a hexbin count grid."""

    node_type = "density_2d"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = Density2DParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        p = self.params
        df = inputs["df"]
        for col in (p.x, p.y):
            if col not in df.columns:
                raise ValueError(f"density_2d: column {col!r} is not in the input data.")

        hue_col = (p.color_by or "").strip()
        use_hue = bool(hue_col) and hue_col in df.columns and p.kind == "contour"
        keep = [p.x, p.y] + ([hue_col] if use_hue else [])
        data = df[keep].copy()
        data[p.x] = pd.to_numeric(data[p.x], errors="coerce")
        data[p.y] = pd.to_numeric(data[p.y], errors="coerce")
        data = data.dropna(subset=[p.x, p.y])
        if len(data) < 3:
            raise ValueError("density_2d: need at least 3 complete (x, y) rows.")
        if use_hue:
            _categorical_hue(data, hue_col)  # raises on a continuous hue column

        marginals_on = bool(p.show_marginals)

        def _neutral_marginal_color() -> Any:
            return plt.get_cmap(p.colormap or "viridis")(0.6)

        with _plot_context(plt):
            if marginals_on:
                fig, ax, ax_top, ax_right = _new_joint_figure(p)
            else:
                fig, ax = _new_figure(p)

            if p.kind == "contour" and use_hue:
                import seaborn as sns

                cats = list(pd.Categorical(data[hue_col]).categories)
                base_cmap = plt.get_cmap(p.colormap or "tab10")
                # A per-level palette needs a *qualitative* map; if a
                # continuous one is still selected (its lookup table has
                # 256 entries), fall back so levels 0 and 1 aren't the
                # same colour.
                if getattr(base_cmap, "N", 256) > 32:
                    base_cmap = plt.get_cmap("tab10")
                cat_colors = [base_cmap(i % base_cmap.N) for i in range(len(cats))]
                for i, cat in enumerate(cats):
                    sub = data[data[hue_col] == cat]
                    if len(sub) < 3:
                        continue
                    sns.kdeplot(
                        data=sub, x=p.x, y=p.y, fill=bool(p.fill),
                        levels=max(int(p.levels), 2),
                        cmap=sns.light_palette(cat_colors[i], as_cmap=True), ax=ax,
                    )
                    if p.show_points:
                        ax.scatter(sub[p.x], sub[p.y], s=6, color=cat_colors[i], alpha=0.3)
                    if marginals_on:
                        _draw_marginals(
                            ax_top, ax_right, sub[p.x], sub[p.y],
                            kind=p.marginal_kind, color=cat_colors[i],
                        )
                if p.show_legend and cats:
                    handles = _encoding_handles(
                        "scatter", cats, colors=cat_colors, shape_seq=None
                    )
                    _place_legends(ax, p, [(hue_col, handles)])
            elif p.kind == "contour":
                import seaborn as sns

                sns.kdeplot(
                    data=data, x=p.x, y=p.y, fill=bool(p.fill),
                    levels=max(int(p.levels), 2), cmap=p.colormap or "viridis", ax=ax,
                )
                if p.show_points:
                    ax.scatter(data[p.x], data[p.y], s=6, color="black", alpha=0.25)
                if marginals_on:
                    _draw_marginals(
                        ax_top, ax_right, data[p.x], data[p.y],
                        kind=p.marginal_kind, color=_neutral_marginal_color(),
                    )
            else:
                hb = ax.hexbin(
                    data[p.x], data[p.y], gridsize=max(int(p.gridsize), 4),
                    cmap=p.colormap or "viridis",
                )
                fig.colorbar(hb, ax=ax, label="count")
                if p.show_points:
                    ax.scatter(data[p.x], data[p.y], s=6, color="black", alpha=0.25)
                if marginals_on:
                    _draw_marginals(
                        ax_top, ax_right, data[p.x], data[p.y],
                        kind=p.marginal_kind, color=_neutral_marginal_color(),
                    )

            _finalize_plot(fig, ax, p, default_xlabel=p.x, default_ylabel=p.y)
        return {"figure": fig}


# ==========================================================================
# PCA-specific plots: pca_scree_plot, pca_corr_circle
# ==========================================================================


class PCAScreePlotParams(NodeParams):
    """
    Parameters for PCAScreePlot.

    Attributes:
        show_cumulative: Overlay the cumulative variance-ratio line (on
            a secondary y-axis).
        show_kaiser_line: Draw a reference line at the point where a
            component's own eigenvalue would equal 1 (the Kaiser
            criterion -- keep components above it).
        bar_color / line_color: Colours for the bars / cumulative line.
        the remaining fields: axes + figure size + title styling.
    """

    show_cumulative: bool = True
    show_kaiser_line: bool = False
    bar_color: str = color_field(suggestions=_COMMON_COLORS, default=_DEFAULT_COLOR)
    line_color: str = color_field(
        suggestions=_COMMON_COLORS, default="crimson", visible_when=("show_cumulative", "True"),
    )
    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.0
    fig_height: float = 4.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class PCAScreePlot(Node):
    """
    Scree plot: percentage of variance explained by each PCA
    component (bars), with an optional cumulative line -- takes the
    ``pca`` node's ``variance`` output directly.
    """

    node_type = "pca_scree_plot"
    category = "grapher"
    inputs = [Port(name="variance", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = PCAScreePlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        p = self.params
        variance = inputs["variance"]
        required = {
            "component", "explained_variance",
            "explained_variance_ratio", "cumulative_variance_ratio",
        }
        missing = required - set(variance.columns)
        if missing:
            raise ValueError(
                "pca_scree_plot: expected the pca node's 'variance' output; "
                f"missing column(s): {sorted(missing)}"
            )

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            positions = range(len(variance))
            ax.bar(
                positions, variance["explained_variance_ratio"] * 100,
                color=p.bar_color or _DEFAULT_COLOR,
            )
            ax.set_xticks(list(positions))
            ax.set_xticklabels(list(variance["component"]))

            if p.show_kaiser_line:
                total_variance = float(variance["explained_variance"].sum())
                if total_variance > 0:
                    kaiser_pct = 100.0 / total_variance
                    ax.axhline(kaiser_pct, color="0.3", linestyle="--", linewidth=1.2)

            if p.show_cumulative:
                ax2 = ax.twinx()
                ax2.plot(
                    list(positions), variance["cumulative_variance_ratio"] * 100,
                    color=p.line_color or "crimson", marker="o",
                )
                ax2.set_ylim(0, 105)
                ax2.set_ylabel("cumulative % variance", fontsize=p.axis_font_size)
                ax2.tick_params(axis="y", labelsize=p.axis_font_size)

            _finalize_plot(
                fig, ax, p,
                default_xlabel="component", default_ylabel="% variance explained",
            )
        return {"figure": fig}


class PCACorrCirclePlotParams(NodeParams):
    """
    Parameters for PCACorrCirclePlot.

    Attributes:
        x_component / y_component: Which two components to plot (the
            PC column names from the pca node's ``loadings`` output).
        show_circle: Draw the unit circle -- the "perfect correlation"
            boundary every vector must fall within.
        arrow_color: Vector colour.
        label_font_size: Variable name label size.
        the remaining fields: axes + figure size + title styling.
    """

    x_component: str = column_field(dtypes=("numeric",), default="PC1")
    y_component: str = column_field(dtypes=("numeric",), default="PC2")
    show_circle: bool = True
    arrow_color: str = color_field(suggestions=_COMMON_COLORS, default=_DEFAULT_COLOR)
    label_font_size: int = 9
    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.0
    fig_height: float = 6.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class PCACorrCirclePlot(Node):
    """
    PCA correlation circle: each original variable as a vector whose
    length is its correlation with the two chosen components -- the
    pca node's raw loadings scaled by sqrt(explained variance), the
    standard convention, so every vector is bounded within the unit
    circle. Takes the ``pca`` node's ``loadings`` *and* ``variance``
    outputs (the latter only for that scaling).
    """

    node_type = "pca_corr_circle"
    category = "grapher"
    inputs = [
        Port(name="loadings", dtype="dataframe"),
        Port(name="variance", dtype="dataframe"),
    ]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = PCACorrCirclePlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Circle

        p = self.params
        loadings = inputs["loadings"]
        variance = inputs["variance"]
        if "variable" not in loadings.columns:
            raise ValueError(
                "pca_corr_circle: expected the pca node's 'loadings' output "
                "(needs a 'variable' column)."
            )
        if not {"component", "explained_variance"} <= set(variance.columns):
            raise ValueError(
                "pca_corr_circle: expected the pca node's 'variance' output "
                "(needs 'component' and 'explained_variance' columns)."
            )
        for col in (p.x_component, p.y_component):
            if col not in loadings.columns:
                raise ValueError(
                    f"pca_corr_circle: component {col!r} is not in the loadings table."
                )

        var_lookup = dict(zip(variance["component"], variance["explained_variance"]))
        missing = {p.x_component, p.y_component} - set(var_lookup)
        if missing:
            raise ValueError(
                f"pca_corr_circle: component(s) {sorted(missing)} not found in "
                f"the variance table."
            )
        scale_x = float(var_lookup[p.x_component]) ** 0.5
        scale_y = float(var_lookup[p.y_component]) ** 0.5

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            if p.show_circle:
                ax.add_patch(
                    Circle((0, 0), 1.0, fill=False, edgecolor="0.5", linestyle="--")
                )
            for _, row in loadings.iterrows():
                vx = float(row[p.x_component]) * scale_x
                vy = float(row[p.y_component]) * scale_y
                ax.annotate(
                    "", xy=(vx, vy), xytext=(0, 0),
                    arrowprops={"arrowstyle": "->", "color": p.arrow_color or _DEFAULT_COLOR},
                )
                ax.text(
                    vx * 1.1, vy * 1.1, str(row["variable"]),
                    fontsize=p.label_font_size, ha="center", va="center",
                )
            ax.set_xlim(-1.2, 1.2)
            ax.set_ylim(-1.2, 1.2)
            ax.set_aspect("equal")
            ax.axhline(0, color="0.85", linewidth=0.8)
            ax.axvline(0, color="0.85", linewidth=0.8)
            _finalize_plot(
                fig, ax, p, default_xlabel=p.x_component, default_ylabel=p.y_component,
            )
        return {"figure": fig}


# ==========================================================================
# Time-series plots (datetime x axis; VAR / VECM diagnostics)
# ==========================================================================

_TIME_FREQ = Literal["auto", "year", "quarter", "month", "week", "day", "hour"]


def _apply_time_ticks(ax: Any, freq: str, fmt: str | None = None) -> None:
    """
    Set the x-axis major locator / formatter for a datetime axis.

    ``fmt`` is the display format the plotted column carries (see
    :mod:`ruyso_app.core.dtformat`) and is only ever passed when a node
    upstream set one *explicitly* -- a format merely inferred from the
    values must not override ``ConciseDateFormatter``, which reads far
    better on an automatic axis. When given, it wins: the person asked
    for their dates to look a certain way, and an axis is one of the two
    places that request is supposed to show up.
    """
    import matplotlib.dates as mdates

    if freq == "auto":
        locator = mdates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(
            mdates.DateFormatter(fmt) if fmt else mdates.ConciseDateFormatter(locator)
        )
        return
    locator, default_fmt = {
        "year": (mdates.YearLocator(), "%Y"),
        "quarter": (mdates.MonthLocator(bymonth=(1, 4, 7, 10)), "%Y-%m"),
        "month": (mdates.MonthLocator(), "%Y-%m"),
        "week": (mdates.WeekdayLocator(byweekday=mdates.MO), "%Y-%m-%d"),
        "day": (mdates.DayLocator(), "%Y-%m-%d"),
        "hour": (mdates.HourLocator(), "%m-%d %H:%M"),
    }[freq]
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt or default_fmt))
    for label in ax.get_xticklabels():
        label.set_rotation(30)
        label.set_horizontalalignment("right")


_CI_STYLE = Literal["band", "lines", "errorbar", "none"]


def _draw_ci(ax: Any, x: Any, mid: Any, low: Any, high: Any, color: Any, style: str) -> None:
    """Draw a confidence interval around ``mid`` in one of several styles."""
    if style == "band":
        ax.fill_between(x, low, high, color=color, alpha=0.22, linewidth=0)
    elif style == "lines":
        ax.plot(x, low, color=color, linestyle="--", linewidth=0.9)
        ax.plot(x, high, color=color, linestyle="--", linewidth=0.9)
    elif style == "errorbar":
        import numpy as _np

        yerr = _np.vstack([_np.asarray(mid) - _np.asarray(low),
                           _np.asarray(high) - _np.asarray(mid)])
        ax.errorbar(x, mid, yerr=yerr, fmt="none", ecolor=color,
                    elinewidth=0.9, capsize=2, alpha=0.85)
    # "none" -> nothing


def _var_history(model: Any, ctx: str, *, require_irf: bool = True):
    """(endog DataFrame, variable names, 'var'|'vecm'|'arima') for a
    fitted model on a ``model`` input port. ``require_irf`` is relaxed
    for ``forecast_plot``, which also accepts a one-variable ARIMA
    bundle (see ``nodes.statistics.ArimaForecast``)."""
    endog = getattr(model, "ruyso_endog", None)
    names = list(getattr(model, "ruyso_names", []) or [])
    method = getattr(model, "ruyso_method", "")
    ok = endog is not None and names and (
        hasattr(model, "irf") or (not require_irf and method == "arima")
    )
    if not ok:
        want = "a 'var' node (VAR or VECM)" if require_irf else (
            "an 'arima' / 'auto_arima' or 'var' node"
        )
        raise ValueError(f"{ctx}: connect the 'model' output of {want}.")
    return endog, names, method


class TimeSeriesPlotParams(NodeParams):
    """
    Parameters for TimeSeriesPlot.

    Attributes:
        x_column: The time axis -- coerced to datetime; rows are sorted
            by it.
        y_column: The numeric series to plot.
        mark: line / line+markers / markers (scatter) / bars.
        x_tick_freq: Major x-tick spacing (ticks only -- resample the
            data first with the Resample node to change its frequency).
        color_by: Optional categorical column -- one series per level,
            coloured from ``colormap``.
        style_by: Optional categorical column -- one series per level,
            given a different marker shape (markers) / line style (line)
            / bar hatch (bars) from ``shape_map``. If ``color_by`` is
            also set it **must name the same column**; either can be set
            on its own.
        multiple: layer (overlaid), stack (stacked areas / bars) or
            dodge (side-by-side bars; falls back to layer for lines).
        alpha: Opacity of the lines / markers / bars.
        colormap / single_color: Palette / fixed colour.
        shape_map: Series of shapes for a ``style_by`` column's levels
            (assorted / geometric / bold / minimal).
        marker_shape / line_style / bar_hatch: The fixed shape used when
            ``style_by`` is not set.
    """

    x_column: str = column_field(dtypes=("datetime", "any"))
    y_column: str = column_field(dtypes=("numeric",))
    mark: Literal["line", "line+markers", "markers", "bars"] = "line"
    x_tick_freq: _TIME_FREQ = "auto"

    # -- grouping: colour and/or shape by the same column ------------
    color_by: str = column_field(
        dtypes=("categorical", "boolean"), default="", allow_none=True,
        description="Colour one series per level of this column.",
    )
    style_by: str = column_field(
        dtypes=("categorical", "boolean"), default="", allow_none=True,
        description="Vary the marker shape / line style / bar hatch by this "
        "column. If 'color by' is also set it must be the same column.",
    )
    multiple: Literal["layer", "stack", "dodge"] = "layer"
    alpha: float = unit_interval_field(0.9)
    colormap: str = reactive_choice_field(
        options="colormaps", depends_on="color_by", default="tab10",
        visible_when_set="color_by",
    )
    single_color: str = color_field(
        suggestions=_COMMON_COLORS, default=_DEFAULT_COLOR, visible_when=("color_by", ""),
    )
    shape_map: Literal["assorted", "geometric", "bold", "minimal"] = visible_field(
        "assorted", visible_when_set="style_by",
        description="Series of shapes assigned to the style-by column's levels.",
    )
    marker_shape: Literal[
        "circle", "square", "triangle", "diamond", "plus", "cross", "star", "point"
    ] = visible_field(
        "circle",
        visible_when_in=("mark", ("markers", "line+markers")),
        visible_when_unset="style_by",
        description="Marker shape (fixed).",
    )
    line_style: Literal["solid", "dashed", "dash-dot", "dotted"] = visible_field(
        "solid",
        visible_when_in=("mark", ("line", "line+markers")),
        visible_when_unset="style_by",
        description="Line style (fixed).",
    )
    bar_hatch: Literal[
        "none", "diagonal", "back-diagonal", "cross", "dots", "stars"
    ] = visible_field(
        "none", visible_when=("mark", "bars"), visible_when_unset="style_by",
        description="Bar hatch pattern (fixed).",
    )

    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    log_y: bool = False
    fig_width: float = 6.0
    fig_height: float = 4.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = True
    legend_title: str = ""
    legend_location: _LEGEND_LOCATIONS = "best"
    legend_font_size: int = 9


@register_node
class TimeSeriesPlot(Node):
    """A single numeric series over a datetime axis: line, markers, or bars."""

    node_type = "time_series_plot"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = TimeSeriesPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        p = self.params
        df = inputs["df"]
        for col in (p.x_column, p.y_column):
            if col not in df.columns:
                raise ValueError(f"time_series_plot: column {col!r} is not in the input data.")

        color_col = (p.color_by or "").strip()
        style_col = (p.style_by or "").strip()
        if color_col and style_col and color_col != style_col:
            raise ValueError(
                "time_series_plot: 'color by' and 'style by' must name the same "
                f"column (got {color_col!r} and {style_col!r})."
            )
        group_col = color_col or style_col
        hue = _categorical_hue(df, group_col)

        work = pd.DataFrame(
            {
                "x": pd.to_datetime(df[p.x_column], errors="coerce"),
                "y": pd.to_numeric(df[p.y_column], errors="coerce"),
            }
        )
        if hue:
            work["g"] = df[group_col].astype("string").to_numpy()
        work = work.dropna(subset=["x", "y"]).sort_values("x")
        if work.empty:
            raise ValueError("time_series_plot: no rows left after dropping missing x / y.")

        groups = list(work.groupby("g", observed=True)) if hue else [(None, work)]
        color_active = bool(hue and color_col)
        style_active = bool(hue and style_col)

        with _plot_context(plt):
            fig, ax = _new_figure(p)
            if color_active:
                cmap = plt.get_cmap(p.colormap or "tab10")
                colors = [cmap(i % cmap.N) for i in range(len(groups))]
            else:
                colors = [p.single_color or _DEFAULT_COLOR] * max(len(groups), 1)
            shapes = self._shapes(p, style_active, len(groups))

            if p.mark == "bars":
                self._draw_bars(ax, groups, colors, shapes, p, np)
            else:
                self._draw_lines(ax, groups, colors, shapes, p, hue, style_active, np)

            _apply_time_ticks(
                ax, p.x_tick_freq, dtformat.display_formats(df).get(p.x_column)
            )
            if hue and p.show_legend:
                _place_legend(ax, p, p.legend_title or group_col)
            elif not hue:
                _remove_legend(ax)
            _finalize_plot(
                fig, ax, p, default_xlabel=p.x_column, default_ylabel=p.y_column,
            )
        return {"figure": fig}

    @staticmethod
    def _shapes(p, style_active: bool, n: int) -> list:
        """Per-group shape value (marker / line style / hatch) for ``mark``."""
        markish = p.mark in ("markers", "line+markers")
        if style_active:
            kind = "scatter" if markish else ("bar" if p.mark == "bars" else "line")
            seq = _shape_sequence(kind, p.shape_map)
            return [seq[i % len(seq)] for i in range(max(n, 1))]
        if markish:
            fixed = _MARKER_SHAPES.get(p.marker_shape, "o")
        elif p.mark == "bars":
            fixed = _BAR_HATCHES.get(p.bar_hatch)
        else:
            fixed = _LINE_STYLES.get(p.line_style, "-")
        return [fixed] * max(n, 1)

    @staticmethod
    def _draw_lines(ax, groups, colors, shapes, p, hue, style_active, np) -> None:
        base_ls = _LINE_STYLES.get(p.line_style, "-")
        if hue and p.multiple == "stack":
            union = np.array(sorted(set(np.concatenate([g["x"].to_numpy() for _, g in groups]))))
            stacks = [
                g.set_index("x")["y"].reindex(union).fillna(0.0).to_numpy() for _, g in groups
            ]
            ax.stackplot(
                union, *stacks, labels=[str(k) for k, _ in groups],
                colors=colors, alpha=float(p.alpha),
            )
            return
        for (key, g), color, shape in zip(groups, colors, shapes):
            if p.mark == "markers":
                kw = {"linestyle": "none", "marker": shape}
            elif p.mark == "line+markers":
                kw = {"linestyle": base_ls, "marker": shape}
            else:  # line
                kw = {"linestyle": shape, "marker": ""}
            ax.plot(
                g["x"].to_numpy(), g["y"].to_numpy(), color=color, alpha=float(p.alpha),
                markersize=4, label=(str(key) if key is not None else None), **kw,
            )

    @staticmethod
    def _draw_bars(ax, groups, colors, shapes, p, np) -> None:
        all_x = np.array(sorted(set(np.concatenate([g["x"].to_numpy() for _, g in groups]))))
        span = (
            np.median(np.diff(all_x)) / np.timedelta64(1, "D") if all_x.size > 1 else 1.0
        )
        width = 0.8 * float(span)
        n = len(groups)
        bottom = {}
        for i, ((key, g), color, hatch) in enumerate(zip(groups, colors, shapes)):
            x = g["x"].to_numpy()
            y = g["y"].to_numpy()
            label = str(key) if key is not None else None
            if p.multiple == "dodge" and n > 1:
                offset = (i - (n - 1) / 2) * (width / n)
                ax.bar(
                    x + np.timedelta64(int(offset * 86400), "s"), y, width=width / n,
                    color=color, alpha=float(p.alpha), hatch=hatch, label=label,
                )
            elif p.multiple == "stack" and n > 1:
                base = np.array([bottom.get(t, 0.0) for t in x])
                ax.bar(
                    x, y, width=width, bottom=base, color=color, alpha=float(p.alpha),
                    hatch=hatch, label=label,
                )
                for t, v in zip(x, y):
                    bottom[t] = bottom.get(t, 0.0) + v
            else:  # layer / single
                ax.bar(
                    x, y, width=width, color=color, alpha=float(p.alpha),
                    hatch=hatch, label=label,
                )


class MultivariateTimeSeriesPlotParams(NodeParams):
    """
    Parameters for MultivariateTimeSeriesPlot.

    Attributes:
        datetime_column: The time axis (coerced to datetime; rows sorted
            by it).
        variables: Numeric series to draw (tickboxes).
        layout: ``overlay`` -- all series on one axes; ``grid`` -- one
            stacked panel per series (shared x).
        normalize: z-score each series (useful when scales differ, for
            ``overlay``).
        x_tick_freq: Major x-tick spacing.
        alpha: Line opacity.
        colormap / mark_color: How the series are coloured, which follows
            ``layout``. In ``overlay`` every line shares one axes, so
            each takes its own colour from a qualitative ``colormap``.
            In ``grid`` each series already has its own panel, so colour
            carries no information and a single ``mark_color`` is used.
            Only the field that applies to the current layout is shown.
    """

    datetime_column: str = column_field(dtypes=("datetime", "any"))
    variables: list[str] | None = checkbox_list_field(source="columns", default=None)
    layout: Literal["overlay", "grid"] = "overlay"
    normalize: bool = False
    x_tick_freq: _TIME_FREQ = "auto"
    alpha: float = unit_interval_field(0.9)
    colormap: str = colormap_field(
        kind="qualitative", default="tab10",
        description="One colour per series.",
        visible_when=("layout", "overlay"),
    )
    mark_color: str = color_field(
        suggestions=_COMMON_COLORS, default="materialblue",
        description="Line colour for every panel.",
        visible_when=("layout", "grid"),
    )

    x_label: str = ""
    y_label: str = ""
    x_min: str = axis_limit_field("Left edge of the x-axis (blank = fit to the data).")
    x_max: str = axis_limit_field("Right edge of the x-axis (blank = fit to the data).")
    y_min: str = axis_limit_field("Bottom edge of the y-axis (blank = fit to the data).")
    y_max: str = axis_limit_field("Top edge of the y-axis (blank = fit to the data).")
    axis_font_size: int = 10
    show_grid: bool = True
    show_box: bool = False
    fig_width: float = 6.5
    fig_height: float = 4.5
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False
    show_legend: bool = True
    legend_title: str = ""
    legend_location: _LEGEND_LOCATIONS = "best"
    legend_font_size: int = 9


@register_node
class MultivariateTimeSeriesPlot(Node):
    """Several numeric series over a shared datetime axis (overlaid or stacked panels)."""

    node_type = "multivariate_timeseries_plot"
    category = "grapher"
    inputs = [Port(name="df", dtype="dataframe")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = MultivariateTimeSeriesPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd

        p = self.params
        df = inputs["df"]
        if p.datetime_column not in df.columns:
            raise ValueError(
                f"multivariate_timeseries_plot: column {p.datetime_column!r} is not "
                "in the input data."
            )
        cols = [c for c in (p.variables or []) if c in df.columns and c != p.datetime_column]
        if not cols:
            raise ValueError("multivariate_timeseries_plot: tick at least one series.")

        x = pd.to_datetime(df[p.datetime_column], errors="coerce")
        data = df[cols].apply(pd.to_numeric, errors="coerce")
        work = pd.concat([x.rename("x"), data], axis=1).dropna(subset=["x"]).sort_values("x")
        if p.normalize:
            for c in cols:
                s = work[c]
                std = s.std(ddof=0)
                work[c] = (s - s.mean()) / std if std else s - s.mean()

        with _plot_context(plt):
            if p.layout == "grid":
                fig, axes = _new_figure(p, len(cols), 1, squeeze=False)
                axes = list(axes[:, 0])
            else:
                fig, ax = _new_figure(p)
                axes = [ax] * len(cols)
            if p.layout == "overlay":
                # One axes, so colour is the only thing separating the
                # lines -- give each series its own from the palette.
                cmap = plt.get_cmap(p.colormap or "tab10")
                line_colors = [cmap(i % cmap.N) for i in range(len(cols))]
            else:
                # One panel per series: colour carries no information.
                line_colors = [p.mark_color or "materialblue"] * len(cols)

            for i, col in enumerate(cols):
                a = axes[i]
                a.plot(
                    work["x"].to_numpy(), work[col].to_numpy(),
                    color=line_colors[i], alpha=float(p.alpha), label=col,
                )
                if p.layout == "grid":
                    a.set_ylabel(col, fontsize=p.axis_font_size)
                    a.tick_params(axis="both", labelsize=p.axis_font_size)
                    a.grid(bool(p.show_grid))
                    if i < len(cols) - 1:
                        a.tick_params(labelbottom=False)

            last = axes[-1]
            _apply_time_ticks(
                last, p.x_tick_freq, dtformat.display_formats(df).get(p.datetime_column)
            )
            if p.layout == "overlay":
                if p.show_legend:
                    _place_legend(axes[0], p, p.legend_title or "series")
                _finalize_plot(
                    fig, axes[0], p,
                    default_xlabel=p.datetime_column, default_ylabel=p.y_label or "value",
                )
            else:
                last.set_xlabel(p.x_label or p.datetime_column, fontsize=p.axis_font_size)
                for a in axes:  # grid: _finalize_plot isn't called per panel
                    _apply_axis_limits(a, p)
                if p.title:
                    fig.suptitle(
                        p.title, fontsize=p.title_font_size,
                        fontweight="bold" if p.title_bold else "normal",
                        fontstyle="italic" if p.title_italic else "normal",
                    )
                fig.tight_layout()
        return {"figure": fig}


class ForecastPlotParams(NodeParams):
    """
    Parameters for ForecastPlot.

    Attributes:
        variables: Which of the model's variables to draw (tickboxes;
            blank = all). Populated from the connected model -- one entry
            for an ``arima`` / ``auto_arima`` model, several for a
            ``var`` / ``vecm``.
        confidence_level: Level for the forecast interval.
        history_window: Trailing history points to show (0 = all).
        history_color / forecast_color: Line colours for the observed
            history and the forecast.
        ci_style: How the interval is drawn -- ``band`` (a lighter fill
            in the forecast colour), ``lines`` (dashed bounds),
            ``errorbar`` (a bar per step), or ``none``.

    The forecast horizon is taken from the ``var`` node's
    ``forecast_periods`` -- set it there.
    """

    variables: list[str] | None = checkbox_list_field(source="columns", default=None)
    confidence_level: float = unit_interval_field(0.95, lo=0.5, hi=0.999)
    history_window: int = 0
    history_color: str = color_field(suggestions=_COMMON_COLORS, default=_DEFAULT_COLOR)
    forecast_color: str = color_field(suggestions=_COMMON_COLORS, default="#d1495b")
    ci_style: _CI_STYLE = "band"

    axis_font_size: int = 10
    show_grid: bool = True
    fig_width: float = 6.5
    fig_height: float = 5.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class ForecastPlot(Node):
    """History + multi-step forecast (with interval): a one-variable ARIMA, or chosen variables of a VAR / VECM."""

    node_type = "forecast_plot"
    category = "grapher"
    inputs = [Port(name="model", dtype="model")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = ForecastPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd

        p = self.params
        model = inputs["model"]
        endog, names, method = _var_history(model, "forecast_plot", require_irf=False)
        steps = max(int(getattr(model, "ruyso_forecast_periods", 10)), 1)
        alpha = 1.0 - float(p.confidence_level)

        if method == "arima":
            fc = model.ruyso_forecast
            mid = fc["mid"].to_numpy("float64")[:, None]
            low = fc["low"].to_numpy("float64")[:, None]
            high = fc["high"].to_numpy("float64")[:, None]
            steps = len(mid)
        elif method == "vecm":
            mid, low, high = model.predict(steps=steps, alpha=alpha)
        else:
            mid, low, high = model.forecast_interval(
                endog.values[-model.k_ar:], steps, alpha=alpha
            )
        mid, low, high = (np.asarray(a, dtype="float64") for a in (mid, low, high))

        chosen = [c for c in (p.variables or names) if c in names] or names
        hist = endog if p.history_window <= 0 else endog.iloc[-int(p.history_window):]
        hx = hist.index
        if isinstance(hx, pd.DatetimeIndex) and hx.freq is not None:
            fx = pd.date_range(hx[-1], periods=steps + 1, freq=hx.freq)[1:]
        elif isinstance(hx, pd.DatetimeIndex) and len(hx) > 1:
            fx = pd.date_range(hx[-1], periods=steps + 1, freq=hx[-1] - hx[-2])[1:]
        else:
            fx = np.arange(len(endog), len(endog) + steps)
            hx = np.arange(len(endog) - len(hist), len(endog))

        with _plot_context(plt):
            fig, axes = _new_figure(p, len(chosen), 1, squeeze=False)
            for ax, name in zip(axes[:, 0], chosen):
                j = names.index(name)
                ax.plot(hx, hist[name].to_numpy(), color=p.history_color, label="history")
                ax.plot(fx, mid[:, j], color=p.forecast_color, label="forecast")
                _draw_ci(ax, fx, mid[:, j], low[:, j], high[:, j],
                         p.forecast_color, p.ci_style)
                ax.set_ylabel(name, fontsize=p.axis_font_size)
                ax.tick_params(axis="both", labelsize=p.axis_font_size)
                ax.grid(bool(p.show_grid))
            axes[0, 0].legend(fontsize=8, loc="best")
            if p.title:
                fig.suptitle(
                    p.title, fontsize=p.title_font_size,
                    fontweight="bold" if p.title_bold else "normal",
                    fontstyle="italic" if p.title_italic else "normal",
                )
            fig.tight_layout()
        return {"figure": fig}


class VarAcorrPlotParams(NodeParams):
    """
    Parameters for VarAcorrPlot.

    Attributes:
        max_lag: Number of lags on each panel.
        confidence_level: Level for the +/- band (white-noise bounds).
    """

    max_lag: int = 12
    confidence_level: float = unit_interval_field(0.95, lo=0.5, hi=0.999)
    fig_width: float = 6.5
    fig_height: float = 6.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class VarAcorrPlot(Node):
    """Residual auto- and cross-correlation grid of a fitted VAR / VECM (a whiteness check)."""

    node_type = "var_acorr_plot"
    category = "grapher"
    inputs = [Port(name="model", dtype="model")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = VarAcorrPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from statsmodels.tsa.stattools import ccf

        p = self.params
        model = inputs["model"]
        _, names, _ = _var_history(model, "var_acorr_plot")
        resid = np.asarray(model.resid, dtype="float64")
        k = len(names)
        n = resid.shape[0]
        max_lag = max(int(p.max_lag), 1)
        z = float(_z_value(p.confidence_level))
        band = z / np.sqrt(n)
        lags = np.arange(max_lag + 1)

        with _plot_context(plt):
            fig, axes = _new_figure(p, k, k, squeeze=False)
            for i in range(k):
                for j in range(k):
                    ax = axes[i, j]
                    cc = ccf(resid[:, j], resid[:, i], adjusted=False)[: max_lag + 1]
                    ax.vlines(lags, 0, cc, color=_DEFAULT_COLOR)
                    ax.axhline(0, color="0.6", linewidth=0.8)
                    ax.axhline(band, color="0.7", linestyle="--", linewidth=0.8)
                    ax.axhline(-band, color="0.7", linestyle="--", linewidth=0.8)
                    ax.set_ylim(-1.05, 1.05)
                    if i == 0:
                        ax.set_title(names[j], fontsize=9)
                    if j == 0:
                        ax.set_ylabel(names[i], fontsize=9)
                    ax.tick_params(labelsize=7)
            fig.suptitle(
                p.title or "Residual autocorrelation",
                fontsize=p.title_font_size,
                fontweight="bold" if p.title_bold else "normal",
                fontstyle="italic" if p.title_italic else "normal",
            )
            fig.tight_layout()
        return {"figure": fig}


class IrfPlotParams(NodeParams):
    """
    Parameters for IrfPlot.

    Attributes:
        periods: Horizon (steps) of the impulse response.
        orthogonalized: Use orthogonalised (Cholesky) shocks.
        cumulative: Plot the cumulative response instead of per-period.
        responses: Response variables to show as rows (tickboxes; blank
            = all). shocks: Impulse variables to show as columns
            (tickboxes; blank = all). Both are populated from the
            connected ``var`` model.
        line_color: Colour of the impulse-response line.
        ci_style: How the +/- standard-error interval is drawn --
            ``band`` / ``lines`` / ``errorbar`` / ``none``.
        confidence_level: Level for the standard-error interval.
    """

    periods: int = 10
    orthogonalized: bool = True
    cumulative: bool = False
    responses: list[str] | None = checkbox_list_field(source="columns", default=None)
    shocks: list[str] | None = checkbox_list_field(source="columns", default=None)
    line_color: str = color_field(suggestions=_COMMON_COLORS, default=_DEFAULT_COLOR)
    ci_style: _CI_STYLE = "band"
    confidence_level: float = unit_interval_field(0.95, lo=0.5, hi=0.999)
    fig_width: float = 6.5
    fig_height: float = 6.0
    title: str | None = None
    title_font_size: int = 12
    title_bold: bool = False
    title_italic: bool = False


@register_node
class IrfPlot(Node):
    """Impulse-response functions of a fitted VAR / VECM, with a standard-error band."""

    node_type = "irf_plot"
    category = "grapher"
    inputs = [Port(name="model", dtype="model")]
    outputs = [Port(name="figure", dtype="figure")]
    params_schema = IrfPlotParams
    cacheable = False

    def run(self, **inputs: Any) -> dict[str, Any]:
        self.validate_inputs(inputs)
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        p = self.params
        model = inputs["model"]
        _, names, _ = _var_history(model, "irf_plot")
        periods = max(int(p.periods), 1)
        irf = model.irf(periods)

        if p.cumulative:
            effects = irf.orth_cum_effects if p.orthogonalized else irf.cum_effects
            stderr = irf.cum_effect_stderr(orth=p.orthogonalized)
        else:
            effects = irf.orth_irfs if p.orthogonalized else irf.irfs
            stderr = irf.stderr(orth=p.orthogonalized)
        effects = np.asarray(effects, dtype="float64")
        stderr = np.asarray(stderr, dtype="float64")
        z = float(_z_value(p.confidence_level))
        horizons = np.arange(effects.shape[0])

        def _sel(chosen: list[str] | None) -> list[int]:
            idx = [names.index(c) for c in (chosen or []) if c in names]
            return idx or list(range(len(names)))

        responses = _sel(p.responses)
        impulses = _sel(p.shocks)

        with _plot_context(plt):
            fig, axes = _new_figure(p, len(responses), len(impulses), squeeze=False)
            for ri, r in enumerate(responses):
                for ci, c in enumerate(impulses):
                    ax = axes[ri, ci]
                    mid = effects[:, r, c]
                    se = stderr[:, r, c]
                    ax.plot(horizons, mid, color=p.line_color)
                    _draw_ci(ax, horizons, mid, mid - z * se, mid + z * se,
                             p.line_color, p.ci_style)
                    ax.axhline(0, color="0.6", linewidth=0.8)
                    if ri == 0:
                        ax.set_title(f"shock: {names[c]}", fontsize=9)
                    if ci == 0:
                        ax.set_ylabel(f"resp: {names[r]}", fontsize=9)
                    ax.tick_params(labelsize=7)
            kind = "Cumulative " if p.cumulative else ""
            orth = "orthogonalised" if p.orthogonalized else "simple"
            fig.suptitle(
                p.title or f"{kind}IRF ({orth})",
                fontsize=p.title_font_size,
                fontweight="bold" if p.title_bold else "normal",
                fontstyle="italic" if p.title_italic else "normal",
            )
            fig.tight_layout()
        return {"figure": fig}
