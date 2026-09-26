"""Allows launching the UI with ``python -m ruyso_app.ui``."""

import multiprocessing
import sys

if __name__ == "__main__":
    # Before anything heavy is imported. In a packaged build a worker
    # process re-executes this very entry point, and without this it
    # starts a second copy of the whole application instead of a worker
    # -- once per job, until the machine gives up.
    multiprocessing.freeze_support()

    from ruyso_app.ui.app import main

    sys.exit(main())
