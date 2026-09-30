# Other features

Everything that is not a node or a panel: menus and shortcuts, the pipeline file format, running without the app, exporting to Python, colormaps and themes.

## Menus and shortcuts

This opens a single window with a three-tab band — **Pipeline**,
**Table**, **Dashboard** — over a global menu bar. There is no
toolbar; every action is in a menu:

- **Pipeline** menu (always available, on every tab):
  - **Save Pipeline** (`Cmd+S` on macOS, `Ctrl+S` elsewhere) writes to
    the open file, asking for a name only the first time; **Save Pipeline
    As (JSON)…** (`Cmd/Ctrl+Shift+S`) always asks.
  - **Open Pipeline (JSON)…** / **Save Pipeline** — read/write
    the exact same JSON format used by the headless CLI below, so a
    pipeline built visually runs from the command line and vice versa.
    The Dashboard's layout rides along in a separate `dashboard` section
    of the same file, and the canvas's in a `canvas` section — where
    every node sits, and which figure previews are collapsed. The CLI
    ignores both. A file without a `dashboard` section opens with an
    empty dashboard; one without a `canvas` section (hand-written, or
    saved before it existed) is laid out in a row.
  - **Export as Script (.py)…** — write the pipeline out as a
    standalone `.py` file (see below).
  - **Run Pipeline** (shortcut **F5**) — execute the canvas on a
    background thread; results land in the run log and the on-canvas
    figure previews. Steps nothing has changed for are reused from the
    last run rather than recomputed (loaders and exports always run, so
    a file edited on disk is still picked up).
  - **Force Full Run** (shortcut **Shift+F5**, or **Shift** with the Run
    button) — the same, but computing every step again from scratch.
- **Edit** menu (always): **Undo** (`Cmd/Ctrl+Z`) and **Redo**
  (`Cmd/Ctrl+Shift+Z`, or `Ctrl+Y`), driven by NodeGraphQt's own
  `QUndoStack` — it already records node creation, deletion, wiring and
  every `set_property`, so a parameter edit is as undoable as a deleted
  node. Two details make it usable: selecting a node is pushed with
  `push_undo=False` (`BaseNode.set_selected` would otherwise stack a
  command per node and the first few `Ctrl+Z` presses would only undo
  selections), and the resync that rebuilds the Options form hangs off
  the undo/redo *actions*, not off the stack's `indexChanged` — the
  latter fires on every ordinary edit too and would rebuild the form out
  from under the widget being typed in. Opening a pipeline clears the
  history, so an undo can never unbuild the file you just opened.
- **Node** menu (Pipeline tab): **New Node ▸ _macro type_** (chord
  shortcuts `Cmd/Ctrl+P` then `L`/`T`/`M`/`S`/`G`/`E`), and
  **Selected Node ▸** **Delete Node** (`Ctrl/Cmd+Backspace`), **Copy** /
  **Cut** / **Paste** (`Cmd/Ctrl+C`/`X`/`V`) and **Duplicate**
  (`Cmd/Ctrl+D`). A pasted or duplicated plot comes with its own figure
  preview, filled in by the next automatic run.
- **Dashboard** menu (Dashboard tab): **Exporter…**.
- **Colormaps** menu (always): **Colormap Designer…** builds custom
  colormaps — a *continuous* one from draggable gradient stops or a
  *qualitative* one from an ordered swatch list, seedable from any
  built-in map and reversible; **Colormap Manager…** picks which maps
  (built-in + custom) appear in the colormap dropdowns, and in what
  order, per kind. Both persist to `~/.config/ruyso/colormaps.json`
  (`engine/colormaps.py`), which the scheduler re-registers with
  matplotlib at the top of every run. (Exported scripts do not yet
  inline a custom colormap's definition — a name-only reference will
  not resolve on a machine without the same config.)
- **View ▸ Theme**: **System** (default — follows the OS light/dark
  setting, live), **Dark**, or **Light**. The whole app is forced onto
  Qt's *Fusion* style driven by a palette from `theme.py`, so every
  widget (including combos, list widgets, spin boxes, the Table-tab
  panels…) is themed consistently rather than half of them following
  the OS appearance.

## Datetime display formats

**Datetime display formats.** A datetime column is *always* a real
`datetime64` column, never a formatted string — that is what keeps
`sort` chronological, `resample_datetime` / `diff` able to do
arithmetic, and the time-series graphers able to place points on a
date axis. Formatting is therefore a **rendering** concern, applied at
the edge and never to the data. `core/dtformat.py` owns the
convention: a node that knows how its column should read (such as
`combine_datetime` with only year + month mapped) records a
`strftime` pattern in `DataFrame.attrs`, which pandas carries through
copies, filters, sorts, merges and resamples, so the format survives
the pipeline with no node forwarding it by hand. Where nothing was set
explicitly the format is **inferred**: the coarsest ISO pattern that
loses nothing, so a column of whole days renders `2020-02-01` rather
than dragging a meaningless `2020-02-01 00:00:00` across every row.
Two places honour it — the Table tab's cell renderer
(`ui/dataframe_model.py`) and a time-series plot's x-axis ticks
(`nodes/viz.py::_apply_time_ticks`). The axis takes only an
*explicitly set* format, since an inferred one would override
matplotlib's `ConciseDateFormatter`, which reads better on an
automatic axis.

## Running a pipeline without the app

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
non-hashable outputs (e.g. `matplotlib_plot`, `export_figure`) opt out
of caching via `Node.cacheable = False` and always re-run.

## Exporting a pipeline as a Python script

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
