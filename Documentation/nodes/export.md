# Export nodes

Export nodes (brown) are the end of a pipeline: they write a result to a file, or send a figure to the Dashboard. They have no outputs.

**Export nodes** (category `export`, all file-writing sinks). Each
has an explicit `format` dropdown that decides the type; the
extension is appended to `filepath` if missing. `export_figure` —
a `figure` to PNG / JPEG / PDF / SVG / TIFF / WEBP / EPS (`dpi`,
`transparent`, `bbox_tight`). `export_table` — a `dataframe` to CSV /
TSV / Excel / Parquet / Feather / JSON, with an `include_index`
toggle (and `sheet_name` for Excel). `export_geodata` — a
`geodataframe` to GeoJSON / GeoPackage / GeoParquet / GeoFeather /
Shapefile (`layer_name` for GPKG). `export_to_dashboard` sends a
figure to the Dashboard tab (above).
