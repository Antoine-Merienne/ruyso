"""
Tests for ``ruyso_app.selftest`` -- the check the packaged builds run.

It lives here, with the other Qt tests, because it constructs a
``MainWindow``. Its job in CI is to be run *against a built binary*,
where nothing else can reach; this test only guards it from rotting in
the meantime.
"""

import os

from ruyso_app import selftest


def test_the_self_test_passes_on_a_working_install(qapp, monkeypatch):
    """If this fails in a source checkout, the packaged builds have no
    hope -- and the CI smoke test would be reporting on itself."""
    # run() points RUYSO_CONFIG_DIR at a throwaway directory; keep that
    # out of the rest of the session, which shares one config dir.
    monkeypatch.setattr(os, "environ", dict(os.environ))

    assert selftest.run() == 0


def test_a_missing_bundled_dataset_is_a_failure_not_a_download(qapp, monkeypatch):
    """The failure this exists for: seaborn does not raise when its
    cache is missing, it fetches from the web -- so a build with no data
    files would otherwise look perfectly healthy."""
    import tempfile
    from pathlib import Path

    from ruyso_app.nodes import example_data

    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(
        example_data, "_SEABORN_DATA_HOME", Path(tempfile.mkdtemp())
    )

    assert selftest.run() == 1
