"""
UI layer: a NodeGraphQt canvas on top of the core/engine layers.

This package depends on core and engine, never the other way around --
ruyso_app.core and ruyso_app.engine remain fully usable (and are fully
tested) with no GUI toolkit installed at all.

Modules:
    theme.py             -> All colors and the Qt stylesheet in one
                             place; the file to edit to re-skin the app.
    property_forms.py    -> pydantic params_schema <-> NodeGraphQt
                             editable properties.
    node_factory.py       -> Builds one NodeGraphQt node class per node
                             registered in ruyso_app.core.registry.
    canvas.py             -> Themed NodeGraphQt canvas wrapper.
    graph_bridge.py        -> Canvas <-> engine.PipelineGraph conversion.
    execution_worker.py    -> Runs a pipeline on a background QThread.
    figure_viewer.py       -> Embeds a matplotlib Figure output in a widget.
    main_window.py         -> Assembles everything into the app window.
    app.py                 -> Entry point (QApplication + event loop).

Launch with: python -m ruyso_app.ui
"""
