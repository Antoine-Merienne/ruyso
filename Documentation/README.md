# Ruyso documentation

New to Ruyso? Start with the [download and five-minute tutorial](../README.md).

## Nodes, by macro type

| Macro type | Colour | What it does |
|---|---|---|
| [Data Loader](nodes/loading.md) | blue | Reads a file (CSV, Excel, Parquet, GeoJSON…) or a bundled example dataset |
| [Transformer](nodes/transform.md) | orange | Cleans, filters, reshapes, encodes, and handles dates and maps |
| [Model](nodes/model.md) | green | Fits scikit-learn models, then predicts, scores and explains them |
| [Statistics](nodes/statistics.md) | grey | Hypothesis tests, regressions, PCA / ICA / t-SNE, ARIMA and VAR |
| [Grapher](nodes/grapher.md) | purple | Charts, maps, model diagnostics and tables as figures |
| [Exporter](nodes/export.md) | brown | Writes figures, tables and map data to files, or to the Dashboard |

## Panels

- [Pipeline tab](panels/pipeline.md): the canvas, adding and wiring nodes, automatic runs, figure previews
- [Options panel](panels/options.md): editing the selected node
- [Table tab](panels/table.md): every table the pipeline produces
- [Dashboard tab](panels/dashboard.md): assembling figures into a report
- [Run log and Problems](panels/problems.md): what ran, and what went wrong
- [Preferences](panels/preferences.md): defaults, caching and toolboxes

## Everything else

- [Other features](features.md): menus and shortcuts, the pipeline file, running without the app,
  exporting to Python, datetime formats
- [Development](development.md): architecture, tests and design decisions
