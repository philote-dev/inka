# Copyright: Ankitects Pty Ltd and contributors
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

"""The attempt log as immutable notes ("notes-as-log"), plus the read-model seam.

Decision "A now, C-ready" (see ``docs/pgrep/planning/l1-coordination-schema.md``
§3): one immutable Anki note per problem-attempt event, riding Anki's free note
sync. There is **no** custom SQL table, **no** Rust, **no** proto, and **no**
sync code here.

Invariants (built in from day one):

- **K1 Immutable, self-contained.** An attempt note is never edited after
  creation; ``event_json`` carries the full payload the fold needs.
- **K2 Identity = note guid.** The ``event_id`` field mirrors the note's GUID;
  folds/caches key on it (idempotent rebuild, union-by-id dedup).
- **K3 Payload = one JSON blob + a few flat fields** (``topic``, ``correct``,
  ``answered_at``) + the topic on tags (a cheap tag-search pre-filter).
- **K4 One read-model seam.** ALL attempt analytics go through :func:`attempts`
  and :func:`performance_fold`. Nothing else reads attempt storage directly.
- **K5 Cache = fold(all Attempt notes), local-only, never synced, recomputable.**
  Defined here (the seam *is* the fold, keyed on ``event_id``) but **not built**
  now: today the seam parses the notes on demand ("A"). A later local cache
  ("C") would parse the *same* JSON into cache rows keyed by ``event_id`` and be
  rebuilt by re-running the fold. No synced table is ever added.

Append is **idempotent on ``event_id``**: appending an event whose ``event_id``
already exists is a no-op (no duplicate, no mutation).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, Union

from anki.pgrep.blueprint import UNKNOWN_CATEGORY
from anki.pgrep.tags import category_of

if TYPE_CHECKING:
    from anki.collection import Collection
    from anki.decks import DeckId
    from anki.models import NotetypeDict

# Schema, per the coordination contract §3.
ATTEMPT_NOTETYPE_NAME = "pgrep::Attempt"
ATTEMPT_TAG = "pgrep::attempt"
ATTEMPT_DECK_NAME = "pgrep::attempt-log"
EVENT_SCHEMA_VERSION = 1

# Field names, in order. Field 1 (``event_id``) is the sort field and mirrors
# the note GUID (K2).
FIELD_EVENT_ID = "event_id"
FIELD_EVENT_JSON = "event_json"
FIELD_TOPIC = "topic"
FIELD_CORRECT = "correct"
FIELD_ANSWERED_AT = "answered_at"
ATTEMPT_FIELDS: tuple[str, ...] = (
    FIELD_EVENT_ID,
    FIELD_EVENT_JSON,
    FIELD_TOPIC,
    FIELD_CORRECT,
    FIELD_ANSWERED_AT,
)

# A window may be:
#   - None                      -> no time filter
#   - int | float N             -> "the last N seconds" (relative to now)
#   - (start, end) 2-tuple      -> [start, end) epoch-second bounds; either bound
#                                  may be None to leave that side unbounded
Window = Union[None, int, float, tuple[Optional[int], Optional[int]]]


@dataclass(frozen=True)
class Event:
    """A single attempt event, parsed from an attempt note's ``event_json``.

    ``payload`` holds the full, self-contained JSON blob (K1); the other fields
    are convenience accessors for the hot-path denormalized values.
    """

    event_id: str
    topic: str | None
    category: str
    correct: bool
    answered_at: int
    payload: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        topic = data.get("topic")
        topic = str(topic) if topic else None
        category = data.get("category") or category_of(topic)
        answered_at = data.get("answered_at") or 0
        return cls(
            event_id=str(data.get("event_id", "")),
            topic=topic,
            category=category or UNKNOWN_CATEGORY,
            correct=bool(data.get("correct", False)),
            answered_at=int(answered_at),
            payload=data,
        )

    @classmethod
    def from_json(cls, raw: str) -> Event:
        return cls.from_dict(json.loads(raw))


@dataclass(frozen=True)
class TopicStats:
    """Correct/total (and accuracy) for a single topic."""

    topic: str | None
    correct: int
    total: int

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


@dataclass(frozen=True)
class PerformanceFold:
    """Aggregate of a set of attempt events: overall + per-topic breakdown."""

    correct: int
    total: int
    by_topic: dict[str | None, TopicStats]

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0


# Notetype / deck bootstrap
##########################################################################


def get_attempt_notetype(col: Collection) -> NotetypeDict | None:
    """The ``pgrep::Attempt`` notetype, or ``None`` if it doesn't exist yet."""
    return col.models.by_name(ATTEMPT_NOTETYPE_NAME)


def ensure_attempt_notetype(col: Collection) -> NotetypeDict:
    """Return the ``pgrep::Attempt`` notetype, creating it if missing."""
    existing = get_attempt_notetype(col)
    if existing:
        return existing

    mm = col.models
    notetype = mm.new(ATTEMPT_NOTETYPE_NAME)
    for field_name in ATTEMPT_FIELDS:
        mm.add_field(notetype, mm.new_field(field_name))
    # event_id is the sort field.
    mm.set_sort_index(notetype, 0)
    # Anki forces >= 1 card per note; give it a trivial, self-referential
    # template. These cards live suspended in a hidden deck and are never shown.
    template = mm.new_template("Attempt")
    template["qfmt"] = "{{" + FIELD_EVENT_ID + "}}"
    template["afmt"] = "{{" + FIELD_EVENT_JSON + "}}"
    mm.add_template(notetype, template)
    mm.add(notetype)
    # Re-fetch so we get the canonical dict (with assigned field ordinals/id).
    created = get_attempt_notetype(col)
    assert created is not None
    return created


def ensure_attempt_deck(col: Collection) -> DeckId:
    """Return the id of the suspended, hidden ``pgrep::attempt-log`` deck.

    The deck is created if missing. Attempt cards are placed here and suspended
    so they are excluded from study; the deck keeps them out of the normal
    browsing/stats flow.
    """
    return col.decks.id(ATTEMPT_DECK_NAME)


# Append (write path)
##########################################################################


def append_attempt(col: Collection, event: dict[str, Any]) -> str:
    """Append an attempt event as one immutable note; return its ``event_id``.

    The event dict is the payload. If it carries an ``event_id``, that value
    becomes the note's GUID (K2) and the append is idempotent on it: a second
    append with the same ``event_id`` is a no-op (no duplicate, no mutation).
    Otherwise a fresh GUID is generated and used as the ``event_id``.

    The whole append (note add + card suspend + move to the hidden deck) is a
    single, undoable action.
    """
    notetype = ensure_attempt_notetype(col)
    deck_id = ensure_attempt_deck(col)

    provided_id = event.get("event_id")
    if provided_id:
        provided_id = str(provided_id)
        # Idempotent on event_id (== note guid). K2/K5 union-by-id dedup.
        if _attempt_exists(col, provided_id, notetype["id"]):
            return provided_id

    note = col.new_note(notetype)
    if provided_id:
        # Force identity so the note GUID == event_id (K2). The backend
        # preserves a caller-supplied guid on add.
        note.guid = provided_id
    event_id = note.guid

    payload = _build_payload(event, event_id)

    note[FIELD_EVENT_ID] = event_id
    note[FIELD_EVENT_JSON] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    note[FIELD_TOPIC] = payload["topic"] or ""
    note[FIELD_CORRECT] = "1" if payload["correct"] else "0"
    note[FIELD_ANSWERED_AT] = str(payload["answered_at"])

    # K3 tag pre-filter: pgrep::attempt plus the item's topic tag (if any).
    note.tags = [ATTEMPT_TAG]
    if payload["topic"]:
        note.tags.append(payload["topic"])

    # Merge the note-add and the suspend into a single undo entry so the append
    # is one clean, undoable action.
    undo_id = col.add_custom_undo_entry("Add pgrep attempt")
    col.add_note(note, deck_id)
    card_ids = list(col.card_ids_of_note(note.id))
    if card_ids:
        col.sched.suspend_cards(card_ids)
    col.merge_undo_entries(undo_id)

    return event_id


def _build_payload(event: dict[str, Any], event_id: str) -> dict[str, Any]:
    """Return a self-contained copy of ``event`` with canonical fields filled.

    Never mutates the caller's dict (K1). Guarantees ``event_id``, ``schema``,
    ``topic``, ``category``, ``correct`` and ``answered_at`` are present so the
    stored blob is self-contained.
    """
    payload = dict(event)
    payload["event_id"] = event_id
    payload.setdefault("schema", EVENT_SCHEMA_VERSION)

    topic = payload.get("topic")
    topic = str(topic) if topic else None
    payload["topic"] = topic
    payload["category"] = payload.get("category") or category_of(topic)
    payload["correct"] = bool(payload.get("correct", False))
    answered_at = payload.get("answered_at")
    payload["answered_at"] = int(answered_at) if answered_at else int(time.time())
    return payload


def _attempt_exists(col: Collection, event_id: str, notetype_id: int) -> bool:
    existing = col.db.scalar(
        "select id from notes where guid = ? and mid = ?",
        event_id,
        notetype_id,
    )
    return existing is not None


# Read-model seam (K4) — the ONLY entry point for attempt analytics.
##########################################################################


def attempts(
    col: Collection,
    topic: str | None = None,
    window: Window = None,
) -> list[Event]:
    """All attempt events, filtered by ``topic`` and ``window``, oldest first.

    This is one half of the single read-model seam (K4). ``topic`` matches the
    event's finest topic exactly, or any subtopic beneath it (hierarchical
    ``::`` match); ``None`` matches all. See :data:`Window` for ``window``.
    """
    bounds = _window_bounds(window)
    matched = [
        event
        for event in _iter_attempt_events(col)
        if _topic_matches(event.topic, topic) and _in_window(event.answered_at, bounds)
    ]
    matched.sort(key=lambda event: event.answered_at)
    return matched


def performance_fold(
    col: Collection,
    topic: str | None = None,
    window: Window = None,
) -> PerformanceFold:
    """Fold matching attempt events into correct/total (accuracy), per topic.

    The other half of the read-model seam (K4); it is defined purely in terms of
    :func:`attempts`, so it is exactly ``fold(all matching Attempt notes)`` — the
    recomputable, cache-free "A" form of K5.
    """
    by_topic: dict[str | None, list[int]] = {}
    correct = 0
    total = 0
    for event in attempts(col, topic=topic, window=window):
        total += 1
        hit = 1 if event.correct else 0
        correct += hit
        bucket = by_topic.setdefault(event.topic, [0, 0])
        bucket[0] += hit
        bucket[1] += 1
    stats = {
        event_topic: TopicStats(topic=event_topic, correct=c, total=t)
        for event_topic, (c, t) in by_topic.items()
    }
    return PerformanceFold(correct=correct, total=total, by_topic=stats)


def _iter_attempt_events(col: Collection) -> Iterator[Event]:
    """Yield an :class:`Event` for every attempt note (identity = notetype)."""
    notetype = get_attempt_notetype(col)
    if not notetype:
        return
    for note_id in col.models.nids(notetype["id"]):
        raw = col.get_note(note_id)[FIELD_EVENT_JSON]
        try:
            yield Event.from_json(raw)
        except (ValueError, TypeError):
            # A malformed blob should never sink the whole fold.
            continue


def _topic_matches(event_topic: str | None, query: str | None) -> bool:
    if query is None:
        return True
    if event_topic is None:
        return False
    return event_topic == query or event_topic.startswith(query + "::")


def _window_bounds(window: Window) -> tuple[int | None, int | None]:
    if window is None:
        return (None, None)
    if isinstance(window, bool):  # guard: bool is an int subclass
        raise ValueError(f"unsupported window: {window!r}")
    if isinstance(window, (int, float)):
        return (int(time.time() - window), None)
    if isinstance(window, (tuple, list)) and len(window) == 2:
        start, end = window
        return (
            int(start) if start is not None else None,
            int(end) if end is not None else None,
        )
    raise ValueError(f"unsupported window: {window!r}")


def _in_window(answered_at: int, bounds: tuple[int | None, int | None]) -> bool:
    start, end = bounds
    if start is not None and answered_at < start:
        return False
    if end is not None and answered_at >= end:
        return False
    return True
