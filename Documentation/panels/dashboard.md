# The Dashboard tab

The Dashboard tab assembles figures into a report page: arrange plots, add titles, text and shapes, then export it as a PDF or PNG.

## Getting figures onto the dashboard

**Dashboard tab.** The `export_to_dashboard` node (`export` macro
type) is a sink: it takes a `figure` — a grapher plot or a
`table_viewer` table — and has no output. Every such node becomes one
item on the Dashboard's **infinite pan/zoom canvas** (same navigation
as the Pipeline tab: two-finger / right-drag pan, pinch / wheel zoom,
no scroll bars), keyed to the node and re-rendered **as a vector**
(SVG) in place on each run / auto-run, so it stays sharp at any zoom.
A figure whose source plot changed since the last run, was
disconnected, or errored gets the Table tab's yellow "· modified"
tag; a figure whose export node was deleted is kept as its last
snapshot. Click an item for a blue selection contour; left-drag
rubber-bands a multi-selection that moves as a group. Selecting one
figure opens the **same Options panel** as on the Pipeline tab, bound
to the upstream plot node — so restyling a dashboard figure is the
same act as editing its grapher (if the plot is disconnected, a
canvas overlay says so). A **tool strip down the left edge** offers
the four assembly tools as icon buttons — title, text box, shape ▾,
arrange ▾ — the last two dropping the same menus as the canvas
right-click; Arrange is disabled until something is selected, since
every entry in it acts on a selection. "Add Title" / "Add Text Box"
(tool strip, Dashboard menu or canvas right-click) drop free-text
items, restyled live (bold, italic, size, colour, alignment, font).
The "add figures using the `export_to_dashboard` node" hint stays up
until a **figure** arrives: it is not asking for a text box, and
clearing it when one was added left someone who had typed a heading
with no idea how to get their plot across. **Dashboard ▸ Exporter…**
renders the bounding box of all items to PDF (vectors preserved) or
PNG, by file extension. The canvas is session state — only each
node's `title` param persists (with the pipeline). Right-clicking a
figure-bearing node on the Pipeline canvas offers **Add to
Dashboard**, which drops a wired `export_to_dashboard` node for it.

## Shapes, arranging and saving

Beyond figures and captions, the canvas takes **shapes** — rectangle,
rounded rectangle, ellipse, line, arrow, triangle — because boxing a
region, circling a result and pointing at it is how a plot becomes an
argument. `ui/dashboard_shapes.py` carries two geometry models in one
class: an *area* is a rect resized from its bottom-right corner, a
*line* is two endpoints with a handle each, which is the only way to
aim one.

The **Add Shape** and **Arrange** menus are built once, in
`ui/dashboard_menus.py`, and filled into all three places that offer
them — the Dashboard menu, the canvas right-click and the left tool
strip — so the three cannot list different commands. The canvas menu is
built by `DashboardPage.build_context_menu()` apart from showing it,
because `exec` blocks until someone clicks: a menu only ever built
inside the handler is a menu no test can look at, which is how it came
to be raising `NameError` on every right-click.

**Arranging** (`ui/dashboard_layout.py`, pure functions over items):
z-order, align on six edges, distribute, nudge with the arrow keys
(Shift for 10px), duplicate, lock. Alignment works on each block's
`visual_rect`, **not** its `sceneBoundingRect` — the latter includes the
padding an item reserves for its selection handles, 15px for a shape
against 3px for a figure, so aligning on it would leave the two twelve
pixels out of line while both claimed to be aligned.

**Undo.** The canvas has its own `QUndoStack`, and Edit ▸ Undo routes to
whichever tab is in front — without that, editing the dashboard and
pressing `Cmd+Z` would quietly undo something on the Pipeline tab, which
is worse than a shortcut that does nothing. Rather than a command class
per operation, each one records the scene either side of itself
(`ui/dashboard_undo.py`): a dashboard holds tens of items, so a snapshot
is cheap, and one mechanism covering add / move / resize / restyle /
reorder / lock / delete is far less to get wrong than seven inverses.
Snapshots hold the item **objects**, so undoing a delete puts back the
same figure with its rendered SVG still in it, not a blank one waiting
for the next run.

**Multi-select restyles as a group** — selecting five shapes and setting
one colour changes all five, which is most of why the inspector exists.
A mixed selection of kinds has nothing in common to edit, so it falls
back to the placeholder.

**Locking** makes a block untouchable: not selectable, movable,
resizable or deletable. Since a locked block cannot be selected, it
cannot be unlocked from its own inspector either — **Dashboard ▸ Unlock
All** is the way back.

**The layout is saved with the pipeline**, in a `dashboard` section of
the same JSON file, so sending someone a pipeline sends the report with
it:

```json
{
  "nodes": [ … ],
  "connections": [ … ],
  "dashboard": {"version": 1, "items": [
    {"type": "figure", "pos": [20, 80], "z": 0,
     "state": {"export_node_id": "Board 1", "title": "Sales by region", …}},
    {"type": "shape", "pos": [300, 40], "z": 1, "state": {"kind": "arrow", …}}
  ]}
}
```

- `graph_to_dict` / `graph_from_dict` stay **pure graph** and never see
  the key, so hand-written files, `examples/*.json` and the headless CLI
  are untouched. `save_document` / `load_document` add the sections; the
  key is only written once the canvas has something on it, and a section
  a future version adds is carried in and out rather than stripped.
- **The rendered picture is not stored** — it comes back from running
  the pipeline, and a stale image on disk would be worse than none. A
  figure block is saved by its **export node's name**, which is what
  re-binds it to the same block (not a duplicate) on the next run; until
  then it wears the "· modified" tag. A block whose node is missing
  stays put and tagged, exactly as when that node is deleted live.
- **Dashboard edits count as unsaved work** — the title's `•` and the
  close prompt watch both undo stacks, because an hour of layout is as
  losable as an hour of wiring.
- **Opening a document replaces the document**: a file with no
  `dashboard` section clears the canvas, so blocks cannot bleed from one
  pipeline into the next and be saved into it.

A block describes itself through the same `capture_state` /
`apply_state` pair the undo snapshots use — saving a layout and undoing
an edit are the same question, so there is one description of a block
rather than two that could drift apart.
