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
    unit_interval_field,
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

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))

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
                        ax.plot(
                            xm[order], np.asarray(y[mask])[order],
                            color=line_color, linestyle=ls, linewidth=lw, alpha=la,
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

            _finalize_plot(fig, ax, p, default_xlabel=p.x, default_ylabel=p.y)

        return {"figure": fig}


# ==========================================================================
# Table viewer -- a small DataFrame rendered as a previewable table figure
# ==========================================================================


class TableViewerParams(NodeParams):
    """
    Parameters for TableViewer.

    Attributes:
        decimals: Rounding for numeric columns.
        max_rows / max_cols: Show at most this many rows / columns; the
            rest are dropped and a note is printed on the figure.
        show_index: Include the DataFrame index as a leading column.
        font_size: Cell text size.
        header_color: Fill colour of the header row.
        row_height: Vertical scale of the cells (1.0 = matplotlib default).
        the remaining fields: figure size + title styling.
    """

    decimals: int = 2
    max_rows: int = 30
    max_cols: int = 12
    show_index: bool = False
    font_size: int = 9
    header_color: str = color_field(
        suggestions=["#cfe2f3", "#d9ead3", "#fce5cd", "lightgrey", "white"],
        default="#cfe2f3",
        description="Header row fill colour.",
    )
    row_height: float = 1.5
    fig_width: float = 8.0
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

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
            ax.axis("off")
            table = ax.table(
                cellText=cell_text,
                colLabels=col_labels,
                rowLabels=row_labels,
                cellLoc="center",
                loc="center",
            )
            table.auto_set_font_size(False)
            table.set_fontsize(int(p.font_size))
            table.scale(1.0, max(float(p.row_height), 0.5))

            header_rgba = to_rgba(p.header_color or "#cfe2f3")
            for (r, _c), cell in table.get_celld().items():
                cell.set_edgecolor("0.75")
                if r == 0:
                    cell.set_facecolor(header_rgba)
                    cell.set_text_props(weight="bold")
                elif r > 0 and r % 2 == 0:
                    cell.set_facecolor((0.965, 0.965, 0.975, 1.0))

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

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
            vertical = p.orientation == "vertical"
            axis_kw = (
                {"x": p.category_column, "y": p.value_column}
                if vertical
                else {"x": p.value_column, "y": p.category_column}
            )
            draw_kw: dict[str, Any] = {"data": plot_df, "ax": ax, **axis_kw}
            if hue:
                draw_kw["hue"] = hue
                draw_kw["palette"] = p.colormap or "tab10"
            else:
                draw_kw["color"] = p.single_color or _DEFAULT_COLOR
            if p.kind == "swarm":
                draw_kw["size"] = float(p.point_size)

            plot_fn(**draw_kw)

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


# ==========================================================================
# Model-visualization plots (consume a fitted model + a held-out X / y)
# ==========================================================================

#: Sequential colormaps offered by the confusion-matrix node.
_MODEL_SEQUENTIAL = Literal[
    "Blues", "viridis", "plasma", "cividis", "magma", "Greens", "Purples", "Greys"
]
#: Qualitative colormaps for the per-class curves (multiclass ROC / PR / DET).
_MODEL_QUALITATIVE = Literal["tab10", "Set1", "Set2", "Dark2", "Paired"]

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
    colormap: _MODEL_SEQUENTIAL = "Blues"
    annotate: bool = True
    colorbar: bool = True

    x_label: str = ""
    y_label: str = ""
    axis_font_size: int = 10
    show_grid: bool = False
    show_box: bool = True
    fig_width: float = 5.0
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

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
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
    colormap: _MODEL_QUALITATIVE = "tab10"  # per-class colours, multiclass
    line_width: float = 1.6

    x_label: str = ""
    y_label: str = ""
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

    with plt.style.context(_BASE_STYLE):
        fig, ax = plt.subplots(figsize=_fig_size(p))

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

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
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

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
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

        with plt.style.context(_BASE_STYLE):
            fig, ax = plt.subplots(figsize=_fig_size(p))
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
