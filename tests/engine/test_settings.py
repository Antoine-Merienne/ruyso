"""
Tests for ``engine.settings`` -- the preferences store.

The property worth defending: a settings file the app did not write --
hand-edited, truncated, or left behind by a newer version -- must never
stop it starting or hand a caller a value of the wrong shape. Every
lookup falls back to the declared default.

``tests/conftest.py`` points ``$RUYSO_CONFIG_DIR`` at a temp directory,
so these never touch a real ``~/.config/ruyso``.
"""

import json

import pytest

from ruyso_app.engine import settings


@pytest.fixture(autouse=True)
def _clean_store():
    """Each test starts from an empty store and leaves one behind."""
    path = settings.config_path()
    if path.exists():
        path.unlink()
    settings.reload()
    yield
    if path.exists():
        path.unlink()
    settings.reload()


# -- reading -------------------------------------------------------------


def test_an_unset_key_reads_its_default():
    assert settings.get("cache.max_gb") == settings.DEFAULTS["cache.max_gb"]
    assert settings.get("execution.debounce_ms") == 450


def test_an_unknown_key_returns_the_caller_s_default():
    assert settings.get("no.such.key") is None
    assert settings.get("no.such.key", "fallback") == "fallback"


def test_a_stored_value_wins():
    settings.set("execution.debounce_ms", 900)
    assert settings.get("execution.debounce_ms") == 900


def test_the_file_is_json_on_disk():
    settings.set("appearance.theme", "dark")
    stored = json.loads(settings.config_path().read_text())
    assert stored["appearance.theme"] == "dark"


def test_a_missing_file_is_not_an_error():
    settings.config_path().unlink(missing_ok=True)
    settings.reload()
    assert settings.get("appearance.theme") == "system"


def test_a_corrupt_file_degrades_to_defaults():
    settings.config_path().write_text("{not json at all")
    settings.reload()
    assert settings.get("appearance.theme") == "system"


def test_a_file_holding_a_list_degrades_to_defaults():
    settings.config_path().write_text("[1, 2, 3]")
    settings.reload()
    assert settings.get("cache.enabled") is True


# -- type guarding -------------------------------------------------------


def test_a_stored_value_of_the_wrong_type_is_ignored():
    settings.save_store({"cache.max_gb": "lots", "execution.debounce_ms": "soon"})
    assert settings.get("cache.max_gb") == 2.0
    assert settings.get("execution.debounce_ms") == 450


def test_a_bool_setting_only_accepts_a_bool():
    settings.save_store({"cache.enabled": 1})
    assert settings.get("cache.enabled") is True  # the default, not the 1


def test_an_int_is_accepted_where_a_float_is_expected():
    """JSON does not distinguish 2 from 2.0."""
    settings.save_store({"cache.max_gb": 5})
    assert settings.get("cache.max_gb") == 5.0
    assert isinstance(settings.get("cache.max_gb"), float)


def test_a_bool_is_not_accepted_as_a_number():
    settings.save_store({"execution.debounce_ms": True})
    assert settings.get("execution.debounce_ms") == 450


# -- writing -------------------------------------------------------------


def test_writing_an_unknown_key_is_refused():
    """A typo would otherwise be stored and read back as the default forever."""
    with pytest.raises(KeyError, match="Unknown setting"):
        settings.set("cache.max_gigabytes", 4)


def test_update_writes_several_keys_at_once():
    settings.update({"appearance.theme": "light", "cache.max_gb": 8.0})
    assert settings.get("appearance.theme") == "light"
    assert settings.get("cache.max_gb") == 8.0


def test_update_rejects_the_whole_batch_if_any_key_is_unknown():
    settings.set("appearance.theme", "dark")
    with pytest.raises(KeyError):
        settings.update({"appearance.theme": "light", "nope": 1})
    assert settings.get("appearance.theme") == "dark"  # nothing was written


def test_a_write_is_atomic_leaving_no_temp_file_behind():
    settings.set("appearance.theme", "dark")
    leftovers = list(settings.config_path().parent.glob("settings.json.tmp"))
    assert leftovers == []


# -- resetting -----------------------------------------------------------


def test_reset_returns_a_key_to_its_default():
    settings.set("execution.debounce_ms", 900)
    settings.reset(["execution.debounce_ms"])
    assert settings.get("execution.debounce_ms") == 450


def test_reset_all_keeps_the_app_s_own_bookkeeping():
    """Resetting preferences should not forget your window size."""
    settings.update(
        {"appearance.theme": "light", "general.window_geometry": "AAAA"}
    )
    settings.reset()

    assert settings.get("appearance.theme") == "system"
    assert settings.get("general.window_geometry") == "AAAA"


def test_as_dict_reports_every_known_setting():
    values = settings.as_dict()
    assert set(values) == set(settings.DEFAULTS)
    assert values["cache.max_gb"] == 2.0


def test_every_default_has_a_page_prefix():
    """The dialog groups by the part before the dot."""
    for key in settings.DEFAULTS:
        assert "." in key, key


# -- the disk cache budget (engine.cache reads these) ---------------------


def test_cache_helpers_follow_the_preferences(tmp_path):
    from ruyso_app.engine import cache

    settings.update({"cache.enabled": True, "cache.max_gb": 3.0})
    assert cache.is_enabled()
    assert cache.size_limit_bytes() == int(3 * 1024**3)

    settings.set("cache.enabled", False)
    assert not cache.is_enabled()
    # With caching off, the scheduler's Memory is a transparent no-op.
    assert cache.get_memory().location is None


def test_measuring_an_absent_cache_directory_is_zero(tmp_path):
    from ruyso_app.engine import cache

    assert cache.current_size_bytes(tmp_path / "nope") == 0


def test_measuring_counts_the_files_it_finds(tmp_path):
    from ruyso_app.engine import cache

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.bin").write_bytes(b"x" * 100)
    (tmp_path / "b.bin").write_bytes(b"y" * 50)

    assert cache.current_size_bytes(tmp_path) == 150


def test_enforcing_the_limit_never_raises(tmp_path):
    """Tidying the cache is housekeeping; it must not be able to fail a run."""
    from ruyso_app.engine import cache

    cache.enforce_size_limit(tmp_path / "does-not-exist")
    settings.set("cache.enabled", False)
    cache.enforce_size_limit(tmp_path)  # disabled: a no-op


def test_clearing_never_raises(tmp_path):
    from ruyso_app.engine import cache

    cache.clear(tmp_path / "does-not-exist")
