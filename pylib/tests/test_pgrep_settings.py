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

from anki import cards_pb2
from anki.consts import CARD_TYPE_NEW, CARD_TYPE_REV, QUEUE_TYPE_NEW, QUEUE_TYPE_REV
from anki.pgrep import settings
from anki.pgrep.attempt_log import (
    ATTEMPT_TAG,
    append_attempt,
    attempts,
    get_attempt_notetype,
)
from anki.pgrep.demo_profile import inject_demo_profile, is_demo_injected
from anki.pgrep.memory import memory_score
from anki.pgrep.performance import performance_score
from anki.pgrep.readiness import readiness_score
from anki.pgrep.seed import DECK_CONFIG_NAME, DECK_NAME, SEEDED_TAG, seed_sample_content
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
        "sync_url": settings.DEFAULT_SYNC_URL,
        "retention_min": settings.MIN_RETENTION,
        "retention_max": settings.MAX_RETENTION,
    }


def test_sync_url_round_trips_and_defaults_honestly():
    col = getEmptyCol()
    # Unset: the local server default (matches ``just sync-server`` on 8080).
    assert settings.sync_url(col) == settings.DEFAULT_SYNC_URL
    # A learner's own endpoint persists through the blob.
    assert settings.set_sync_url(col, "https://sync.example.com/") == (
        "https://sync.example.com/"
    )
    assert settings.sync_url(col) == "https://sync.example.com/"
    # Clearing it falls back to the honest default rather than an empty string.
    assert settings.set_sync_url(col, "  ") == settings.DEFAULT_SYNC_URL


def test_apply_settings_only_writes_present_keys():
    col = getEmptyCol()
    settings.set_theme(col, "Dark")

    # Only test_date is present, so theme and retention are left untouched.
    result = settings.apply_settings(col, {"test_date": "2027-05-01"})
    assert result["test_date"] == "2027-05-01"
    assert result["theme"] == "Dark"
    assert result["target_retention"] == settings.DEFAULT_RETENTION

    result = settings.apply_settings(col, {"target_retention": 0.8, "theme": "Light"})
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


# Reset progress (conservative scope)
##########################################################################


def test_reset_progress_clears_attempts_and_forgets_sample_cards():
    col = getEmptyCol()
    seed_sample_content(col)
    seeded_cids = list(col.find_cards(f"tag:{SEEDED_TAG}"))
    # The bundle seeds cold (P4: no fabricated FSRS state), so put a few seeded
    # cards into a reviewed state with memory first, mirroring studied cards, so
    # the reset's forget-to-new actually has memory state to drop.
    reviewed_before = []
    for cid in seeded_cids[:3]:
        card = col.get_card(cid)
        card.type = CARD_TYPE_REV
        card.queue = QUEUE_TYPE_REV
        card.memory_state = cards_pb2.FsrsMemoryState(stability=30.0, difficulty=5.0)
        col.update_cards([card])
        reviewed_before.append(card)
    assert reviewed_before

    append_attempt(
        col, {"event_id": "a1", "topic": "topic::mechanics", "correct": True}
    )
    append_attempt(col, {"event_id": "a2", "topic": "topic::quantum", "correct": False})
    assert len(attempts(col)) == 2

    result = settings.reset_progress(col)

    assert result["attempts_deleted"] == 2
    assert result["cards_reset"] == len(seeded_cids)

    # The attempt log is gone: no events, no attempt notes.
    assert attempts(col) == []
    assert col.find_notes(f"tag:{ATTEMPT_TAG}") == []

    # Every seeded card is back to new with no memory state, and none were lost.
    assert list(col.find_cards(f"tag:{SEEDED_TAG}")) == seeded_cids
    for cid in seeded_cids:
        card = col.get_card(cid)
        assert card.type == CARD_TYPE_NEW
        assert card.queue == QUEUE_TYPE_NEW
        assert card.memory_state is None


def test_reset_progress_keeps_settings_notetypes_and_generated_content():
    col = getEmptyCol()
    seed_sample_content(col)

    # Preferences the reset must not disturb.
    settings.set_target_retention(col, 0.8)
    settings.set_test_date(col, "2026-10-24")
    settings.set_theme(col, "Dark")

    # An attempt so the attempt notetype exists (reset removes notes, not types).
    append_attempt(
        col, {"event_id": "a1", "topic": "topic::mechanics", "correct": True}
    )
    assert get_attempt_notetype(col) is not None

    # A non-seeded "generated" review card (stands in for AI Library/Problem
    # content): it carries memory state and lives outside the sample deck.
    basic = col.models.by_name("Basic")
    assert basic is not None
    generated = col.new_note(basic)
    generated["Front"] = "generated q"
    generated["Back"] = "generated a"
    generated_did = col.decks.id("PGRE::Library")
    assert generated_did is not None
    col.add_note(generated, generated_did)
    generated_cid = generated.cards()[0].id
    card = col.get_card(generated_cid)
    card.type = CARD_TYPE_REV
    card.queue = QUEUE_TYPE_REV
    card.memory_state = cards_pb2.FsrsMemoryState(stability=30.0, difficulty=5.0)
    col.update_cards([card])

    notetypes_before = {nt.name for nt in col.models.all_names_and_ids()}
    decks_before = {d.name for d in col.decks.all_names_and_ids()}

    settings.reset_progress(col)

    # Settings survive.
    assert settings.target_retention(col) == 0.8
    assert settings.test_date(col) == "2026-10-24"
    assert settings.theme(col) == "Dark"

    # Notetypes (including pgrep::Attempt) and decks survive.
    assert get_attempt_notetype(col) is not None
    assert {nt.name for nt in col.models.all_names_and_ids()} == notetypes_before
    assert {d.name for d in col.decks.all_names_and_ids()} == decks_before

    # The generated card is completely untouched: still a review card, still
    # holding its FSRS memory state. Reset never forgot it.
    after = col.get_card(generated_cid)
    assert after.type == CARD_TYPE_REV
    assert after.queue == QUEUE_TYPE_REV
    assert after.memory_state is not None
    assert after.memory_state.stability == 30.0


def test_reset_progress_is_safe_with_nothing_to_reset():
    col = getEmptyCol()
    # No seed, no attempts, no demo: a no-op that still reports an honest summary
    # and does not raise or leave an empty undo entry behind.
    assert settings.reset_progress(col) == {
        "attempts_deleted": 0,
        "cards_reset": 0,
        "demo_cards_removed": 0,
    }


def test_reset_progress_clears_an_injected_demo_profile():
    col = getEmptyCol()
    # A dev demo profile lights up all three scores. The demo reviewed cards are
    # tagged pgrep::demo (not pgrep::seeded), so before this fix a Reset dropped
    # the attempts (Performance, Readiness) but left those cards, keeping Memory
    # lit and the three scores inconsistent.
    inject_demo_profile(col)
    assert is_demo_injected(col) is True
    assert memory_score(col)["overall"]["abstain"] is False
    assert performance_score(col)["overall"]["abstain"] is False
    assert readiness_score(col)["abstain"] is False

    result = settings.reset_progress(col)

    # The summary reports the demo reviewed cards it swept, alongside the
    # attempts (which include the demo attempts, being Attempt notes too).
    assert result["demo_cards_removed"] > 0
    assert result["attempts_deleted"] > 0

    # The profile marker is gone and, crucially, all three scores abstain again,
    # exactly like a fresh account.
    assert is_demo_injected(col) is False
    assert memory_score(col)["overall"]["abstain"] is True
    assert performance_score(col)["overall"]["abstain"] is True
    assert readiness_score(col)["abstain"] is True
