# Preferences

Preferences set app-wide defaults: appearance, execution, caching, chart and export defaults, and which node families (toolboxes) appear in the menus.

**Edit ▸ Preferences…** (`Cmd/Ctrl+,`; macOS files it under the
application menu) opens nine pages — General, Appearance, Execution,
Cache, Chart defaults, Export, Dashboard, Data, Advanced. Values live in
`~/.config/ruyso/settings.json` (`$RUYSO_CONFIG_DIR` overrides it),
written atomically, alongside `colormaps.json`.

`engine/settings.py` holds them because several are read with no window
open: the disk-cache budget by `engine/cache.py`, the plot style and
font by `nodes/viz.py`. A headless run honours the same preferences the
app does. `DEFAULTS` is the single source of truth for what exists and
what type it is — an unknown key is refused on write, and a stored value
of the wrong type is ignored on read, so a hand-edited or
newer-version settings file degrades to defaults instead of breaking
the app.

Four things are worth knowing:

- **Changes are staged.** Editing a control writes to a pending dict;
  OK or Apply commits, Cancel drops it. Unlike the colormap dialogs,
  several of these (font size, accent, grid) change how the whole app
  looks the instant they land.
- **Chart / Export / Data defaults seed *new nodes*** — applied at
  creation by `ui/node_defaults.py`, not by rewriting schema defaults.
  Existing nodes keep their values, and `pipeline_to_canvas` suspends
  seeding entirely: a file's unmentioned parameter means the node's own
  default, the same on every machine, rather than "whatever this person
  prefers".
- **Blank or 0 means "leave each node's own default alone."** The
  graphers deliberately use eight different figure sizes (one is a
  6.0×2.2 strip), so a single figure-size preference applied to all of
  them would flatten choices their authors made on purpose. Set one and
  it wins everywhere; leave it at 0 and nothing is overridden.
- **The disk-cache budget is applied at startup, on a background
  thread.** joblib 1.5 dropped `bytes_limit` from `Memory.__init__`, so
  it has to be an explicit `reduce_size` pass, and that walks the whole
  directory — not something to do on the way to seeing a result. The
  cache may drift over its budget during a long session; it is a disk
  allowance, not a hard ceiling.

The window also behaves like a document: the title names the open file
and gains a `•` while there are unsaved edits (which is exactly "the
undo stack has moved since the last save", straight off `QUndoStack`),
and closing with unsaved work prompts unless that preference is off.

### Toolboxes

129 nodes is a lot to scroll past when your work is loading a CSV and
plotting it, so **Preferences ▸ Toolbox** switches families off:

| Family | Modules | Nodes |
|---|---|---|
| Loading | `loaders`, `example_data` | 8 — always on |
| Transform | `transforms` | 29 — always on |
| Charts | `viz` | 23 — always on |
| Export | `export` | 4 |
| Machine learning | `models`, `model_ops` | 26 |
| Statistics & time series | `statistics` | 19 |
| Geo / maps | `geo_loaders`, `geo_transforms`, `geo_viz` | 20 |

A family is defined by its **modules**, not by node category, because
that is the granularity an import can be skipped at — and the two do not
line up: `models.py` holds one transform node among its model nodes, and
geo spans three modules across three categories.

Switching one off does two things. It **shortens the menus** at once:
`node_factory.core_node_types_by_category` filters by the enabled set,
and the New Node menu, the canvas menu and the micro-type dropdown all
read that one function, so they narrow together. And it **skips the
import** at the next launch, via
`NodeRegistry.discover_package(only=…)` — measured, dropping geo takes
node discovery from **671 ms to 451 ms** and means geopandas and pyproj
are never imported at all. Only geo carries real weight; statistics and
ML together add ~25 ms, because pandas and numpy arrive with
`transforms` regardless. The page says so, since the menu change is
immediate and the load-time change is not.

Two edges are handled. A family the canvas is **using cannot be switched
off** — the dialog names the nodes and refuses, rather than letting you
create a pipeline you cannot reopen. And opening a pipeline whose nodes
come from a switched-off family **offers to switch it back on**, naming
the family; declining leaves both the preference and the canvas alone.

The filter lives in `node_factory`, never in `NodeRegistry`: the
registry is the truth about what the app *has*, and a preference about
what to show is not its business.
