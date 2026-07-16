# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""Backends for the pgrep Settings surface (L5.9).

Three kinds of setting live here, each stored where it truly belongs:

- **Target retention** is a real FSRS scheduler setting, so it is persisted as
  ``desiredRetention`` on the sample deck's own deck-config group (never the
  user's default group). Reading and writing mirror
  ``seed._ensure_points_at_stake_config``: the sample deck gets a dedicated
  config the first time retention is set, so the user's other decks are never
  touched. Writing the value does not reschedule or rewrite any card state.
- **Test date** and **theme** are UI preferences, not scheduler state, so they
  live in a small ``pgrepSettings`` blob in the collection config (synced with
  the collection, like the AI on/off flag).
- **Export** and **reset** are actions, not stored values. Only the pure,
  testable parts live here (the default export path, and the progress-reset
  fold over pgrep notes). The GUI orchestration (progress, close/reopen,
  confirmation) stays in the ``qt/aqt/pgrep.py`` handlers.

Everything works with AI off; none of this touches the AI seam or scoring.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anki.collection import Collection

# Collection-config blob holding the pgrep UI preferences (not deck settings).
SETTINGS_KEY = "pgrepSettings"

# Target retention is stored on the sample deck's FSRS config, not in the blob,
# because it is a genuine scheduler setting. Range matches the Settings slider.
RETENTION_CONFIG_KEY = "desiredRetention"
DEFAULT_RETENTION = 0.9
MIN_RETENTION = 0.7
MAX_RETENTION = 0.97

# The three theme choices the Appearance control offers. ``None`` (unstored)
# means "reflect whatever the app currently shows", so a fresh profile stays
# honest instead of forcing a choice the user never made.
THEMES: tuple[str, ...] = ("Light", "Dark", "System")

# The self-hosted sync server URL, persisted in the blob so a learner's own
# endpoint survives restarts. Defaults to the local server ``just serve-sync``
# binds: port 8090, not 8080, because ``just run``/``just dev`` hold 8080 for the
# Qt remote-debug/hot-reload server. Matches the Settings sync default and the
# login gate's prefill so a local sign-in works without editing the URL.
DEFAULT_SYNC_URL = "http://127.0.0.1:8090/"

# A collection export is written next to a timestamped, non-clobbering name.
EXPORT_PREFIX = "pgrep-export-"
EXPORT_SUFFIX = ".colpkg"


# Read model
##########################################################################


def get_settings(col: Collection) -> dict[str, Any]:
    """The full settings blob the Settings surface reads on load.

    ``theme`` and ``test_date`` are ``None`` when unset so the surface can stay
    honest (reflect the live theme, show no fabricated test date).
    """
    return {
        "target_retention": target_retention(col),
        "test_date": test_date(col),
        "theme": theme(col),
        "sync_url": sync_url(col),
        "retention_min": MIN_RETENTION,
        "retention_max": MAX_RETENTION,
    }


def apply_settings(col: Collection, args: dict[str, Any]) -> dict[str, Any]:
    """Apply only the settings present in ``args`` and return the new state.

    A key that is absent is left untouched; a present key is written (so the
    surface can send just the one control the user changed). Returns
    :func:`get_settings` so the caller always sees the persisted truth.
    """
    if "target_retention" in args:
        set_target_retention(col, args["target_retention"])
    if "test_date" in args:
        set_test_date(col, args["test_date"])
    if "theme" in args:
        set_theme(col, args["theme"])
    if "sync_url" in args:
        set_sync_url(col, args["sync_url"])
    return get_settings(col)


# Test date and theme (the pgrepSettings blob)
##########################################################################


def _blob(col: Collection) -> dict[str, Any]:
    raw = col.get_config(SETTINGS_KEY, None)
    return dict(raw) if isinstance(raw, dict) else {}


def _save_blob(col: Collection, blob: dict[str, Any]) -> None:
    col.set_config(SETTINGS_KEY, blob)


def test_date(col: Collection) -> str | None:
    """The stored test date (an ``YYYY-MM-DD`` string), or ``None`` if unset."""
    value = _blob(col).get("test_date")
    return value if isinstance(value, str) and value else None


def set_test_date(col: Collection, value: str | None) -> str | None:
    """Store (or clear, on empty/``None``) the test date; return the new value."""
    blob = _blob(col)
    cleaned = value.strip() if isinstance(value, str) else ""
    if cleaned:
        blob["test_date"] = cleaned
    else:
        blob.pop("test_date", None)
    _save_blob(col, blob)
    return test_date(col)


def theme(col: Collection) -> str | None:
    """The stored theme choice, or ``None`` when the user has not chosen one."""
    value = _blob(col).get("theme")
    return value if value in THEMES else None


def set_theme(col: Collection, value: str | None) -> str | None:
    """Store (or clear, on an unknown value) the theme; return the new value."""
    blob = _blob(col)
    if value in THEMES:
        blob["theme"] = value
    else:
        blob.pop("theme", None)
    _save_blob(col, blob)
    return theme(col)


def sync_url(col: Collection) -> str:
    """The stored self-hosted sync server URL, or the local default if unset."""
    value = _blob(col).get("sync_url")
    return value if isinstance(value, str) and value.strip() else DEFAULT_SYNC_URL


def set_sync_url(col: Collection, value: str | None) -> str:
    """Store (or reset to the default, on empty) the sync URL; return the value."""
    blob = _blob(col)
    cleaned = value.strip() if isinstance(value, str) else ""
    if cleaned:
        blob["sync_url"] = cleaned
    else:
        blob.pop("sync_url", None)
    _save_blob(col, blob)
    return sync_url(col)


# Target retention (the sample deck's FSRS config)
##########################################################################


def clamp_retention(value: Any) -> float:
    """Coerce ``value`` to the supported retention range, or the default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_RETENTION
    return max(MIN_RETENTION, min(MAX_RETENTION, number))


def target_retention(col: Collection) -> float:
    """The sample deck's desired retention, or the default if it has no deck yet."""
    from anki.pgrep.seed import DECK_NAME

    deck = col.decks.by_name(DECK_NAME)
    if deck is None:
        return DEFAULT_RETENTION
    conf = col.decks.config_dict_for_deck_id(deck["id"])
    return clamp_retention(conf.get(RETENTION_CONFIG_KEY, DEFAULT_RETENTION))


def set_target_retention(col: Collection, value: Any) -> float:
    """Persist desired retention on the sample deck's own config; return it.

    Ensures the sample deck exists and has a dedicated config group first, so
    the user's default deck config is never overwritten. Only the retention
    value is changed; no card is rescheduled and no schedule state is rewritten.
    """
    from anki.pgrep.seed import DECK_CONFIG_NAME, DECK_NAME

    cleaned = clamp_retention(value)
    deck_id = col.decks.id(DECK_NAME)
    assert deck_id is not None
    _ensure_dedicated_config(col, deck_id, DECK_CONFIG_NAME)
    conf = col.decks.config_dict_for_deck_id(deck_id)
    conf[RETENTION_CONFIG_KEY] = cleaned
    col.decks.update_config(conf)
    return cleaned


def _ensure_dedicated_config(col: Collection, deck_id: Any, config_name: str) -> None:
    """Give the sample deck its own config group before writing retention.

    Mirrors ``seed._ensure_points_at_stake_config`` (clone the current config
    under the sample name and point the deck at it) so retention never lands on
    the shared default group. Idempotent: an already-dedicated deck is left as
    is, and the review order the seed sets is not disturbed.
    """
    deck = col.decks.get(deck_id)
    assert deck is not None
    conf = col.decks.config_dict_for_deck_id(deck_id)
    if conf.get("name") != config_name:
        conf = col.decks.add_config(config_name, clone_from=conf)
        col.decks.set_config_id_for_deck_dict(deck, conf["id"])


# Export (pure path helper; GUI orchestration lives in the handler)
##########################################################################


def default_export_dir() -> str:
    """A sensible, user-visible directory for an export (Downloads, else home)."""
    downloads = os.path.expanduser(os.path.join("~", "Downloads"))
    if os.path.isdir(downloads):
        return downloads
    return os.path.expanduser("~")


def export_basename(now: float | None = None) -> str:
    """A timestamped, non-clobbering export filename."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    return f"{EXPORT_PREFIX}{stamp}{EXPORT_SUFFIX}"


def default_export_path(now: float | None = None, base_dir: str | None = None) -> str:
    """A full export path: a timestamped ``.colpkg`` in a user-visible folder."""
    directory = base_dir if base_dir is not None else default_export_dir()
    return os.path.join(directory, export_basename(now))


# Reset progress (conservative, scoped; confirmed with Frank)
##########################################################################


def reset_progress(col: Collection) -> dict[str, int]:
    """Reset pgrep progress and return a summary of what was cleared.

    Three things happen, all scoped to pgrep's own data:

    - Every ``pgrep::Attempt`` note is deleted, which clears the Performance and
      Readiness history (and removes the suspended attempt cards with them). This
      sweep also takes any demo-profile attempts, since they are Attempt notes.
    - The seeded sample cards (tagged ``pgrep::seeded``) are forgotten back to
      new, so their FSRS memory state is dropped and Memory and mastery start
      fresh. The cards and their notes are kept.
    - If a dev demo profile is present, it is cleared too (its ``pgrep::demo``
      reviewed cards, the now-empty demo deck, and the profile marker). Those
      cards carry FSRS memory state, so without this Memory would stay lit while
      Performance and Readiness reset, leaving the three scores inconsistent.
      After the reset all three abstain again, matching a fresh account.

    Everything else is left untouched: settings (retention, test date, theme),
    notetypes, decks, and all other content, including AI-generated Library
    cards and Problems. The collection is never wiped. The writes are merged into
    a single action so the reset is one clean unit.
    """
    from anki.pgrep.attempt_log import get_attempt_notetype
    from anki.pgrep.demo_profile import clear_demo_profile, is_demo_injected
    from anki.pgrep.seed import SEEDED_TAG

    attempt_note_ids: list[Any] = []
    notetype = get_attempt_notetype(col)
    if notetype is not None:
        attempt_note_ids = list(col.models.nids(notetype["id"]))
    seeded_card_ids = list(col.find_cards(f"tag:{SEEDED_TAG}"))
    demo_present = is_demo_injected(col)

    demo_cards_removed = 0
    if attempt_note_ids or seeded_card_ids or demo_present:
        undo_id = col.add_custom_undo_entry("Reset pgrep progress")
        if attempt_note_ids:
            col.remove_notes(attempt_note_ids)
        if seeded_card_ids:
            col.sched.schedule_cards_as_new(seeded_card_ids)
        if demo_present:
            # The demo attempts were already swept above (they are Attempt
            # notes); this drops the demo reviewed cards, the empty demo deck,
            # and the profile marker, so Memory abstains after the reset. Its
            # inner undo step folds into this one via the merge below.
            demo_cards_removed = clear_demo_profile(col)["cards_removed"]
        col.merge_undo_entries(undo_id)

    return {
        "attempts_deleted": len(attempt_note_ids),
        "cards_reset": len(seeded_card_ids),
        "demo_cards_removed": demo_cards_removed,
    }
