# Loading nodes

Loading nodes (blue) bring data into a pipeline: one node per file format, plus `example_data` for bundled datasets that need no file at all. They have no inputs.

**Data-loader family.** The `loading` macro type has one micro type
per file format: `csv_loader`, `fixed_width_loader`, `excel_loader`,
`json_loader`, `parquet_loader`, `feather_loader`, `stata_loader`
(all -> `dataframe`), plus `geojson_loader`, `shapefile_loader`,
`geopackage_loader`, `geoparquet_loader`, `geofeather_loader`
(-> `geodataframe`; the geo Parquet / Feather loaders use
`geopandas.read_parquet` / `read_feather`, which decode the WKB
geometry column and the file's CRS metadata — the plain
`parquet_loader` / `feather_loader` cannot). `csv_loader` also carries
`encoding` and `decimal`, seeded from Preferences ▸ Data — a European
CSV is `;`-separated with `,` as the decimal point, and setting that
once beats setting it per node. Loaders otherwise leave
dtypes alone, with one opt-in exception: the four text formats
(`csv_loader`, `fixed_width_loader`, `excel_loader`, `json_loader`)
offer **`parse_dates`** (default off) plus `datetime_columns`
(comma-separated; blank = auto-detect) and a `datetime_format`. It
exists because a date left as text sorts *lexically* for the rest of
the pipeline — `01/02/2020` before `15/07/2019` — and converting at
the source is the cheapest place to prevent that. Auto-detection is
deliberately conservative: a column is only converted when every
sampled value carries a date separator and a 4-digit year *and* ≥95 %
of them parse, so version strings (`1.2.3`) and padded IDs are left
alone. The binary formats already carry real dtypes and have no such
option. You can still convert downstream instead with the
`change_type` transform (target `datetime`, with an optional
`strptime` format) or build one from parts with `combine_datetime`.
A `geodataframe` output may be wired into any node that expects a
plain `dataframe` (a GeoDataFrame is one); the reverse is rejected by
`PipelineGraph.validate()`. Alongside the file loaders,
**`example_data`** loads a bundled dataset with no file and no link —
a `dataset` dropdown of `sklearn/…` toy sets (iris, wine, …),
`statsmodels/…` datasets (longley, macrodata, sunspots, …) and
`seaborn/…` datasets (tips, penguins, …). Every `seaborn/…` dataset is
pre-seeded as a CSV under `nodes/data/seaborn/` and passed to seaborn
as its cache dir (`data_home`), so loading one never touches the
network. The Micro type dropdown groups `loading`'s entries with a
separator line between general file loaders, geo-border formats, and
the example loader (`ui.micro_type_groups`).
