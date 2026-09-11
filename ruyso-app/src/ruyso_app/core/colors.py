"""
Named colours this app adds on top of matplotlib's own.

matplotlib resolves colour *names* through one global mapping, so a name
it has never heard of ("materialblue") raises wherever it is used. Rather
than translating our names to hex at every call site -- and there are
many, since every ``core.params.color_field`` accepts a free-text colour
-- the names are registered into that mapping once, and from then on both
matplotlib and the UI's swatch renderer (which falls back to
``matplotlib.colors.to_hex``) understand them.

Registration is idempotent and uses ``setdefault``, so a name matplotlib
already knows is never shadowed. It lives in ``core`` with a lazy
matplotlib import so ``nodes/viz.py`` can stay matplotlib-free at module
level, and so an exported script -- which never touches the UI or the
engine -- resolves the same names the app does.
"""

from __future__ import annotations

#: Extra colour names, resolved exactly like a built-in matplotlib name.
#: ``materialblue`` is the app's accent (Material Blue 600, the dark
#: theme's ``theme.highlight_color``), pinned as a hex literal rather
#: than read from the theme: a figure keeps its colours when exported,
#: so a plot must never change appearance with the UI's light/dark mode.
NAMED_COLORS: dict[str, str] = {
    "materialblue": "#1e88e5",
}


def register() -> None:
    """Add :data:`NAMED_COLORS` to matplotlib's named-colour mapping."""
    try:
        from matplotlib.colors import get_named_colors_mapping
    except ImportError:  # pragma: no cover - matplotlib always present in practice
        return
    mapping = get_named_colors_mapping()
    for name, value in NAMED_COLORS.items():
        mapping.setdefault(name, value)
