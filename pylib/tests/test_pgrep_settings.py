# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Tests for the pgrep Settings backends (L5.9).

Target retention is a real FSRS setting, so it round-trips through the sample
deck's own config group (never the user's default). Test date and theme are UI
preferences that round-trip through the collection config. The export path
helper is pure. Reset semantics are covered in ``test_pgrep_settings_reset``
once its scope is confirmed.
"""

from __future__ import annotations

import os

from anki.pgrep import settings
from anki.pgrep.seed import DECK_CONFIG_NAME, DECK_NAME
from tests.shared import getEmptyCol

DEFAULT_DECK_CONFIG_ID = 1


# Target retention
##########################################################################


def test_target_retention_defaults_before_any_sample_deck():
    col = getEmptyCol()
    # No sample deck yet, so the read reports the honest default.
    assert col.decks.by_name(DECK_NAME) is None
    assert settings.target_retention(col) == settings.DEFAULT_RETENTION


def test_set_target_retention_persists_on_sample_deck_config():
    col = getEmptyCol()

    returned = settings.set_target_retention(col, 0.85)
    assert returned == 0.85

    # It created the sample deck and pointed it at its own dedicated config.
    deck = col.decks.by_name(DECK_NAME)
    assert deck is not None
    conf = col.decks.config_dict_for_deck_id(deck["id"])
    assert conf["name"] == DECK_CONFIG_NAME
    assert conf[settings.RETENTION_CONFIG_KEY] == 0.85

    # Read-back agrees, and it survives a restart (persisted, not in memory).
    assert settings.target_retention(col) == 0.85
    col.close(downgrade=False)
    col.reopen()
    assert settings.target_retention(col) == 0.85


def test_set_target_retention_does_not_touch_default_config():
    col = getEmptyCol()
    default_before = col.decks.get_config(DEFAULT_DECK_CONFIG_ID)
    assert default_before is not None
    before = default_before.get(settings.RETENTION_CONFIG_KEY)

    settings.set_target_retention(col, 0.75)

    # The sample deck got its own group; the shared default is untouched.
    sample = col.decks.by_name(DECK_NAME)
    assert sample is not None
    assert sample["conf"] != DEFAULT_DECK_CONFIG_ID
    default_after = col.decks.get_config(DEFAULT_DECK_CONFIG_ID)
    assert default_after is not None
    assert default_after.get(settings.RETENTION_CONFIG_KEY) == before


def test_set_target_retention_clamps_to_supported_range():
    col = getEmptyCol()
    assert settings.set_target_retention(col, 0.99) == settings.MAX_RETENTION
    assert settings.set_target_retention(col, 0.10) == settings.MIN_RETENTION
    # Non-numeric input falls back to the default rather than raising.
    assert settings.set_target_retention(col, "not a number") == (
        settings.DEFAULT_RETENTION
    )


def test_set_target_retention_is_idempotent_on_config_group():
    col = getEmptyCol()
    settings.set_target_retention(col, 0.8)
    deck = col.decks.by_name(DECK_NAME)
    assert deck is not None
    conf_id = deck["conf"]

    # A second write reuses the same dedicated config, it does not spawn another.
    settings.set_target_retention(col, 0.9)
    deck_again = col.decks.by_name(DECK_NAME)
    assert deck_again is not None
    assert deck_again["conf"] == conf_id
    names = [c["name"] for c in col.decks.all_config()]
    assert names.count(DECK_CONFIG_NAME) == 1


# Test date and theme (the pgrepSettings blob)
##########################################################################


def test_test_date_round_trips_and_clears():
    col = getEmptyCol()
    assert settings.test_date(col) is None

    assert settings.set_test_date(col, "2026-10-24") == "2026-10-24"
    assert settings.test_date(col) == "2026-10-24"
    col.close(downgrade=False)
    col.reopen()
    assert settings.test_date(col) == "2026-10-24"

    # Empty or None clears it back to unset.
    assert settings.set_test_date(col, "") is None
    assert settings.test_date(col) is None
    settings.set_test_date(col, "2026-10-24")
    assert settings.set_test_date(col, None) is None
    assert settings.test_date(col) is None


def test_theme_round_trips_and_ignores_unknown():
    col = getEmptyCol()
    assert settings.theme(col) is None

    for choice in settings.THEMES:
        assert settings.set_theme(col, choice) == choice
        assert settings.theme(col) == choice

    # An unknown value clears the stored choice instead of persisting garbage.
    settings.set_theme(col, "Dark")
    assert settings.set_theme(col, "Rainbow") is None
    assert settings.theme(col) is None


# get_settings / apply_settings
##########################################################################


def test_get_settings_reports_full_honest_shape():
    col = getEmptyCol()
    state = settings.get_settings(col)
    assert state == {
        "target_retention": settings.DEFAULT_RETENTION,
        "test_date": None,
        "theme": None,
        "retention_min": settings.MIN_RETENTION,
        "retention_max": settings.MAX_RETENTION,
    }


def test_apply_settings_only_writes_present_keys():
    col = getEmptyCol()
    settings.set_theme(col, "Dark")

    # Only test_date is present, so theme and retention are left untouched.
    result = settings.apply_settings(col, {"test_date": "2027-05-01"})
    assert result["test_date"] == "2027-05-01"
    assert result["theme"] == "Dark"
    assert result["target_retention"] == settings.DEFAULT_RETENTION

    result = settings.apply_settings(
        col, {"target_retention": 0.8, "theme": "Light"}
    )
    assert result["target_retention"] == 0.8
    assert result["theme"] == "Light"
    assert result["test_date"] == "2027-05-01"


# Export path helper (pure)
##########################################################################


def test_export_basename_is_timestamped_colpkg():
    name = settings.export_basename()
    assert name.startswith(settings.EXPORT_PREFIX)
    assert name.endswith(settings.EXPORT_SUFFIX)
    # prefix + YYYYMMDD-HHMMSS + suffix
    stamp = name[len(settings.EXPORT_PREFIX) : -len(settings.EXPORT_SUFFIX)]
    assert len(stamp) == len("YYYYMMDD-HHMMSS")


def test_default_export_path_joins_dir_and_name(tmp_path):
    path = settings.default_export_path(base_dir=str(tmp_path))
    assert os.path.dirname(path) == str(tmp_path)
    assert os.path.basename(path).startswith(settings.EXPORT_PREFIX)
    assert path.endswith(settings.EXPORT_SUFFIX)
