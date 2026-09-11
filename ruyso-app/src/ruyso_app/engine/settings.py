"""
Application preferences: one JSON file, read and written GUI-free.

Mirrors :mod:`ruyso_app.engine.colormaps` -- same config directory, same
``$RUYSO_CONFIG_DIR`` override, same atomic temp-file write -- so the two
stores behave identically and can be reasoned about together.

It lives in ``engine`` rather than ``ui`` because several of the things
it holds are read outside any window: the disk-cache budget by
:mod:`ruyso_app.engine.cache`, the chart defaults by ``nodes/viz.py``.
A headless run therefore honours the same preferences the app does.

Keys are flat dotted strings (``"cache.max_gb"``) grouped by the
Preferences page they appear on. :data:`DEFAULTS` is the single source
of truth for what exists and what type it is: :func:`get` falls back to
it, :func:`set` rejects unknown keys outright, and a value of the wrong
type is treated as absent rather than being handed to a caller that
expects a number. A settings file half-edited by hand, or written by a
newer version, therefore degrades to defaults instead of breaking the
app.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

#: Every preference, with its default. Adding a key here is all it takes
#: for the store to accept it; the dialog decides how to present it.
DEFAULTS: dict[str, Any] = {
    # -- General -------------------------------------------------------
    "general.restore_window": True,
    "general.restore_last_pipeline": False,
    "general.confirm_on_close": True,
    "general.default_folder": "",
    #: Written by the app, not shown in the dialog.
    "general.window_geometry": "",
    "general.last_pipeline": "",
    # -- Appearance ----------------------------------------------------
    "appearance.theme": "system",  # system | dark | light
    "appearance.accent_color": "",  # blank = the theme's own accent
    "appearance.font_size": 0,  # 0 = whatever the platform uses
    "appearance.canvas_grid": "dots",  # none | dots | lines
    "appearance.snap_to_grid": False,
    "appearance.grid_size": 20,
    "appearance.node_thumbnails": True,
    "appearance.thumbnail_width": 180,
    "appearance.show_run_log": True,
    # -- Execution -----------------------------------------------------
    "execution.auto_run": True,
    "execution.debounce_ms": 450,
    "execution.render_figures_in_autorun": True,
    "execution.stop_on_first_error": False,
    # -- Cache ---------------------------------------------------------
    "cache.enabled": True,
    "cache.max_gb": 2.0,
    # -- Chart defaults ------------------------------------------------
    #: These are *overrides*, and blank / 0 means "leave each node's own
    #: default alone". Graphers deliberately differ -- eight distinct
    #: figure sizes are in use, one of them a 6.0x2.2 strip -- so a
    #: single value applied to all of them would flatten choices the
    #: node authors made on purpose. Set one and it wins everywhere.
    "charts.fig_width": 0.0,
    "charts.fig_height": 0.0,
    "charts.dpi": 0,
    "charts.continuous_colormap": "",
    "charts.categorical_colormap": "",
    "charts.style": "seaborn-v0_8-whitegrid",
    "charts.font_family": "",
    # -- Export --------------------------------------------------------
    #: Aligned with the export nodes' own schema defaults, so seeding
    #: changes nothing until someone changes a preference.
    "export.figure_format": "png",
    "export.figure_dpi": 150,
    "export.transparent": False,
    "export.bbox_tight": True,
    "export.table_format": "csv",
    "export.folder": "",
    # -- Dashboard -----------------------------------------------------
    "dashboard.grid_size": 20,
    "dashboard.snap": False,
    "dashboard.show_grid": False,
    "dashboard.page_size": "content",  # content | a4 | letter
    "dashboard.export_dpi": 200,
    "dashboard.title_font": "",
    "dashboard.text_font": "",
    # -- Data ----------------------------------------------------------
    "data.max_preview_rows": 5000,
    "data.float_precision": 4,
    "data.missing_display": "",
    "data.csv_separator": ",",
    "data.csv_encoding": "utf-8",
    "data.csv_decimal": ".",
    # -- Toolbox -------------------------------------------------------
    #: Keys of the optional node families that are switched on; the
    #: essential ones are always on and are never listed. See
    #: ``core.toolboxes``. Filled in below, so the default is "everything".
    "toolbox.enabled": [],
    # -- Advanced ------------------------------------------------------
    "advanced.verbose_log": False,
}


def _install_toolbox_default() -> None:
    """Default the toolbox list to every optional family, without a
    circular import at module level (``core.toolboxes`` reads settings)."""
    from ruyso_app.core import toolboxes

    DEFAULTS["toolbox.enabled"] = toolboxes.default_enabled()


_install_toolbox_default()

#: Keys the app maintains itself; the dialog neither shows nor resets them.
INTERNAL_KEYS = frozenset({"general.window_geometry", "general.last_pipeline"})

#: In-process copy of the file, so a lookup during a run costs nothing.
#: ``None`` until first read; :func:`reload` drops it.
_cache: dict[str, Any] | None = None


# -- store ---------------------------------------------------------------


def config_path() -> Path:
    """Location of ``settings.json`` (override with ``$RUYSO_CONFIG_DIR``)."""
    env = os.environ.get("RUYSO_CONFIG_DIR")
    if env:
        base = Path(env)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "ruyso"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ruyso"
    return base / "settings.json"


def load_store() -> dict[str, Any]:
    """
    The stored values, or an empty mapping if the file is missing or
    unreadable. Never raises -- a corrupt settings file must not stop
    the app from starting.
    """
    global _cache
    if _cache is not None:
        return _cache
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    _cache = data if isinstance(data, dict) else {}
    return _cache


def save_store(store: dict[str, Any]) -> None:
    """Write ``store`` atomically (temp file + rename)."""
    global _cache
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=2, sort_keys=True, ensure_ascii=False))
    tmp.replace(path)
    _cache = dict(store)


def reload() -> None:
    """Drop the in-process copy, so the next read hits the file."""
    global _cache
    _cache = None


# -- accessors -----------------------------------------------------------


def get(key: str, default: Any = None) -> Any:
    """
    The value for ``key``, falling back to :data:`DEFAULTS`.

    A stored value whose type does not match the default's is ignored:
    a hand-edited ``"max_gb": "lots"`` should leave the cache on its
    2 GB budget, not hand a string to something that will multiply it.
    Ints are accepted where a float is expected, since JSON does not
    distinguish ``2`` from ``2.0``.
    """
    fallback = DEFAULTS.get(key, default)
    if key not in DEFAULTS:
        return default
    value = load_store().get(key, None)
    if value is None:
        return fallback
    if isinstance(fallback, bool):
        return value if isinstance(value, bool) else fallback
    if isinstance(fallback, float):
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback
    if isinstance(fallback, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else fallback
    if isinstance(fallback, str):
        return value if isinstance(value, str) else fallback
    if isinstance(fallback, list):
        # Only a list of strings: a stored list holding anything else is
        # not something a caller expecting names can use.
        return (
            list(value)
            if isinstance(value, list) and all(isinstance(v, str) for v in value)
            else list(fallback)
        )
    return value


def set(key: str, value: Any) -> None:  # noqa: A001 - the obvious name for it
    """
    Store one value and write the file.

    Raises:
        KeyError: If ``key`` is not in :data:`DEFAULTS`. A typo in a
            settings key would otherwise be stored happily and read back
            as the default forever.
    """
    update({key: value})


def update(values: dict[str, Any]) -> None:
    """Store several values in one write (one file rewrite, not N)."""
    unknown = [k for k in values if k not in DEFAULTS]
    if unknown:
        raise KeyError(f"Unknown setting(s): {', '.join(sorted(unknown))}")
    store = dict(load_store())
    store.update(values)
    save_store(store)


def reset(keys: list[str] | None = None) -> None:
    """
    Forget stored values, so they fall back to :data:`DEFAULTS`.

    ``keys=None`` resets everything the dialog can change, keeping the
    app's own bookkeeping (:data:`INTERNAL_KEYS`) -- resetting your
    preferences should not also forget which window size you had.
    """
    store = dict(load_store())
    if keys is None:
        keys = [k for k in store if k not in INTERNAL_KEYS]
    for key in keys:
        store.pop(key, None)
    save_store(store)


def as_dict() -> dict[str, Any]:
    """Every known setting with its effective value (stored or default)."""
    return {key: get(key) for key in DEFAULTS}
