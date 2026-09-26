# The Table tab

The Table tab shows every table a pipeline produces, step by step, with a summary of its columns.

**Table tab navigator is a flat list, not a node diagram.** Steps
appear in execution order; a step with several output tables (e.g.
`train_test_split`) lists each one (`step / port`). Entries are
greyed out until the pipeline has been run and produced that table.
Selecting one fills the **Table description** panel and shows the
data in a grid with mouse-resizable columns. The description has a
scalar summary (kind of table — plain / geo / time-indexed /
geo+time — row count, variable count, missing/empty-value count)
plus two tables: **numeric variables** (`variable | type | mean |
std. dev | min | max`; datetime columns included here) and **string
/ categorical variables** (`variable | type | # distinct values`;
bool columns included here). See `ui/table_description.py`.

**The Table tab keeps showing the last successful run.** Editing the
pipeline afterwards does not blank the tables; instead a step whose
type, parameters or wiring changed since that run — or anything
downstream of such a step — is tagged **· modified** (pale yellow)
in the navigator, so a stale table is never mistaken for the current
result. Detection lives in `ui/run_snapshot.py`; the snapshot is
reset when a pipeline file is opened.
