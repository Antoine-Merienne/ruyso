# The run log and Problems panel

Under the canvas, the run log records each run, and the Problems panel lists what went wrong and where to fix it.

Failures land in a **Problems** panel beside the run log on the Pipeline
tab, not in a modal dialog. A `QMessageBox` holding `str(exception)`
interrupted the work, said nothing actionable, and was gone the moment
it was dismissed; a panel stays until the problem does, reads as a
sentence, and leads to the node it is about.

```
Problems (1)                          [tab band: ● 1 problem]

● Load Data · There is no file at '/no/such/file.csv'.
  Check the file path setting on this node.
  Fix in Options ▸ filepath
  ▸ Show technical details          (the traceback, with Copy)
```

- **Only nodes that actually raised get a row.** Blocked nodes are left
  to the canvas's grey dots and their tooltips: one bad parameter can
  block eight steps, and eight rows saying so would bury the one row
  that matters. A graph too broken to run at all has no node to blame,
  so it gets a single pipeline-wide row.
- **Auto-run fills it live**, so a mistake shows up as you make it
  rather than waiting for a Run — silently, as auto-run always has been:
  no dialog, no log spam, just the panel and a red chip in the tab band.
  The chip is hidden when there is nothing wrong.
- **Clicking a row selects that node** and outlines the offending
  setting in the Options panel. The outline clears the moment you edit
  that field — it points at the thing to fix and must not argue with a
  value you have already changed; whether the edit *worked* is the next
  run's answer.
- **Modals survive only for file actions you invoked** — Open, Save,
  Export script, Export dashboard. You asked for a thing and it did not
  happen, and a failed Save reported only in a panel on another tab is
  a good way to lose work.
