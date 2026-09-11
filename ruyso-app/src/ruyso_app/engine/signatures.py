"""
Fingerprinting a pipeline: what would change a node's output.

A *signature* captures everything about a node that could make it
produce something different -- its type, its parameter values, and its
incoming wiring. Two uses, both of which are really the same question
asked at different times:

* **Is this shown result still current?** The Table and Dashboard tabs
  compare a node's signature against the one it had when the pipeline
  was last run, and tag the difference "· modified"
  (:func:`modified_since_run`).
* **Do we need to run this node at all?** The scheduler compares a
  node's *transitive* signature -- its own, folded together with every
  upstream node's -- against the one its cached result was computed
  under (:func:`transitive_signatures`, used by
  :mod:`ruyso_app.engine.run_cache`).

The transitive variant is the important one for skipping work: a node's
own signature is unchanged when you edit something three steps
upstream, and running it again on new inputs is exactly what you want.
Folding the upstream signatures in makes "unchanged" mean "unchanged
all the way back to the loaders".

Pure functions over :class:`~ruyso_app.engine.graph.PipelineGraph`, with
no UI and no pandas -- ``ui/run_snapshot.py`` re-exports the first two
for the UI's own use.
"""

from __future__ import annotations

import hashlib
from typing import Iterable

from ruyso_app.engine.graph import GraphValidationError, PipelineGraph

#: Separator between the parts of a signature. A unit separator cannot
#: appear in a node id, a port name or a repr, so two different pipelines
#: cannot collide by having a part that merely *looks* like two parts.
_SEP = "\x1f"


def pipeline_signatures(pipeline: PipelineGraph) -> dict[str, str]:
    """
    ``node_id -> signature`` for every node, from its own definition only.

    Covers the node's type, its parameters and the wires coming into it
    -- but *not* what any upstream node is doing. Two runs where only a
    loader's file path changed produce identical signatures for every
    node downstream of it; :func:`transitive_signatures` is the variant
    that notices.
    """
    incoming: dict[str, list[str]] = {}
    for conn in pipeline.connections:
        incoming.setdefault(conn.target_node, []).append(
            f"{conn.source_node}.{conn.source_port}->{conn.target_port}"
        )
    signatures: dict[str, str] = {}
    for node_id, spec in pipeline.nodes.items():
        params = repr(sorted(spec.params.items(), key=lambda kv: kv[0]))
        wires = repr(sorted(incoming.get(node_id, [])))
        signatures[node_id] = f"{spec.node_type}|{params}|{wires}"
    return signatures


def fold_signature(own: str, upstream_signatures: Iterable[str]) -> str:
    """
    Combine a node's own signature with its upstreams' into one digest.

    Upstream signatures are sorted first, so the order connections
    happen to be listed in cannot change the answer.
    """
    parts = [own, *sorted(upstream_signatures)]
    return hashlib.blake2b(_SEP.join(parts).encode("utf-8"), digest_size=16).hexdigest()


def upstream_map(pipeline: PipelineGraph) -> dict[str, set[str]]:
    """``node_id -> {source node id, ...}`` for every wired input."""
    upstream: dict[str, set[str]] = {}
    for conn in pipeline.connections:
        upstream.setdefault(conn.target_node, set()).add(conn.source_node)
    return upstream


def transitive_signatures(pipeline: PipelineGraph) -> dict[str, str]:
    """
    ``node_id -> signature`` folding in every upstream node's signature.

    Walks in dependency order so each node can be hashed together with
    its already-resolved upstreams; the result changes if *anything*
    that feeds the node changed, however far back. Upstream signatures
    are sorted before hashing so the order connections happen to be
    listed in cannot change the answer.

    Returns an empty mapping for a graph with a cycle: there is no
    dependency order to fold along, and a cyclic pipeline cannot run
    anyway.
    """
    own = pipeline_signatures(pipeline)
    upstream = upstream_map(pipeline)

    try:
        order = pipeline.topological_order()
    except GraphValidationError:
        return {}

    resolved: dict[str, str] = {}
    for node_id in order:
        resolved[node_id] = fold_signature(
            own.get(node_id, ""),
            (resolved.get(source, "") for source in upstream.get(node_id, ())),
        )
    return resolved


def modified_since_run(
    pipeline: PipelineGraph, run_signatures: dict[str, str]
) -> set[str]:
    """
    Node ids whose output may differ from ``run_signatures`` (the
    signatures captured when the pipeline was last run).

    Empty if ``run_signatures`` is empty (nothing has been run).
    """
    if not run_signatures:
        return set()

    current = pipeline_signatures(pipeline)

    try:
        order = pipeline.topological_order()
    except Exception:  # noqa: BLE001 - fall back to arbitrary order
        order = list(pipeline.nodes)

    upstream: dict[str, set[str]] = {}
    for conn in pipeline.connections:
        upstream.setdefault(conn.target_node, set()).add(conn.source_node)

    modified: set[str] = set()
    for node_id in order:
        if run_signatures.get(node_id) != current.get(node_id):
            modified.add(node_id)
        elif any(up in modified for up in upstream.get(node_id, ())):
            modified.add(node_id)
    return modified
