"""
The one lock that keeps matplotlib sane across threads.

matplotlib is not thread-safe, and this app uses it from three threads:
figures are **built** on the run thread (``ui/auto_run.py``,
``ui/execution_worker.py``), **drawn** on the render thread
(``ui/render_queue.py``), and **read** on the GUI thread whenever a
preview card asks a figure how tall it is or a window asks how big to
open. Two of those overlapping corrupts the result, in two distinct
ways, both of which were reported as "the preview fails to render
properly":

* ``nodes/viz.py::_plot_context`` applies the chart preferences by
  entering a **global** ``rcParams`` context. A render that runs while
  that context is being entered or left picks up half of somebody
  else's style, so a plot comes out with pieces missing, or blank.
  Measured: 25 renders taken while another thread built figures
  produced 21 *different* images, none of them equal to the same
  figure rendered on its own.
* ``savefig`` temporarily changes the figure it is saving -- during a
  save a 6.0 x 4.0 inch figure at 100 dpi reads as 5.953 x 3.917 at
  72 dpi. Anything reading the size right then gets that transient
  value, and ``node_preview.window_size_for`` *memoises* it onto the
  figure, so a window opens at the wrong size and stays wrong.

So: hold this lock around building a figure, around drawing one, and
around reading one's geometry. It is re-entrant, because those nest --
a render reads the size it is about to draw at.

Deliberately in ``core``: ``nodes`` and ``engine`` must not import a
GUI toolkit, and all three layers need the same lock object.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

_LOCK = threading.RLock()


@contextmanager
def figure_guard() -> Iterator[None]:
    """Serialise one piece of matplotlib work against every other."""
    with _LOCK:
        yield
