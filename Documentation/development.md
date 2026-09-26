# Development

For contributors: how the code is organised, how to run the tests, and the design decisions behind the UI. Using the app needs none of this.

## Architecture

Visual data science pipeline builder: a node-graph desktop application
where each box defines a step (load, clean, model, visualize) of a
Python data science pipeline.

The codebase is split into three independently testable layers:

| Layer | Package | Depends on | Status |
|---|---|---|---|
| 1. Node model | `ruyso_app.core`, `ruyso_app.nodes` | pydantic (+ the libs each node uses: pandas, geopandas, mapclassify, scikit-learn, statsmodels, scipy, matplotlib, seaborn) | done |
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

## Launching from source

```bash
python -m ruyso_app.ui
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

## Project layout

```
src/ruyso_app/
├── core/     # Node/Port/NodeParams contracts + NodeRegistry
├── nodes/    # Concrete nodes (file + geo loaders, transforms, models, viz, export)
├── engine/   # PipelineGraph, serialization, cache, scheduler, codegen, errors
└── ui/       # NodeGraphQt canvas, property forms, main window
```

## What a run reports

`PipelineScheduler.run()` / `run_available()` return a **`RunReport`**
with three parts, because a run has three outcomes and only two of them
used to be reported:

- `.outputs` — nodes that ran cleanly, mapped to their output dicts.
- `.errors` — nodes that raised, mapped to a **`NodeError`**
  (`engine/errors.py`).
- `.blocked` — nodes that never ran, mapped to *the node that caused
  it*, or `None` when the node simply is not wired up yet. These
  previously appeared in neither dict, so a run that stopped a third of
  the way through reported one failure and said nothing at all about
  the steps it skipped. `.unwired` is the subset with no cause.

The report unpacks as `(outputs, errors)`, so existing two-value
callers are unaffected.

A `NodeError` carries a one-line `title` (what `str()` returns), a
longer `detail`, the `kind` (`param` / `input` / `runtime` / `blocked`),
the `field` at fault when one can be identified — so the UI can point at
the right row of the Options panel — and the original traceback in
`raw`. `errors.translate()` rewrites pydantic, pandas, sklearn and OS
exceptions as sentences about settings and columns rather than about
Python: *"The "columns" setting expects a list of values, not the text
'nope'."* rather than pydantic's `[type=list_type, input_value='nope'…]`
dump. Anything it does not recognise falls through to
`TypeName: message`, exactly what was shown before, so an unmodelled
failure is never made worse.

## Why an auto-run is fast

Auto-run fires after every parameter edit, and 31 nodes — every grapher,
every export — opt out of the joblib disk cache, so each background run
used to re-render every figure on the canvas even when the edit was
three steps away. `engine/run_cache.py` works one level up from joblib:
instead of "have I computed this function on these arguments", it asks
**"has anything that feeds this node changed since I last ran it"**,
using the transitive signatures from `engine/signatures.py`. When the
answer is no, the node's previous outputs are handed back and it never
runs at all.

```
cold                 ran 6: load, plot0…plot4
untouched            ran 1: load
edit plot2's params  ran 2: load, plot2
delete plot4         ran 1: load        (its cache entry is pruned)
```

Design points, each load-bearing:

- **One entry per node**, keyed by node id, holding its latest
  `(signature, outputs)`. The cache is never larger than the graph and a
  deleted node's entry is pruned on the next run — entries hold
  DataFrames and figures, so a signature-keyed history could quietly
  reach hundreds of megabytes.
- **Loaders and exports always execute.** A loader because a file can
  change on disk under an unchanged path; an export because its value
  *is* the side effect, so skipping it means a deleted output file is
  never rewritten.
- **What a loader read is folded into what its dependents key on**
  (`run_cache.content_token`). Re-running the loader is not enough on its
  own: a signature is built from node types, parameters and wiring, none
  of which move when a CSV is edited under the same path — so everything
  downstream would keep serving results computed from the old file while
  the loader happily read the new one.
- **A hit is only served once the inputs are known to be available**, so
  a node whose loader has just started failing is reported blocked
  rather than showing yesterday's data under a red node.
- **Run Pipeline reuses the same cache; Force Full Run passes none**
  (Shift+F5), which is the way to force genuine re-execution — rewriting
  exports, redrawing every figure.
- **The worker gets a snapshot, not the live cache.**
  `AutoRunController.interrupt()` calls `QThread.terminate()`, which
  kills the thread at an arbitrary instruction; the snapshot is adopted
  as the live cache on the GUI thread only once a run reaches
  `_on_worker_done`, so a terminated run costs one wasted pass and
  nothing else.

A reused node's outputs come back **by identity** — no node in `nodes/`
mutates its input in place — and the UI leans on exactly that to skip
the work of drawing a figure it has already drawn: `FigureThumbnail`
does not re-rasterise, and the Dashboard does not re-serialise to SVG,
when the `Figure` object is the same one as last time. Serialising a
figure to SVG is the most expensive thing the Dashboard does, and it
used to happen on every background run.

The on-canvas figure previews cost nothing while the canvas is idle, and
nothing extra while it moves: each card is a scene item re-placed by its
node's own geometry notification, so there is no timer at all. (They were
widgets over the `QGraphicsView`, re-placed by a timer that first ticked
16 times a second for the life of the app and was later throttled to run
only during interaction — and still trailed a dragged node.)

## Visual design decisions

The UI is being reworked to match the `ruyso_ui_principles` mockups in
phases. Decisions taken so far (spec section 8):

- **Macro types & palette.** The six macro types are `loading`,
  `transform`, `model`, `statistics`, `grapher`, `export` (`viz` was
  split into `grapher` + `statistics`). Each maps to one Matplotlib
  *tab10* color, identical in both themes so a node stays recognizable
  across a theme toggle; the map is in `theme._MACRO_TYPE_COLORS`.
  Every macro type now has at least one concrete node (a macro type
  with none would show its "New Node" entry **disabled** rather than
  omitted or crashing).
- **Palette hex values.** Dark and light chrome palettes are the
  `DARK_THEME` / `LIGHT_THEME` dataclasses in `theme.py` (window,
  panel, text, border, accent, canvas-background values).
- **Options panel background.** A lightened, ~92%-opaque tint of the
  selected node's macro-type color (`theme.options_panel_background`),
  falling back to an opaque panel color when nothing is selected.
- **How a node is drawn** (`ui/node_item.py`, a `NodeItem` subclass
  handed to every generated class as its `qgraphics_item`). NodeGraphQt
  fills the whole node with its colour; here the body is the **theme's
  panel colour** in both themes, so a node is a card like every other
  surface, and the **macro-type colour is a thick contour** (2.0 units,
  3.2 selected) plus the **name bar, which fills with it only while the
  node is selected**. That fill is the text item's own box, so it stops
  right below the name rather than at the port row NodeGraphQt measures
  to. Unselected, the name bar is just the top of the card — no divider,
  no tint — so the fill is unmistakable. Corners are 12, a little
  rounder than the 8 the QSS uses, which a node at this size carries
  well. The name and the port labels take the theme's text
  colour; the name flips to whatever reads on the macro colour while
  selected (`node_item.readable_on` — white on the blue loader,
  near-black on the orange transform), which is why
  `_set_text_color` is overridden rather than called once: NodeGraphQt
  re-applies its own white-on-dark default from `draw_node`.
- **Fonts.** `Helvetica, Arial, sans-serif` everywhere except the run
  console and any library/class name, which use
  `Consolas, Menlo, 'Courier New', monospace`.
- **Node creation is right-click**, not a left-click popup: the empty
  canvas shows a centered `+` and "Right-click to add a node".

- **Ports and links** are drawn by `ui/wiring.py`, not by NodeGraphQt's
  own palette (teal ports, orange links, cyan when selected, yellow on a
  selected node's links — none of it related to either theme). A **port**
  is the theme's `wire_color`, plain white on the dark theme and plain
  black on the light one: a hollow ring while nothing is plugged in, a
  solid disc once something is, so wiring state reads without a second
  colour; hovering it takes the accent. A **link** is that same colour at
  rest and the **accent** while it is selected or while either end's node
  is, so selecting a node lights its whole neighbourhood. A link **being
  dragged** is its origin node's macro-type colour *desaturated* — that
  node's colour, visibly not yet a connection — turning red over a target
  it cannot attach to. The mid-link **direction arrow** is 3.5 units
  (NodeGraphQt's is 6) and **solid in the link's colour**; upstream fills
  it with `color.darker(200)` inside a `color` outline, which is what
  made it read as two-tone.

  Ports go through NodeGraphQt's supported hook (`add_input(...,
  painter_func=)`): its own `PortItem.paint` consults a port's colour
  only while the port is idle, and falls back to hard-coded enum colours
  as soon as it is hovered *or connected*. Links have no such hook —
  `PipeItem` hard-codes those colours inside `reset` / `activate` /
  `highlight` — so those methods are patched on the class, the way
  `canvas_grid.py` patches the dot grid. Each patched method reads the
  theme as it runs, so a dark/light toggle only needs `refresh_wiring()`.

## Visual design internals

To change how the app looks (colors, node macro-type colors, window
stylesheet, fonts), edit `src/ruyso_app/ui/theme.py` — it is the only
file that needs touching for purely visual changes.

**Popups — dropdowns and menus — need one thing QSS cannot express.**
A widget that paints an opaque window covers up its own
`border-radius`, so a rounded rule produced square corners. A
`QComboBox` popup is two nested widgets — a `QComboBoxPrivateContainer`
(a plain top-level `QFrame`) wrapping the list view — and QSS reaches
only the view, so a rounded list sat inside a square, usually wider,
frame; a `QMenu` is one widget with the same problem.
`theme.install_combo_popup_styler()` installs one application-wide event
filter that makes each of them frameless and translucent the first time
it is polished, leaving just the rounded card. It hooks `Polish`
rather than `Show` on purpose: `setWindowFlags` hides an already-visible
widget, so restyling on show would close the popup as it opened.

The same filter **clears a menu's own stylesheet**. NodeGraphQt's
`BaseMenu` sets a hard-coded dark one in its constructor, and a
widget-local stylesheet beats the application's — which is why the
canvas "New Node" menu used to look nothing like the rest of the app.

A popup — a dropdown list or a menu, they are the same kind of floating
card — is painted in `Theme.popup_background`: **white** in the light
theme, one step brighter than the panel it opened from, and the panel
colour in the dark theme, which has nowhere brighter to go. Rows take a
rounded overlay on hover rather than an edge-to-edge highlight
(`show-decoration-selected: 0`).

That filter also gives each dropdown **`ui/popup_delegate.py`**. Qt
draws combo rows with a private delegate that hands the *combo box* to
the style as the widget being painted, so under a stylesheet every row
resolved against the `QComboBox` rule and came out wearing the closed
combo's own bordered box — the white rectangle that appeared over the
list. A plain `QStyledItemDelegate` draws them as view items. It has to
draw **separators** itself (Qt marks them in
`AccessibleDescriptionRole` and leaves them to that combo delegate),
with a size hint small enough that the stylesheet's item `min-height`
cannot inflate one into a blank row. A combo that already has a
delegate of its own — the colormap and marker swatches — keeps it.

**Panes are divided by a grip, not a band.** A `QSplitter` handle paints
nothing but three dots (`assets/grip-*.svg`, a true mid-grey that reads
on both themes — a border-coloured line was invisible on the light one),
so the Log/Problems strip butts straight against the canvas and the drag
target sits on the strip's own top edge. The Table tab's description
panel scrolls, and a splitter cannot divide something that scrolls, so
its two variable tables get the same affordance from
`ui/height_grip.py`. That grip is a **cap, not a height**: a table stays
exactly as tall as its rows, and the grip only appears once there are
more rows than fit, deciding how much of the panel that table takes
before it scrolls inside itself (double-click resets it). Resizing
happens only while a drag is in progress — acting on every mouse-move
sent the table to an arbitrary height as the pointer crossed the grip,
because a hover move carries no press to measure against. The height is
set in one place for the same reason the first attempt broke: the panel
setting a fixed height while `_fill_stat_table` set a maximum left
`min > max`, and Qt's layout then stacked the sections over each other
— which is what put the second table far below its own title. The canvas itself is frameless — NodeGraphQt
wraps the viewer in a `QTabWidget` whose constructor paints its own
near-black background, which showed as a black band around the canvas on
the light theme; `PipelineCanvas.widget` clears that stylesheet on the
way out (doing it in `__init__` builds the wrapper for canvases nobody
shows, which reintroduces the exit-139 teardown crash in the tests).

**The canvas grid** is small round dots 25 scene units apart
(`ui/canvas_grid.py`), replacing NodeGraphQt's 5-px hard squares 50
units apart. It is a monkey-patch of `NodeScene._draw_dots`: the scene
is built inside NodeGraphQt's viewer with no hook to substitute a
class, and swapping the scene afterwards would orphan the live-pipe
items already parented to it. The dot colour is derived from the canvas
background, so the grid stays a hint in both themes rather than the
fixed near-black NodeGraphQt ships.
