# The Pipeline tab

The Pipeline tab is the canvas where you build a pipeline: add nodes, wire them together, and watch results appear as you go.

## Adding and wiring nodes

**Adding a node:** right-click the canvas → **New Node ▸ _macro type_**
— the node appears **under the cursor**. (The Node menu and the
`Cmd/Ctrl+P` chords drop it in the middle of the view instead.) A node
of that macro type appears and is selected; the Options panel on the
right then shows a **macro type** and a **micro type** dropdown
(changing either recreates the node in place — its name follows the
new type; see `ui/node_editing.py`), plus its parameter form. Wire
nodes together by dragging between ports. Grapher / figure nodes carry
a **preview card** just beneath them that, after a run, shows the
figure; click it to select that plot and open (or raise) its resizable
window — always at the figure's own size, and following any edit you
then make in the Options panel. The chevron at the right of such a
node's name bar collapses its card; that, and every node's position,
is saved with the pipeline.

## Moving around the canvas

**Canvas navigation** (`ui/canvas_nav.py`): two-finger trackpad drag
**pans** (both axes, following the OS scroll direction); **pinch**
**zooms**; **Cmd/Ctrl + wheel** zooms for a mouse. Pan by click with a
middle-button drag, or hold **Space** and left-drag. Left-drag
rubber-band select and right-click "New Node" are unchanged.

## Automatic runs

**Automatic background runs:** whenever you set a data file, wire up a
node, or edit a parameter, the app runs whatever part of the pipeline
is ready, on a background thread (`ui/auto_run.py`,
`PipelineScheduler.run_available`). Data files load without pressing
Run, so column pickers and previews populate on their own; unfinished
or broken branches are skipped silently (no error dialog). An explicit
**Run Pipeline** covers the whole pipeline and reports errors — reusing,
like auto-run does, whatever nothing has changed for; **Force Full Run**
(Shift+F5) is the way to recompute every step.

## Run controls

**Run controls:** the right of the tab band holds a **Run Pipeline**
button, a slim progress bar, and a percentage. During a run the bar
fills node-by-node with the percent to its right; it settles solid
**green** on success or **red** on failure and stays there until the
next run. The button is disabled while a run is in progress.

## Node status dots

`run_available()` also tells **`blocked`** (something upstream failed)
apart from **`unwired`** (a required input has nothing plugged in).
Both draw a grey dot; only the tooltip differs. Conflating them made a
canvas someone was still assembling look like a broken pipeline.

That dot is **drawn with the node** (`ui/node_item.py`), not set as a
pixmap on NodeGraphQt's icon slot, so it stays a circle however far you
zoom in — the 16-px bitmap it used to be went visibly blocky. It is
drawn rather than added as a child `QGraphicsEllipseItem`: a child item
is destroyed with its C++ parent while the Python wrapper is still
held, and collecting that wrapper afterwards segfaults in NodeGraphQt's
`QUndoStack` teardown. `ui/node_status.py` keeps the pixmap path as a
fallback for a node that is not ours.

## Figure previews

**On-canvas figure preview** is a **card in the canvas scene**
(`ui/preview_card.py`), not a widget over it. It is re-placed from the
node item's own `itemChange` (`ItemPositionHasChanged`, plus
`draw_node` for a resize — `ui/node_item.py`), so it moves in the same
frame as its node: the widget it replaced was re-placed by a 60 ms
timer and, measured over a 60-frame drag, sat off its node in 44
frames (a 0 → 6 → 12 → 18 px sawtooth); the card is off in none. It is
stacked at z 0 — above the wires, below every node — so it never
covers a neighbouring node. It is a *scene-owned* item rather than a
child of the node: a child item is deleted with its C++ parent while
Python still holds the wrapper, and collecting it afterwards segfaults
in NodeGraphQt's `QUndoStack` teardown.

It is drawn as a rounded card in the theme's panel colour with a
hairline border (the node keeps the macro-type colour as its
identity), around the figure on its own **white plate, as it will
export**; before a run, a muted placeholder line. The figure is a
**bitmap at the resolution it is shown at**: the plate's on-screen
width × the device pixel ratio, rounded up to a power of two
(`preview_card.raster_bucket`, 128–2048 px), re-rendered 150 ms after a
zoom settles rather than on every frame of a pinch. The old thumbnail
was scaled at *logical* size and shown on a 2× screen, which is why its
tick labels were unreadable. An unchanged `Figure` object is never
rasterised again, and a new one is rendered for the zoom the card was
last *painted* at rather than for 1:1 — auto-run hands back a new
figure after every edit, so rendering each at 1:1 left a zoomed-in card
blurry after every change. A card asks for a re-render only when the
size it needs actually changes: asking on every paint let unrelated
repaints (a status-dot animation, a hover) keep restarting the
debounce, so the re-render always ran a zoom step late. `figure_to_pixmap` goes through `savefig` with an
explicit dpi rather than wrapping the figure in a `FigureCanvasAgg`,
which would replace the canvas of a figure also open in a window.

**Collapsing**: a chevron at the right of a figure node's name bar
(drawn by `RuysoNodeItem`, pointing down while the card shows and right
while it is collapsed) hides that one card; Preferences ▸ Appearance
still turns them all off. The flag lives on the node item, so it
survives delete + undo, and is saved in the document's `canvas` section
(`ui/graph_bridge.canvas_layout` / `apply_canvas_layout`) with every
node's position. It pushes no undo command — a Python `QUndoCommand` is
exactly the teardown-crash area — so `MainWindow` marks the document
modified with a flag of its own.

Clicks on a card or a chevron are taken in a **viewport event filter**,
before NodeGraphQt sees them: its viewer treats anything that is not a
node or a wire as empty canvas and starts a rubber band without ever
handing the press to the scene. A click acts on release over the same
target, like a button. Clicking a card:
- **selects its plot node**, so the Options panel shows that figure's
  parameters while you look at it. The click is *accepted*: letting it
  fall through (`QWidget.mousePressEvent` ignores the event) reached
  the NodeGraphQt viewport, which read it as a click on empty canvas
  and cleared the selection — opening a figure used to blank its own
  options.
- **raises one `FigureWindow` per node**, hidden on close and reused,
  rather than stacking a new window per click.
- opens it at a **stable size**: the figure's own `fig_width` ×
  `fig_height` at a fixed 100 dpi, memoised on the figure and clamped
  to 90 % of the screen. It must not read `figure.get_dpi()`: attaching
  a `FigureCanvasQTAgg` rewrites the figure's dpi to
  `devicePixelRatio × dpi`, and the ratio is only 2.0 once the widget
  is on a Retina screen — so the same plot opened at 650×450, then at
  1300×900 ever after. (Not reproducible offscreen, where the ratio is
  always 1.0; the test applies the mutation by hand.)
- an already-open window **follows re-renders**, so editing the plot's
  params updates the big figure live.

## Resizable panels

**Panels are resizable** via splitter handles: canvas ↔ run log,
canvas ↔ Options panel (Pipeline and Dashboard tabs), navigator ↔
data grid (Table tab).
