"""
Shared fixtures for UI-layer tests.

Sets the Qt platform plugin to "offscreen" before any Qt import, so
this test suite can run in headless environments (CI, containers,
this very sandbox) with no real display server: widgets are still
fully constructed and functional, just never actually shown on screen.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication instance shared by every UI test in this session."""
    app = QApplication.instance() or QApplication([])
    yield app
