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
nodes registered.
"""

#: The submodules :meth:`NodeRegistry.discover_package` imports.
#:
#: Declared rather than scanned because a packaged build has no
#: directory to scan: ``pkgutil.iter_modules`` returns nothing from
#: inside a PyInstaller archive, and the whole node catalogue would
#: quietly become empty. Adding a module here is the one manual step a
#: new node file needs, and
#: ``tests/core/test_registry.py::test_declared_submodules_match_the_files_on_disk``
#: fails if it is forgotten.
__all__ = (
    "example_data",
    "export",
    "geo_loaders",
    "geo_transforms",
    "geo_viz",
    "loaders",
    "model_ops",
    "models",
    "statistics",
    "transforms",
    "viz",
)
