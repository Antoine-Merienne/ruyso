"""
Shared fixtures for UI-layer tests.

Sets the Qt platform plugin to "offscreen" before any Qt import, so
this test suite can run in headless environments (CI, containers,
this very sandbox) with no real display server: widgets are still
fully constructed and functional, just never actually shown on screen.
"""

import gc
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication instance shared by every UI test in this session."""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _collect_qt_garbage():
    """
    Force a garbage collection after every UI test, while the
    ``QApplication`` is still alive.

    NodeGraphQt gives each ``NodeGraph`` its own ``QUndoStack``. If a
    stack is only reclaimed during interpreter shutdown -- after Qt has
    started tearing itself down -- PySide6 can crash in
    ``QUndoStack::clear`` (seen as a SIGSEGV with exit code 139).
    Collecting here keeps that deallocation inside the normal Qt
    lifetime instead.
    """
    yield
    gc.collect()
