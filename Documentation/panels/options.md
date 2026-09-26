# The Options panel

The Options panel, on the right of the Pipeline and Dashboard tabs, edits the selected node: its type, then every parameter it has.

## Changing a node's type

**Micro-type change after creation = recreate.** Node classes are
fully typed at instantiation (ports/params differ per micro type),
so changing the Options dropdown deletes the node and builds a new
one in place, keeping its name, position, every still-valid wire,
and any parameter whose field name is shared. See
`ui/node_editing.py`.

## Parameter fields

**Parameter form niceties:** file-path fields get a **Browse…** button
(open dialog for loaders, save dialog for exporters). Column-name
fields (marked with `core.params.column_field`) become a single
editable dropdown of the input DataFrame's columns — the same widget
for every node. For a multi-column field (e.g. `scaler.columns`,
`drop_na.columns`), picking an item from the dropdown toggles it in or
out of the comma-separated value; you can still type any name. A
warning appears below the field if a name isn't a column, or if that
column's type isn't accepted by the parameter. Acceptable types are
declared per field on the node (e.g. `scaler.columns` needs
numeric; `matplotlib_plot.x/y` accept anything).

**Path parameters get a Browse… button** (loaders open, exporters
save; filters in `ui/file_filters.py`) and a full-width text field.

## Colour

**Options panel background.** A lightened, ~92%-opaque tint of the
selected node's macro-type color (`theme.options_panel_background`),
falling back to an opaque panel color when nothing is selected.
