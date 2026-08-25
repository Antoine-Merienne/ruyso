# ruyso-app

Visual data science pipeline builder: a node-graph desktop application
where each box defines a step (load, clean, model, visualize) of a
Python data science pipeline.

The codebase is split into three independently testable layers:

| Layer | Package | Depends on | Status |
|---|---|---|---|
| 1. Node model | `ruyso_app.core`, `ruyso_app.nodes` | pydantic only | done |
| 2. Execution engine | `ruyso_app.engine` | Layer 1, networkx, joblib | done |
| 3. UI | `ruyso_app.ui` | Layers 1 & 2, PySide6, NodeGraphQt | not started |

Layers 1 and 2 have **no dependency on any GUI toolkit**: a pipeline
can be built, validated, and executed entirely from a script or the
command line.

## Setup

```bash
pip install -e ".[dev]"
```

## Running the test suite

```bash
pytest -q
```

## Running a pipeline headlessly (no UI)

A pipeline is described as JSON: a list of node instances and a list
of connections between their ports. See
`examples/simple_regression_pipeline.json` for a hand-written example
(CSV load -> drop missing values -> train/test split -> linear
regression fit -> scatter plot).

```bash
python examples/run_example.py examples/simple_regression_pipeline.json
```

Node execution results are cached on disk (via `joblib.Memory`, keyed
on node type + parameters + input values), so re-running the same
pipeline — or a pipeline that only changed a downstream node — does
not recompute unchanged upstream steps.

## Project layout

```
src/ruyso_app/
├── core/     # Node/Port/NodeParams contracts + NodeRegistry
├── nodes/    # Concrete nodes (loaders, transforms, models, viz)
├── engine/   # PipelineGraph, serialization, cache, scheduler
└── ui/       # Node-graph canvas (Phase 3, not started)
```
