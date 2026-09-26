# Ruyso

Ruyso is a desktop app for building data-science pipelines visually. Each box on the canvas is
one step: load a file, clean a table, fit a model, run a statistical test, draw a chart or export
a result. Wiring the boxes together makes a pipeline that re-runs by itself as you edit it, so
tables and charts update while you work. More than 130 steps are built in, covering data cleaning,
scikit-learn machine learning, statistics and time series (statsmodels, scipy), maps (geopandas)
and charts (matplotlib, seaborn). Finished figures can be arranged into a printable dashboard, and
any pipeline can be saved as a file or exported as a plain Python script.

## Download

### Without Python (recommended)

Click the link for your computer. The download starts straight away.

| Your computer | Download |
|---|---|
| **Mac with Apple silicon** (M1, M2, M3, M4…) | [Ruyso-macOS-arm64.dmg](https://github.com/Antoine-Merienne/ruyso/releases/latest/download/Ruyso-macOS-arm64.dmg) |
| **Mac with an Intel processor** | [Ruyso-macOS-x86_64.dmg](https://github.com/Antoine-Merienne/ruyso/releases/latest/download/Ruyso-macOS-x86_64.dmg) |
| **Windows 10 or 11** | [Ruyso-Windows-x64-Setup.exe](https://github.com/Antoine-Merienne/ruyso/releases/latest/download/Ruyso-Windows-x64-Setup.exe) |
| **Linux** | [Ruyso-Linux-x86_64.AppImage](https://github.com/Antoine-Merienne/ruyso/releases/latest/download/Ruyso-Linux-x86_64.AppImage) |

Not sure which Mac you have? Open the Apple menu and choose **About This Mac**. "Chip: Apple M…"
means Apple silicon; "Processor: … Intel" means Intel.

Then install it:

**macOS**

1. Open the downloaded `.dmg` and drag **Ruyso** onto the **Applications** folder.
2. Open **Terminal** (in Applications ▸ Utilities), paste this line and press Return:

   ```
   xattr -dr com.apple.quarantine /Applications/Ruyso.app
   ```

3. Open Ruyso from Applications.

Step 2 is needed once, because Ruyso is not yet signed by Apple. Without it macOS says the app
"is damaged". It isn't: that is macOS's message for an app from an unidentified developer. If you
prefer not to use Terminal, open Ruyso once, click **Done**, then go to **System Settings ▸
Privacy & Security** and click **Open Anyway**.

**Windows**

1. Run `Ruyso-Windows-x64-Setup.exe`.
2. If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.
3. Follow the installer. No administrator rights are needed. Ruyso then appears in the Start menu.

**Linux**

Make the file executable, then run it:

```
chmod +x Ruyso-Linux-x86_64.AppImage
./Ruyso-Linux-x86_64.AppImage
```

More help, older versions and checksums: [installation guide](https://github.com/Antoine-Merienne/ruyso/blob/main/INSTALL.md)
· [all releases](https://github.com/Antoine-Merienne/ruyso/releases).

### With Python

If you already use Python 3.13 or 3.14, install Ruyso from PyPI. Include `[ui]` to get the desktop
app:

```
pipx install "ruyso[ui]"
ruyso
```

(`uv tool install "ruyso[ui]"` works too.) Without `[ui]` you get only the pipeline engine, which
runs pipelines from scripts with no window. To work on Ruyso itself, see
[Development](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/development.md).

## A first pipeline in five minutes

The window has three tabs: **Pipeline** (where you build), **Table** (the data at each step) and
**Dashboard** (a page of figures). Options for the selected step appear on the right.

Every step belongs to one of six **macro types**, each with its own colour: Data Loader,
Transformer, Model, Statistics, Grapher and Exporter. Within a macro type, the **micro type**
picks the exact step, such as `csv_loader` or `drop_na`.

1. **Load data.** Right-click the empty canvas and choose **New Node ▸ Data Loader**. In the
   Options panel, set **Micro type** to `example_data` and **dataset** to `seaborn/penguins`.
   The data loads at once; no Run button needed. To use your own file, pick `csv_loader` (or
   `excel_loader`, `parquet_loader`…) instead and click **Browse…**.
2. **Clean it.** Right-click again, choose **New Node ▸ Transformer**, and set its micro type to
   `drop_na`. Drag from the loader's output port (the small circle on its right edge) to the
   `drop_na` node's input port. In the Options panel, tick `bill_length_mm` and `bill_depth_mm`
   so rows missing either value are removed.
3. **Plot it.** Add **New Node ▸ Grapher**, set its micro type to `matplotlib_plot`, and wire
   `drop_na` into it. Set **x** to `bill_length_mm`, **y** to `bill_depth_mm` and **color by** to
   `species`. A preview of the chart appears under the node. Click it to open the full-size figure.
4. **Look at the data.** Open the **Table** tab and click a step to see its table, with a summary
   of every column.
5. **Build a report.** Back on the canvas, right-click the plot node and choose **Add to
   Dashboard**. The **Dashboard** tab now holds the figure; add titles, text and arrows, then use
   **Dashboard ▸ Exporter…** to save a PDF or PNG.
6. **Save your work.** **Pipeline ▸ Save Pipeline (JSON)…** saves the whole pipeline, including
   the canvas layout and the dashboard. **Pipeline ▸ Export as Script (.py)…** writes it as plain
   Python you can run or share.

Ruyso re-runs whatever you change in the background. A coloured dot on each node shows its state,
and anything that fails is listed in the **Problems** panel under the canvas, with a link to the
setting that needs fixing. **Run Pipeline** (F5) runs everything explicitly.

## Documentation

**Nodes**, by macro type:
[Data Loader](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/nodes/loading.md) ·
[Transformer](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/nodes/transform.md) ·
[Model](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/nodes/model.md) ·
[Statistics](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/nodes/statistics.md) ·
[Grapher](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/nodes/grapher.md) ·
[Exporter](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/nodes/export.md)

**Panels**:
[Pipeline](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/panels/pipeline.md) ·
[Options](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/panels/options.md) ·
[Table](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/panels/table.md) ·
[Dashboard](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/panels/dashboard.md) ·
[Run log & Problems](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/panels/problems.md) ·
[Preferences](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/panels/preferences.md)

**Everything else**:
[Other features](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/features.md)
(menus and shortcuts, the pipeline file, running without the app, exporting to Python, colormaps,
themes) ·
[Development](https://github.com/Antoine-Merienne/ruyso/blob/main/Documentation/development.md)
(architecture, tests, design decisions)

## License

[MIT](https://github.com/Antoine-Merienne/ruyso/blob/main/LICENSE) © 2026 Antoine Merienne
