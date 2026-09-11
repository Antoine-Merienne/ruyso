"""
Caching configuration for node execution.

Rather than hand-rolling a hash-based cache, we rely directly on
``joblib.Memory``: it already knows how to hash arbitrary Python
objects — including numpy arrays and pandas DataFrames — safely and
reasonably efficiently, and it handles cache invalidation and on-disk
storage for us. This module's only responsibility is to provide a
single, consistently configured ``Memory`` instance for the whole
engine, so every part of the codebase caches to the same place.

The actual "node + params + hash(inputs)" cache key described in the
architecture is realized in ``scheduler.py``: the function wrapped by
``Memory.cache`` takes ``(node_type, params, inputs)`` as its
arguments, and joblib hashes exactly those three things to form the
cache key.

Nothing evicts from that directory on its own, so it grows for as long
as the app is used — mine reached 835 MB before anyone looked. The
budget in ``cache.max_gb`` is applied by :func:`enforce_size_limit`,
which the app calls once at startup on a background thread: joblib 1.5
dropped ``bytes_limit`` from ``Memory.__init__`` in favour of an
explicit ``reduce_size`` pass, and that pass walks the whole directory,
which is not something to do on the way to seeing a result.
"""

from pathlib import Path

import joblib

from ruyso_app.engine import settings

# Default on-disk location for cached node results. Kept outside the
# repository (in the user's home directory) so the cache is never
# accidentally committed to version control and persists across
# checkouts of the project.
DEFAULT_CACHE_DIR = Path.home() / ".ruyso_app" / "cache"

_BYTES_PER_GB = 1024 ** 3


def cache_dir() -> Path:
    """Where cached node results are written."""
    return DEFAULT_CACHE_DIR


def is_enabled() -> bool:
    """Whether results are cached to disk at all (``cache.enabled``)."""
    return bool(settings.get("cache.enabled"))


def size_limit_bytes() -> int:
    """The configured disk budget, in bytes."""
    return int(float(settings.get("cache.max_gb")) * _BYTES_PER_GB)


def get_memory(
    location: str | Path | None = None, verbose: int = 0
) -> joblib.Memory:
    """
    Build a joblib.Memory instance used to cache node executions.

    Args:
        location: Directory where cached results are stored. ``None``
            (the default) means "whatever the preferences say" --
            :func:`cache_dir`, or no caching at all when
            ``cache.enabled`` is off. Pass an explicit path to override,
            or ``joblib.Memory(location=None)`` at the call site to
            disable caching regardless (as the tests do).
        verbose: joblib verbosity level (0 = silent, higher = more
            logging of cache hits/misses).

    Returns:
        A configured joblib.Memory instance.
    """
    if location is None:
        location = cache_dir() if is_enabled() else None
    return joblib.Memory(location=location, verbose=verbose)


def current_size_bytes(location: str | Path | None = None) -> int:
    """
    How much disk the cache is using right now.

    Walks the directory, so it is slow enough on a large cache to be
    worth calling off the GUI thread. Unreadable entries are skipped
    rather than raising: a size readout must not be able to fail.
    """
    root = Path(location) if location is not None else cache_dir()
    total = 0
    if not root.exists():
        return 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:  # noqa: PERF203 - a vanishing temp file is normal
            continue
    return total


def enforce_size_limit(location: str | Path | None = None) -> None:
    """
    Evict the oldest cached results until the cache fits its budget.

    Uses ``Memory.reduce_size(bytes_limit=...)``: joblib 1.5 removed the
    ``bytes_limit`` constructor argument, so this cannot be configured
    once and forgotten — it has to be an explicit pass. Never raises;
    failing to tidy the cache is not a reason to stop a run.
    """
    if not is_enabled():
        return
    root = Path(location) if location is not None else cache_dir()
    if not root.exists():
        return
    try:
        joblib.Memory(location=root, verbose=0).reduce_size(
            bytes_limit=size_limit_bytes()
        )
    except Exception:  # noqa: BLE001 - best-effort housekeeping
        return


def clear(location: str | Path | None = None) -> None:
    """Delete every cached result. Never raises."""
    root = Path(location) if location is not None else cache_dir()
    try:
        joblib.Memory(location=root, verbose=0).clear(warn=False)
    except Exception:  # noqa: BLE001 - best-effort
        return
