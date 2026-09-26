"""
Small rendered previews ("swatches") for the Options-panel dropdowns
that pick a *visual* thing rather than a word: a colormap, a marker
shape, a line style, a bar hatch, a marker-shape *series*
(``shape_map``), or a plain colour.

Everything here returns a ``QPixmap`` / ``QIcon`` and touches no
NodeGraphQt or app state, so it is trivially reusable -- the Options
panel decorates its combos with these, and the colormap designer /
manager (a later batch) renders its previews the same way.

Only the colormap swatch needs matplotlib (for the real lookup table);
it is imported lazily so importing this module stays cheap. Marker /
line / hatch glyphs are drawn directly with ``QPainter`` in a neutral
colour taken from the active :mod:`ui.theme` so they read in both the
dark and light palettes.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
)

# -- sizes ---------------------------------------------------------------

_ICON_SIZES: dict[str, QSize] = {
    "colormap": QSize(96, 16),
    "marker": QSize(22, 16),
    "linestyle": QSize(46, 16),
    "hatch": QSize(24, 16),
    "shapemap": QSize(108, 16),
    "color": QSize(20, 16),
}


def icon_size(kind: str) -> QSize:
    """The natural pixmap size for one swatch ``kind`` (see :data:`_ICON_SIZES`)."""
    return QSize(_ICON_SIZES.get(kind, QSize(24, 16)))


# -- shared helpers -----------------------------------------------------


def _neutral_color() -> QColor:
    """The active theme's text colour -- glyphs drawn in it read in both modes."""
    try:
        from ruyso_app.ui import theme

        return QColor(theme.current_theme().text_color)
    except Exception:  # noqa: BLE001 - theme not importable (e.g. bare unit test)
        return QColor("#888888")


def _theme_key() -> str:
    try:
        from ruyso_app.ui import theme

        return theme.current_theme().name
    except Exception:  # noqa: BLE001
        return "?"


_CACHE: dict[tuple, QPixmap] = {}


def clear_cache() -> None:
    """Drop every cached swatch. Call after a custom colormap is edited
    so its gradient re-renders from the new definition."""
    _CACHE.clear()


def _blank(size: QSize) -> QPixmap:
    pm = QPixmap(size)
    pm.fill(Qt.GlobalColor.transparent)
    return pm


# -- colormap ----------------------------------------------------------


def colormap_pixmap(name: str, size: QSize | None = None) -> QPixmap:
    """A horizontal gradient strip of matplotlib colormap ``name``.

    Rendered at any width (the floating-width colormap combo asks for a
    fresh size as the panel resizes), so the lookup is vectorised.
    An unknown name yields a hatched grey placeholder rather than an
    error, so a stale stored value never breaks the panel.
    """
    size = size or icon_size("colormap")
    w, h = max(size.width(), 1), max(size.height(), 1)
    key = ("cmap", name, w, h)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    cmap = None
    try:
        import matplotlib

        if name in matplotlib.colormaps:
            cmap = matplotlib.colormaps[name]
    except Exception:  # noqa: BLE001 - matplotlib missing / odd name
        cmap = None

    if cmap is None:
        pm = _placeholder(size)
        _CACHE[key] = pm
        return pm

    import numpy as np

    rgb = cmap(np.linspace(0.0, 1.0, w), bytes=True)[:, :3].astype(np.uint32)  # (w, 3)
    argb = (0xFF000000 | (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]).astype("<u4")
    buf = np.ascontiguousarray(np.tile(argb, (h, 1)))  # (h, w)
    img = QImage(buf.tobytes(), w, h, w * 4, QImage.Format.Format_RGB32).copy()

    pm = QPixmap.fromImage(img)
    painter = QPainter(pm)
    painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
    painter.drawRect(0, 0, w - 1, h - 1)
    painter.end()

    if len(_CACHE) > 512:  # bound growth from many transient widths
        _CACHE.clear()
    _CACHE[key] = pm
    return pm


def _placeholder(size: QSize) -> QPixmap:
    pm = _blank(size)
    painter = QPainter(pm)
    painter.fillRect(pm.rect(), QColor("#9a9a9a"))
    painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
    for off in range(-size.height(), size.width(), 5):
        painter.drawLine(off, size.height(), off + size.height(), 0)
    painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
    painter.drawRect(0, 0, size.width() - 1, size.height() - 1)
    painter.end()
    return pm


# -- markers ----------------------------------------------------------

#: Options-panel marker names -> the matplotlib marker code they map to
#: (kept in step with ``nodes/viz.py`` ``_MARKER_SHAPES``).
_MARKER_NAME_TO_CODE = {
    "circle": "o", "square": "s", "triangle": "^", "diamond": "D",
    "plus": "P", "cross": "X", "star": "*", "point": ".",
}


def _draw_marker(painter: QPainter, code: str, cx: float, cy: float, r: float) -> None:
    """Draw one filled marker glyph centred at (cx, cy) with radius ~r."""

    def poly(pts: list[tuple[float, float]]) -> QPolygonF:
        return QPolygonF([QPointF(cx + dx * r, cy + dy * r) for dx, dy in pts])

    if code in ("o", "."):
        rr = r if code == "o" else r * 0.45
        painter.drawEllipse(QPointF(cx, cy), rr, rr)
    elif code == "s":
        painter.drawRect(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    elif code in ("D", "d"):
        wx = 0.72 if code == "d" else 1.0
        painter.drawPolygon(poly([(0, -1), (wx, 0), (0, 1), (-wx, 0)]))
    elif code == "^":
        painter.drawPolygon(poly([(0, -1), (0.9, 0.8), (-0.9, 0.8)]))
    elif code == "v":
        painter.drawPolygon(poly([(0, 1), (0.9, -0.8), (-0.9, -0.8)]))
    elif code == "<":
        painter.drawPolygon(poly([(-1, 0), (0.8, -0.9), (0.8, 0.9)]))
    elif code == ">":
        painter.drawPolygon(poly([(1, 0), (-0.8, -0.9), (-0.8, 0.9)]))
    elif code == "P":  # filled thick plus
        t = 0.38
        painter.drawPolygon(poly([
            (-t, -1), (t, -1), (t, -t), (1, -t), (1, t), (t, t),
            (t, 1), (-t, 1), (-t, t), (-1, t), (-1, -t), (-t, -t),
        ]))
    elif code == "X":  # filled thick x
        t, o = 0.30, 0.72
        painter.drawPolygon(poly([
            (-o, -1), (0, -t), (o, -1), (1, -o), (t, 0), (1, o),
            (o, 1), (0, t), (-o, 1), (-1, o), (-t, 0), (-1, -o),
        ]))
    elif code == "*":
        import math

        pts: list[tuple[float, float]] = []
        for i in range(10):
            ang = -math.pi / 2 + i * math.pi / 5
            rad = 1.0 if i % 2 == 0 else 0.42
            pts.append((math.cos(ang) * rad, math.sin(ang) * rad))
        painter.drawPolygon(poly(pts))
    elif code in ("p", "h", "8"):
        import math

        sides = {"p": 5, "h": 6, "8": 8}[code]
        start = -math.pi / 2
        painter.drawPolygon(poly([
            (math.cos(start + i * 2 * math.pi / sides),
             math.sin(start + i * 2 * math.pi / sides))
            for i in range(sides)
        ]))
    elif code == "+":
        painter.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        painter.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
    elif code == "x":
        painter.drawLine(QPointF(cx - r, cy - r), QPointF(cx + r, cy + r))
        painter.drawLine(QPointF(cx - r, cy + r), QPointF(cx + r, cy - r))
    else:
        painter.drawEllipse(QPointF(cx, cy), r, r)


def marker_pixmap(shape: str, size: QSize | None = None, color: QColor | None = None) -> QPixmap:
    """One marker glyph (name from the panel, or a raw matplotlib code)."""
    size = size or icon_size("marker")
    col = color or _neutral_color()
    key = ("marker", shape, size.width(), size.height(), col.name(), _theme_key())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    code = _MARKER_NAME_TO_CODE.get(shape, shape)
    pm = _blank(size)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(col, 1.4))
    painter.setBrush(QBrush(col) if code not in ("+", "x") else Qt.BrushStyle.NoBrush)
    r = min(size.width(), size.height()) * 0.34
    _draw_marker(painter, code, size.width() / 2, size.height() / 2, r)
    painter.end()
    _CACHE[key] = pm
    return pm


# -- line styles ------------------------------------------------------

_LINESTYLE_TO_PEN = {
    "solid": Qt.PenStyle.SolidLine,
    "dashed": Qt.PenStyle.DashLine,
    "dash-dot": Qt.PenStyle.DashDotLine,
    "dotted": Qt.PenStyle.DotLine,
}


def linestyle_pixmap(style: str, size: QSize | None = None, color: QColor | None = None) -> QPixmap:
    """A short horizontal line drawn in ``style`` (solid / dashed / dash-dot / dotted)."""
    size = size or icon_size("linestyle")
    col = color or _neutral_color()
    key = ("line", style, size.width(), size.height(), col.name(), _theme_key())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    pm = _blank(size)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(col, 1.8)
    pen.setStyle(_LINESTYLE_TO_PEN.get(style, Qt.PenStyle.SolidLine))
    painter.setPen(pen)
    y = size.height() / 2
    painter.drawLine(QPointF(2, y), QPointF(size.width() - 2, y))
    painter.end()
    _CACHE[key] = pm
    return pm


# -- hatches --------------------------------------------------------

_HATCH_NAME_TO_BRUSH = {
    "diagonal": Qt.BrushStyle.FDiagPattern,
    "back-diagonal": Qt.BrushStyle.BDiagPattern,
    "cross": Qt.BrushStyle.DiagCrossPattern,
    "dots": Qt.BrushStyle.Dense4Pattern,
}


def hatch_pixmap(hatch: str, size: QSize | None = None, color: QColor | None = None) -> QPixmap:
    """A small rectangle filled with the bar-hatch pattern ("none" = outline only)."""
    size = size or icon_size("hatch")
    col = color or _neutral_color()
    key = ("hatch", hatch, size.width(), size.height(), col.name(), _theme_key())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    pm = _blank(size)
    painter = QPainter(pm)
    rect = QRectF(1.5, 1.5, size.width() - 3, size.height() - 3)
    painter.setPen(QPen(col, 1.0))
    brush_style = _HATCH_NAME_TO_BRUSH.get(hatch)
    if brush_style is not None:
        b = QBrush(col)
        b.setStyle(brush_style)
        painter.setBrush(b)
        painter.drawRect(rect)
    elif hatch == "stars":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
        f = QFont()
        f.setPixelSize(int(size.height() * 0.6))
        painter.setFont(f)
        painter.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "* *")
    else:  # "none"
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)
    painter.end()
    _CACHE[key] = pm
    return pm


# -- shape-map series -----------------------------------------------

#: Marker series per ``shape_map`` choice (kept in step with
#: ``nodes/viz.py`` ``_SHAPE_MAP_MARKERS``).
_SHAPEMAP_MARKERS = {
    "assorted": ["o", "s", "^", "D", "v", "P", "X", "*"],
    "geometric": ["o", "s", "^", "D", "p", "h", "8", "v"],
    "bold": ["*", "P", "X", "D", "o", "s", "^", "v"],
    "minimal": ["o", "^", "s", "D", "v", "<", ">", "p"],
}


def shapemap_pixmap(name: str, size: QSize | None = None, color: QColor | None = None) -> QPixmap:
    """A row of the first several marker glyphs in the ``shape_map`` series."""
    size = size or icon_size("shapemap")
    col = color or _neutral_color()
    key = ("shapemap", name, size.width(), size.height(), col.name(), _theme_key())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    markers = _SHAPEMAP_MARKERS.get(name, _SHAPEMAP_MARKERS["assorted"])
    pm = _blank(size)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(col, 1.2))
    painter.setBrush(QBrush(col))
    step = size.width() / len(markers)
    r = min(step, size.height()) * 0.32
    cy = size.height() / 2
    for i, code in enumerate(markers):
        _draw_marker(painter, code, step * (i + 0.5), cy, r)
    painter.end()
    _CACHE[key] = pm
    return pm


# -- plain colour --------------------------------------------------


def color_pixmap(spec: str, size: QSize | None = None) -> QPixmap:
    """A solid swatch of matplotlib colour ``spec`` (name or ``#rrggbb``).

    Returns a null pixmap for an unparseable colour, so callers can
    show nothing rather than a wrong colour.
    """
    size = size or icon_size("color")
    qcolor = _to_qcolor(spec)
    if qcolor is None:
        return QPixmap()
    pm = _blank(size)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
    painter.setBrush(QBrush(qcolor))
    # Rounded to match the 8px radius the theme gives every control;
    # scaled to the swatch so a small square still reads as rounded
    # rather than as a circle.
    radius = min(size.width(), size.height()) / 3.0
    painter.drawRoundedRect(
        QRectF(0.5, 0.5, size.width() - 1, size.height() - 1), radius, radius
    )
    painter.end()
    return pm


def _to_qcolor(spec: str) -> QColor | None:
    spec = (spec or "").strip()
    if not spec:
        return None
    c = QColor(spec)
    if c.isValid():
        return c
    try:  # matplotlib understands many names Qt does not ("darkblue" it does; "C0" it doesn't)
        from matplotlib.colors import to_hex

        from ruyso_app.core import colors

        # The panel draws swatches long before any plot has run, so the
        # app's own colour names ("materialblue") have to be registered
        # here too -- otherwise they render as an empty square until the
        # first figure is built. Idempotent.
        colors.register()
        return QColor(to_hex(spec))
    except Exception:  # noqa: BLE001
        return None


# -- dispatch -----------------------------------------------------


def pixmap_for(kind: str, value: str, size: QSize | None = None) -> QPixmap:
    """Render the swatch for one combo item. ``kind`` is one of the
    keys of :data:`_ICON_SIZES`."""
    if kind == "colormap":
        return colormap_pixmap(value, size)
    if kind == "marker":
        return marker_pixmap(value, size)
    if kind == "linestyle":
        return linestyle_pixmap(value, size)
    if kind == "hatch":
        return hatch_pixmap(value, size)
    if kind == "shapemap":
        return shapemap_pixmap(value, size)
    if kind == "color":
        return color_pixmap(value, size)
    return QPixmap()


def icon_for(kind: str, value: str, size: QSize | None = None) -> QIcon:
    """:func:`pixmap_for` wrapped in a ``QIcon`` (empty icon if nothing renders)."""
    pm = pixmap_for(kind, value, size)
    return QIcon(pm) if not pm.isNull() else QIcon()
