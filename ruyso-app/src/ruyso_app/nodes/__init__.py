"""
Concrete node implementations, grouped by category:

- loaders.py       -> tabular file loaders (CSV, Excel, JSON, Parquet, ...)
- geo_loaders.py   -> geospatial file loaders (GeoJSON, Shapefile, GeoPackage)
- transforms.py    -> cleaning / reshaping (DropNA, StandardScaler,
                      ChangeType, ColumnFilter, RowFilter, DtypeFilter)
- geo_transforms.py -> GeoDataFrame <-> DataFrame + reproject
- models.py      -> modeling nodes (e.g. TrainTestSplit, LinearRegressionFit)
- viz.py         -> visualization nodes (e.g. MatplotlibPlot)
- export.py      -> artifact export nodes (e.g. ExportFigure)

Each module registers its node classes with the NodeRegistry via the
``@register_node`` decorator at import time. Call
``NodeRegistry.discover_package(ruyso_app.nodes)`` once at startup
to ensure every module in this package has been imported and its
nodes registered, without needing to list them by hand.
"""
