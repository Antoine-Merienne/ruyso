"""
Custom / favourite colormaps: an on-disk store plus matplotlib
registration.

The Options-panel colormap dropdowns (and the Colormap Designer /
Manager UI) read the *resolved lists* from here; grapher nodes just
pass a colormap *name* to matplotlib, so any custom map has to be
registered with matplotlib before a node runs -- ``PipelineScheduler``
does that via :func:`register_all` at the top of every run.

GUI-free: this lives in the engine layer and imports matplotlib only
lazily, so ``core`` / ``nodes`` importing it stays cheap and
toolkit-free.

Store file (JSON, at :func:`config_path`)::

    {
      "custom": {
        "Ocean":  {"kind": "continuous",  "stops":  [[0.0,"#012"],[1.0,"#9ef"]]},
        "Teams":  {"kind": "qualitative", "colors": ["#e41","#37b","#4a4"]}
      },
      "lists": {                      # user's visible + ordered selection
        "continuous":  ["viridis", "Ocean", "coolwarm"],
        "qualitative": ["Teams", "tab10"]
      }
    }

An absent / empty ``lists`` entry means "use the built-in defaults plus
any custom maps of that kind".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONTINUOUS = "continuous"
QUALITATIVE = "qualitative"
KINDS = (CONTINUOUS, QUALITATIVE)

#: Built-in maps offered by default, per kind, in default order.
BUILTIN: dict[str, list[str]] = {
    CONTINUOUS: [
        "viridis", "plasma", "cividis", "magma", "coolwarm",
        "Spectral", "Blues", "Greens", "Purples", "Greys",
    ],
    QUALITATIVE: ["tab10", "tab20", "Set1", "Set2", "Set3", "Paired", "Dark2", "Accent"],
}


# -- store -----------------------------------------------------------


def config_path() -> Path:
    """Location of ``colormaps.json`` (override with ``$RUYSO_CONFIG_DIR``)."""
    env = os.environ.get("RUYSO_CONFIG_DIR")
    if env:
        base = Path(env)
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") / "ruyso"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "ruyso"
    return base / "colormaps.json"


def _empty_store() -> dict[str, Any]:
    return {"custom": {}, "lists": {}}


def load_store() -> dict[str, Any]:
    """The parsed store, or an empty one if it is missing / unreadable."""
    try:
        data = json.loads(config_path().read_text())
    except (OSError, ValueError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("custom", {})
    data.setdefault("lists", {})
    if not isinstance(data["custom"], dict):
        data["custom"] = {}
    if not isinstance(data["lists"], dict):
        data["lists"] = {}
    return data


def save_store(store: dict[str, Any]) -> None:
    """Write ``store`` atomically (temp file + rename)."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(store, indent=2, ensure_ascii=False))
    tmp.replace(path)


# -- queries -------------------------------------------------------


def custom_definitions() -> dict[str, dict]:
    """``{name: {"kind":..., "stops"|"colors":...}}`` for every custom map."""
    return dict(load_store().get("custom", {}))


def _custom_names(store: dict, kind: str) -> list[str]:
    return [n for n, d in store.get("custom", {}).items() if d.get("kind") == kind]


def _dedupe(names: list[str]) -> list[str]:
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def all_manageable(kind: str) -> list[str]:
    """Every colormap name the Manager can show for ``kind`` (built-in + custom)."""
    return _dedupe(BUILTIN[kind] + _custom_names(load_store(), kind))


def resolved_lists() -> dict[str, list[str]]:
    """The effective visible + ordered colormap names for each kind.

    Uses the user's saved order/visibility when present; otherwise the
    built-in defaults for that kind plus its custom maps. Never empty.
    """
    store = load_store()
    out: dict[str, list[str]] = {}
    for kind in KINDS:
        available = set(all_manageable(kind))
        saved = store.get("lists", {}).get(kind)
        if saved:
            names = [n for n in saved if n in available]
        else:
            names = all_manageable(kind)
        if not names:  # safety net -- a dropdown is never empty
            names = [BUILTIN[kind][0]]
        out[kind] = _dedupe(names)
    return out


# -- matplotlib registration ------------------------------------------


def build_cmap(name: str, definition: dict) -> Any:
    """Turn a stored definition into a matplotlib ``Colormap``."""
    from matplotlib.colors import LinearSegmentedColormap, ListedColormap

    if definition.get("kind") == QUALITATIVE:
        colours = list(definition.get("colors") or []) or ["#000000"]
        return ListedColormap(colours, name=name)
    raw = definition.get("stops") or [[0.0, "#000000"], [1.0, "#ffffff"]]
    stops = sorted(([float(p), str(c)] for p, c in raw), key=lambda s: s[0])
    if len(stops) < 2:
        stops = [[0.0, stops[0][1]], [1.0, stops[0][1]]]
    lo, hi = stops[0][0], stops[-1][0]
    span = (hi - lo) or 1.0
    return LinearSegmentedColormap.from_list(
        name, [((p - lo) / span, c) for p, c in stops]
    )


def upsert(name: str, definition: dict) -> None:
    """Add or replace a custom colormap and re-register with matplotlib."""
    store = load_store()
    store["custom"][name] = definition
    save_store(store)
    register_all(force=True)


def forget(name: str) -> None:
    """Delete a custom colormap: drop it from the store, every ``lists``
    selection, and matplotlib's registry."""
    store = load_store()
    store["custom"].pop(name, None)
    for kind in KINDS:
        current = store["lists"].get(kind)
        if current and name in current:
            store["lists"][kind] = [n for n in current if n != name]
    save_store(store)
    try:
        import matplotlib

        matplotlib.colormaps.unregister(name)
    except Exception:  # noqa: BLE001 - not registered / older matplotlib
        pass
    register_all(force=True)


def set_lists(lists: dict[str, list[str]]) -> None:
    """Persist the Manager's visible + ordered selection for each kind."""
    store = load_store()
    store["lists"] = {kind: list(lists.get(kind, [])) for kind in KINDS}
    save_store(store)


def reset_lists() -> None:
    """Forget the Manager's customisation -- back to built-in defaults."""
    store = load_store()
    store["lists"] = {}
    save_store(store)


_last_signature: tuple | None = None


def register_all(force: bool = True) -> None:
    """Register every custom colormap with matplotlib.

    Called at the top of each scheduler run (``force=False`` -- a
    cheap mtime check skips the work when nothing changed) and by the
    Designer / Manager after a save (``force=True``). Never raises.
    """
    global _last_signature
    try:
        path = config_path()
        try:
            signature = (str(path), path.stat().st_mtime_ns)
        except OSError:
            signature = (str(path), 0)
        if not force and signature == _last_signature:
            return

        import warnings

        import matplotlib

        with warnings.catch_warnings():
            # re-registering an existing custom map is expected here
            warnings.filterwarnings("ignore", message="Overwriting the cmap")
            for name, definition in custom_definitions().items():
                try:
                    matplotlib.colormaps.register(
                        build_cmap(name, definition), name=name, force=True
                    )
                except Exception:  # noqa: BLE001 - one bad entry must not block the rest
                    continue
        _last_signature = signature
    except Exception:  # noqa: BLE001 - a broken config never blocks a run
        pass
