"""
Concrete node implementations, grouped by category:

- loaders.py     -> data loading nodes (e.g. CSVLoader)
- transforms.py  -> data cleaning / transformation nodes (e.g. DropNA, StandardScaler)
- models.py      -> modeling nodes (e.g. TrainTestSplit, LinearRegressionFit)
- viz.py         -> visualization nodes (e.g. MatplotlibPlot)
- export.py      -> artifact export nodes (e.g. FigureExport)

Each module registers its node classes with the NodeRegistry via the
``@register_node`` decorator at import time. Call
``NodeRegistry.discover_package(ruyso_app.nodes)`` once at startup
to ensure every module in this package has been imported and its
nodes registered, without needing to list them by hand.
"""
