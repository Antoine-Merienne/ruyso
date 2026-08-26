"""Allows launching the UI with ``python -m ruyso_app.ui``."""

import sys

from ruyso_app.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
