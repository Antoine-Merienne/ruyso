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
"""

from pathlib import Path

import joblib

# Default on-disk location for cached node results. Kept outside the
# repository (in the user's home directory) so the cache is never
# accidentally committed to version control and persists across
# checkouts of the project.
DEFAULT_CACHE_DIR = Path.home() / ".ruyso_app" / "cache"


def get_memory(location: str | Path | None = DEFAULT_CACHE_DIR, verbose: int = 0) -> joblib.Memory:
    """
    Build a joblib.Memory instance used to cache node executions.

    Args:
        location: Directory where cached results are stored. Pass
            ``None`` to disable caching entirely — joblib.Memory with
            ``location=None`` becomes a transparent no-op, which is
            useful in tests that must not depend on cache state.
        verbose: joblib verbosity level (0 = silent, higher = more
            logging of cache hits/misses).

    Returns:
        A configured joblib.Memory instance.
    """
    return joblib.Memory(location=location, verbose=verbose)
