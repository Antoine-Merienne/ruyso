"""
Pipeline scheduler: executes a PipelineGraph node by node.

The scheduler's job is strictly limited to orchestration:
    1. Ask the graph for a valid topological execution order.
    2. For each node, collect its inputs from the already-computed
       outputs of its upstream connections.
    3. Execute the node (through a joblib-cached function) and record
       its outputs.

It knows nothing about pandas, scikit-learn, or any specific node —
only about the generic Node/NodeSpec/Connection contracts from
``core`` and ``graph.py``. This is what lets a graph be executed
headlessly (from a script, a test, or a CLI) with no UI involved.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

import joblib

from ruyso_app.core import dtformat as _dtformat
from ruyso_app.core.registry import NodeRegistry
from ruyso_app.engine import cache as _cache
from ruyso_app.engine import errors as _errors
from ruyso_app.engine import run_cache as _run_cache
from ruyso_app.engine import settings as _settings
from ruyso_app.engine import signatures as _signatures
from ruyso_app.engine.errors import NodeError
from ruyso_app.engine.run_cache import ResultCache, is_skippable
from ruyso_app.engine import colormaps as _colormaps
from ruyso_app.engine.cache import get_memory
from ruyso_app.engine.graph import GraphValidationError, PipelineGraph


def _execute_node(
    node_type: str,
    params: dict[str, Any],
    inputs: dict[str, Any],
    source_token: tuple = (),
) -> dict[str, Any]:
    """
    Instantiate and run a single node — a pure function of its inputs.

    Kept as a standalone module-level function (rather than a method)
    specifically so it can be wrapped by ``joblib.Memory.cache``:
    joblib hashes exactly this function's arguments — ``node_type``,
    ``params``, and ``inputs`` — to decide whether a previously cached
    result can be reused instead of re-running the node. This is the
    "node + params + hash(inputs)" cache key from the design.

    Args:
        node_type: Identifier registered in the NodeRegistry.
        params: Raw parameter values for the node (validated here,
            when the node is constructed).
        inputs: Values for the node's input ports, keyed by port name.
        source_token: A stamp of the files this node reads
            (:func:`run_cache.source_token`). Unused by the body, and
            that is the whole point: it is here to be *hashed*. A
            loader has no inputs, so without it joblib keyed a CSV
            loader on its path alone and never noticed the file being
            edited under that path.

    Returns:
        The node's output dict, keyed by output port name.
    """
    node_cls = NodeRegistry.get(node_type)
    node = node_cls(params=params)
    node.validate_inputs(inputs)
    started = time.perf_counter()
    outputs = node.run(**inputs)
    # Only reached when there was no cached result, so this is always
    # real work: what ``cache.worth_caching`` decides the node's future
    # by (see engine/cache.py).
    _cache.record_compute_time(node_type, time.perf_counter() - started)
    # Datetime display formats ride along in ``DataFrame.attrs``, which
    # pandas drops for any result built from two parents (a merge, say).
    # Restoring them here covers every node at once, including ones
    # written later. Duck-typed, so no pandas import reaches the engine.
    _dtformat.carry_formats_through(outputs, inputs)
    return outputs


class _SkipCache:
    """
    "Has anything feeding this node changed since it last ran?", for the
    length of one run.

    Wraps a :class:`~ruyso_app.engine.run_cache.ResultCache` together
    with the transitive signatures it is keyed on, so both
    :meth:`PipelineScheduler.run` and
    :meth:`~PipelineScheduler.run_available` ask the question the same
    way. Disabled -- every answer a miss -- when no cache was passed.

    Signatures are folded *as the run goes* rather than upfront, because
    what a node's dependents key on can depend on what it produced: see
    ``run_cache.content_token``.
    """

    def __init__(self, graph: PipelineGraph, result_cache: ResultCache | None) -> None:
        self.cache = result_cache
        self.enabled = result_cache is not None
        self._own = _signatures.pipeline_signatures(graph) if self.enabled else {}
        self._upstream = _signatures.upstream_map(graph) if self.enabled else {}
        self._effective: dict[str, str] = {}

    def signature(self, node_id: str) -> str:
        if not self.enabled:
            return ""
        return _signatures.fold_signature(
            self._own.get(node_id, ""),
            (self._effective.get(s, "") for s in self._upstream.get(node_id, ())),
        )

    def get(self, node_id: str, node_cls: Any, signature: str) -> dict | None:
        """This node's previous outputs, if nothing feeding it changed."""
        if not self.enabled or not is_skippable(node_cls):
            return None
        return self.cache.get(node_id, signature)

    def reused(self, node_id: str, signature: str) -> None:
        self._effective[node_id] = signature

    def store(
        self,
        node_id: str,
        node_cls: Any,
        signature: str,
        outputs: dict,
        source_token: tuple = (),
    ) -> None:
        if not self.enabled:
            return
        if is_skippable(node_cls):
            self.cache.put(node_id, signature, outputs)
            self._effective[node_id] = signature
        else:
            # A loader or an export: its dependents must key on what it
            # produced, not merely on how it is configured.
            self._effective[node_id] = _run_cache.content_token(
                signature, outputs, source_token
            )

    def prune(self, order: Any) -> None:
        if self.enabled:
            self.cache.prune(order)  # a deleted node keeps nothing alive


@dataclass
class RunReport:
    """
    What one execution of a pipeline produced.

    Three outcomes, kept apart because they mean different things to
    whoever reads them:

    * :attr:`outputs` -- nodes that ran cleanly, mapped to their output
      dicts.
    * :attr:`errors` -- nodes that raised, mapped to a
      :class:`~ruyso_app.engine.errors.NodeError`. ``str()`` of one is a
      plain sentence, so anywhere the old code interpolated the
      exception keeps working.
    * :attr:`blocked` -- nodes that never ran, mapped to *the node that
      caused it*, or ``None`` when the node is simply not wired up yet.
      These used to appear in neither dict, so a run that stopped a
      third of the way through reported one failure and said nothing at
      all about the eight steps it silently skipped.

    Unpacks as ``(outputs, errors)`` so every existing caller --
    ``PipelineExecutionWorker``, ``AutoRunController``, the engine tests
    -- keeps working untouched while the blocked map becomes available
    to anything that asks for it.
    """

    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    errors: dict[str, NodeError] = field(default_factory=dict)
    blocked: dict[str, str | None] = field(default_factory=dict)
    #: Nodes whose result came from the cache instead of being computed
    #: (see :mod:`ruyso_app.engine.run_cache`). They appear in
    #: :attr:`outputs` like any other; this says which ones did no work,
    #: which is what lets the UI skip re-drawing a figure it already has.
    reused: set[str] = field(default_factory=set)

    def __iter__(self) -> Iterator[dict]:
        return iter((self.outputs, self.errors))

    @property
    def unwired(self) -> set[str]:
        """Blocked nodes that are missing a connection rather than a result."""
        return {node_id for node_id, cause in self.blocked.items() if cause is None}


class PipelineScheduler:
    """
    Executes a validated PipelineGraph and returns every node's outputs.
    """

    def __init__(self, memory: joblib.Memory | None = None) -> None:
        """
        Args:
            memory: A joblib.Memory instance used to cache node
                executions. Defaults to ``engine.cache.get_memory()``.
                Pass ``joblib.Memory(location=None)`` to disable
                caching (e.g. in tests).
        """
        self._memory = memory if memory is not None else get_memory()
        self._cached_execute = self._memory.cache(_execute_node)

    def _execute(
        self,
        node_type: str,
        params: dict[str, Any],
        inputs: dict[str, Any],
        source_token: tuple | None = None,
    ) -> dict[str, Any]:
        """
        Run a node, going through the joblib cache only if two things
        are true.

        Its class must opt in (``Node.cacheable``): nodes with side
        effects or non-hashable inputs/outputs (e.g. MatplotlibPlot,
        ExportFigure) declare ``cacheable = False`` and are always
        re-executed directly.

        And the work must be worth caching (``cache.worth_caching``):
        joblib hashes every input before it can even say whether it
        has an answer, so for a node that runs in 50 ms that question
        costs more than the answer. A type is judged by what it last
        really took, which is a per-type average of sorts -- the same
        node fed a tiny table and a huge one is remembered by whichever
        ran last.

        ``source_token`` is folded into the cache key so a node that
        reads a file re-runs when that file changes. Passed in by
        ``run_available``, which needs the same stamp for the skip
        cache; computed here otherwise.
        """
        node_cls = NodeRegistry.get(node_type)
        if not node_cls.cacheable or not _cache.worth_caching(node_type):
            return _execute_node(node_type, params, inputs)
        if source_token is None:
            source_token = _run_cache.source_token(node_cls, params)
        return self._cached_execute(node_type, params, inputs, source_token)

    def run(
        self,
        graph: PipelineGraph,
        progress_callback: Callable[[int, int], None] | None = None,
        node_callback: Callable[[str, str], None] | None = None,
        result_cache: ResultCache | None = None,
    ) -> RunReport:
        """
        Execute ``graph`` in dependency order, attempting *every* node.

        The graph is structurally validated first — an invalid graph
        (bad node type, unsatisfied required port, cycle) raises
        ``GraphValidationError`` before any node runs. Past that, a node
        that raises at runtime is recorded rather than aborting the run,
        and its descendants are reported *blocked* (never executed).

        Args:
            graph: The pipeline to run.
            progress_callback: If given, called ``(done, total)`` after
                each node is dealt with (run, failed, or blocked).
            node_callback: If given, called ``(node_id, phase)`` as each
                node is reached, with ``phase`` one of
                ``"running"`` / ``"ok"`` / ``"error"`` / ``"blocked"``.
            result_cache: If given, a node whose *transitive* signature
                matches its cached one is served from the cache instead
                of being executed, exactly as in ``run_available``, and
                is listed in ``RunReport.reused``. Loaders and exports
                still always run (``run_cache.ALWAYS_RUN_CATEGORIES``).
                Passing nothing -- the default -- executes every node,
                which is what "run this whole pipeline again" means.

        Returns:
            A :class:`RunReport`. It unpacks as ``(outputs, errors)``,
            so existing two-value callers are unaffected.
        """
        _colormaps.register_all(force=False)  # custom colormaps -> matplotlib
        graph.validate()

        order = graph.topological_order()
        total = len(order)
        report = RunReport()
        skip = _SkipCache(graph, result_cache)

        def emit(node_id: str, phase: str) -> None:
            if node_callback is not None:
                node_callback(node_id, phase)

        stop_on_first_error = bool(_settings.get("execution.stop_on_first_error"))

        for index, node_id in enumerate(order, start=1):
            spec = graph.get_node(node_id)
            cause = self._blocking_cause(graph, node_id, report)
            if cause is None and stop_on_first_error and report.errors:
                # Everything after the first failure is reported as
                # waiting on it, even where the graph would have let it
                # run: with this on, the first error is the answer and
                # the rest is noise.
                report.blocked[node_id] = next(iter(report.errors))
                emit(node_id, "blocked")
                if progress_callback is not None:
                    progress_callback(index, total)
                continue
            if cause is not None:
                # ``validate()`` guarantees every required port is wired,
                # so in a full run "not run" can only mean an upstream
                # failure -- never an unconnected input.
                report.blocked[node_id] = cause
                emit(node_id, "blocked")
            else:
                node_cls = NodeRegistry.all().get(spec.node_type)
                signature = skip.signature(node_id)
                cached = skip.get(node_id, node_cls, signature)
                if cached is not None:
                    report.outputs[node_id] = cached
                    report.reused.add(node_id)
                    skip.reused(node_id, signature)
                    emit(node_id, "ok")
                    if progress_callback is not None:
                        progress_callback(index, total)
                    continue
                emit(node_id, "running")
                inputs = self._collect_inputs(graph, node_id, report.outputs)
                token = _run_cache.source_token(node_cls, spec.params)
                try:
                    report.outputs[node_id] = self._execute(
                        spec.node_type, spec.params, inputs, token
                    )
                except Exception as exc:  # noqa: BLE001 - collected, not raised
                    report.errors[node_id] = self._describe(exc, spec, inputs)
                    emit(node_id, "error")
                else:
                    emit(node_id, "ok")
                    skip.store(
                        node_id, node_cls, signature, report.outputs[node_id], token
                    )
            if progress_callback is not None:
                progress_callback(index, total)

        skip.prune(order)
        return report

    @staticmethod
    def _blocking_cause(
        graph: PipelineGraph, node_id: str, report: RunReport
    ) -> str | None:
        """
        The node whose failure stops ``node_id`` from running, or ``None``.

        Reports the node that actually *failed*, not the immediate
        upstream neighbour: in a chain of five where the second raised,
        every one after it says "waiting on the second", which is the
        one worth going and looking at.

        ``None`` means no upstream *failure* -- either the node can run,
        or (in ``run_available``, where a caller checks for missing
        inputs first) the branch is merely unwired. The cause recorded
        for an upstream is passed straight through rather than falling
        back to the upstream's own name: a node sitting below an
        unfinished branch is unwired too, not blocked by a failure.
        """
        for conn in graph.incoming_connections(node_id):
            source = conn.source_node
            if source in report.errors:
                return source
            if source in report.blocked:
                return report.blocked[source]
        return None

    def _describe(self, exc: BaseException, spec: Any, inputs: dict[str, Any]) -> NodeError:
        """Read a raised exception as a sentence about the node that raised it."""
        return _errors.translate(
            exc,
            node_id=spec.id,
            node_type=spec.node_type,
            node_cls=NodeRegistry.all().get(spec.node_type),
            input_columns=_errors.columns_from_inputs(inputs),
            raw=traceback.format_exc(),
        )

    def run_available(
        self,
        graph: PipelineGraph,
        node_callback: Callable[[str, str], None] | None = None,
        result_cache: ResultCache | None = None,
        skip_categories: frozenset[str] = frozenset(),
    ) -> RunReport:
        """
        Best-effort partial execution: run every node whose inputs are
        all present and whose execution succeeds, silently skipping
        nodes that are unwired, misconfigured, or downstream of a
        skipped/failed node. Never raises.

        This backs the UI's automatic background refresh (loading a
        data file, wiring up a node) so results appear without an
        explicit Run, even while the rest of the pipeline is unfinished.

        Args:
            node_callback: If given, called ``(node_id, phase)`` as each
                node is reached -- ``"running"`` / ``"ok"`` /
                ``"error"`` / ``"blocked"`` (something upstream failed)
                / ``"unwired"`` (a required input has nothing plugged
                into it). The last two used to share the one
                ``"blocked"`` phase, which conflated a broken pipeline
                with a half-built one -- the ordinary state of a canvas
                someone is still assembling.
            result_cache: If given, a node whose *transitive* signature
                matches its cached one is served from the cache and
                never executed. This is what stops a background run
                re-rendering every figure on the canvas after each
                keystroke: graphers opt out of the joblib cache, so
                without this they re-ran unconditionally. Loaders and
                exports are always executed anyway (see
                ``run_cache.ALWAYS_RUN_CATEGORIES``), and the manual
                "Run Pipeline" passes no cache at all, so pressing Run
                stays the way to force real re-execution.
            skip_categories: Node categories to leave alone entirely.
                Backs the "re-render figures during auto-run"
                preference: with it off, ``{"grapher"}`` is passed and
                plots are left showing whatever they last rendered
                rather than being redrawn on every keystroke. Skipped
                nodes emit no phase, so their canvas dot keeps its last
                state instead of flickering.

        Returns:
            A :class:`RunReport`. It unpacks as ``(outputs, errors)``,
            so existing two-value callers are unaffected.
        """

        def emit(node_id: str, phase: str) -> None:
            if node_callback is not None:
                node_callback(node_id, phase)

        _colormaps.register_all(force=False)  # custom colormaps -> matplotlib
        report = RunReport()
        try:
            order = graph.topological_order()
        except GraphValidationError:
            return report

        skip = _SkipCache(graph, result_cache)

        for node_id in order:
            spec = graph.get_node(node_id)
            node_cls = NodeRegistry.all().get(spec.node_type)
            if node_cls is None:
                continue
            if getattr(node_cls, "category", "") in skip_categories:
                continue  # deliberately left alone; not blocked, not failed

            inputs: dict[str, Any] = {}
            missing_upstream = False
            cause: str | None = None
            for conn in graph.incoming_connections(node_id):
                upstream = report.outputs.get(conn.source_node)
                if upstream is None or conn.source_port not in upstream:
                    missing_upstream = True
                    cause = self._blocking_cause(graph, node_id, report)
                    break
                inputs[conn.target_port] = upstream[conn.source_port]
            if missing_upstream:
                # A missing upstream result is only a *failure* when
                # something actually failed; otherwise this branch is
                # merely unfinished, like the node itself.
                report.blocked[node_id] = cause
                emit(node_id, "blocked" if cause else "unwired")
                continue

            required = {p.name for p in node_cls.inputs if p.required}
            if not required.issubset(inputs):
                report.blocked[node_id] = None
                emit(node_id, "unwired")
                continue

            # Only now, with the inputs known to be available, is a
            # cache hit safe to serve: reaching here means nothing
            # upstream failed this run. Checking earlier would hand back
            # a stale result under a node whose loader had just started
            # erroring -- a green node showing yesterday's data below a
            # red one.
            signature = skip.signature(node_id)
            cached = skip.get(node_id, node_cls, signature)
            if cached is not None:
                report.outputs[node_id] = cached
                report.reused.add(node_id)
                skip.reused(node_id, signature)
                emit(node_id, "ok")
                continue

            emit(node_id, "running")
            token = _run_cache.source_token(node_cls, spec.params)
            try:
                report.outputs[node_id] = self._execute(
                    spec.node_type, spec.params, inputs, token
                )
            except Exception as exc:  # noqa: BLE001 - collected, not raised
                report.errors[node_id] = self._describe(exc, spec, inputs)
                emit(node_id, "error")
            else:
                emit(node_id, "ok")
                skip.store(
                    node_id, node_cls, signature, report.outputs[node_id], token
                )

        skip.prune(order)
        return report

    @staticmethod
    def _collect_inputs(
        graph: PipelineGraph,
        node_id: str,
        computed_outputs: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build the input dict for ``node_id`` from upstream outputs.

        Args:
            graph: The pipeline graph being executed.
            node_id: The node whose inputs are being assembled.
            computed_outputs: Outputs already produced by upstream
                nodes (guaranteed available because nodes are visited
                in topological order).

        Returns:
            Dict mapping each connected input port name to the value
            produced by the corresponding upstream output port.
        """
        inputs: dict[str, Any] = {}
        for connection in graph.incoming_connections(node_id):
            upstream_outputs = computed_outputs[connection.source_node]
            inputs[connection.target_port] = upstream_outputs[connection.source_port]
        return inputs
