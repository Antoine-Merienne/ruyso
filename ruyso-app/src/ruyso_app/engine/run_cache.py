"""
Reusing the results of nodes that nothing has changed for.

The joblib cache in :mod:`ruyso_app.engine.cache` already memoises node
executions on disk, but 31 nodes opt out of it -- every grapher, and
every export -- because a matplotlib figure is not reliably hashable and
an export's whole point is a side effect. So a background auto-run,
which fires after *every* parameter edit, re-rendered every figure on
the canvas each time somebody nudged a colour three steps upstream.

This cache works one level up from joblib's: instead of asking "have I
computed this function on these arguments before", it asks "has anything
that feeds this node changed since I last ran it" -- using the
transitive signatures from :mod:`ruyso_app.engine.signatures`. When the
answer is no, the node's previous outputs are handed back and it never
runs at all, figure or not.

Two deliberate limits:

* **One entry per node.** Keyed by node id, holding its latest
  ``(signature, outputs)``. The cache is therefore never larger than the
  graph, and :meth:`ResultCache.prune` drops nodes that no longer exist.
  Entries hold DataFrames and figures, so an unbounded history keyed by
  signature could quietly reach hundreds of megabytes.
* **The results are shared, not copied.** A cached output is handed back
  by identity: no node in ``nodes/`` mutates its input in place, and
  returning the same object is what lets the UI skip re-rasterising a
  figure it has already drawn.
"""

from __future__ import annotations

from typing import Any, Iterable

#: Node categories that must always re-execute, whatever their signature
#: says. Loaders because a file can change on disk under an unchanged
#: path -- the signature cannot see that. Exports because their value
#: *is* the side effect: skipping one means an output file that was
#: deleted or edited outside the app is never written again. (The one
#: export with no side effect, ``export_to_dashboard``, returns ``{}``
#: immediately, so running it anyway costs nothing and saves the engine
#: from having to know any node by name.)
ALWAYS_RUN_CATEGORIES = frozenset({"loading", "export"})


def is_skippable(node_cls: Any) -> bool:
    """Whether a node of this class may be served from cache at all."""
    return getattr(node_cls, "category", "") not in ALWAYS_RUN_CATEGORIES


def content_token(signature: str, outputs: dict[str, Any]) -> str:
    """
    A signature that also changes when the node's *output* changes.

    Needed by exactly the nodes that are never cached. Re-running a
    loader is not enough on its own: a signature is built from node
    types, parameters and wiring, none of which move when a CSV is
    edited under an unchanged path -- so everything downstream would
    still see a cache hit and serve results computed from the old file.
    Folding a hash of what the loader actually returned into what its
    dependents key on closes that hole: same file, same token, and the
    rest of the pipeline is still skipped; changed file, and it is not.

    A value joblib cannot hash yields a token that never repeats, so
    the safe reading -- "assume it changed" -- is the fallback.
    """
    try:
        import joblib

        digest = joblib.hash(outputs)
    except Exception:  # noqa: BLE001 - unhashable output: assume it changed
        digest = None
    if digest is None:
        from uuid import uuid4

        digest = uuid4().hex
    return f"{signature}:{digest}"


class ResultCache:
    """
    The latest ``(signature, outputs)`` for each node, by node id.

    Not thread-safe by design: the auto-run worker is handed a
    :meth:`snapshot` to read from and fill, and the controller adopts it
    on the GUI thread once the run finishes. A worker that is terminated
    mid-run simply never has its snapshot adopted, so the live cache can
    never be observed half-written.
    """

    def __init__(self, entries: dict[str, tuple[str, dict]] | None = None) -> None:
        self._entries: dict[str, tuple[str, dict]] = dict(entries or {})

    # -- lookup / storage ------------------------------------------------

    def get(self, node_id: str, signature: str) -> dict[str, Any] | None:
        """
        This node's cached outputs, if they were computed under
        ``signature``. ``None`` on a miss -- including a *stale* hit,
        where the node is known but something feeding it has changed.
        """
        entry = self._entries.get(node_id)
        if entry is None or entry[0] != signature:
            return None
        return entry[1]

    def put(self, node_id: str, signature: str, outputs: dict[str, Any]) -> None:
        """Record what this node produced, replacing any earlier entry."""
        self._entries[node_id] = (signature, outputs)

    def forget(self, node_id: str) -> None:
        self._entries.pop(node_id, None)

    def prune(self, live_node_ids: Iterable[str]) -> None:
        """Drop entries for nodes that are no longer in the pipeline."""
        live = set(live_node_ids)
        for node_id in [n for n in self._entries if n not in live]:
            del self._entries[node_id]

    def clear(self) -> None:
        self._entries.clear()

    # -- handing it to a worker thread -----------------------------------

    def snapshot(self) -> ResultCache:
        """
        A detached copy for a background run to read from and add to.

        Shallow: the cached output dicts are shared, which is the point
        -- an unchanged figure must come back as the *same* object.
        Only the mapping is copied, so the live cache is unaffected by
        whatever the worker does to its own.
        """
        return ResultCache(self._entries)

    # -- introspection ---------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._entries

    def signature_of(self, node_id: str) -> str | None:
        """The signature this node's cached result was computed under."""
        entry = self._entries.get(node_id)
        return entry[0] if entry else None
