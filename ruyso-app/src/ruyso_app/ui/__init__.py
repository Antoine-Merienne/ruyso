"""
UI layer: a NodeGraphQt canvas on top of the core/engine layers.

This package depends on core and engine, never the other way around --
ruyso_app.core and ruyso_app.engine remain fully usable (and are fully
tested) with no GUI toolkit installed at all.

Modules:
    theme.py             -> All colors (dark + light) and the Qt
                             stylesheet in one place; the file to edit
                             to re-skin the app.
    property_forms.py    -> pydantic params_schema <-> NodeGraphQt
                             editable properties.
    node_factory.py       -> Builds one NodeGraphQt node class per node
                             registered in ruyso_app.core.registry.
    canvas.py             -> Themed NodeGraphQt canvas wrapper.
    canvas_overlay.py      -> "Right-click to add a node" empty-state hint.
    node_menu.py           -> Canvas right-click "New Node" macro menu.
    node_editing.py        -> Recreate a node under a new micro type.
    node_preview.py        -> Floating on-canvas figure preview + pop-out
                             window for grapher / figure nodes.
    graph_bridge.py        -> Canvas <-> engine.PipelineGraph conversion.
    execution_worker.py    -> Runs a pipeline on a background QThread.
    figure_viewer.py       -> Embeds a matplotlib Figure output in a widget.
    tab_bar.py             -> The Pipeline / Table / Dashboard tab band.
    options_panel.py       -> Right-hand settings panel: selected-node
                             editor (macro + micro dropdowns + form,
                             Browse... for path fields, column pickers).
    file_filters.py        -> node_type -> file-dialog filter map.
    column_spec.py         -> Resolve/validate column-name parameters
                             against the input DataFrame's columns.
    run_snapshot.py        -> Detect steps changed since the last run.
    auto_run.py            -> Debounced background "run what's ready".
    run_progress.py        -> The run progress bar in the tab band.
    pipeline_page.py       -> The Pipeline tab (canvas + run log + options).
    table_page.py          -> The Table tab (step output inspector).
    table_nav.py           -> Flat, execution-ordered list of a
                             pipeline's output tables.
    table_description.py   -> Summarise a table (type, vars, missing...).
    dataframe_model.py     -> Read-only QAbstractTableModel over a df.
    dashboard_page.py      -> The Dashboard tab (report canvas + export).
    main_window.py         -> Assembles everything into the app window.
    app.py                 -> Entry point (QApplication + event loop).

Launch with: python -m ruyso_app.ui
"""
