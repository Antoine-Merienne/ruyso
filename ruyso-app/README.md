# ruyso-app

Visual data science pipeline builder: a node-graph desktop application
where each box defines a step (load, clean, model, visualize) of a
Python data science pipeline.

The codebase is split into three independently testable layers:

| Layer | Package | Depends on | Status |
|---|---|---|---|
| 1. Node model | `ruyso_app.core`, `ruyso_app.nodes` | pydantic only | done |
| 2. Execution engine | `ruyso_app.engine` | Layer 1, networkx, joblib | done |
| 3. UI | `ruyso_app.ui` | Layers 1 & 2, PySide6, NodeGraphQt | done (beta) |

Layers 1 and 2 have **no dependency on any GUI toolkit**: a pipeline
can be built, validated, and executed entirely from a script or the
command line, with nothing installed beyond `pip install -e .`.

## Setup

```bash
# Core + engine only (no GUI toolkit installed):
pip install -e ".[dev]"

# Everything, including the desktop UI:
pip install -e ".[dev,ui]"
```

## Running the test suite

```bash
pytest -q
```

The `tests/ui/` suite requires the `ui` extra (PySide6 + NodeGraphQt).
It runs fully headlessly — no display server is needed, including in
CI — via the Qt "offscreen" platform plugin:

```bash
QT_QPA_PLATFORM=offscreen pytest -q
```

## Launching the desktop app

```bash
pip install -e ".[ui]"
python -m ruyso_app.ui
```

This opens the node-graph canvas with a node palette (drag nodes in,
or press Tab on the canvas to search), a properties panel for the
selected node (auto-generated from each node's parameters — no manual
form-building), a run log, and a live preview of the last figure
produced. The toolbar lets you:

- **Load Pipeline...** / **Save Pipeline...** — read/write the exact
  same JSON format used by the headless CLI below, so a pipeline built
  visually can be run from the command line and vice versa.
- **Export as Script...** — write the current pipeline out as a
  standalone `.py` file (see below).
- **Run Pipeline** — execute the current canvas on a background
  thread (the UI stays responsive) and show results in the run log
  and figure preview.

To change how the app looks (colors, node category colors, window
stylesheet), edit `src/ruyso_app/ui/theme.py` — it is the only file
that needs touching for purely visual changes.

> Packaging the app into a standalone executable (PyInstaller/Nuitka)
> is intentionally not set up yet — planned for once more features
> have been added.

## Running a pipeline headlessly (no UI)

A pipeline is described as JSON: a list of node instances and a list
of connections between their ports. See
`examples/simple_regression_pipeline.json` for a hand-written example
(CSV load -> drop missing values -> train/test split -> linear
regression fit -> scatter plot -> save the plot to disk).

```bash
python examples/run_example.py examples/simple_regression_pipeline.json
```

Node execution results are cached on disk (via `joblib.Memory`, keyed
on node type + parameters + input values), so re-running the same
pipeline — or a pipeline that only changed a downstream node — does
not recompute unchanged upstream steps. Nodes with side effects or
non-hashable outputs (e.g. `matplotlib_plot`, `figure_export`) opt out
of caching via `Node.cacheable = False` and always re-run.

## Exporting a pipeline as a standalone script

Any validated pipeline (built visually or written by hand as JSON) can
be exported to a plain `.py` file that reproduces it exactly, with
**no dependency on the engine** (no `PipelineGraph`,
`PipelineScheduler`, `networkx`, or `joblib`) and none on the UI —
only on the concrete node classes it actually uses:

```bash
python examples/export_to_script.py \
    examples/simple_regression_pipeline.json \
    examples/simple_regression_pipeline_exported.py

python examples/simple_regression_pipeline_exported.py
```

This is useful for reproducing a result without installing the app,
for auditing exactly what a pipeline does, or for handing a pipeline
off as ordinary, readable Python code.

## Project layout

```
src/ruyso_app/
├── core/     # Node/Port/NodeParams contracts + NodeRegistry
├── nodes/    # Concrete nodes (loaders, transforms, models, viz, export)
├── engine/   # PipelineGraph, serialization, cache, scheduler, codegen
└── ui/       # NodeGraphQt canvas, property forms, main window
```
