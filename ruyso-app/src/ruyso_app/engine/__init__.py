"""
Execution engine layer.

This package is the only part of the codebase (besides ``ui/``) that
is allowed to depend on ``core`` and ``nodes`` together: it takes a
pipeline description (a graph of node instances and their
connections), validates it, and executes it — without ever importing
anything from ``ui``. That last point is what keeps this layer usable
from a plain CLI / test / notebook, with no GUI installed at all.

Modules:
    graph.py          -> PipelineGraph: in-memory representation of the
                          pipeline as a networkx.DiGraph, plus validation
                          and topological ordering.
    serialization.py  -> Convert a PipelineGraph to/from a plain JSON
                          document (the on-disk pipeline format).
    cache.py           -> A single, consistently configured joblib.Memory
                          instance used to memoize node executions.
    scheduler.py       -> PipelineScheduler: runs a PipelineGraph node by
                          node in topological order, wiring outputs to
                          downstream inputs, with caching.
"""
